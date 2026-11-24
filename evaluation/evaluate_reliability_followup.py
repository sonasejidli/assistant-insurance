"""Paired multipart, source discovery, and deterministic citation regression probes."""

import json
from collections import Counter
from pathlib import Path
from time import perf_counter

import torch

from App import embedding, legal_answers, legal_documents, legal_evidence, query_plan, text_search
from App.document_processing import load_documents
from App.query_resolution import resolve_query
from evaluation.evaluate_platform import ROOT, RankingRetriever, diagnostic_cases, read, write
from evaluation.evaluate_real_insurance import chunk_id, read_archives, validate_dataset, verify_archives


SOURCE_PROBES = (
    ("Mülki Məcəllədə sığorta müqaviləsi nədir?", "civil-code.pdf", "883", "müqaviləsi"),
    ("Fərdi məlumatların transsərhəd ötürülməsi hansı hallarda mümkündür?", "personal-data.pdf", "14", "transsərhəd"),
    ("Həkim sirri təşkil edən məlumat razılıq olmadan nə vaxt verilə bilər?", "health-confidentiality.txt", "53", "razılığı olmadan"),
    ("Avtomobil sahiblərinin icbari sığorta haqqı məbləğinin hesablanması qaydası və baza haqqı", "motor-tariff.pdf", None, "baza sığorta haqqı 50"),
)


def compare_multipart(retriever, documents, cases, *, provision_mode=False):
    rows = []
    for case in cases:
        if not case.get("part_parents"):
            continue
        row = {"id": case["id"], "query": case["query"], "variants": {}}
        variants = [("baseline", False, False), ("reliability", True, False)]
        if provision_mode:
            variants.append(("provisions", True, True))
        for name, enabled, provision in variants:
            start = perf_counter()
            plan = query_plan.plan_query(resolve_query(case["query"], []), "az", forced=True, reliability=enabled, provision=provision)
            hits, _, associations, parts = query_plan.retrieve_plan(retriever, plan, k=10, filters={},
                decompose_parts=True, routing=enabled, reliability=enabled, provision=provision)
            seen = {chunk_id(hit): associations[query_plan.passage_key(hit)] for hit in hits}
            by_part = [sum(f"Q{i}" in seen.get(key, ()) for key in expected)
                       for i, expected in enumerate(case["part_parents"], 1)]
            requirements = list(map(len, case["part_parents"]))
            package = legal_evidence.assemble_evidence(case["query"], hits, documents, associations=associations,
                part_questions={part.id: part.question for part in parts} if enabled else None, critical_groups=provision)
            assembled = {item["passage_id"]: item["subquestions"] for item in package.items}
            assembled_by_part = [sum(f"Q{i}" in assembled.get(key, ()) for key in expected)
                                 for i, expected in enumerate(case["part_parents"], 1)]
            row["variants"][name] = {"attributed": by_part, "required": requirements, "complete": by_part == requirements,
                "attributed_after_assembly": assembled_by_part, "complete_after_assembly": assembled_by_part == requirements,
                "missing_labeled": [[key for key in expected if f"Q{i}" not in assembled.get(key, ())]
                                    for i, expected in enumerate(case["part_parents"], 1)],
                "recall": {str(k): sum(key in list(seen)[:k] for key in {pid for part in case["part_parents"] for pid in part}) /
                           len({pid for part in case["part_parents"] for pid in part}) for k in (5, 10)},
                "parts": [part.question for part in parts], "parents": list(seen), "elapsed_ms": (perf_counter()-start)*1000}
        rows.append(row)
    return rows


def source_discovery(base, staged):
    results = {}
    for name, chunks in (("baseline", base), ("staged", [*base, *staged])):
        bm25 = text_search.RetrievalBM25.from_chunks(chunks)
        rows = []
        for query, target, article, phrase in SOURCE_PROBES:
            scores = bm25.get_scores(text_search.lexical_query(query)[0])
            ranked = sorted((i for i, score in enumerate(scores) if score > 0), key=lambda i: -scores[i])
            rank = next((i for i, index in enumerate(ranked, 1) if chunks[index]["doc"] == target), None)
            passage_rank = next((i for i, index in enumerate(ranked, 1) if chunks[index]["doc"] == target
                                 and (article is None or chunks[index]["metadata"].get("article") == article)
                                 and phrase in chunks[index]["text"].casefold()), None)
            rows.append({"query": query, "source": target, "rank": rank, "anchor_rank": passage_rank})
        results[name] = rows
    return results


def claim_probes():
    evidence = {"S1": {"original_text": "18.1. Sığortaçı sonuncu sənəddən sonra 7 iş günü ərzində ödəniş edir. 17.1-ci maddə tətbiq edilir.",
                        "article": "18", "clause": "18.1"}}
    rows = (("Ödəniş 7 iş günü ərzində edilir.", "S1", True), ("Ödəniş 7 təqvim günü ərzində edilir.", "S1", False),
            ("Ödəniş 7 ay ərzində edilir.", "S1", False), ("Ödəniş 7 gün ərzində edilir.", "S1", False),
            ("17.1-ci maddə qaydanı müəyyən edir.", "S1", False),
            ("Ödəniş 9 iş günü ərzində edilir.", "S1", False), ("Ödəniş 7 iş günü ərzində edilir.", "S99", False))
    return [{"claim": text, "expected_binding": expected, **{
        name: legal_answers.claim_is_bound(legal_answers.Claim(text=text, source_ids=[marker]), evidence, set(), strict=enabled)
        for name, enabled in (("baseline", False), ("guarded", True))}}
        for text, marker, expected in rows]


def main():
    torch.set_num_threads(4)
    dataset = read(ROOT / "real_insurance_dataset.json")
    documents = read(".venv/eval_corpus_snapshot.json")
    chunks = [chunk for document in documents for chunk in document["chunks"]]
    validate_dataset(dataset, chunks)
    legal_documents.link_references(documents)
    config = embedding.embedding_configuration()
    archives = read_archives(Path(".venv/real_eval_vectors.jsonl"), chunks, config["dimensions"], config["model_repository"])
    verify_archives(archives)
    retriever = RankingRetriever(chunks, archives[1], False)
    multipart = compare_multipart(retriever, documents, diagnostic_cases(dataset))
    staged = load_documents(Path("data/staged_legal"), staged=True)
    staged_chunks = [chunk for document in staged for chunk in document["chunks"]]
    staged_ids = {doc["metadata"]["document_id"] for doc in staged}
    legal_documents.link_references([*documents, *staged])
    result = {"multipart": multipart, "source_discovery": source_discovery(chunks, staged_chunks), "claim_guard": claim_probes(),
              "staged_passages": dict(Counter(chunk["doc"] for chunk in staged_chunks)), "review_status": "draft diagnostics",
              "verified_links_to_staged": dict(Counter(reference["reference_type"] for chunk in [*chunks, *staged_chunks]
                  for reference in chunk.get("legal_references", []) if reference["resolution_status"] == "verified"
                  and reference["referenced_document_id"] in staged_ids))}
    write(ROOT / "reliability_followup_results.json", result)
    print(json.dumps({"complete": {name: sum(row["variants"][name]["complete"] for row in multipart)
                                  for name in ("baseline", "reliability")}, "source_discovery": result["source_discovery"],
                      "staged_passages": result["staged_passages"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
