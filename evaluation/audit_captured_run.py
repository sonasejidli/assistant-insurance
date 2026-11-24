"""Export citation evidence and trace-local retrieval diagnostics for manual review."""

import argparse
import json
from pathlib import Path

from evaluation.evaluate_latest_seven import validate
from evaluation.gold_framework import indexed_sources, read
from evaluation.rag_run import DRAFT, load, replay


def audit(run, dataset, documents):
    validate(dataset, documents)
    report = replay(run, dataset)
    sources = indexed_sources(documents)
    rows = []
    for case, scored in zip(dataset["queries"], report["rows"], strict=True):
        row = load(run / f"{case['id']}.json")
        ranked = row["ranked_passage_ids"]
        branches = row["branches"]
        requested = case["required_passage_ids"]
        positions = {}
        for pid in requested:
            positions[pid] = [
                {stage: next((item for item in branch.get(stage, []) if item["passage_id"] == pid), None)
                 for stage in ("bm25", "dense", "fusion", "reranked")}
                for branch in branches
            ]
        bindings = row.get("citation_passages", {})
        if bindings:
            packed = {item["id"]: item["passage_id"] for item in row["generation_attempts"][-1]["sources"]}
            if any(packed.get(marker) != pid for marker, pid in bindings.items()):
                raise ValueError(f"Citation differs from final packed source in {case['id']}")
        refs = {}
        for marker, pid in bindings.items():
            hit = sources[pid]
            metadata = hit["metadata"]
            refs[marker] = {"passage_id": pid, "text": hit["text"], **{
                key: metadata.get(key) for key in ("document_name", "law_name", "article", "clause", "page_number")
            }}
        rows.append({"id": case["id"], "query": row["query"], "expected_mode": case["expected_mode"],
                     "mode": row.get("mode"), "decision_reason": row.get("decision_reason"),
                     "answer": row.get("answer"), "source_bindings": refs,
                     "generation_attempts": row["generation_attempts"], "provider_calls": row.get("provider_calls"),
                     "operational": scored["operational"], "recall@5": scored["metrics"]["retrieval"]["recall@5"],
                     "ranked_passage_ids": ranked, "required_ranks_by_branch": positions,
                     "branch_sizes": [{stage: len(branch.get(stage, []))
                                       for stage in ("bm25", "dense", "fusion", "reranked")} for branch in branches],
                     "part_evidence_in_top_5": {part: [pid for pid in value["required_passage_ids"] if pid in ranked[:5]]
                                                for part, value in case["parts"].items()}})
    return {"run_id": report["run_id"], "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run, read(DRAFT), read(args.snapshot))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
