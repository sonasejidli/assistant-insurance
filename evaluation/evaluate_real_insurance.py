"""Evaluate real legal evidence against isolated, read-only vector snapshots."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.benchmark_insurance import dcg
from evaluation.build_real_insurance_dataset import digest
from App import embedding, system, text_search
from App.query_resolution import resolve_query
from App.settings import RetrievalSettings


HERE = Path(__file__).resolve().parent
STAGES = ("bm25", "dense", "rrf", "reranked")
TAXONOMY = (
    "query_normalization", "query_resolution", "lexical_retrieval", "dense_retrieval",
    "hybrid_fusion", "reranking", "document_extraction", "indexing_chunking", "coverage_gap",
    "context_assembly", "answer_generation",
)


def verified_approval(dataset, review):
    if not review or review.get("dataset_sha256") != digest(dataset):
        return False
    entries = review.get("queries", {})
    return all(
        entries.get(row["id"], {}).get("status") == "approved"
        and bool(str(entries[row["id"]].get("reviewer") or "").strip())
        and bool(str(entries[row["id"]].get("expertise") or "").strip())
        for row in dataset["queries"]
    )


def chunk_id(chunk):
    return chunk["metadata"]["chunk_id"]


def validate_dataset(dataset, chunks):
    if digest([(chunk_id(c), c["text"]) for c in chunks]) != dataset["corpus_sha256"]:
        raise ValueError("Corpus differs from the labeled snapshot")
    by_id = {chunk_id(c): c for c in chunks}
    for row in dataset["queries"]:
        ids = [item["parent_passage_id"] for item in row["evidence"]]
        if ids != row["relevant_parent_passage_ids"] or bool(ids) != row["covered"]:
            raise ValueError(f"Missing or inconsistent labels for {row['id']}")
        for item in row["evidence"]:
            actual = by_id[item["parent_passage_id"]]
            if (item["text"], item["document_id"]) != (actual["text"], actual["metadata"]["document_id"]):
                raise ValueError(f"Stale or incorrect source label for {row['id']}")


class FrozenIndex:
    """Exact isolated index over one archive. Never merges vectors from different archives."""

    def __init__(self, name, vectors, parents, inputs, points):
        self.name = name
        self.points = points
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.parents = np.asarray(parents, dtype=np.int32)
        self.inputs = inputs
        if (self.vectors.shape[0] != points or not np.isfinite(self.vectors).all()
                or not np.allclose(np.linalg.norm(self.vectors, axis=1), 1, atol=0.001)):
            raise ValueError(f"Invalid archived vectors in {name}")

    def search(self, vector, eligible, limit, *, exact=False, score_threshold=None):
        eligible = set(eligible)
        if not eligible:
            return []
        scores = self.vectors @ np.asarray(vector, dtype=np.float32)
        best = {}
        for row in np.argsort(-scores, kind="stable"):
            score = float(scores[row])
            if score_threshold is not None and score <= score_threshold:
                break
            parent = int(self.parents[row])
            if parent in eligible:
                best.setdefault(parent, score)
                if len(best) == limit:
                    break
        return sorted(best.items(), key=lambda item: (-item[1], item[0]))


def read_archives(path, chunks, dimensions, repository):
    state = None
    archives = []
    by_id = {chunk_id(c): i for i, c in enumerate(chunks)}
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            row = json.loads(line)
            if "collection" in row:
                if state:
                    archives.append(FrozenIndex(*state))
                if row["vectors"]["size"] != dimensions or row["vectors"]["distance"] != "Dot":
                    raise ValueError("Archive uses a different vector space")
                state = (row["collection"], [], [], [], row["points"])
                continue
            if state is None:
                raise ValueError("Archive header is missing")
            payload = row["payload"]
            parent = by_id[payload.get("parent_chunk_id") or payload["chunk_id"]]
            if (chunks[parent]["text"] != payload["text"] or repository != payload["embedding_model"]
                    or len(row["vector"]) != dimensions):
                raise ValueError(f"Archive mismatch at parent {parent}")
            state[1].append(row["vector"])
            state[2].append(parent)
            state[3].append(payload.get("embedding_text") or text_search.searchable_text(chunks[parent]))
    if state:
        archives.append(FrozenIndex(*state))
    if len(archives) != 2 or any(len(set(a.parents)) != len(chunks) for a in archives):
        raise ValueError("Expected two separately complete corpus archives")
    return archives


def verify_archives(archives):
    """Check the historical snapshots against fresh encodings of fixed probes."""
    results = {}
    for archive in archives:
        sample = [i for i in (0, len(archive.inputs) // 3, 2 * len(archive.inputs) // 3, len(archive.inputs) - 1)
                  if embedding.token_counts(embedding.get_model(), [embedding.model_input(archive.inputs[i], "passage")])[0]
                  <= embedding.input_limit(embedding.get_model())]
        if len(sample) < 2:
            raise ValueError("Insufficient compatibility probes")
        vectors = embedding.embed([archive.inputs[i] for i in sample])
        similarities = np.sum(vectors * archive.vectors[sample], axis=1)
        if min(similarities) < 0.9999:
            raise ValueError(f"Archive encoder probe failed for {archive.name}")
        results[archive.name] = [round(float(score), 7) for score in similarities]
    return results


def quality(ranks, grades):
    if not grades:
        return None
    return {
        **{f"recall@{k}": sum(rank is not None and rank <= k for rank in ranks.values()) / len(grades)
           for k in (5, 10, 20, 50)},
        "mrr@20": max((1 / rank for rank in ranks.values() if rank is not None and rank <= 20), default=0),
        "ndcg@10": dcg([next((grades[key] for key, rank in ranks.items() if rank == position), 0)
                        for position in range(1, 11)]) / dcg(sorted(grades.values(), reverse=True)[:10]),
    }


def diagnosis(case, standalone, ranks, assembled):
    if not case["covered"]:
        return "coverage_gap", case["label_rationale"]
    if standalone is None:
        return "query_resolution", "The resolver asked for clarification before retrieval."
    if not set(case["relevant_parent_passage_ids"]) - set(assembled):
        return None, None
    misses = {stage: [key for key, rank in ranked.items() if rank is None]
              for stage, ranked in ranks.items()}
    if "reranked" in ranks:
        missing = set(case["relevant_parent_passage_ids"]) - set(assembled)
        if any((ranks["rrf"].get(key) or 51) <= 5 < (ranks["reranked"].get(key) or 51) for key in missing):
            return "reranking", "A missing required parent moved from RRF top five to below reranked top five."
        if all((ranks["reranked"].get(key) or 51) <= 5 for key in missing):
            return "context_assembly", "A required parent ranked in the top five but was absent from packed context."
    if misses.get("dense"):
        return "dense_retrieval", f"Required parent(s) outside the dense top 50: {', '.join(misses['dense'])}."
    if misses.get("bm25"):
        return "lexical_retrieval", f"Required parent(s) outside the BM25 top 50: {', '.join(misses['bm25'])}."
    return "hybrid_fusion", "Required evidence entered the candidate pools but did not reach the packed context."


def run_case(retriever, case, before, rerank):
    start = perf_counter()
    original, history = case["query"], case["history"]
    if before:
        standalone = f"{history[-1]} {original}" if history and original.lower().startswith("bəs ") else original
        context = history[-1:] if standalone != original else []
    else:
        query = resolve_query(original, history)
        standalone, context = query.standalone, list(query.context)
    orders = {stage: [] for stage in STAGES if stage != "reranked" or rerank}
    state = None
    if standalone:
        state = {"question": standalone, "original_question": original, "k": 5}
        # Isolate the four semantic ranking stages from the exact article shortcut.
        tokens, alternatives = text_search.lexical_query(standalone)
        state.update(eligible=list(range(len(retriever.chunks))), query_tokens=tokens, alternative_concepts=alternatives)
        state.update(retriever._bm25(state))
        state.update(retriever._vector_search(state))
        state.update(retriever._fuse(state))
        orders.update(bm25=state["lexical_rank"], dense=state["vector_rank"],
                      rrf=[doc.metadata["index"] for doc in state["candidates"]])
    retrieval_ms = (perf_counter() - start) * 1000
    rerank_ms = None
    pairs = []

    def record_reranker(question, documents):
        if len(documents) > 1:
            pairs.extend((question, text_search.reranker_passage(doc)) for doc in documents)
        return text_search.rank_with_cross_encoder(question, documents)

    if rerank and state is not None:
        state["rerank_query"] = original if before else standalone
        start = perf_counter()
        with patch.object(text_search, "rerank_documents", side_effect=record_reranker):
            state.update(retriever._rerank(state))
        rerank_ms = (perf_counter() - start) * 1000
        orders["reranked"] = [doc.metadata["index"] for doc in state["candidates"]]
    assembled, selected_count = [], 0
    if state is not None:
        hits = system.surrounding_evidence(retriever._select_context(state)["hits"], retriever.documents)
        selected_count = len(hits)
        _, included = system.evidence_message(original, system.answer_instructions("az", "question"), hits, context)
        assembled = [chunk_id(hits[i]) for i in sorted(included)]
    return orders, assembled, standalone, context, selected_count, retrieval_ms, rerank_ms, pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=HERE / "real_insurance_dataset.json")
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--vectors", required=True, type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--draft", action="store_true", help="Allow exploratory metrics without expert approval")
    parser.add_argument("--rerank-ids", nargs="+", help="Measure D only for this declared sample")
    parser.add_argument("--rerank-depth", type=int, default=24)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    review = json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else None
    approved = verified_approval(dataset, review)
    if not approved and not args.draft:
        parser.error("Domain-expert approval for this exact dataset is required. Use --draft for exploratory runs.")
    if min(args.repeats, args.threads) < 1 or args.rerank_depth < 5:
        parser.error("Use positive repeats and threads and a rerank depth of at least five")
    torch.set_num_threads(args.threads)
    documents = json.loads(args.snapshot.read_text(encoding="utf-8"))
    chunks = [chunk for doc in documents for chunk in doc["chunks"]]
    validate_dataset(dataset, chunks)
    start = perf_counter()
    config = embedding.embedding_configuration()
    model_load_ms = (perf_counter() - start) * 1000
    start = perf_counter()
    archives = read_archives(args.vectors, chunks, config["dimensions"], config["model_repository"])
    index_load_ms = (perf_counter() - start) * 1000
    probes = verify_archives(archives)
    start = perf_counter()
    encoder = text_search.get_reranker()
    reranker_load_ms = (perf_counter() - start) * 1000
    retriever = object.__new__(text_search.TextRetriever)
    retriever.settings = RetrievalSettings(rerank_top_k=args.rerank_depth)
    retriever.chunks, retriever.documents = chunks, documents
    retriever.bm25 = text_search.RetrievalBM25.from_chunks(chunks)
    rerank_ids = set(args.rerank_ids or [row["id"] for row in dataset["queries"]])
    if not rerank_ids <= {row["id"] for row in dataset["queries"]}:
        parser.error("Unknown rerank query ID")
    rows = []
    cold = {}
    for pos, case in enumerate(dataset["queries"]):
        grades = {item["parent_passage_id"]: item["relevance"] for item in case["evidence"]}
        results = {"id": case["id"], "category": case["category"], "covered": case["covered"], "versions": {}}
        rerank = case["id"] in rerank_ids
        for index in ((0, 1) if pos % 2 == 0 else (1, 0)):
            archive = retriever.vector_index = archives[index]
            timings = []
            for repeat in range(args.repeats):
                start = perf_counter()
                orders, assembled, standalone, context, count, retrieval, ranking, pairs = run_case(
                    retriever, case, index == 0, rerank,
                )
                timing = {"retrieval_ms": retrieval, "rerank_ms": ranking, "total_ms": (perf_counter() - start) * 1000}
                timings.append(timing)
                if pos == repeat == 0:
                    cold[archive.name] = timing
            ranks = {}
            for stage, order in orders.items():
                positions = {chunk_id(chunks[i]): rank for rank, i in enumerate(order[:50], 1)}
                ranks[stage] = {key: positions.get(key) for key in grades}
            failure, reason = diagnosis(case, standalone, ranks, assembled)
            pair_counts = [] if not pairs else encoder.tokenizer(
                [q for q, _ in pairs], [p for _, p in pairs], return_length=True, truncation=False, verbose=False,
            )["length"]
            results["versions"]["before" if index == 0 else "after"] = {
                "standalone": standalone, "history_used": context, "ranks": ranks,
                "metrics": {stage: quality(ranked, grades) for stage, ranked in ranks.items()},
                "assembled_parent_ids": assembled, "context_candidates": count, "timings": timings,
                "candidate_counts": {stage: len(order) for stage, order in orders.items()},
                "query_tokens": (embedding.token_counts(embedding.get_model(),
                                                        [embedding.model_input(standalone, "query")])[0] if standalone else 0),
                "reranker_input_tokens": pair_counts, "failure": failure, "failure_evidence": reason,
            }
        rows.append(results)
        if (pos + 1) % 12 == 0:
            print(f"Evaluated {pos + 1}/{len(dataset['queries'])}", flush=True)
    payload = {
        "dataset_sha256": digest(dataset), "expert_approved": approved, "archives": [a.name for a in archives],
        "archive_probe_cosines": probes, "embedding_configuration": config, "rows": rows,
        "cold": {"embedding_load_ms": model_load_ms, "index_load_ms": index_load_ms,
                 "reranker_load_ms": reranker_load_ms, "first_queries": cold},
        "rerank_depth": args.rerank_depth, "rerank_ids": sorted(rerank_ids), "repeats": args.repeats,
        "threads": args.threads, "failure_taxonomy": TAXONOMY,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report data written to {args.output}", flush=True)


if __name__ == "__main__":
    main()
