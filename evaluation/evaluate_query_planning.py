"""Compare query planning policies on the frozen real-corpus archive."""

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from unittest.mock import patch

import torch

from App import embedding, query_plan, text_search
from App.query_resolution import resolve_query
from App.settings import RetrievalSettings
from evaluation.evaluate_real_insurance import chunk_id, quality, read_archives, validate_dataset, verify_archives


MULTIPART_CASES = (
    ("İcbari sığorta tələbində faydalananlar hansı şəxsiyyət sənədlərini təqdim etməlidir və nə vaxt sığortaçı sonuncu sənəddən sonra ödəniş barədə qərar verməlidir?",
     ("AZR095", "AZR097")),
    ("İş qəzası sığortasında hansı hallarda sığorta olunanın hadisəni qəsdən törətməsi imtina əsasıdır və nə vaxt işəgötürən qəza barədə sığortaçıya məlumat verməlidir?",
     ("AZR010", "AZR105")),
    ("Auditor sığortasında hansı sənədlər zərər etiraf edildikdə sığortaçıya təqdim edilir və hansı halda sığorta haqqı ödənilmədikdə ödənişdən imtina mümkündür?",
     ("AZR106", "AZR012")),
)


def multipart_cases(cases):
    by_id = {case["id"]: case for case in cases}
    for i, (question, references) in enumerate(MULTIPART_CASES, start=1):
        parts = [by_id[reference]["evidence"] for reference in references]
        evidence = {item["parent_passage_id"]: item for part in parts for item in part}
        yield {"id": f"MP{i:02}", "category": "multipart", "query": question, "history": [], "covered": True,
               "evidence": list(evidence.values()), "label_sources": references,
               "part_parents": [[item["parent_passage_id"] for item in part] for part in parts]}


class ArchivedRetriever(text_search.TextRetriever):
    def __init__(self, chunks, index, rerank):
        self.chunks, self.vector_index = chunks, index
        self.settings = RetrievalSettings(bm25_weight=.7, vector_weight=.3, rerank_top_k=50)
        self.bm25 = text_search.RetrievalBM25.from_chunks(chunks)
        self.rerank = rerank

    def search(self, resolution, *, k, filters):
        state = {"question": resolution.standalone, "original_question": resolution.original,
                 "dense_query": resolution.dense_query, "dense_input_kind": "passage" if resolution.dense_hypothesis else "query",
                 "k": k, "filters": filters}
        state.update(self._preprocess(state))
        if state["articles"]:
            result = self._exact_lookup(state)
        else:
            for stage in (self._bm25, self._vector_search, self._fuse):
                state.update(stage(state))
            if self.rerank:
                state.update(self._rerank(state))
            result = self._select_context(state)
        return result["hits"], result["score"]


def evaluate(retriever, cases, configurations):
    rows = []
    generate = query_plan.generated_queries
    for case in cases:
        resolution = resolve_query(case["query"], case["history"], direct_article=bool(text_search.article_number(case["query"])))
        plan = query_plan.plan_query(resolution, "az", forced=True)
        grades = {e["parent_passage_id"]: e["relevance"] for e in case["evidence"]}
        row = {"id": case["id"], "category": case["category"], "intent": plan.intent,
               "standalone": resolution.standalone, "parts": [part.question for part in plan.parts],
               "label_sources": case.get("label_sources", []), "variants": {}}
        for name, options in configurations.items():
            start = perf_counter()
            expansions = []
            hypotheses = []
            statuses = []

            def record(*args, **kwargs):
                variants = generate(*args, **kwargs)
                expansions.extend(variants.alternatives)
                statuses.append(variants.status)
                if variants.hypothesis:
                    hypotheses.append(variants.hypothesis)
                return variants

            with patch.object(query_plan, "generated_queries", side_effect=record):
                hits, _, associations, parts = query_plan.retrieve_plan(retriever, plan, k=10, filters={}, **options)
            ids = [chunk_id(hit) for hit in hits]
            observed = {key: ids.index(key) + 1 if key in ids else None for key in grades}
            matched_parts = [sum(observed[key] is not None for key in part) for part in case.get("part_parents", [])]
            attributed_parts = [sum(ids[j] in parents and part.id in associations[query_plan.passage_key(hit)]
                                    for j, hit in enumerate(hits))
                                for part, parents in zip(parts, case.get("part_parents", []))] if len(parts) > 1 else []
            row["variants"][name] = {"metrics": quality(observed, grades), "parent_ranks": observed,
                                     "relevant_per_part": matched_parts, "attributed_per_part": attributed_parts,
                                     "generated_queries": expansions, "hypotheses": hypotheses,
                                     "expansion_statuses": statuses,
                                     "elapsed_ms": (perf_counter() - start) * 1000}
        rows.append(row)
    return rows


def summarize(rows, configurations):
    summary = {}
    for name in configurations:
        samples = [row["variants"][name] for row in rows]
        measured = [sample["metrics"] for sample in samples if sample["metrics"] is not None]
        summary[name] = {"scored": len(measured), "expanded_queries": sum(bool(s["generated_queries"]) for s in samples),
                         "queries_with_hypotheses": sum(bool(s["hypotheses"]) for s in samples),
                         "expansion_statuses": dict(Counter(status for s in samples for status in s["expansion_statuses"])),
                         "p50_ms": median(s["elapsed_ms"] for s in samples),
                         **{key: mean(r[key] for r in measured) for key in ("recall@5", "recall@10", "ndcg@10")}}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "snapshot", "vectors", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--llm", action="store_true", help="Enable the two external model experiments")
    parser.add_argument("--only-ids", nargs="+")
    parser.add_argument("--multipart", action="store_true", help="Evaluate three composite requests with existing evidence labels")
    args = parser.parse_args()
    torch.set_num_threads(4)
    dataset, documents = (json.loads(path.read_text(encoding="utf-8")) for path in (args.dataset, args.snapshot))
    chunks = [chunk for doc in documents for chunk in doc["chunks"]]
    validate_dataset(dataset, chunks)
    config = embedding.embedding_configuration()
    archives = read_archives(args.vectors, chunks, config["dimensions"], config["model_repository"])
    verify_archives(archives)
    retriever = ArchivedRetriever(chunks, archives[1], args.rerank)
    source_cases = multipart_cases(dataset["queries"]) if args.multipart else dataset["queries"]
    cases = [case for case in source_cases if not args.only_ids or case["id"] in args.only_ids]
    if not cases or not any(case["covered"] for case in cases):
        parser.error("Select at least one case with labeled evidence")
    configurations = {"original": {}, "decomposition": {"decompose_parts": True}, "routing": {"routing": True}}
    if args.llm:
        configurations.update(multi_query={"alternatives": True}, multi_query_hyde={"alternatives": True, "hyde": True})
    rows = evaluate(retriever, cases, configurations)
    summary = summarize(rows, configurations)
    payload = {"archive": archives[1].name, "rerank": args.rerank, "query_count": len(rows),
               "intents": dict(Counter(row["intent"] for row in rows)), "summary": summary, "rows": rows}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
