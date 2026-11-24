"""Validate the seven-case draft and score an optional capture of the original run."""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean

from evaluation.gold_framework import HERE, MODES, digest, indexed_sources, read, retrieval_scores, verify_source


ANSWER_MODES = {MODES[key] for key in ("answerable", "partially_answerable", "unanswerable")}
TRACE_ERROR_LABELS = {
    "Retrieval miss", "Candidate recall failure", "Reranking failure", "Evidence assembly failure",
    "Multipart decomposition or attribution failure", "Query normalization failure", "Domain routing failure",
}
ERROR_LABELS = TRACE_ERROR_LABELS | {
    "Unsupported inference", "Citation validation failure", "Incomplete answer", "Incorrect answer mode",
}
METRICS = (
    "recall@5", "recall@10", "mrr@10", "ndcg@10", "citation_precision", "citation_completeness",
    "multipart_evidence_coverage", "answer_correctness", "answer_mode_accuracy",
)


def expected_mode(parts):
    modes = {part["expected_mode"] for part in parts.values()}
    return next(iter(modes)) if len(modes) == 1 else "PARTIAL"


def evidence_pairs(case):
    return {(key, pid) for key, part in case["parts"].items() for pid in part["required_passage_ids"]}


def validate(dataset, documents=None):
    cases = dataset["queries"]
    if (dataset["schema_version"] != 1 or dataset["gold"] is not False
            or dataset["status"] != "pending_domain_expert"
            or len(cases) != 7 or len({case["query"] for case in cases}) != 7):
        raise ValueError("Expected seven unique questions in an unreleased draft")
    if documents is not None:
        snapshot = [(hit["metadata"]["chunk_id"], hit["text"]) for doc in documents for hit in doc["chunks"]]
        if (len(snapshot), digest(snapshot)) != (dataset["parent_count"], dataset["corpus_sha256"]):
            raise ValueError("Snapshot differs from the frozen corpus")
        source = indexed_sources(documents)
        by_document = {doc["doc"]: doc["chunks"] for doc in documents}
    for i, case in enumerate(cases, 1):
        parts = case["parts"]
        direct = {item["passage_id"] for item in case["evidence"] if item["role"] == "direct"}
        if (case["id"] != f"AZ7-{i:02}" or not case["query"].strip() or not case["domain"]
                or case["domain_scope"] not in {"in_corpus", "out_of_domain"}
                or case["status"] != "pending" or case["observation_status"] != "missing"
                or case["observed"] is not None or case["error_labels"] is not None
                or not parts or case["expected_mode"] != expected_mode(parts)
                or MODES.get(case["answerability"]) != case["expected_mode"]
                or direct != set(case["required_passage_ids"]) or direct != {pid for _, pid in evidence_pairs(case)}
                or len({item["passage_id"] for item in case["evidence"]}) != len(case["evidence"])):
            raise ValueError(f"Invalid case {case['id']}")
        for part in parts.values():
            mode = part["expected_mode"]
            ids = part["required_passage_ids"]
            if (mode not in ANSWER_MODES or not part["question"].strip()
                    or len(ids) != len(set(ids))
                    or bool(ids) != (mode != "NOT_FOUND")
                    or bool(part["expected_answer"]) != bool(ids)
                    or bool(part["unresolved"]) != (mode != "FULL")):
                raise ValueError(f"Inconsistent evidence or unresolved label in {case['id']}")
        for item in case["evidence"]:
            if (item["role"] not in {"direct", "related"}
                    or item["relevance"] != (3 if item["role"] == "direct" else None)
                    or item["page"] < 1 or item["chunk_ordinal"] < 0 or not item["text"].strip()):
                raise ValueError(f"Invalid source label in {case['id']}")
            if documents is not None:
                hit = source.get(item["passage_id"])
                if hit is None or not verify_source(hit, item):
                    raise ValueError(f"Source text or identifiers mismatch in {case['id']}")
                meta = hit["metadata"]
                original = meta.get("original_text") if meta.get("original_text_verbatim") else None
                if (item["page"] != meta.get("page_number") or item["original_text"] != original
                        or item["document"] != meta["document_name"] or item["law_name"] != meta["law_name"]
                        or item["law_number"] != meta.get("law_number")
                        or by_document[item["document"]][item["chunk_ordinal"]] != hit):
                    raise ValueError(f"PDF locator mismatch in {case['id']}")


def score(case, observed):
    scores = dict.fromkeys(METRICS)
    blocked = dict.fromkeys(METRICS, "Original observation unavailable")
    if observed is None:
        return scores, blocked
    if (observed["query"] != case["query"] or not isinstance(observed["answer"], str)
            or not observed["artifact"]):
        raise ValueError(f"Original output provenance required for {case['id']}")

    grades = {item["passage_id"]: item["relevance"] for item in case["evidence"] if item["role"] == "direct"}
    required = evidence_pairs(case)
    order = observed.get("ranked_passage_ids")
    blocked.update(dict.fromkeys(METRICS[:4], "Missing ranked retrieval or direct evidence labels"))
    if order is not None:
        retrieval = retrieval_scores(order[:10], grades)
        if retrieval is not None:
            scores.update({metric: retrieval[metric] for metric in METRICS[:4] if metric != "mrr@10"})
            scores["mrr@10"] = retrieval["mrr@20"]  # The input is truncated to ten above.

    blocked["multipart_evidence_coverage"] = "Requires multipart labels and assembled passage attribution"
    attributions = observed.get("part_passage_ids")
    if len(case["parts"]) > 1 and attributions is not None and required:
        attributed = {(part, pid) for part, ids in attributions.items() for pid in ids}
        scores["multipart_evidence_coverage"] = len(required & attributed) / len(required)

    blocked["answer_mode_accuracy"] = "Missing explicit answer mode or applicable mode label"
    if observed.get("mode") in ANSWER_MODES and case["domain_scope"] == "in_corpus":
        scores["answer_mode_accuracy"] = observed["mode"] == case["expected_mode"]
    blocked.update(dict.fromkeys(("citation_precision", "citation_completeness", "answer_correctness"),
                                 "Requires reviewed judgments tied to the exact answer"))
    review = observed.get("generation_review")
    if review is not None:
        answer_hash = hashlib.sha256(observed["answer"].encode("utf-8")).hexdigest()
        if (review["status"] != "approved" or not review["reviewer"] or not review["expertise"]
                or review["answer_sha256"] != answer_hash):
            raise ValueError(f"Unapproved or unbound generation review for {case['id']}")
        if type(review.get("correct")) is bool:
            scores["answer_correctness"] = review["correct"]
        citations = review.get("citations")
        if citations is not None:
            if any(type(citation["supports_claim"]) is not bool for citation in citations):
                raise ValueError("Citation review requires a support judgment for each citation occurrence")
            supported = [citation for citation in citations if citation["supports_claim"]]
            if citations:
                scores["citation_precision"] = len(supported) / len(citations)
            else:
                blocked["citation_precision"] = "No emitted citation occurrences"
            if required:
                cited = {(citation["part"], citation["passage_id"]) for citation in supported}
                scores["citation_completeness"] = len(required & cited) / len(required)
    return scores, {metric: blocked[metric] for metric in METRICS if scores[metric] is None}


def evaluate(dataset, observations):
    if set(observations) - {case["id"] for case in dataset["queries"]}:
        raise ValueError("Unknown observation IDs")
    rows = []
    for case in dataset["queries"]:
        observed = observations.get(case["id"])
        metrics, blocked = score(case, observed)
        errors = None if observed is None else observed.get("error_labels")
        if errors is not None and any(
            error["label"] not in ERROR_LABELS or not error["evidence"]
            or (error["label"] in TRACE_ERROR_LABELS and not error.get("trace_stage"))
            for error in errors
        ):
            raise ValueError("Error labels require a trace or output evidence locator")
        rows.append({"id": case["id"], "metrics": metrics, "blocked": blocked, "error_labels": errors})
    summary = {}
    for metric in METRICS:
        values = [row["metrics"][metric] for row in rows if row["metrics"][metric] is not None]
        summary[metric] = {"n": len(values), "mean": mean(values) if values else None}
    return {"draft_only": True, "summary": summary, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=HERE / "latest_seven_dataset.json")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--observations", type=Path, help="Original run capture keyed by AZ7 case ID")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dataset = read(args.dataset)
    validate(dataset, read(args.snapshot))
    report = evaluate(dataset, read(args.observations) if args.observations else {})
    result = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()
