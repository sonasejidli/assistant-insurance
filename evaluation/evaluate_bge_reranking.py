"""Validate RRF settings and compare the baseline and bounded BGE policies."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys
from time import perf_counter
from unittest.mock import patch

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from App import embedding, text_search
from App.query_resolution import resolve_query
from App.settings import RetrievalSettings
from evaluation.benchmark_insurance import dcg
from evaluation.evaluate_real_insurance import chunk_id, quality, read_archives, validate_dataset, verify_archives


WEIGHTS = ((0.5, 0.5), (0.6, 0.4), (0.4, 0.6), (0.7, 0.3))
POOLS = (30, 40, 50)
TOP_K = (5, 8, 10)


def split_cases(cases):
    """Keep cases sharing labeled source parents on the same side of the split."""
    groups = []
    for case in cases:
        evidence = set(case["relevant_parent_passage_ids"])
        linked = [group for group in groups if evidence & group[0]]
        existing = [row for _, members in linked for row in members]
        for group in linked:
            evidence.update(group[0])
        groups = [group for group in groups if group not in linked]
        groups.append((evidence, [*existing, case]))
    ordered = sorted(groups, key=lambda group: hashlib.sha256(
        min(row["id"] for row in group[1]).encode()).hexdigest())
    validation, heldout = [], []
    for i, (_, group) in enumerate(ordered):
        (validation if i % 3 == 0 else heldout).extend(group)
    return validation, heldout


def settings(weights, depth, rank_constant):
    return RetrievalSettings(bm25_weight=weights[0], vector_weight=weights[1],
                             rerank_top_k=depth, rrf_k=rank_constant)


def candidate_inputs(retriever, case):
    start = perf_counter()
    query = resolve_query(case["query"], case["history"]).standalone
    if query is None:
        return None, (perf_counter() - start) * 1000
    tokens, alternatives = text_search.lexical_query(query)
    state = {"question": query, "query_tokens": tokens, "alternative_concepts": alternatives,
             "eligible": list(range(len(retriever.chunks))), "k": 5}
    state.update(retriever._bm25(state))
    state.update(retriever._vector_search(state))
    return state, (perf_counter() - start) * 1000


def relevant_ranks(retriever, indexes, relevant):
    positions = {chunk_id(retriever.chunks[i]): pos for pos, i in enumerate(indexes, 1)}
    return {key: positions.get(key) for key in relevant}


def stage_quality(ranks, relevant):
    result = quality(ranks, relevant)
    if result is not None:
        result["ndcg@5"] = dcg([next((relevant[key] for key, rank in ranks.items() if rank == i), 0)
                               for i in range(1, 6)]) / dcg(sorted(relevant.values(), reverse=True)[:5])
    return result


def fusion(retriever, state, weights, depth, rank_constant):
    retriever.settings = settings(weights, depth, rank_constant)
    return {**state, **retriever._fuse(state)}


def shortlist(retriever, state):
    with patch.object(text_search, "rerank_documents", side_effect=lambda query, docs: docs[:]) as rank:
        retriever._rerank(state)
    return rank.call_args.args[1]


def rank_ids(documents):
    return [doc.metadata["index"] for doc in documents]


def validation_grid(retriever, validation, rank_constant):
    prepared = [(case, candidate_inputs(retriever, case)[0]) for case in validation if case["covered"]]
    results = []
    for weights in WEIGHTS:
        for depth in POOLS:
            scored = []
            for case, state in prepared:
                relevant = {item["parent_passage_id"]: item["relevance"] for item in case["evidence"]}
                if state is None:
                    ranks = {key: None for key in relevant}
                    recall = 0
                else:
                    fused = fusion(retriever, state, weights, depth, rank_constant)
                    ranks = relevant_ranks(retriever, rank_ids(fused["candidates"]), relevant)
                    pool_ranks = relevant_ranks(retriever, rank_ids(shortlist(retriever, fused)), relevant)
                    recall = sum(rank is not None for rank in pool_ranks.values()) / len(relevant)
                scored.append({"pool_recall": recall, **stage_quality(ranks, relevant),
                               **{f"all_required@{k}": all(rank is not None and rank <= k for rank in ranks.values())
                                  for k in TOP_K}})
            results.append({"weights": weights, "pool": depth, "n": len(scored),
                            **{key: mean(row[key] for row in scored) for key in scored[0]}})
    best_weights = max(WEIGHTS, key=lambda weights: next(
        row["ndcg@10"] for row in results if row["weights"] == weights))
    best_recall = max(row["pool_recall"] for row in results if row["weights"] == best_weights)
    depth = next(row["pool"] for row in results
                 if row["weights"] == best_weights and row["pool_recall"] >= best_recall - 0.03)
    return results, best_weights, depth


def evaluate_case(retriever, case, optimized, depth, rank_constant, latency_repeats):
    state, retrieval_ms = candidate_inputs(retriever, case)
    relevant = {item["parent_passage_id"]: item["relevance"] for item in case["evidence"]}
    configurations = {"A": (WEIGHTS[0], "baseline"), "B": (WEIGHTS[0], "bge_safe"),
                      "C": (optimized, "baseline"), "D": (optimized, "bge_safe")}
    selected, fused, fusion_ms = {}, {}, {}
    for label, (weights, mode) in configurations.items():
        if state is None:
            continue
        start = perf_counter()
        fused[label] = fusion(retriever, state, weights, depth, rank_constant)
        selected[label] = shortlist(retriever, fused[label])
        fusion_ms[label] = (perf_counter() - start) * 1000
    union = {doc.metadata["index"]: doc for docs in selected.values() for doc in docs}
    cached = {}
    if union:
        for mode in ("baseline", "bge_safe"):
            scores = text_search.cross_encoder_scores(state["question"], list(union.values()), mode=mode)
            cached[mode] = dict(zip(union, map(float, scores), strict=True))
    results = {}
    for label, (weights, mode) in configurations.items():
        ordered = []
        survival = {}
        timings = []
        if state is not None:
            retriever.settings = settings(weights, depth, rank_constant)
            scored = sorted(selected[label], key=lambda doc: -cached[mode][doc.metadata["index"]])
            ids = set(rank_ids(scored))
            ordered = scored + [doc for doc in fused[label]["candidates"] if doc.metadata["index"] not in ids]
            for k in TOP_K:
                hits = retriever._select_context({**fused[label], "candidates": ordered, "k": k})["hits"]
                ids_at_k = {chunk_id(hit) for hit in hits}
                survival[str(k)] = {key: key in ids_at_k for key in relevant}
            for _ in range(latency_repeats):
                start = perf_counter()
                live_state, _ = candidate_inputs(retriever, case)
                live_state = fusion(retriever, live_state, weights, depth, rank_constant)
                start_rerank = perf_counter()
                live_selected = shortlist(retriever, live_state)
                live_scores = text_search.cross_encoder_scores(live_state["question"], live_selected, mode=mode)
                live_ranked = [doc for _, doc in sorted(zip(live_scores, live_selected, strict=True),
                                                       key=lambda pair: -float(pair[0]))]
                rerank_ms = (perf_counter() - start_rerank) * 1000
                live_ids = set(rank_ids(live_ranked))
                live_state["candidates"] = live_ranked + [doc for doc in live_state["candidates"]
                                                         if doc.metadata["index"] not in live_ids]
                retriever._select_context(live_state)
                timings.append({"rerank_ms": rerank_ms, "pipeline_ms": (perf_counter() - start) * 1000})
        ranks = relevant_ranks(retriever, rank_ids(ordered)[:50], relevant)
        results[label] = {
            "final_ranks": ranks, "metrics": stage_quality(ranks, relevant), "survives_top_k": survival,
            "candidate_ranks": relevant_ranks(retriever, rank_ids(selected.get(label, [])), relevant),
            "rrf_ranks": relevant_ranks(retriever, rank_ids(fused.get(label, {}).get("candidates", []))[:50], relevant),
            "top_10": [chunk_id(retriever.chunks[i]) for i in rank_ids(ordered)[:10]],
            "uncached_timings": timings, "retrieval_ms": retrieval_ms + fusion_ms.get(label, 0),
        }
    return {"id": case["id"], "query": case["query"], "category": case["category"],
            "covered": case["covered"], "standalone": state["question"] if state else None,
            "bm25": relevant_ranks(retriever, state["lexical_rank"] if state else [], relevant),
            "dense": relevant_ranks(retriever, state["vector_rank"] if state else [], relevant),
            "experiments": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "snapshot", "vectors", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--rrf-k", default=60, type=int)
    parser.add_argument("--per-category", default=1, type=int)
    parser.add_argument("--latency-cases", default=1, type=int)
    parser.add_argument("--latency-repeats", default=2, type=int)
    parser.add_argument("--only-ids", nargs="+", help="Evaluate only these predeclared held-out cases")
    parser.add_argument("--threads", default=4, type=int)
    args = parser.parse_args()
    if min(args.per_category, args.threads, args.latency_repeats) < 1 or args.latency_cases < 0 or args.rrf_k < 0:
        parser.error("Invalid sample, thread count, repeats, or RRF rank constant")
    torch.set_num_threads(args.threads)
    dataset, documents = (json.loads(path.read_text(encoding="utf-8")) for path in (args.dataset, args.snapshot))
    chunks = [chunk for doc in documents for chunk in doc["chunks"]]
    validate_dataset(dataset, chunks)
    config = embedding.embedding_configuration()
    archives = read_archives(args.vectors, chunks, config["dimensions"], config["model_repository"])
    probes = verify_archives(archives)
    retriever = object.__new__(text_search.TextRetriever)
    retriever.chunks, retriever.documents, retriever.vector_index = chunks, documents, archives[1]
    retriever.settings = settings(WEIGHTS[0], 24, args.rrf_k)
    retriever.bm25 = text_search.RetrievalBM25.from_chunks(chunks)
    validation, heldout = split_cases(dataset["queries"])
    grid, weights, depth = validation_grid(retriever, validation, args.rrf_k)
    print(f"Validation {len(validation)}, held out {len(heldout)}. Selected {weights}, pool {depth}", flush=True)
    by_category = defaultdict(list)
    for case in sorted(heldout, key=lambda case: case["id"]):
        by_category[case["category"]].append(case)
    sample = [case for group in by_category.values() for case in group[:args.per_category]]
    for category in ("casco_compulsory", "conversational"):
        for case in by_category[category]:
            if case["multiple_passages_required"] and case not in sample:
                sample.append(case)
                break
    if args.only_ids:
        allowed = {case["id"]: case for case in heldout}
        if not set(args.only_ids) <= allowed.keys():
            parser.error("Additional cases must be in the held-out partition")
        sample = [allowed[case_id] for case_id in dict.fromkeys(args.only_ids)]
    text_search.get_reranker()
    rows = []
    for i, case in enumerate(sample):
        repeats = args.latency_repeats if i < args.latency_cases else 0
        rows.append(evaluate_case(retriever, case, weights, depth, args.rrf_k, repeats))
        print(f"Held out {i+1}/{len(sample)} {case['id']}", flush=True)
    result = {"validation_ids": [case["id"] for case in validation], "heldout_ids": [case["id"] for case in heldout],
              "validation_grid": grid, "selected_weights": weights, "selected_pool": depth,
              "threads": args.threads, "rrf_k": args.rrf_k, "archive": archives[1].name,
              "archive_probe_cosines": probes, "rows": rows}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
