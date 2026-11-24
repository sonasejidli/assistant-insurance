"""Benchmark lexical, dense, hybrid, and reranked Azerbaijani insurance retrieval."""

import argparse
import csv
import json
import platform
import re
import sys
from itertools import zip_longest
from math import log2
from pathlib import Path
from statistics import mean, median, quantiles
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from App import text_search, vector_store
from App.azerbaijani import surface_tokens
from App.settings import BM25_B, BM25_K1, EMBED_MODEL, RERANK_MODEL, RetrievalSettings

HERE = Path(__file__).resolve().parent
CONFIGS = {
    "A": "Standard BM25", "B": "BM25 + Azerbaijani normalization",
    "C": "BM25 + normalization + lemmatization", "D": "BM25 + query expansion",
    "E": "Qdrant dense retrieval", "F": "Hybrid with rank interleaving",
    "G": "Hybrid with RRF and contextual reranker",
}


def read_fixture():
    source = json.loads((HERE / "salary_evidence.json").read_text(encoding="utf-8"))
    chunks = [chunk for filename in ("bm25_cases.json", "reranker_cases.json")
              for chunk in json.loads((HERE / filename).read_text(encoding="utf-8"))["chunks"]]
    chunks.extend(source["chunks"])
    with (HERE / "insurance_queries.tsv").open(encoding="utf-8", newline="") as file:
        cases = list(csv.DictReader(file, delimiter="\t"))
    ids = {chunk["doc"] for chunk in chunks}
    if len(ids) != len(chunks) or len(cases) < 100 or len({item["id"] for item in cases}) != len(cases):
        raise ValueError("Benchmark requires unique chunks and at least 100 uniquely identified queries")
    if len({item["query"] for item in cases}) != len(cases):
        raise ValueError("Benchmark queries must be distinct")
    for item in cases:
        item["relevance"] = {key: int(grade) for key, grade in
                             (label.split(":") for label in item["relevance"].split(","))}
        if not item["relevance"].keys() <= ids or not all(1 <= grade <= 3 for grade in item["relevance"].values()):
            raise ValueError(f"Invalid relevance labels for {item['id']}")
    return chunks, cases, source["expected"]


def base_tokens(text, metadata):
    return re.findall(r"\w+", text.lower())


def normalized_tokens(text, metadata):
    surface, exact = text_search.exact_value_tokens(text, metadata)
    return [*surface_tokens(surface), *exact]


def lemma_tokens(text, metadata):
    return text_search.lexical_tokens(text, set(), metadata=metadata)


def lexical_order(index, tokens, limit):
    scores = index.get_scores(list(dict.fromkeys(tokens)))
    return sorted((i for i, score in enumerate(scores) if score > 0), key=lambda i: -scores[i])[:limit]


def measure(operation):
    start = perf_counter()
    result = operation()
    return result, (perf_counter() - start) * 1000


def dcg(grades):
    return sum((2 ** grade - 1) / log2(rank + 1) for rank, grade in enumerate(grades, 1))


def metrics(order, relevant):
    grades = [relevant.get(doc, 0) for doc in order]
    return {
        "recall5": sum(grade > 0 for grade in grades[:5]) / len(relevant),
        "recall10": sum(grade > 0 for grade in grades[:10]) / len(relevant),
        "mrr": next((1 / rank for rank, grade in enumerate(grades, 1) if grade), 0),
        "ndcg5": dcg(grades[:5]) / dcg(sorted(relevant.values(), reverse=True)[:5]),
    }


def run(chunks, cases, args):
    texts = [text_search.searchable_text(chunk) for chunk in chunks]
    tokenizers = {"A": base_tokens, "B": normalized_tokens, "C": lemma_tokens}
    indexes = {key: text_search.RetrievalBM25(
        [tokens(text, chunk.get("metadata")) or [""] for text, chunk in zip(texts, chunks)],
        k1=BM25_K1, b=BM25_B,
    ) for key, tokens in tokenizers.items()}
    settings = RetrievalSettings(bm25_top_k=args.depth, vector_top_k=args.depth)
    # Always isolate benchmark vectors from application collections and credentials.
    with patch.object(text_search, "load_chunks", return_value=chunks), patch.multiple(
        vector_store, QDRANT_PATH="", QDRANT_URL=""
    ):
        retriever = text_search.TextRetriever(settings)
    try:
        all_indexes = list(range(len(chunks)))

        def dense(question):
            vector = text_search.embed([question], kind="query")[0].tolist()
            return [i for i, _ in retriever.vector_index.search(
                vector, all_indexes, args.depth, score_threshold=settings.similarity_threshold,
            )]

        dense(cases[0]["query"])
        warm = retriever._fuse({"lexical_rank": [0, 1], "vector_rank": []})["candidates"]
        text_search.rank_with_cross_encoder(cases[0]["query"], warm)
        results = []
        for count, case in enumerate(cases, 1):
            question = case["query"]
            orders = {}
            times = {}
            for key, tokens in tokenizers.items():
                orders[key], times[key] = measure(lambda: lexical_order(indexes[key], tokens(question, None), args.depth))
            lexical, times["D"] = measure(lambda: lexical_order(
                retriever.bm25, text_search.lexical_query(question)[0], args.depth,
            ))
            vector, times["E"] = measure(lambda: dense(question))
            orders["D"], orders["E"] = lexical, vector
            orders["F"], merge_ms = measure(lambda: list(dict.fromkeys(
                i for pair in zip_longest(lexical, vector) for i in pair if i is not None
            )))
            candidates, fusion_ms = measure(lambda: retriever._fuse(
                {"lexical_rank": lexical, "vector_rank": vector}
            )["candidates"])
            reranked, rerank_ms = measure(lambda: text_search.rank_with_cross_encoder(
                question, candidates[:args.rerank_depth]
            ))
            orders["G"] = [doc.metadata["index"] for doc in (*reranked, *candidates[args.rerank_depth:])]
            times["F"] = times["D"] + times["E"] + merge_ms
            times["G"] = times["D"] + times["E"] + fusion_ms
            scores = {}
            for key, order in orders.items():
                ranked = [chunks[i]["doc"] for i in order[:args.depth]]
                scores[key] = {**metrics(ranked, case["relevance"]), "ranking": ranked,
                               "retrieval_ms": times[key], "rerank_ms": rerank_ms if key == "G" else None}
            results.append({"id": case["id"], "category": case["category"], "scores": scores})
            if count % 12 == 0:
                print(f"Evaluated {count}/{len(cases)} queries", flush=True)
        return results
    finally:
        retriever.close()


def latency(samples):
    return f"{median(samples):.2f} / {quantiles(samples, n=100, method='inclusive')[94]:.2f}" if samples else "—"


def report(cases, chunks, expected, results, args):
    summary = {key: {metric: mean(row["scores"][key][metric] for row in results)
                     for metric in ("recall5", "recall10", "mrr", "ndcg5")} for key in CONFIGS}
    winner = max(summary, key=lambda key: summary[key]["ndcg5"])
    lines = [
        "# Azerbaijani insurance retrieval benchmark", "",
        f"**Best by nDCG@5: {winner}. {CONFIGS[winner]}** ({summary[winner]['ndcg5']:.3f}).", "",
        f"The benchmark covers {len(cases)} distinct Azerbaijani queries and {len(chunks)} passages. "
        "Most passages are synthetic. Three clauses come from the supplied medical-insurance PDF. "
        "Labels are curated for this fixture. Production legal accuracy remains unverified.", "",
        "## Results", "",
        "| Configuration | Recall@5 | Recall@10 | MRR | nDCG@5 | Retrieval ms p50 / p95 | Reranking ms p50 / p95 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, label in CONFIGS.items():
        scores = [row["scores"][key] for row in results]
        values = " | ".join(f"{value:.3f}" for value in summary[key].values())
        lines.append(f"| {key}. {label} | {values} | {latency([row['retrieval_ms'] for row in scores])} | "
                     f"{latency([row['rerank_ms'] for row in scores if row['rerank_ms'] is not None])} |")
    lines.extend(["", "## nDCG@5 by query category", "",
                  "| Category | Queries | A | B | C | D | E | F | G |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for category in dict.fromkeys(case["category"] for case in cases):
        group = [row for row in results if row["category"] == category]
        values = " | ".join(f"{mean(row['scores'][key]['ndcg5'] for row in group):.3f}" for key in CONFIGS)
        lines.append(f"| {category.replace('_', ' ')} | {len(group)} | {values} |")

    salary = next(case for case in cases if case["id"] == expected["case"])
    scored = next(row for row in results if row["id"] == expected["case"])["scores"]
    concepts, alternatives = text_search.TERMINOLOGY.expand(salary["query"])
    lines.extend([
        "", f"## Salary threshold case ({salary['id']})", "", f"> {salary['query']}", "",
        expected["interpretation"], "",
        f"Query expansion produced {', '.join(sorted(concepts))}. The alternative group was "
        f"{', '.join(key for group in alternatives for key in group)}.", "",
        "| Configuration | Indexed salary clause rank | Contrast passages in top 10 |",
        "| --- | ---: | --- |",
    ])
    for key in CONFIGS:
        order = scored[key]["ranking"]
        target = expected["authoritative_fixture_passage"]
        contrast = ", ".join(doc for doc in order[:10] if doc in expected["contrast_passages"]) or "—"
        lines.append(f"| {key} | {order.index(target) + 1 if target in order else '—'} | {contrast} |")
    target = expected["authoritative_fixture_passage"]
    strongest = [key for key in CONFIGS if target in scored[key]["ranking"][:5]]
    bounded_contrast = [key for key in strongest if "sum-insured" in scored[key]["ranking"][:10]]
    lines.extend([
        "", f"The indexed clause reached the top five in {', '.join(strongest) or 'no configuration'}. "
        f"The clause and distinct insured-amount evidence met their top-five and top-ten cutoffs, respectively, "
        f"in {', '.join(bounded_contrast) or 'no configuration'}.",
    ])
    lines.extend([
        "", "The evidence assessment above is the benchmark's expected interpretation. The run evaluates "
        "retrieval and query expansion. Answer generation is outside the benchmark.", "",
        "## Method", "",
        f"- A uses generic lowercasing and word tokens. B adds Azerbaijani casing, Unicode normalization, "
        f"and canonical legal numbers and units. C adds the domain lemmatizer. D adds the production "
        f"terminology and query expansion. All lexical runs use positive-IDF BM25 with k1={BM25_K1} and b={BM25_B}.",
        f"- E uses {EMBED_MODEL} and in-memory Qdrant with a vector threshold of 0. "
        f"F alternates BM25 and dense ranks with deduplication. G applies unit-weight RRF with k=60 "
        f"and {RERANK_MODEL} to the first {args.rerank_depth} fused candidates. "
        f"Each branch and output list is capped at {args.depth}. Exact article shortcuts are disabled.",
        "- Grade 3 is direct evidence, grade 2 is material supporting evidence or a plausible alternative, "
        "and grade 1 is partial context. Recall counts all positively labeled passages. MRR uses the first "
        "relevant hit in the returned list. nDCG@5 uses exponential gain. Quality metrics are macro-averaged.",
        "- Latency excludes indexing, model loading, and warm-up. F and G retrieval latency is the sum of "
        "measured lexical and dense stages plus the measured merge, representing serial stage cost. "
        "Reranking latency is measured separately. These timings exclude network and API overhead.",
        f"- Host: {platform.system()} {platform.machine()}, PyTorch {torch.__version__}, "
        f"{args.threads} Torch threads. Inference used the local model cache.", "",
        "Reproduce with `python evaluation/benchmark_insurance.py`.", "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=20)
    parser.add_argument("--rerank-depth", type=int, default=12)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output", type=Path, default=HERE / "insurance_benchmark_report.md")
    args = parser.parse_args()
    if not 10 <= args.rerank_depth <= args.depth or args.threads < 1:
        parser.error("require 10 <= rerank-depth <= depth and at least one CPU thread")
    torch.set_num_threads(args.threads)
    chunks, cases, expected = read_fixture()
    results = run(chunks, cases, args)
    args.output.write_text(report(cases, chunks, expected, results, args), encoding="utf-8")
    print(f"Report written to {args.output}", flush=True)


if __name__ == "__main__":
    main()
