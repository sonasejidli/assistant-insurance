"""Measure dense retrieval on the labeled Azerbaijani insurance fixture."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from App.embedding import embed
from App.settings import EMBED_MODEL
from App.text_search import searchable_text


def main():
    fixture = json.loads(Path(__file__).with_name("bm25_cases.json").read_text(encoding="utf-8"))
    chunks = fixture["chunks"]
    passages = embed([searchable_text(chunk) for chunk in chunks])
    print(EMBED_MODEL, flush=True)
    for split in ("tuning", "holdout"):
        cases = fixture[split]
        queries = embed([case["question"] for case in cases], kind="query")
        ranks = (-(queries @ passages.T)).argsort(axis=1, kind="stable")
        for k in (1, 3, 5):
            recalls = []
            reciprocal_ranks = []
            for order, case in zip(ranks, cases):
                relevant = set(case["relevant_docs"])
                hits = [rank for rank, index in enumerate(order[:k], 1) if chunks[index]["doc"] in relevant]
                recalls.append(len(hits) / len(relevant))
                reciprocal_ranks.append(1 / hits[0] if hits else 0)
            print(f"{split} ({len(cases)} queries) @ {k}: recall={sum(recalls)/len(cases):.3f}, "
                  f"MRR={sum(reciprocal_ranks)/len(cases):.3f}", flush=True)


if __name__ == "__main__":
    main()
