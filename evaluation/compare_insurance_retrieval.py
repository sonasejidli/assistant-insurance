"""Paired before-and-after benchmark using the existing insurance fixture."""
import argparse
import json
from pathlib import Path
from statistics import mean
from unittest.mock import patch

import numpy as np
import torch

from benchmark_insurance import latency, measure, metrics, read_fixture
from App import embedding, text_search, vector_store
from App.query_resolution import QueryResolution, resolve_query
from App.settings import RetrievalSettings


def supplemental_fixture():
    # These are fictional rules and are never added to the application corpus.
    chunks = [
        {"doc": "limitation", "text": "Sığorta ödənişi ilə bağlı məhkəmə iddiası üçün üç il nəzərdə tutulur. "
         "İddia müddəti sığortaçının yazılı imtinasının alındığı gündən başlayır."},
        {"doc": "privacy", "text": "Sığorta tələbindəki fərdi məlumatlar yalnız şəxsin razılığı olduqda "
         "və ya qanunla tələb edildikdə üçüncü şəxsə açıqlana bilər."},
        {"doc": "privacy-tail", "text": ("Yazışma möhürlənir və elektron arxivdə saxlanılır. Arxiv məsulu "
          "qeydiyyat nömrəsini və sənədin tarixini ayrıca yoxlayır. ") * 25
         + "İstisna: sığorta iddiasındakı tibbi məlumatlar audit podratçısına yalnız məlumat subyektinin "
         "ayrıca yazılı razılığı ilə verilə bilər."},
        {"doc": "kasko-scope", "text": "İcbari avtomobil sığortasının üçüncü şəxsin əmlakına görə məsuliyyət "
         "limiti KASKO-ya tətbiq edilmir. KASKO üzrə öz avtomobilinə dəyən zərərin sığorta məbləği "
         "müqavilədə ayrıca müəyyən olunur."},
    ]
    rows = [
        ("limitation", "İcbari sığorta ödənişi ilə bağlı iddia müddəti nə vaxt başlayır?", "limitation", ""),
        ("privacy", "Sığorta tələbindəki şəxsi məlumatlar hansı halda üçüncü şəxsə verilə bilər?", "privacy", ""),
        ("privacy_tail", "Sığorta iddiasındakı tibbi məlumatları audit podratçısına vermək üçün hansı razılıq lazımdır?",
         "privacy-tail", ""),
        ("follow_up", "Bəs bu halda?", "water-exception",
         "Əmlak sığortasında boru qəfil partladıqda hansı hallarda su zərəri ödənilir?"),
        ("follow_up", "Bəs istisnalar necə?", "intentional-fire",
         "Əmlak sığortasında yanğın zərəri hansı hallarda ödənilir?"),
        ("follow_up", "Bu müddət neçə ildir?", "limitation",
         "İcbari sığorta ödənişi üzrə iddia müddəti nə qədərdir?"),
        ("follow_up", "Bu qayda KASKO-ya da aiddir?", "kasko-scope",
         "İcbari avtomobil sığortasında üçüncü şəxsin əmlakına zərər üçün limit nə qədərdir?"),
    ]
    return chunks, [{"id": f"S{i:02}", "category": category, "query": query, "relevance": {target: 3},
                     "history": [prior] if prior else []}
                    for i, (category, query, target, prior) in enumerate(rows, 1)]


def legacy_embed(texts, kind="passage"):
    model = embedding.get_model()
    return np.asarray(model.encode([embedding.model_input(text, kind) for text in texts],
                                   normalize_embeddings=True, batch_size=16), dtype=np.float32)


def run_case(retriever, case, before):
    original = case["query"]
    history = case.get("history", [])

    def retrieve():
        if before:
            standalone = f"{history[-1]} {original}" if history and original.lower().startswith("bəs ") else original
            query = QueryResolution(original, standalone)
        else:
            query = resolve_query(original, history)
        if query.standalone is None:
            return None, query
        # The existing benchmark disables exact article shortcuts.
        tokens, alternatives = text_search.lexical_query(query.bm25_query)
        state = {"question": query.standalone, "original_question": original, "k": 5,
                 "dense_query": query.dense_query, "rerank_query": original if before else query.rerank_query,
                 "eligible": list(range(len(retriever.chunks))), "query_tokens": tokens,
                 "alternative_concepts": alternatives}
        state.update(retriever._bm25(state))
        state.update(retriever._vector_search(state))
        state.update(retriever._fuse(state))
        return state, query

    (state, query), retrieval_ms = measure(retrieve)
    ranked, dense, rerank_ms = [], [], None
    if state is not None:
        candidates, rerank_ms = measure(lambda: retriever._rerank(state)["candidates"])
        ranked = [doc.metadata["doc"] for doc in candidates[:20]]
        dense = [retriever.chunks[i]["doc"] for i in state["vector_rank"]]
    return {**metrics(ranked, case["relevance"]), "standalone": query.standalone,
            "retrieval_ms": retrieval_ms, "rerank_ms": rerank_ms, "ranked": ranked, "dense": dense}


def compare(chunks, cases, label):
    settings = RetrievalSettings(bm25_top_k=20, vector_top_k=20, rerank_top_k=12)
    with patch.multiple(
        text_search, load_chunks=lambda: chunks, rerank_documents=text_search.rank_with_cross_encoder,
    ), patch.multiple(vector_store, QDRANT_PATH="", QDRANT_URL="", QDRANT_API_KEY=""):
        with patch.multiple(text_search, plan_passages=lambda chunks, texts: None, embed=legacy_embed):
            before = text_search.TextRetriever(settings)
        try:
            after = text_search.TextRetriever(settings)
            try:
                pair = ((True, before), (False, after))
                for old, retriever in pair:
                    with patch.object(text_search, "embed", legacy_embed if old else embedding.embed):
                        run_case(retriever, cases[0], old)
                results = []
                for i, case in enumerate(cases, 1):
                    scores = {}
                    for old, retriever in (pair if i % 2 else reversed(pair)):
                        with patch.object(text_search, "embed", legacy_embed if old else embedding.embed):
                            scores["before" if old else "after"] = run_case(retriever, case, old)
                    results.append({**case, **scores})
                    if i % 6 == 0:
                        print(f"{label}: compared {i}/{len(cases)}", flush=True)
                return {"rows": results, "points": [len(r.vector_index.index_by_id) for _, r in pair]}
            finally:
                after.close()
        finally:
            before.close()


def aggregate(rows, phase):
    scores = [row[phase] for row in rows]
    result = {key: round(mean(s[key] for s in scores), 6) for key in ("recall5", "recall10", "mrr", "ndcg5")}
    for key in ("retrieval_ms", "rerank_ms"):
        values = [s[key] for s in scores if s[key] is not None]
        result[key] = latency(values) if len(values) != 1 else f"{values[0]:.2f}"
    return result


def render_report(payload):
    core = payload["core"]["rows"]
    supplement = payload["supplement"]["rows"]
    points = payload["core"]["points"]
    followups = [row for row in supplement if row["category"] == "follow_up"]
    lines = [
        "# Azerbaijani insurance retrieval before and after", "",
        "## Root causes and implementation", "",
        "- The old character budget left 155 production passage inputs above E5's 512-token limit. "
        "Tokenizer-aware legal child passages now cover the full body. Reranking, citations, and answer "
        "generation use the complete source parent.",
        "- Repository name and passage text alone could reuse vectors from changed model or tokenizer artifacts. "
        "A deterministic configuration fingerprint now namespaces both collections and reusable vectors. "
        "Startup checks dimensions, IDs, and fingerprints before serving a collection.",
        "- Dense search and BM25 could see prior context while the reranker received only the follow-up. "
        "A shared resolver now supplies the same standalone query to all three stages. It requests clarification "
        "when it cannot establish the reference.",
        "- Earlier investigation also identified colloquial routing misses, spaced PDF headings that misplaced "
        "clauses, and citation-format failures that appeared as insufficient evidence. "
        "See the [initial retrieval audit](azerbaijani_retrieval_audit.md) and "
        "[production truncation evaluation](embedding_truncation_report.md).",
        "- Structured log fields capture original and effective token counts, source identity, resolution "
        "decisions, and the fingerprint and validation outcome of each collection. Query text is logged at "
        "debug level. The benchmark never connects to application Qdrant.",
        "", "## Original benchmark", "",
        f"The original {len(core)} queries and graded labels are unchanged. Its 43 source passages produced "
        f"{points[0]} vectors before and {points[1]} after.", "",
    ]
    latency_header = [
        "| Version | Recall@5 | Recall@10 | MRR@20 | nDCG@5 | Retrieval ms p50 / p95 | Reranking ms p50 / p95 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def metric_table(rows):
        lines.extend(latency_header)
        for phase in ("before", "after"):
            stats = aggregate(rows, phase)
            quality = [f"{stats[key]:.3f}" for key in ("recall5", "recall10", "mrr", "ndcg5")]
            values = " | ".join([*quality, stats["retrieval_ms"], stats["rerank_ms"]])
            lines.append(f"| {phase.title()} | {values} |")

    metric_table(core)
    changes = sum(row["before"]["ranked"] != row["after"]["ranked"] for row in core)
    lines.extend(["", f"Final top-20 rankings changed on {changes} of {len(core)} original queries."])
    lines.extend(["", "| Focus subset | Queries | Recall@5 before / after | Recall@10 before / after | MRR@20 before / after | nDCG@5 before / after |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"])
    groups = {
        "Legal conditions": [row for row in core if row["category"] == "conditions"],
        "Numerical limits and values": [row for row in core if row["category"] == "numbers"],
        "Payment exclusions and qualifications": [row for row in core if row["id"] in
                                                 {"AZ018", "AZ029", "AZ046", "AZ073", "AZ075", "AZ076", "AZ084", "AZ087"}],
        "Notification, decision, and payment deadlines": [row for row in core if row["id"] in
                                                         {"AZ003", "AZ025", "AZ032", "AZ078", "AZ079", "AZ086", "AZ105"}],
    }
    for label, rows in groups.items():
        before, after = (aggregate(rows, phase) for phase in ("before", "after"))
        values = " | ".join(f"{before[key]:.3f} / {after[key]:.3f}" for key in ("recall5", "recall10", "mrr", "ndcg5"))
        lines.append(f"| {label} | {len(rows)} | {values} |")
    lines.extend([
        "", "## Separate synthetic supplement", "",
        "The original fixture has no labeled personal-data protection or claim limitation-period questions and "
        "contains no conversation history. The supplement uses fictional provisions and four follow-ups. "
        "Its metrics are excluded from the original benchmark aggregate. The long privacy passage "
        "is an encoder stress case supplied directly to the vector planner.", "",
        "| Query | Relevant source | Final rank before / after | Dense rank before / after |",
        "| --- | --- | ---: | ---: |",
    ])
    for row in supplement:
        target, = row["relevance"]
        ranks = []
        for branch in ("ranked", "dense"):
            for phase in ("before", "after"):
                order = row[phase][branch]
                ranks.append(str(order.index(target) + 1) if target in order else ">20")
        lines.append(f"| {row['query']} | {target} | {ranks[0]} / {ranks[1]} | {ranks[2]} / {ranks[3]} |")
    lines.extend(["", "### Four follow-ups", ""])
    metric_table(followups)
    lines.extend([
        "", "## Method and limits", "",
        "- Both paths use the same runtime model artifacts, BM25 vocabulary, fusion settings, and rerank "
        "shortlist. Before reconstructs the older one-vector-per-passage encoding, recognized follow-up "
        "concatenation, and original-question reranking. After uses the workspace splitter and resolver. "
        "This is a paired implementation comparison, distinct from the historical A–G benchmark.",
        "- In-memory Qdrant isolates both paths from application collections. Each branch can return 20 "
        "candidates. The reranker scores a 12-pair shortlist and the metric ranking is capped at 20. "
        "As in the original benchmark, exact article shortcuts are disabled.",
        "- Retrieval latency includes resolution, BM25, dense search, and fusion. Reranking is timed "
        "separately. After warm-up the before/after execution order alternates. Startup, indexing, HTTP, and answer "
        "generation are outside the timings. The sample is too small to infer production latency gains.",
        f"- Docker Linux CPU, PyTorch {payload['torch']}, {payload['threads']} Torch threads. "
        "Quality metrics use macro averages with the original fixture's relevance grades.",
        "- Run `python evaluation/compare_insurance_retrieval.py` to reproduce the comparison. "
        "The [per-query results](insurance_before_after_results.json) retain the ranking, standalone text, and timings.",
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("insurance_before_after_results.json"))
    parser.add_argument("--report-only", action="store_true", help="Render the Markdown report from the measured JSON")
    parser.add_argument("--report", type=Path, default=Path(__file__).with_name("insurance_before_after_report.md"))
    args = parser.parse_args()
    if args.report_only:
        args.report.write_text(render_report(json.loads(args.output.read_text(encoding="utf-8"))), encoding="utf-8")
        return
    torch.set_num_threads(args.threads)
    chunks, cases, _ = read_fixture()
    additional_chunks, additional_cases = supplemental_fixture()
    core = compare(chunks, cases, "Existing fixture")
    supplement = compare(chunks + additional_chunks, additional_cases, "Supplement")
    payload = {"threads": args.threads, "torch": str(torch.__version__), "core": core, "supplement": supplement}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(render_report(payload), encoding="utf-8")
    for label, rows in (("core", core["rows"]), ("follow_up", [row for row in supplement["rows"]
                                                           if row["category"] == "follow_up"])):
        print(label, {phase: aggregate(rows, phase) for phase in ("before", "after")}, flush=True)


if __name__ == "__main__":
    main()
