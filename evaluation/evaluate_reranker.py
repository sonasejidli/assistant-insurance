"""Evaluate Azerbaijani reranking on synthetic hard-negative insurance passages."""

import json
import sys
from pathlib import Path
from statistics import mean
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.documents import Document

from App import text_search


def main():
    fixture = json.loads(Path(__file__).with_name("reranker_cases.json").read_text(encoding="utf-8"))
    rankings = {}

    def capture(question, documents):
        rankings[question] = documents
        return documents

    with patch.object(text_search, "load_chunks", return_value=fixture["chunks"]):
        retriever = text_search.TextRetriever()
    try:
        with patch.object(text_search, "rerank_documents", side_effect=capture):
            for case in fixture["cases"]:
                retriever.search(case["question"])
    finally:
        retriever.close()

    orders = {"RRF": [], "Text-only cross-encoder": [], "Contextual cross-encoder": []}
    for case in fixture["cases"]:
        question = case["question"]
        documents = [doc for doc in rankings[question] if doc.metadata["doc"] in case["candidates"]]
        if len(documents) != len(case["candidates"]):
            raise RuntimeError(f"RRF did not retrieve all hard negatives for {question!r}")
        plain = [Document(page_content=doc.page_content, metadata={"doc": doc.metadata["doc"]}) for doc in documents]
        # The evaluation must fail on model errors instead of silently reporting fallback scores.
        for label, candidates in (("RRF", documents), ("Text-only cross-encoder", plain),
                                  ("Contextual cross-encoder", documents)):
            if label != "RRF":
                candidates = text_search.rank_with_cross_encoder(question, candidates)
            rank = next(i for i, doc in enumerate(candidates, 1) if doc.metadata["doc"] == case["relevant"])
            orders[label].append(rank)
        print(f"{case['relevant']}: " + ", ".join(f"{label} rank {ranks[-1]}" for label, ranks in orders.items()),
              flush=True)
    for label, ranks in orders.items():
        print(f"{label}: hit@1={mean(rank == 1 for rank in ranks):.3f}, "
              f"MRR={mean(1 / rank for rank in ranks):.3f}", flush=True)


if __name__ == "__main__":
    main()
