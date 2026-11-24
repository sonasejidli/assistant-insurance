import argparse
import json
import sys
from itertools import product
from math import log2
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from App.text_search import RetrievalBM25, lexical_query

BASELINE = (1.5, 0.75)
GRID = tuple(product((0.3, 0.6, 0.9, 1.2, 1.5, 2.0), (0.0, 0.25, 0.5, 0.75, 1.0)))


def evaluate(index, docs, cases, k):
    metrics = []
    for tokens, relevant in cases:
        scores = index.get_scores(tokens)
        order = sorted((i for i, score in enumerate(scores) if score > 0), key=lambda i: -scores[i])
        ranks = [rank for rank, i in enumerate(order[:k], 1) if docs[i] in relevant]
        dcg = sum(1 / log2(rank + 1) for rank in ranks)
        ideal = sum(1 / log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
        metrics.append((dcg / ideal, len(ranks) / len(relevant), 1 / ranks[0] if ranks else 0))
    return tuple(map(mean, zip(*metrics)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).with_name("bm25_cases.json"))
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be positive")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    chunks = fixture["chunks"]
    docs = [chunk["doc"] for chunk in chunks]
    splits = {}
    for name in ("tuning", "holdout"):
        cases = fixture[name]
        if not cases or any(not case["relevant_docs"] or not set(case["relevant_docs"]) <= set(docs) for case in cases):
            parser.error(f"{name} requires cases with valid document labels")
        splits[name] = [(lexical_query(case["question"])[0], set(case["relevant_docs"])) for case in cases]

    def score(params, split):
        index = RetrievalBM25.from_chunks(chunks, k1=params[0], b=params[1])
        return evaluate(index, docs, splits[split], args.k)

    tuning_scores = {params: score(params, "tuning") for params in GRID}
    best = max(GRID, key=lambda params: (tuning_scores[params], params == BASELINE))
    print(f"{len(GRID)} settings, {len(splits['tuning'])} tuning queries, {len(splits['holdout'])} held-out queries")
    print(f"Selection order: nDCG@{args.k}, recall@{args.k}, MRR@{args.k}, baseline on a complete tie")
    for label, params in (("Baseline", BASELINE), ("Selected", best)):
        print(f"{label}: k1={params[0]:g}, b={params[1]:g}")
        for split in splits:
            ndcg, recall, mrr = tuning_scores[params] if split == "tuning" else score(params, split)
            print(f"  {split}: nDCG={ndcg:.4f}, recall={recall:.4f}, MRR={mrr:.4f}")


if __name__ == "__main__":
    main()
