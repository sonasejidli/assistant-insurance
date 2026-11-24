"""Trace source anchors through isolated exact BM25, E5, RRF and BGE retrieval."""

import argparse
from pathlib import Path

import numpy as np
import torch

from App import embedding, legal_documents, legal_evidence, query_plan, text_search
from App.document_processing import load_documents
from App.query_resolution import resolve_query
from evaluation.evaluate_bge_reranking import shortlist
from evaluation.evaluate_platform import RankingRetriever, diagnostic_cases, read, write
from evaluation.evaluate_real_insurance import FrozenIndex, chunk_id, read_archives, validate_dataset, verify_archives
from evaluation.evaluate_reliability_followup import SOURCE_PROBES, compare_multipart
from App.vector_store import fingerprint


def build_index(base, staged):
    settings = embedding.embedding_configuration()
    archives = read_archives(Path(".venv/real_eval_vectors.jsonl"), base, settings["dimensions"], settings["model_repository"])
    verify_archives(archives)
    archive = archives[1]
    texts = [text_search.embedding_passage_text(chunk) for chunk in staged]
    key = fingerprint([settings, [(chunk_id(c), t) for c, t in zip(staged, texts, strict=True)]])
    cache = Path(f".venv/staged-trace-{key[:20]}.npz")
    if not cache.exists():
        plans = embedding.plan_passages(staged, texts)
        flat = [part.text for plan in plans for part in plan]
        parents = [i for i, plan in enumerate(plans) for _ in plan]
        vectors = []
        for i in range(0, len(flat), 64):
            vectors.extend(embedding.embed(flat[i:i+64]))
            print(f"Encoded {min(i+64, len(flat))}/{len(flat)} staged views", flush=True)
        np.savez_compressed(cache, vectors=vectors, parents=parents)
    with np.load(cache) as staged_archive:
        vectors = np.concatenate([archive.vectors, staged_archive["vectors"]])
        parents = np.concatenate([archive.parents, len(base) + staged_archive["parents"]])
    return FrozenIndex("isolated-overlay", vectors, parents, [], len(parents))


def trace(retriever, documents, probe, *, scoped=False, rerank=True, provision=False):
    query, target, article, phrase = probe
    q = resolve_query(query, [])
    clause = "883.1" if article else "2.2"
    matching = {i for i, chunk in enumerate(retriever.chunks) if chunk["doc"] == target and chunk["metadata"].get("clause") == clause
                and (article is None or chunk["metadata"].get("article") == article)
                and phrase in chunk["text"].casefold()}
    if not matching:
        raise ValueError(f"Source anchor missing: {target}")
    law = next(doc["metadata"]["law_name"] for doc in documents if doc["doc"] == target)
    filters = {"law": law} if scoped else {}
    part = query_plan.plan_query(q, "az", forced=True, provision=provision)
    state = {"question": q.standalone, "original_question": q.original, "filters": filters, "k": 10}
    state.update(retriever._preprocess(state))
    state.update(retriever._bm25(state))
    state.update(retriever._vector_search(state))
    state.update(retriever._fuse(state))
    raw_bm25 = retriever.bm25.get_scores(state["query_tokens"])
    full_bm25 = sorted((i for i in state["eligible"] if raw_bm25[i] > 0), key=lambda i: -raw_bm25[i])
    full_dense = [i for i, _ in retriever.vector_index.search(state["query_vector"], state["eligible"], len(state["eligible"]))]
    def rank(ids):
        return next((i for i, index in enumerate(ids, 1) if index in matching), None)
    fused = [doc.metadata["index"] for doc in state["candidates"]]
    result = {"query": q.standalone, "target": target, "filters": filters, "matching_ids": [chunk_id(retriever.chunks[i]) for i in sorted(matching)],
              "eligible_targets": len(matching & set(state["eligible"])), "tokens": state["query_tokens"],
              "formal_variant": query_plan.formal_variant(q.standalone), "parts": [item.question for item in part.parts],
              "route": query_plan.route_query(part.parts[0].question).filters, "direct_provisions": rank(state.get("direct_provisions", [])),
              "bm25_full": rank(full_bm25), "dense_full": rank(full_dense), "bm25_branch": rank(state["lexical_rank"]),
              "dense_branch": rank(state["vector_rank"]), "rrf": rank(fused),
              "bge_shortlist": rank([doc.metadata["index"] for doc in shortlist(retriever, state)])}
    if rerank:
        state.update(retriever._rerank(state))
        result["after_bge"] = rank([doc.metadata["index"] for doc in state["candidates"]])
    hits = retriever._select_context(state)["hits"]
    package = legal_evidence.assemble_evidence(query, hits, documents)
    ids = set(result["matching_ids"])
    for name, hits in (("selected", hits), ("expanded", package.hits)):
        result[name] = next((i for i, hit in enumerate(hits, 1) if chunk_id(hit) in ids), None)
    print(target, "scoped" if scoped else "broad", {k: result[k] for k in ("bm25_full", "dense_full", "rrf", "bge_shortlist")}, flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-bge", action="store_true")
    parser.add_argument("--lexical-only", action="store_true")
    parser.add_argument("--provision", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(4)
    dataset = read("evaluation/real_insurance_dataset.json")
    documents = read(".venv/eval_corpus_snapshot.json")
    base = [hit for doc in documents for hit in doc["chunks"]]
    validate_dataset(dataset, base)
    staged_docs = load_documents(Path("data/staged_legal"), staged=True)
    staged = [hit for doc in staged_docs for hit in doc["chunks"]]
    if args.lexical_only:
        chunks = [*base, *staged]
        bm25 = text_search.RetrievalBM25.from_chunks(chunks)
        result = []
        for query, target, article, phrase in (SOURCE_PROBES[0], SOURCE_PROBES[3]):
            tokens = text_search.lexical_query(query)[0]
            scores = bm25.get_scores(tokens)
            order = sorted(range(len(chunks)), key=lambda index: -scores[index])
            rows = []
            for rank, index in enumerate(order, 1):
                hit = chunks[index]
                match = (hit["doc"] == target and (article is None or hit["metadata"].get("article") == article)
                         and phrase in hit["text"].casefold())
                if rank <= 5 or match:
                    rows.append({"rank": rank, "target": match, "doc": hit["doc"], "text": hit["text"][:260],
                                 "terms": {term: bm25.doc_freqs[index][term] for term in tokens if term in bm25.doc_freqs[index]}})
            result.append({"query": query, "tokens": tokens, "rows": rows})
        write(args.output, {"lexical": result, "parts": [{"id": case["id"], "query": case["query"], "evidence": case["evidence"]}
              for case in diagnostic_cases(dataset) if case.get("part_parents")]})
        return
    index = build_index(base, staged)
    documents += staged_docs
    legal_documents.link_references(documents)
    retriever = RankingRetriever([*base, *staged], index, False)
    retriever.provision_retrieval = args.provision
    rows = [trace(retriever, documents, probe, scoped=scoped, rerank=not args.skip_bge, provision=args.provision)
            for probe in (SOURCE_PROBES[0], SOURCE_PROBES[3]) for scoped in (False, True)]
    write(args.output, {"traces": rows, "multipart": compare_multipart(retriever, documents, diagnostic_cases(dataset), provision_mode=args.provision)})


if __name__ == "__main__":
    main()
