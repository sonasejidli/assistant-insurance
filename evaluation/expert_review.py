"""Collect independent legal annotations and freeze approved evaluation splits."""

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from evaluation import gold_framework as gold


LABELS = ("answerability", "evidence", "required_passage_ids", "parts",
          "expected_answer", "required_qualifications", "groups", "standalone")
DECISIONS = {"annotate", "defer", "exclude"}


def reviewer(record):
    if any(not isinstance(record.get(key), str) or not record[key].strip()
           for key in ("reviewer", "expertise", "revision")):
        raise ValueError("Each submission needs a reviewer, expertise, and revision")
    return record["reviewer"].strip().casefold()


def template(packet, role):
    decisions = {key: {"decision": None, "reason": None, "labels": None} for key in packet["queries"]}
    if role == "adjudication":
        decisions = {key: {**row, "reviewed_decision_sha256": None} for key, row in decisions.items()}
    return {"schema_version": 1, "role": role, "packet_sha256": gold.digest(packet),
            "reviewer": None, "expertise": None, "revision": None, "decisions": decisions}


def annotation(submission, key):
    row = submission["decisions"].get(key)
    if row is None or row["decision"] is None:
        return None
    decision = row["decision"]
    labels = row["labels"]
    if (decision not in DECISIONS or not isinstance(row.get("reason"), str) or not row["reason"].strip()
            or (decision == "annotate" and (not isinstance(labels, dict) or set(labels) != set(LABELS)))
            or (decision != "annotate" and labels is not None)):
        raise ValueError(f"Invalid decision or missing rationale for {key}")
    return row


def label_signature(label):
    """Compare source sets independent of presentation order. Keep wording differences reviewable."""
    copy = deepcopy(label)
    for field in ("required_passage_ids", "required_qualifications", "groups"):
        copy[field] = sorted(copy[field])
    copy["evidence"] = sorted(copy["evidence"], key=lambda item: item["passage_id"])
    for part in copy["parts"].values():
        part["required_passage_ids"] = sorted(part["required_passage_ids"])
    return copy


def resolve(packet, reviews, adjudication, source):
    packet_hash = gold.digest(packet)
    if len(reviews) != 2 or len({reviewer(record) for record in reviews}) != 2:
        raise ValueError("Supply two distinct independent reviewer submissions")
    submissions = [*reviews, *([adjudication] if adjudication else [])]
    if len({reviewer(record) for record in submissions}) != len(submissions):
        raise ValueError("The adjudicator must be independent of both reviewers")
    for index, record in enumerate(submissions):
        if (record["schema_version"] != 1 or record["role"] != ("annotation" if index < 2 else "adjudication")
                or record["packet_sha256"] != packet_hash or not record["decisions"].keys() <= packet["queries"].keys()):
            raise ValueError("Submission revision or case IDs differ from the frozen packet")
    finalized, details = deepcopy(packet), {}
    for key, case in finalized["queries"].items():
        first, second = decisions = [annotation(record, key) for record in reviews]
        final = annotation(adjudication, key) if adjudication else None
        history = [{field: submission[field] for field in ("reviewer", "expertise", "revision")} |
                   {"decision": decision["decision"], "reason": decision["reason"], "decision_sha256": gold.digest(decision)}
                   for submission, decision in zip(reviews, decisions) if decision is not None]
        different = []
        if first and second:
            if first["decision"] != second["decision"]:
                different = ["decision"]
            elif first["decision"] == "annotate":
                a, b = label_signature(first["labels"]), label_signature(second["labels"])
                different = sorted(field for field in LABELS if a[field] != b[field])
        if final:
            if not first or not second or not different:
                raise ValueError(f"Adjudication requires two disagreeing decisions for {key}")
            if final["reviewed_decision_sha256"] != [gold.digest(row) for row in decisions]:
                raise ValueError(f"Adjudication is stale for {key}")
            history.append({field: adjudication[field] for field in ("reviewer", "expertise", "revision")} |
                           {"decision": final["decision"], "reason": final["reason"], "decision_sha256": gold.digest(final)})
        selected = final or (first if first and second and not different else None)
        if selected and selected["decision"] == "annotate":
            decision_author = adjudication if final else reviews[0]
            case.update(selected["labels"], status="approved", reviewer=decision_author["reviewer"],
                        expertise=decision_author["expertise"], revision_history=history)
            status = "adjudicated_approved" if final else "agreed_approved"
        elif selected:
            status = "excluded" if selected["decision"] == "exclude" else "deferred"
        else:
            status = "disagreement" if different else "one_review" if history else "awaiting_review"
        details[key] = {"status": status, "case_type": "control" if case["diagnostic"] else "corpus",
                        "disputed_fields": different, "decisions": history}
    eligible = gold.approved_queries(finalized, packet, source)
    return finalized, coverage_report(packet, finalized, details, len(eligible))


def coverage_report(packet, finalized=None, details=None, approved=0):
    if details is None:
        details = {key: {"status": "awaiting_review", "case_type": "control" if case["diagnostic"] else "corpus",
                         "disputed_fields": [], "decisions": []} for key, case in packet["queries"].items()}
    cohorts = {name: dict(Counter(row["status"] for row in details.values() if row["case_type"] == name))
               for name in ("corpus", "control")}
    source_checks = [item["snapshot_verified"] for case in packet["queries"].values() for item in case["draft_evidence"]]
    totals = Counter(row["status"] for row in details.values())
    return {"packet_sha256": gold.digest(packet), "review_sha256": gold.digest(finalized) if finalized else None,
            "approved": approved, "cases": len(details),
            "status_counts": dict(totals),
            "release_counts": {"approved": approved, "rejected": totals["excluded"], "disputed": totals["disagreement"],
                               "pending": sum(totals[state] for state in ("awaiting_review", "one_review", "deferred"))},
            "by_cohort": cohorts, "draft_source_checks": {"verified": sum(source_checks), "total": len(source_checks)},
            "unresolved_ids": [key for key, row in details.items()
                               if row["status"] in {"awaiting_review", "one_review", "deferred", "disagreement"}],
            "rows": details}


def freeze_gold(finalized, approved, report, version):
    if not version.strip() or report["review_sha256"] != gold.digest(finalized):
        raise ValueError("Release needs a version and the matching adjudication report")
    cases = report["rows"]
    if set(cases) != finalized["queries"].keys():
        raise ValueError("Adjudication does not cover the frozen cohort")
    if set(approved) != {key for key, row in cases.items() if row["status"] in {"agreed_approved", "adjudicated_approved"}}:
        raise ValueError("Approved cases differ from adjudication")
    if not approved or any(key not in approved and row["status"] != "excluded" for key, row in cases.items()):
        raise ValueError("Cannot freeze while required cases are pending, deferred, or disputed")
    return {"schema_version": 1, "gold_version": version, "dataset_sha256": finalized["dataset_sha256"],
            "corpus_sha256": finalized["corpus_sha256"], "review_sha256": report["review_sha256"],
            "adjudication_sha256": gold.digest(report), "queries": approved,
            "rejected_ids": sorted(cases.keys() - approved.keys())}


def freeze_splits(packet, approved, assignment):
    if (assignment.get("status") != "approved" or assignment["review_sha256"] != gold.digest(packet)
            or not str(assignment.get("split_version") or "").strip()):
        raise ValueError("Require a versioned split assignment approved for this exact review packet")
    reviewer(assignment)
    entries = assignment["cases"]
    splits = {"validation": [], "holdout": []}
    families = {}
    queries = {}
    for key, item in sorted(entries.items()):
        split, family = item["split"], item["family"]
        status = approved.get(key, {}).get("answerability")
        if split not in splits or not isinstance(family, str) or not family.strip() or status not in {
            "answerable", "partially_answerable", "unanswerable"
        }:
            raise ValueError(f"Unapproved or ineligible calibration case {key}")
        query = " ".join((approved[key].get("standalone") or approved[key]["query"]).casefold().split())
        if families.setdefault(family.strip().casefold(), split) != split or queries.setdefault(query, split) != split:
            raise ValueError(f"Case {key} leaks a question or family across splits")
        splits[split].append(key)
    support = {split: dict(Counter(gold.MODES[approved[key]["answerability"]] for key in ids))
               for split, ids in splits.items()}
    if any(set(counts) != {"FULL", "PARTIAL", "NOT_FOUND"} for counts in support.values()):
        raise ValueError("Both splits need approved examples of FULL, PARTIAL, and NOT_FOUND")
    return {"schema_version": 1, "split_version": assignment["split_version"],
            "review_sha256": assignment["review_sha256"], "assignment_sha256": gold.digest(assignment),
            "splits": splits, "support": support}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("template", "status", "resolve", "freeze", "splits"))
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=("annotation", "adjudication"), default="annotation")
    parser.add_argument("--annotation", type=Path, action="append", default=[])
    parser.add_argument("--gold-version")
    for name in ("adjudication", "snapshot", "report", "approved", "assignment", "release"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    packet = gold.read(args.packet)

    def write(path, data):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.operation == "template":
        write(args.output, template(packet, args.role))
        return
    if not args.snapshot:
        parser.error("Approval and splits require the frozen corpus snapshot")
    from evaluation.evaluate_platform import diagnostic_cases

    dataset = gold.read(gold.HERE / "real_insurance_dataset.json")
    documents = gold.read(args.snapshot)
    if packet != gold.review_packet(dataset, documents, list(diagnostic_cases(dataset))):
        parser.error("Use the immutable pending packet generated from the original corpus and controls")
    source = gold.indexed_sources(documents)
    if args.operation == "status":
        write(args.output, coverage_report(packet))
    elif args.operation in {"resolve", "freeze"}:
        if len(args.annotation) != 2 or not args.report:
            parser.error("Resolve and freeze require two --annotation files and --report")
        finalized, report = resolve(packet, list(map(gold.read, args.annotation)),
                                    gold.read(args.adjudication) if args.adjudication else None, source)
        write(args.report, report)
        if args.operation == "freeze":
            if not args.gold_version:
                parser.error("Freeze requires --gold-version")
            approved = gold.approved_queries(finalized, packet, source)
            write(args.output, freeze_gold(finalized, approved, report, args.gold_version))
        else:
            write(args.output, finalized)
    else:
        if not args.approved or not args.assignment or not args.release:
            parser.error("Splits require --approved, --assignment, and --release")
        finalized = gold.read(args.approved)
        approved = gold.approved_queries(finalized, packet, source)
        release = gold.read(args.release)
        if (release["review_sha256"] != gold.digest(finalized) or release["queries"] != approved
                or set(release["rejected_ids"]) != packet["queries"].keys() - approved.keys()
                or not release["gold_version"]):
            parser.error("Split inputs do not match the frozen gold release")
        assignment = gold.read(args.assignment)
        release_hash = gold.digest(release)
        if assignment.get("gold_release_sha256") != release_hash:
            parser.error("Split assignment must be approved for this gold release")
        write(args.output, {**freeze_splits(finalized, approved, assignment),
                            "gold_release_sha256": release_hash, "gold_version": release["gold_version"]})


if __name__ == "__main__":
    main()
