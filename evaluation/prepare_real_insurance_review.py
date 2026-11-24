"""Prepare expert label review and optionally capture unscored candidate answers."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.build_real_insurance_dataset import digest


RUBRIC = {
    "factual_correctness": None,
    "evidence_coverage": None,
    "citation_correctness": None,
    "conditions_and_exceptions_preserved": None,
    "invented_provisions": None,
    "appropriate_abstention": None,
    "reviewer": None,
    "expertise": None,
    "notes": "",
}


def label_review(dataset):
    return {
        "dataset_sha256": digest(dataset),
        "instructions": "Review the actual cited passages, plausible alternative sources, scope, and coverage before approving.",
        "queries": {
            item["id"]: {"status": "pending", "reviewer": None, "expertise": None,
                         "notes": "", "failure_category": None, "failure_evidence": ""}
            for item in dataset["queries"]
        },
    }


def answer_packet(dataset, results, documents, ids, generate):
    by_id = {chunk["metadata"]["chunk_id"]: chunk for doc in documents for chunk in doc["chunks"]}
    trials = {row["id"]: row["versions"]["after"] for row in results["rows"]}
    answers = []
    for item in dataset["queries"]:
        if item["id"] not in ids:
            continue
        trial = trials[item["id"]]
        assembled = trial["assembled_parent_ids"]
        has_required = set(item["relevant_parent_passage_ids"]) <= set(assembled)
        row = {
            "id": item["id"], "question": item["query"], "history_used": trial["history_used"],
            "expected_coverage": item["covered"], "has_all_required_parents": has_required,
            "retrieval_stage": "reranked" if "reranked" in trial["ranks"] else "rrf",
            "expected_evidence": item["evidence"], "context": [
                {"parent_passage_id": key, "document": by_id[key]["doc"], "text": by_id[key]["text"]}
                for key in assembled
            ],
            "status": "pending_capture", "answer": None, "citations": [], "review": dict(RUBRIC),
        }
        if item["covered"] and not has_required:
            row["status"] = "blocked_by_missing_evidence"
        elif generate:
            from App import system

            hits = [by_id[key] for key in assembled]
            start = perf_counter()
            try:
                answer = system.answer_question(item["query"], hits, language="az", history=trial["history_used"])
                row["answer"] = answer
                indexes = system.cited_indexes(answer, hits) or []
                row["citations"] = [{"source": f"S{i+1}", "parent_passage_id": assembled[i]} for i in indexes]
                row["status"] = "abstention_candidate" if answer == system.NOT_FOUND else "pending_human_review"
            except Exception as exc:
                row.update(status="generation_service_error", error_type=type(exc).__name__)
            row["generation_ms"] = (perf_counter() - start) * 1000
        answers.append(row)
    return {"dataset_sha256": digest(dataset), "human_scoring_status": "pending", "answers": answers}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--ids", nargs="+", default=[])
    parser.add_argument("--generate", action="store_true", help="Invoke the configured answer provider for selected cases")
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if args.labels:
        if args.labels.exists():
            parser.error("Keep existing reviewer work. Choose a new label review output path.")
        write(args.labels, label_review(dataset))
    if args.answers:
        if not (args.results and args.snapshot and args.ids):
            parser.error("Answer packets require results, snapshot, and explicit query IDs")
        results, documents = (json.loads(path.read_text(encoding="utf-8")) for path in (args.results, args.snapshot))
        if results["dataset_sha256"] != digest(dataset):
            parser.error("Results must match this exact dataset")
        if not set(args.ids) <= {row["id"] for row in dataset["queries"]}:
            parser.error("Unknown query ID")
        if args.answers.exists():
            parser.error("Keep existing reviewer work. Choose a new answer review output path.")
        packet = answer_packet(dataset, results, documents, set(args.ids), args.generate)
        write(args.answers, packet)
        print(Counter(row["status"] for row in packet["answers"]))


if __name__ == "__main__":
    main()
