# Azerbaijani insurance retrieval before and after

## Root causes and implementation

- The old character budget left 155 production passage inputs above E5's 512-token limit. Tokenizer-aware legal child passages now cover the full body. Reranking, citations, and answer generation use the complete source parent.
- Repository name and passage text alone could reuse vectors from changed model or tokenizer artifacts. A deterministic configuration fingerprint now namespaces both collections and reusable vectors. Startup checks dimensions, IDs, and fingerprints before serving a collection.
- Dense search and BM25 could see prior context while the reranker received only the follow-up. A shared resolver now supplies the same standalone query to all three stages. It requests clarification when it cannot establish the reference.
- Earlier investigation also identified colloquial routing misses, spaced PDF headings that misplaced clauses, and citation-format failures that appeared as insufficient evidence. See the [initial retrieval audit](azerbaijani_retrieval_audit.md) and [production truncation evaluation](embedding_truncation_report.md).
- Structured log fields capture original and effective token counts, source identity, resolution decisions, and the fingerprint and validation outcome of each collection. Query text is logged at debug level. The benchmark never connects to application Qdrant.

## Original benchmark

The original 108 queries and graded labels are unchanged. Its 43 source passages produced 43 vectors before and 43 after.

| Version | Recall@5 | Recall@10 | MRR@20 | nDCG@5 | Retrieval ms p50 / p95 | Reranking ms p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Before | 0.948 | 0.958 | 0.941 | 0.903 | 73.92 / 109.18 | 2969.64 / 4877.13 |
| After | 0.948 | 0.958 | 0.941 | 0.903 | 74.45 / 100.66 | 2975.40 / 4974.73 |

Final top-20 rankings changed on 0 of 108 original queries.

| Focus subset | Queries | Recall@5 before / after | Recall@10 before / after | MRR@20 before / after | nDCG@5 before / after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Legal conditions | 12 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 0.967 / 0.967 |
| Numerical limits and values | 12 | 1.000 / 1.000 | 1.000 / 1.000 | 0.917 / 0.917 | 0.928 / 0.928 |
| Payment exclusions and qualifications | 8 | 0.844 / 0.844 | 0.844 / 0.844 | 0.938 / 0.938 | 0.868 / 0.868 |
| Notification, decision, and payment deadlines | 7 | 0.964 / 0.964 | 0.964 / 0.964 | 1.000 / 1.000 | 0.976 / 0.976 |

## Separate synthetic supplement

The original fixture has no labeled personal-data protection or claim limitation-period questions and contains no conversation history. The supplement uses fictional provisions and four follow-ups. Its metrics are excluded from the original benchmark aggregate. The long privacy passage is an encoder stress case supplied directly to the vector planner.

| Query | Relevant source | Final rank before / after | Dense rank before / after |
| --- | --- | ---: | ---: |
| İcbari sığorta ödənişi ilə bağlı iddia müddəti nə vaxt başlayır? | limitation | 1 / 1 | 1 / 1 |
| Sığorta tələbindəki şəxsi məlumatlar hansı halda üçüncü şəxsə verilə bilər? | privacy | 1 / 1 | 1 / 1 |
| Sığorta iddiasındakı tibbi məlumatları audit podratçısına vermək üçün hansı razılıq lazımdır? | privacy-tail | 1 / 1 | 11 / 1 |
| Bəs bu halda? | water-exception | 4 / 1 | 1 / 1 |
| Bəs istisnalar necə? | intentional-fire | 3 / 1 | 5 / 4 |
| Bu müddət neçə ildir? | limitation | 1 / 1 | 1 / 1 |
| Bu qayda KASKO-ya da aiddir? | kasko-scope | 1 / 1 | 1 / 1 |

### Four follow-ups

| Version | Recall@5 | Recall@10 | MRR@20 | nDCG@5 | Retrieval ms p50 / p95 | Reranking ms p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Before | 1.000 | 1.000 | 0.646 | 0.733 | 52.84 / 64.77 | 2783.82 / 14794.83 |
| After | 1.000 | 1.000 | 1.000 | 1.000 | 65.27 / 68.53 | 2984.06 / 14086.76 |

## Method and limits

- Both paths use the same runtime model artifacts, BM25 vocabulary, fusion settings, and rerank shortlist. Before reconstructs the older one-vector-per-passage encoding, recognized follow-up concatenation, and original-question reranking. After uses the workspace splitter and resolver. This is a paired implementation comparison, distinct from the historical A–G benchmark.
- In-memory Qdrant isolates both paths from application collections. Each branch can return 20 candidates. The reranker scores a 12-pair shortlist and the metric ranking is capped at 20. As in the original benchmark, exact article shortcuts are disabled.
- Retrieval latency includes resolution, BM25, dense search, and fusion. Reranking is timed separately. After warm-up the before/after execution order alternates. Startup, indexing, HTTP, and answer generation are outside the timings. The sample is too small to infer production latency gains.
- Docker Linux CPU, PyTorch 2.15.0+cpu, 4 Torch threads. Quality metrics use macro averages with the original fixture's relevance grades.
- Run `python evaluation/compare_insurance_retrieval.py` to reproduce the comparison. The [per-query results](insurance_before_after_results.json) retain the ranking, standalone text, and timings.
