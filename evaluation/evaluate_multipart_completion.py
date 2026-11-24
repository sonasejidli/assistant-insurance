"""Held-constant six-case comparison and per-part recall/attribution audit."""

import argparse
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

import torch

from App import legal_documents, legal_evidence, query_plan, text_search
from App.query_resolution import resolve_query
from evaluation.evaluate_bge_reranking import shortlist
from evaluation.evaluate_platform import RankingRetriever, diagnostic_cases, read, write
from evaluation.evaluate_query_planning import ArchivedRetriever
from evaluation.evaluate_real_insurance import chunk_id, validate_dataset
from evaluation.trace_passage_retrieval import build_index


def metrics(order, relevant):
    ranks = [i for i, key in enumerate(order, 1) if key in relevant]
    return {"recall5": sum(rank <= 5 for rank in ranks) / len(relevant), "recall10": len(ranks) / len(relevant),
            "mrr10": 1 / ranks[0] if ranks else 0,
            "ndcg10": sum(1/math.log2(rank+1) for rank in ranks) /
            sum(1/math.log2(i+1) for i in range(1, min(10, len(relevant))+1))}


def run_cases(retriever, documents, cases):
    rows = []
    for case in cases:
        if not case.get("part_parents"):
            continue
        report = {"id": case["id"], "requirements": case["part_parents"], "variants": {}}
        for enabled in (False, True):
            retriever.multipart_coverage = enabled
            plan = query_plan.plan_query(resolve_query(case["query"], []), "az", forced=True, provision=True)
            expected = {f"Q{i}": set(ids) for i, ids in enumerate(case["part_parents"], 1)}
            parts = {part.id: part.question for part in plan.parts}
            trace = defaultdict(dict)
            for part in plan.parts:
                state = {"question": part.question, "original_question": "", "k": 10}
                for method in (retriever._preprocess, retriever._bm25, retriever._vector_search, retriever._fuse):
                    state.update(method(state))
                stages = {"bm25": state["lexical_rank"], "dense": state["vector_rank"],
                          "fusion": [doc.metadata["index"] for doc in state["candidates"]],
                          "bge_eligible": [doc.metadata["index"] for doc in shortlist(retriever, state)]}
                if retriever.rerank:
                    state.update(retriever._rerank(state))
                    eligible = set(stages["bge_eligible"])
                    stages["bge"] = [doc.metadata["index"] for doc in state["candidates"] if doc.metadata["index"] in eligible]
                for name, order in stages.items():
                    positions = {chunk_id(retriever.chunks[index]): rank for rank, index in enumerate(order, 1)}
                    trace[part.id][name] = {key: positions.get(key) for key in sorted(expected.get(part.id, ()))}
            hits, _, associations, _ = query_plan.retrieve_plan(retriever, plan, k=10, filters={},
                                                                decompose_parts=True, routing=True, provision=True)
            packed = legal_evidence.assemble_evidence(case["query"], hits, documents, associations=associations,
                part_ids=parts.keys(), part_questions=parts, critical_groups=True, multipart_coverage=enabled)
            relevant = set().union(*expected.values())
            final = packed.items[:10]
            ids = [item["passage_id"] for item in final]
            missing = {part: sorted(ids - {item["passage_id"] for item in final if part in item["subquestions"]})
                       for part, ids in expected.items()}
            report["variants"]["after" if enabled else "before"] = {
                "parts": parts, "stage_ranks": dict(trace), "retrieved": [chunk_id(hit) for hit in hits],
                "final": [{key: item[key] for key in ("passage_id", "subquestions", "retrieval_source", "source_url")} for item in final],
                "metrics": metrics(ids, relevant), "missing": missing,
                "extra_attributions": sum(part != actual for item in final for part, wanted in expected.items()
                                          if item["passage_id"] in wanted for actual in item["subquestions"]),
                "complete": not any(missing.values()), "assigned": sum(len(ids)-len(missing[part]) for part, ids in expected.items()),
            }
        rows.append(report)
    return rows


def main():
    from App.document_processing import load_documents

    parser = argparse.ArgumentParser()
    parser.add_argument("--bge", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(4)
    dataset = read("evaluation/real_insurance_dataset.json")
    documents = read(".venv/eval_corpus_snapshot.json")
    base = [hit for doc in documents for hit in doc["chunks"]]
    validate_dataset(dataset, base)
    staged = load_documents(Path("data/staged_legal"), staged=True)
    staged_chunks = [hit for doc in staged for hit in doc["chunks"]]
    index = build_index(base, staged_chunks)
    documents += staged
    legal_documents.link_references(documents)
    retriever_type = ArchivedRetriever if args.bge else RankingRetriever
    retriever = retriever_type([*base, *staged_chunks], index, args.bge)
    retriever.provision_retrieval = True
    rows = run_cases(retriever, documents, diagnostic_cases(dataset))
    summary = {}
    for name in ("before", "after"):
        values = [row["variants"][name] for row in rows]
        summary[name] = {"complete": sum(row["complete"] for row in values), "assigned": sum(row["assigned"] for row in values),
                         "extra_attributions": sum(row["extra_attributions"] for row in values),
                         **{key: mean(row["metrics"][key] for row in values) for key in values[0]["metrics"]}}
    suffix = "_bge" if args.bge else ""
    write(f"evaluation/multipart_completion{suffix}_results.json", {"summary": summary, "rows": rows})
    print(summary)


if __name__ == "__main__":
    main()
