"""Paired dense evaluation on a fixed real-corpus subset, without Qdrant writes."""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

import numpy as np
import torch

from App import embedding, text_search
from App.query_resolution import resolve_query
from evaluation.evaluate_real_insurance import chunk_id, quality


CASES = {"AZR010", "AZR023", "AZR036", "AZR063", "AZR097", "AZR141"}


def evaluate(chunks, queries, *, contextual):
    start = perf_counter()
    texts = [text_search.embedding_passage_text(chunk, contextual=contextual) for chunk in chunks]
    plans = embedding.plan_passages(chunks, texts, contextual=contextual)
    flat = [part for groups in plans for part in groups]
    vectors = embedding.embed([part.text for part in flat], kind="passage", batch_size=8)
    prepared = (perf_counter() - start) * 1000
    starts = np.cumsum([0, *[len(group) for group in plans[:-1]]])
    query_vectors = embedding.embed([resolve_query(case["query"], case["history"]).standalone for case in queries], kind="query")
    rows = []
    for vector, case in zip(query_vectors, queries, strict=True):
        scores = np.maximum.reduceat(vectors @ vector, starts)
        order = sorted(range(len(chunks)), key=lambda i: -scores[i])
        positions = {chunk_id(chunks[i]): rank for rank, i in enumerate(order, 1)}
        relevant = {item["parent_passage_id"]: item["relevance"] for item in case["evidence"]}
        ranks = {key: positions[key] for key in relevant}
        rows.append({"id": case["id"], "category": case["category"], "ranks": ranks, "metrics": quality(ranks, relevant)})
    return {"parents": len(chunks), "children": len(flat), "max_embedded_tokens": max(part.embedded_tokens for part in flat),
            "mean_embedded_tokens": mean(part.embedded_tokens for part in flat), "index_preparation_ms": prepared,
            "means": {key: mean(row["metrics"][key] for row in rows) for key in ("recall@5", "recall@10", "ndcg@10")},
            "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--distractors", type=int, default=48)
    args = parser.parse_args()
    torch.set_num_threads(4)
    dataset = json.loads(Path("evaluation/real_insurance_dataset.json").read_text(encoding="utf-8"))
    queries = [case for case in dataset["queries"] if case["id"] in CASES]
    all_chunks = text_search.load_chunks()
    by_id = {chunk_id(chunk): chunk for chunk in all_chunks}
    labels = {item["parent_passage_id"]: item for case in queries for item in case["evidence"]}
    if not all(key in by_id and item["text"] == by_id[key]["text"] for key, item in labels.items()):
        raise ValueError("Evidence labels no longer match the extracted corpus")
    sample = sorted(by_id.keys() - labels.keys(), key=lambda key: hashlib.sha256(key.encode()).hexdigest())[:args.distractors]
    chunks = [by_id[key] for key in sorted(labels.keys() | set(sample))]
    result = {"baseline": evaluate(chunks, queries, contextual=False), "headers": evaluate(chunks, queries, contextual=True),
              "case_ids": sorted(CASES), "label_status": "pending domain expert"}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key]["means"] for key in ("baseline", "headers")}))


if __name__ == "__main__":
    main()
