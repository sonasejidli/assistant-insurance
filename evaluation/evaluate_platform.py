"""Versioned retrieval evaluation, expert review packets, and paired answer judgments."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from time import perf_counter
from unittest.mock import patch

from App import embedding, legal_documents, legal_evidence, query_plan, text_search
from App.query_resolution import resolve_query
from evaluation.benchmark_insurance import read_fixture
from evaluation.build_real_insurance_dataset import digest
from evaluation.evaluate_bge_reranking import shortlist, stage_quality
from evaluation.evaluate_query_planning import ArchivedRetriever, multipart_cases
from evaluation.evaluate_real_insurance import chunk_id, read_archives, validate_dataset, verified_approval, verify_archives


ROOT = Path(__file__).resolve().parent
LEGACY_FILES = ("insurance_queries.tsv", "bm25_cases.json", "reranker_cases.json", "salary_evidence.json")
STAGES = ("bm25", "dense", "rrf", "rrf_bge", "rrf_expansion", "rrf_routing", "rrf_cross_references")
ANSWER_METRICS = ("correctness", "faithfulness", "relevancy", "citation_accuracy", "evidence_coverage",
                  "qualifications", "exceptions", "abstention", "multi_source_consistency")
NEGATIVE_CONTROLS = (
    ("missing_legislation", "Fərdi məlumatlar haqqında Qanunun transsərhəd ötürülmə ilə bağlı tam hüquqi şərtləri nədir?"),
    ("related_insufficient", "KASKO dərsliyindəki qaydadan mənim müqaviləmdəki franşizanın dəqiq məbləğini tapa bilərsən?"),
    ("unsupported_conclusion", "Bu məlumatlarla sığortaçının konkret məhkəmə işində mütləq məsuliyyət daşıdığını təsdiq edə bilərsən?"),
)
EXTRA_MULTIPART = (
    ("İcbari sığortada və iş qəzası sığortasında gecikmiş müraciətə hansı müddətlər tətbiq olunur?", ("AZR023",)),
    ("İstehsalat riskinin icbari sığorta haqqı necə hesablanır və hansı hallarda hadisəni qəsdən törətmək ödənişdən imtinaya səbəb olur?", ("AZR074", "AZR010")),
    ("İcbari sığortada son sənəd alındıqdan sonra qərar üçün müddət nə qədərdir və hansı şəxsiyyət sənədləri istinad edilən qaydaya daxildir?", ("AZR097", "AZR095")),
)


class RankingRetriever(ArchivedRetriever):
    def search(self, resolution, *, k, filters):
        state = {"question": resolution.standalone, "original_question": "", "filters": filters,
                 "dense_query": resolution.dense_query, "k": k}
        for stage in (self._preprocess, self._bm25, self._vector_search, self._fuse):
            state.update(stage(state))
        return [self.chunks[document.metadata["index"]] for document in state["candidates"][:k]], 0.0


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fixture_lock(dataset):
    return {"legacy": {name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                       for name in LEGACY_FILES}, "real_corpus": digest(dataset)}


def lexical_baseline():
    chunks, cases, _ = read_fixture()
    bm25 = text_search.RetrievalBM25.from_chunks(chunks)
    ranks = []
    for case in cases:
        tokens, _ = text_search.lexical_query(case["query"])
        scores = bm25.get_scores(tokens)
        ranks.append([case["id"], sorted(range(len(chunks)), key=lambda i: -scores[i])[:10]])
    return {"cases": len(cases), "lexical_ranking_hash": digest(ranks)}


def review_packet(dataset):
    cases = {}
    for row in dataset["queries"]:
        cases[row["id"]] = {
            "query_id": row["id"], "category": row["category"], "query": row["query"], "history": row["history"],
            "expected_standalone_query": row.get("expected_standalone_query") or row.get("expected_standalone"),
            "document_ids": sorted({e["document_id"] for e in row["evidence"]}),
            "articles": sorted({e["article"] for e in row["evidence"] if e.get("article")}),
            "paragraphs": sorted({e["clause"] for e in row["evidence"] if e.get("clause")}),
            "passage_ids": row["relevant_parent_passage_ids"], "relevance": {e["parent_passage_id"]: e["relevance"] for e in row["evidence"]},
            "expected_answer": None, "required_qualifications": None, "covered": row["covered"],
            "multiple_passages_required": row["multiple_passages_required"],
            "expected_abstention": "insufficient" if not row["covered"] else None,
            "status": "pending", "reviewer": None, "expertise": None, "revision_history": [],
        }
    return {"schema_version": 1, "dataset_sha256": digest(dataset), "queries": cases}


def gold_approved(dataset, packet):
    if not verified_approval(dataset, packet):
        return False
    originals = review_packet(dataset)["queries"]
    for key, row in packet["queries"].items():
        if key not in originals:
            return False
        fixed = originals[key]
        if any(row.get(field) != fixed[field] for field in ("covered", "passage_ids", "relevance", "document_ids", "paragraphs", "articles")):
            return False
        if not row.get("revision_history") or not isinstance(row.get("required_qualifications"), list):
            return False
        if row["covered"] and not str(row.get("expected_answer") or "").strip():
            return False
        if not row["covered"] and row.get("expected_abstention") not in {"partial", "insufficient", "clarification"}:
            return False
    return True


def diagnostic_cases(dataset):
    for i, (category, query) in enumerate(NEGATIVE_CONTROLS, 1):
        yield {"id": f"NEG{i:02}", "category": category, "query": query, "history": [],
               "evidence": [], "covered": False, "expected_abstention": "insufficient"}
    yield from multipart_cases(dataset["queries"])
    by_id = {case["id"]: case for case in dataset["queries"]}
    for i, (query, references) in enumerate(EXTRA_MULTIPART, 4):
        parts = [by_id[key]["evidence"] for key in references]
        if len(parts) == 1:
            parts = [[item] for item in parts[0]]
        yield {"id": f"MP{i:02}", "category": "multipart", "query": query, "history": [], "covered": True,
               "evidence": list({item["parent_passage_id"]: item for part in parts for item in part}.values()),
               "part_parents": [[item["parent_passage_id"] for item in part] for part in parts]}


def summarize(rows):
    by_category = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    groups = {"overall": rows, **by_category}
    result = {}
    for category, group in groups.items():
        result[category] = {}
        for stage in STAGES:
            available = [row["stages"][stage] for row in group if stage in row["stages"]]
            scored = [row["metrics"] for row in available if row["metrics"] is not None]
            times = sorted(row["elapsed_ms"] for row in available)
            result[category][stage] = {"scored": len(scored), "cases": len(available),
                                       "latency_p50_ms": times[(len(times)-1)//2] if times else None,
                                       "latency_p95_ms": times[int((len(times)-1)*.95)] if times else None,
                                       **({metric: mean(row[metric] for row in scored) for metric in scored[0]} if scored else {})}
    return result


def evaluate_case(retriever, documents, case, *, rerank=False, llm=False):
    query = case["query"]
    resolution = resolve_query(query, case["history"], direct_article=bool(text_search.article_number(query)))
    grades = {item["parent_passage_id"]: item["relevance"] for item in case["evidence"]}
    row = {"id": case["id"], "category": case["category"], "stages": {}, "covered": case["covered"],
           "candidate_selection_failures": [], "reranker_demotions_at_5": []}
    if not resolution.standalone:
        row["outcome"] = "clarification"
        for name in STAGES:
            if (name != "rrf_bge" or rerank) and (name != "rrf_expansion" or llm):
                ranks = {key: None for key in grades}
                row["stages"][name] = {"ranks": ranks, "metrics": stage_quality(ranks, grades), "elapsed_ms": 0.0}
        return row
    state = {"question": resolution.standalone, "original_question": query, "k": 50}
    ids = lambda indexes: [chunk_id(retriever.chunks[index]) for index in indexes]
    plan = query_plan.plan_query(resolution, "az", forced=True)

    def record(name, order, start):
        positions = {key: rank for rank, key in enumerate(order, 1)}
        ranks = {key: positions.get(key) for key in grades}
        row["stages"][name] = {"ranks": ranks, "metrics": stage_quality(ranks, grades),
                               "elapsed_ms": (perf_counter()-start)*1000,
                               "candidate_count": len(order)}

    # Evaluate branch rankings even on explicit article queries. Exact lookup is reported separately in app tests.
    state["original_question"] = ""
    state.update(retriever._preprocess(state))
    for name, function, key in (("bm25", retriever._bm25, "lexical_rank"), ("dense", retriever._vector_search, "vector_rank")):
        start = perf_counter()
        state.update(function(state))
        record(name, ids(state[key][:50]), start)
    start = perf_counter()
    state.update(retriever._fuse(state))
    candidates = ids([doc.metadata["index"] for doc in state["candidates"][:50]])
    record("rrf", candidates, start)
    row["candidate_selection_failures"] = sorted(grades.keys() - set(candidates))
    if rerank:
        rerank_pool = set(ids([doc.metadata["index"] for doc in shortlist(retriever, state)]))
        row["candidate_selection_failures"] = sorted(grades.keys() - rerank_pool)
        start = perf_counter()
        ranked = retriever._rerank(state)["candidates"]
        record("rrf_bge", ids([doc.metadata["index"] for doc in ranked[:50]]), start)
        row["reranker_demotions_at_5"] = [key for key in grades if key in candidates[:5]
                                         and (row["stages"]["rrf_bge"]["ranks"][key] or 51) > 5]
    start = perf_counter()
    parents = [retriever.chunks[doc.metadata["index"]] for doc in state["candidates"][:5]]
    by_id = {chunk_id(chunk): (chunk, i) for doc in documents for i, chunk in enumerate(doc["chunks"])}
    extra, relationships = legal_evidence.expand_references(resolution.standalone, parents, by_id)
    expanded = list(dict.fromkeys([*candidates[:5], *map(chunk_id, extra), *candidates[5:]]))[:50]
    record("rrf_cross_references", expanded, start)
    row["cross_reference_targets"] = [link["included_target_passage_id"] for link in relationships]
    if case.get("part_parents"):
        hits, _, associations, parts = query_plan.retrieve_plan(retriever, plan, k=10, filters={}, decompose_parts=True)
        ordered = {chunk_id(hit): associations.get(query_plan.passage_key(hit), ()) for hit in hits}
        row["multipart"] = [{"required": parents, "found": [key for key in parents if key in ordered],
                              "attributed": [key for key in parents if f"Q{i}" in ordered.get(key, ())]}
                             for i, parents in enumerate(case["part_parents"], 1)]
    for name, options in (("rrf_routing", {"routing": True}), ("rrf_expansion", {"alternatives": True})):
        if name == "rrf_expansion" and not llm:
            continue
        start = perf_counter()
        if name == "rrf_expansion":
            expansion = query_plan.generated_queries(resolution.standalone, alternatives=True, hyde=False)
            row["expansion_status"] = expansion.status
            with patch.object(query_plan, "generated_queries", return_value=expansion):
                hits, _, _, _ = query_plan.retrieve_plan(retriever, plan, k=50, filters={}, **options)
        else:
            hits, _, _, _ = query_plan.retrieve_plan(retriever, plan, k=50, filters={}, **options)
        record(name, list(map(chunk_id, hits)), start)
    return row


def answer_agreement(packet):
    rows = packet["examples"]
    if (not 30 <= len(rows) <= 50 or packet.get("status") != "approved"
            or len({row["id"] for row in rows}) != len(rows)):
        raise ValueError("Require 30–50 unique, approved human-reviewed answers")
    if any(not row.get("reviewer") or not row.get("answer_sha256") or not row.get("judge_version")
           or set(row["human"]) != set(ANSWER_METRICS) or set(row["automated"]) != set(ANSWER_METRICS) for row in rows):
        raise ValueError("Each judgment must identify the reviewer, answer, judge revision, and complete rubric")
    result = {}
    for metric in ANSWER_METRICS:
        pairs = [(row["human"][metric], row["automated"][metric]) for row in rows]
        if any(value is not None and type(value) is not bool for pair in pairs for value in pair):
            raise ValueError("Judgments must be Boolean or null for not applicable")
        matched = [(human, automated) for human, automated in pairs if human is not None and automated is not None]
        result[metric] = {"human_scored": sum(human is not None for human, _ in pairs), "jointly_scored": len(matched),
                          "human_pass_rate": mean(human for human, _ in pairs if human is not None) if any(h is not None for h, _ in pairs) else None,
                          "judge_agreement": mean(human == automated for human, automated in matched) if matched else None,
                          "judge_false_passes": sum(not human and automated for human, automated in matched)}
    return result


def pending_answers(dataset):
    grouped = defaultdict(list)
    for row in dataset["queries"]:
        grouped[row["category"]].append(row)
    cohort = [group[i] for i in range(4) for group in grouped.values() if len(group) > i][:36]
    return {"status": "pending", "dataset_sha256": digest(dataset), "evaluated_commit": None, "examples": [
        {"id": case["id"], "reviewer": None, "answer_sha256": None, "judge_version": None,
         "human": dict.fromkeys(ANSWER_METRICS), "automated": dict.fromkeys(ANSWER_METRICS)} for case in cohort
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("lock", "ci", "packet", "answer-packet", "answers", "retrieval"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--dataset", type=Path, help="Explicitly versioned alternative corpus labels for review and scoring")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--vectors", type=Path)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--suite", choices=("full", "controls"), default="full")
    parser.add_argument("--expected-commit")
    args = parser.parse_args()
    if args.dataset and args.operation in {"lock", "ci"}:
        parser.error("Fixture locks always verify the original datasets")
    dataset = read(args.dataset or ROOT / "real_insurance_dataset.json")
    if args.operation == "lock":
        result = fixture_lock(dataset)
    elif args.operation == "packet":
        result = review_packet(dataset)
    elif args.operation == "answer-packet":
        result = pending_answers(dataset)
    elif args.operation == "answers":
        packet = read(args.reviews)
        if packet.get("dataset_sha256") != digest(dataset) or (args.expected_commit and packet.get("evaluated_commit") != args.expected_commit):
            parser.error("Answer judgments must match the dataset and evaluated commit")
        result = answer_agreement(packet)
    elif args.operation == "ci":
        if fixture_lock(dataset) != read(ROOT / "benchmark_lock.json"):
            raise SystemExit("Benchmark content changed. Review and version the fixture explicitly.")
        result = lexical_baseline()
        if result != read(ROOT / "ci_lexical_baseline.json"):
            raise SystemExit(f"Lexical golden rankings changed: {result}")
    else:
        approved = args.reviews is not None and gold_approved(dataset, read(args.reviews))
        if not approved and not args.draft:
            parser.error("Full gold reporting requires the approved, hash-bound expert packet")
        if not args.snapshot or not args.vectors:
            parser.error("Provide both frozen snapshot and vector archive")
        import torch

        torch.set_num_threads(4)
        documents = read(args.snapshot)
        legal_documents.link_references(documents)
        chunks = [chunk for document in documents for chunk in document["chunks"]]
        validate_dataset(dataset, chunks)
        config = embedding.embedding_configuration()
        archives = read_archives(args.vectors, chunks, config["dimensions"], config["model_repository"])
        verify_archives(archives)
        retriever = RankingRetriever(chunks, archives[1], False)
        cases = dataset["queries"] if args.suite == "full" else [case for case in dataset["queries"] if not case["covered"]]
        rows = [evaluate_case(retriever, documents, case, rerank=args.rerank, llm=args.llm) for case in cases]
        controls = [evaluate_case(retriever, documents, case, rerank=args.rerank, llm=args.llm) for case in diagnostic_cases(dataset)]
        result = {"gold": approved and not args.draft and args.suite == "full", "dataset_sha256": digest(dataset),
                  "archive": archives[1].name, "summary": summarize(rows), "rows": rows,
                  "draft_control_summary": summarize(controls), "draft_controls": controls}
    if args.output:
        write(args.output, result)
    else:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
