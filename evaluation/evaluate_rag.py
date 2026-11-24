import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from App import text_search


def main():
    parser = argparse.ArgumentParser(description="Evaluate retrieval on a small synthetic, labelled corpus.")
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).with_name("rag_cases.json"),
                        help="Path to a labelled corpus and its evaluation cases.")
    parser.add_argument("--min-recall", type=float,
                        help="Fail if mean recall at the chosen cutoff is below this fraction (0 to 1).")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be positive")
    if args.min_recall is not None and not 0 <= args.min_recall <= 1:
        parser.error("--min-recall must be between 0 and 1")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    if not fixture["cases"]:
        parser.error("the fixture must contain at least one evaluation case")
    indexed_docs = {chunk["doc"] for chunk in fixture["chunks"]}
    for case in fixture["cases"]:
        relevant = set(case["relevant_docs"])
        if not relevant or not relevant <= indexed_docs:
            parser.error(f"{case['question']!r} must label at least one document from the fixture")
    sys.stdout.reconfigure(errors="backslashreplace")
    with patch.object(text_search, "load_chunks", return_value=fixture["chunks"]):
        retriever = text_search.TextRetriever()
    recalls = []
    reciprocal_ranks = []
    for case in fixture["cases"]:
        hits, _ = retriever.search(case["question"], k=args.k)
        ranked = [hit["doc"] for hit in hits]
        relevant = set(case["relevant_docs"])
        recall = len(relevant.intersection(ranked)) / len(relevant)
        reciprocal_rank = next((1 / rank for rank, doc in enumerate(ranked, 1) if doc in relevant), 0.0)
        recalls.append(recall)
        reciprocal_ranks.append(reciprocal_rank)
        print(f"{case['question']} | recall={recall:.2f} | rank={ranked}")
    mean_recall = sum(recalls) / len(recalls)
    print(f"Mean recall@{args.k}: {mean_recall:.3f}")
    print(f"MRR@{args.k}: {sum(reciprocal_ranks) / len(reciprocal_ranks):.3f}")
    if args.min_recall is not None and mean_recall < args.min_recall:
        print(f"Recall@{args.k} fell below the required {args.min_recall:.1%}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
