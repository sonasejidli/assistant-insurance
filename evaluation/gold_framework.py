"""Audit frozen legal labels, score paired runs, and calibrate offline."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import mean


HERE = Path(__file__).resolve().parent
MODES = {"answerable": "FULL", "partially_answerable": "PARTIAL", "unanswerable": "NOT_FOUND",
         "ambiguous": "CLARIFY", "conflicting": "CONFLICTING"}
GROUPS = ("negative_claim", "multipart", "missing_knowledge", "informal", "formal")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(value):
    from evaluation.build_real_insurance_dataset import digest as benchmark_digest
    return benchmark_digest(value)


def indexed_sources(documents):
    return {hit["metadata"]["chunk_id"]: hit for doc in documents for hit in doc["chunks"]}


def verify_source(hit, label):
    meta = hit["metadata"]
    parent = meta.get("parent_passage_id") or meta["chunk_id"]
    return (label["parent_passage_id"] == parent
            and all(label.get(field) == meta.get(field) for field in ("document_id", "article", "clause"))
            and label["text"] == hit["text"])


def review_packet(dataset, documents, controls):
    from evaluation.evaluate_real_insurance import validate_dataset

    source = indexed_sources(documents)
    validate_dataset(dataset, list(source.values()))
    rows = {}
    for case in [*dataset["queries"], *controls]:
        groups = [case["style"]] if case.get("style") in {"informal", "formal"} else []
        if case.get("part_parents"):
            groups.append("multipart")
        if case["category"] == "coverage_gap":
            groups.append("missing_knowledge")
        if case["id"].startswith("NEG"):
            groups.append("negative_claim")
        evidence = [{**label, "snapshot_verified": (
            label["passage_id"] in source and verify_source(source[label["passage_id"]], label)
        )} for label in case["evidence"]]
        rows[case["id"]] = {
            "query": case["query"], "history": case["history"], "category": case["category"],
            "style": case.get("style"), "groups": groups, "diagnostic": case["id"].startswith(("NEG", "MP")),
            "standalone": case.get("expected_standalone_query") or case.get("expected_standalone"),
            "draft_evidence": evidence,
            "draft_part_parents": {f"Q{i}": ids for i, ids in enumerate(case.get("part_parents", []), 1)},
            "status": "pending", "reviewer": None, "expertise": None, "revision_history": [],
            "answerability": None, "evidence": [], "required_passage_ids": None,
            "parts": {}, "expected_answer": None, "required_qualifications": None,
        }
    return {"schema_version": 1, "dataset_sha256": digest(dataset), "corpus_sha256": dataset["corpus_sha256"],
            "queries": rows}


def approved_queries(packet, expected, source):
    if (packet["schema_version"] != 1 or packet["dataset_sha256"] != expected["dataset_sha256"]
            or packet["corpus_sha256"] != expected["corpus_sha256"] or set(packet["queries"]) != set(expected["queries"])):
        raise ValueError("Review packet does not match the frozen dataset and controls")
    approved = {}
    for key, row in packet["queries"].items():
        fixed = expected["queries"][key]
        if row["status"] == "pending":
            continue
        evidence = row["evidence"]
        ids = {label["passage_id"] for label in evidence}
        required = row["required_passage_ids"]
        answerability = row["answerability"]
        if (row["status"] != "approved" or not all(str(row.get(field) or "").strip() for field in ("reviewer", "expertise"))
                or not row["revision_history"] or answerability not in MODES
                or any(row[field] != fixed[field] for field in ("query", "history", "category", "style", "diagnostic"))
                or not set(fixed["groups"]) <= set(row["groups"]) <= set(GROUPS)
                or not isinstance(required, list) or len(set(required)) != len(required) or not set(required) <= ids
                or not isinstance(row["required_qualifications"], list) or not str(row.get("expected_answer") or "").strip()
                or len(ids) != len(evidence) or any(type(label["relevance"]) is not int or not 1 <= label["relevance"] <= 3
                    or label["passage_id"] not in source or not verify_source(source[label["passage_id"]], label)
                    for label in evidence)
                or answerability in {"answerable", "partially_answerable", "conflicting"} and not required
                or answerability == "unanswerable" and required
                or not set(fixed["draft_part_parents"]) <= row["parts"].keys()
                or any(not part["question"].strip() or not isinstance(part["required_passage_ids"], list)
                       or not set(part["required_passage_ids"]) <= set(required) for part in row["parts"].values())
                or row["parts"] and set(required) != {pid for part in row["parts"].values() for pid in part["required_passage_ids"]}):
            raise ValueError(f"Invalid expert approval for {key}")
        approved[key] = row
    return approved


def retrieval_scores(order, grades):
    if len(order) != len(set(order)):
        raise ValueError("Ranked passage IDs must be distinct")
    if not grades:
        return None
    def dcg(relevances):
        return sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(relevances))
    return {
        **{f"recall@{k}": sum(pid in grades for pid in order[:k]) / len(grades) for k in (5, 10)},
        "mrr@20": next((1 / i for i, pid in enumerate(order[:20], 1) if pid in grades), 0),
        "ndcg@10": dcg([grades.get(pid, 0) for pid in order[:10]]) / dcg(sorted(grades.values(), reverse=True)[:10]),
    }


def summary(rows):
    metrics = {key for row in rows for key in row}
    return {key: {"n": len(values), "mean": mean(values)} for key in sorted(metrics)
            if (values := [row[key] for row in rows if row.get(key) is not None])}


def run_rows(run):
    rows = {row["id"]: row for row in run["rows"]}
    if len(rows) != len(run["rows"]):
        raise ValueError("Duplicate evaluation cases")
    return rows


def score_run(run, labels, source):
    observations = run_rows(run)
    if observations.keys() != labels.keys():
        raise ValueError("Both runs must cover the same approved cohort")
    rows, summaries = {}, {}
    for key, label in labels.items():
        observed = observations[key]
        order = observed["ranked_passage_ids"]
        if not set(order) <= source.keys() or observed["mode"] not in MODES.values():
            raise ValueError(f"Unknown ranked passage or answer mode for {key}")
        grades = {item["passage_id"]: item["relevance"] for item in label["evidence"]}
        missing = sorted(set(label["required_passage_ids"]) - set(order[:10]))
        attributions = observed.get("part_passage_ids", {})
        missing_parts = {part: sorted(set(data["required_passage_ids"]) - (set(attributions.get(part, ())) & set(order[:10])))
                         for part, data in label["parts"].items()}
        expected_pairs = {(part, pid) for part, data in label["parts"].items() for pid in data["required_passage_ids"]}
        observed_pairs = {(part, pid) for part, ids in attributions.items() for pid in ids if pid in order[:10]}
        mode = MODES[label["answerability"]]
        judgment = observed.get("generation_review")
        generated = {}
        if judgment is not None:
            answer_hash = hashlib.sha256(observed["answer"].encode("utf-8")).hexdigest()
            if (judgment["status"] != "approved" or judgment["answer_sha256"] != answer_hash
                    or not judgment["reviewer"] or not judgment["expertise"] or not judgment["rubric_version"]
                    or any(judgment[field] is not None and type(judgment[field]) is not bool
                           for field in ("faithfulness", "relevancy"))):
                raise ValueError(f"Generation judgments must be approved and bound to the output for {key}")
            generated = {name: judgment[name] for name in ("faithfulness", "relevancy")}
        retrieval = retrieval_scores(order, grades) or {}
        if label["required_passage_ids"]:
            retrieval["complete_required_at_10"] = not missing
        if label["parts"]:
            retrieval["complete_multipart_at_10"] = not any(missing_parts.values())
        rows[key] = {"retrieval": retrieval, "generation": generated,
                     "behavior": {"answer_mode_accuracy": observed["mode"] == mode,
                                  "unsafe_full": observed["mode"] == "FULL" and mode != "FULL"},
                     "missing_required_at_10": missing, "missing_by_part_at_10": missing_parts,
                     "extra_attributions_at_10": sorted(observed_pairs - expected_pairs),
                     "expected_mode": mode, "actual_mode": observed["mode"]}
    for group in ("overall", *GROUPS):
        ids = [key for key, label in labels.items() if group == "overall" or group in label["groups"]]
        summaries[group] = {"cases": len(ids), **{axis: summary([rows[key][axis] for key in ids])
                             for axis in ("retrieval", "generation", "behavior")}}
    return {"summary": summaries, "rows": rows}


def paired_deltas(before, after, labels):
    result = {}
    for group in ("overall", *GROUPS):
        ids = [key for key, label in labels.items() if group == "overall" or group in label["groups"]]
        axes = {}
        for axis in ("retrieval", "generation", "behavior"):
            rows = []
            for key in ids:
                a, b = before["rows"][key][axis], after["rows"][key][axis]
                rows.append({metric: b[metric] - value for metric, value in a.items()
                             if value is not None and b.get(metric) is not None})
            axes[axis] = summary(rows)
        result[group] = axes
    return result


def calibrate(run, labels, policy):
    observed = run_rows(run)
    if (policy.get("status") != "approved" or not policy.get("reviewer") or not policy.get("expertise")
            or policy["score_version"] != run["score_version"] or policy["configuration_id"] != run["configuration_id"]
            or not policy.get("candidates") or type(policy.get("max_unsafe_full")) is not int or policy["max_unsafe_full"] < 0):
        raise ValueError("Calibration requires an approved, version-matched candidate policy")
    splits = policy["splits"]
    fit, test = splits["validation"], splits["holdout"]
    if not fit or not test or len(set(fit + test)) != len(fit + test) or not set(fit + test) <= labels.keys():
        raise ValueError("Calibration and holdout cases must be disjoint and expert-approved")
    expected = {key: MODES[labels[key]["answerability"]] for key in fit + test}
    if any(mode in {"CLARIFY", "CONFLICTING"} for mode in expected.values()):
        raise ValueError("Evaluate clarification and conflict routing separately from numeric calibration")
    for split in (fit, test):
        if {expected[key] for key in split} != {"FULL", "PARTIAL", "NOT_FOUND"}:
            raise ValueError("Each calibration split needs expert labels for all three answer modes")
    def measure(ids, thresholds=None):
        predictions = {}
        for key in ids:
            if thresholds is None:
                predictions[key] = observed[key]["mode"]
                continue
            score = observed[key]["score"]
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError(f"Missing or invalid versioned confidence score for {key}")
            full, partial = thresholds["full"], thresholds["partial"]
            predictions[key] = "FULL" if score >= full else "PARTIAL" if score >= partial else "NOT_FOUND"
        return {"n": len(ids), "accuracy": mean(predictions[key] == expected[key] for key in ids),
                "unsafe_full": sum(predictions[key] == "FULL" and expected[key] != "FULL" for key in ids),
                "predictions": predictions}
    candidates = []
    for thresholds in policy["candidates"]:
        full, partial = thresholds["full"], thresholds["partial"]
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (full, partial)) or partial >= full:
            raise ValueError("Candidate must specify finite PARTIAL < FULL cutoffs")
        validation = measure(fit, thresholds)
        if validation["unsafe_full"] <= policy["max_unsafe_full"]:
            candidates.append((validation, thresholds))
    if not candidates:
        return {"status": "blocked", "reason": "No approved candidate met the validation safety budget"}
    validation, selected = min(candidates, key=lambda pair: (-pair[0]["accuracy"], pair[0]["unsafe_full"]))
    holdout = measure(test, selected)
    return {"status": "evaluated" if holdout["unsafe_full"] <= policy["max_unsafe_full"] else "holdout_safety_failed",
            "selected": selected, "validation": validation, "holdout_before": measure(test), "holdout_after": holdout}


def draft_baseline(dataset, archived):
    if archived["expert_approved"] or archived["dataset_sha256"] != digest(dataset):
        raise ValueError("Draft measurements differ from the frozen dataset")
    results = run_rows(archived)
    if results.keys() != {case["id"] for case in dataset["queries"]}:
        raise ValueError("Draft measurements must cover the entire dataset")
    grouped = {}
    for group in ("overall", "formal", "informal", "missing_knowledge"):
        rows = [results[case["id"]] for case in dataset["queries"] if group == "overall" or group == case["style"]
                or group == "missing_knowledge" and not case["covered"]]
        grouped[group] = {"cases": len(rows)}
        for version in ("before", "after"):
            stage_rows = [row["versions"][version] for row in rows]
            grouped[group][version] = {
                "retrieval": {stage: summary([row["metrics"].get(stage) or {} for row in stage_rows])
                              for stage in ("bm25", "dense", "rrf")},
                "failure_counts": dict(Counter(row.get("failure") or "none" for row in stage_rows)),
            }
    return grouped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("packet", "audit", "compare"))
    parser.add_argument("--snapshot", type=Path, required=True)
    for name in ("reviews", "before", "after", "policy", "split-manifest", "output"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    from evaluation.evaluate_platform import diagnostic_cases

    dataset = read(HERE / "real_insurance_dataset.json")
    documents = read(args.snapshot)
    packet = review_packet(dataset, documents, list(diagnostic_cases(dataset)))
    source = indexed_sources(documents)
    approved = approved_queries(read(args.reviews), packet, source) if args.reviews else {}
    if args.operation == "packet":
        output = packet
    elif args.operation == "audit":
        cases = [row for row in packet["queries"].values() if not row["diagnostic"]]
        evidence = [item for row in cases for item in row["draft_evidence"]]
        output = {"dataset_sha256": packet["dataset_sha256"], "queries": len(cases),
                  "diagnostics": len(packet["queries"]) - len(cases), "approved": sum(not row["diagnostic"] for row in approved.values()),
                  "approved_diagnostics": sum(row["diagnostic"] for row in approved.values()),
                  "pending_ids": sorted(packet["queries"].keys() - approved.keys()),
                  "draft_evidence_rows": len(evidence), "verified_source_rows": sum(item["snapshot_verified"] for item in evidence),
                  "missing_source_article": sum(not item["article"] for item in evidence),
                  "missing_source_clause": sum(not item["clause"] for item in evidence),
                  "group_counts": {group: sum(group in row["groups"] for row in packet["queries"].values()) for group in GROUPS},
                  "draft_baseline": draft_baseline(dataset, read(HERE / "real_insurance_draft_results.json")),
                  "gold_generation": None, "gold_behavior": None, "calibration": {"status": "not_run"}}
    else:
        if not approved or not all((args.before, args.after, args.reviews)):
            parser.error("Paired scoring requires approved labels and two recorded runs")
        before, after = read(args.before), read(args.after)
        review_hash = digest(read(args.reviews))
        for run in (before, after):
            if (run["review_sha256"] != review_hash or run["corpus_sha256"] != packet["corpus_sha256"]
                    or not run["configuration_id"] or not run["evaluated_commit"]):
                parser.error("Runs must identify the approved packet, corpus, commit, and configuration")
        before_result, after_result = (score_run(run, approved, source) for run in (before, after))
        output = {"review_sha256": review_hash, "approved_cases": len(approved),
                  "pending_cases": len(packet["queries"]) - len(approved),
                  "runs": [{field: run[field] for field in ("configuration_id", "evaluated_commit")} for run in (before, after)],
                  "before": before_result, "after": after_result,
                  "paired_deltas": paired_deltas(before_result, after_result, approved),
                  "calibration": {"status": "not_run"}}
        if args.policy:
            policy = read(args.policy)
            if not args.split_manifest:
                parser.error("Calibration requires an approved, frozen split manifest")
            manifest = read(args.split_manifest)
            if (manifest["review_sha256"] != review_hash or policy["review_sha256"] != review_hash
                    or policy["split_manifest_sha256"] != digest(manifest)
                    or ("splits" in policy and policy["splits"] != manifest["splits"])):
                parser.error("Calibration policy and splits must identify the same approved review and manifest")
            output["calibration"] = {**calibrate(after, approved, {**policy, "splits": manifest["splits"]}),
                                     "split_version": manifest["split_version"], "split_manifest_sha256": digest(manifest)}
            if "selected" in output["calibration"]:
                holdout = {key: approved[key] for key in manifest["splits"]["holdout"]}
                baseline, candidate = (score_run({**run, "rows": [row for row in run["rows"] if row["id"] in holdout]},
                                                 holdout, source) for run in (before, after))
                output["holdout_performance"] = {"cases": len(holdout), "before": baseline, "after": candidate,
                                                 "paired_deltas": paired_deltas(baseline, candidate, holdout),
                                                 "calibrated_answer_mode": output["calibration"]["holdout_after"]}
    content = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
