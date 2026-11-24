# Azerbaijani insurance retrieval benchmark

**Best by nDCG@5: G. Hybrid with RRF and contextual reranker** (0.904).

The benchmark covers 108 distinct Azerbaijani queries and 43 passages. Most passages are synthetic. Three clauses come from the supplied medical-insurance PDF. Labels are curated for this fixture. Production legal accuracy remains unverified.

## Results

| Configuration | Recall@5 | Recall@10 | MRR | nDCG@5 | Retrieval ms p50 / p95 | Reranking ms p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A. Standard BM25 | 0.712 | 0.753 | 0.711 | 0.668 | 0.19 / 0.29 | — |
| B. BM25 + Azerbaijani normalization | 0.719 | 0.762 | 0.732 | 0.681 | 0.19 / 0.29 | — |
| C. BM25 + normalization + lemmatization | 0.807 | 0.878 | 0.810 | 0.746 | 0.23 / 0.36 | — |
| D. BM25 + query expansion | 0.813 | 0.884 | 0.815 | 0.758 | 0.36 / 0.55 | — |
| E. Qdrant dense retrieval | 0.832 | 0.927 | 0.855 | 0.795 | 128.80 / 165.02 | — |
| F. Hybrid with rank interleaving | 0.887 | 0.949 | 0.862 | 0.813 | 129.12 / 165.50 | — |
| G. Hybrid with RRF and contextual reranker | 0.950 | 0.961 | 0.941 | 0.904 | 129.26 / 165.65 | 3703.63 / 7217.79 |

## nDCG@5 by query category

| Category | Queries | A | B | C | D | E | F | G |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| formal | 12 | 0.854 | 0.854 | 0.857 | 0.913 | 0.875 | 0.941 | 1.000 |
| informal | 12 | 0.256 | 0.256 | 0.291 | 0.313 | 0.737 | 0.652 | 0.815 |
| morphology | 12 | 0.671 | 0.671 | 0.780 | 0.785 | 0.826 | 0.776 | 0.956 |
| incomplete | 12 | 0.421 | 0.498 | 0.762 | 0.762 | 0.704 | 0.794 | 0.863 |
| terminology | 12 | 0.896 | 0.896 | 0.903 | 0.915 | 0.837 | 0.911 | 0.972 |
| numbers | 12 | 0.914 | 0.959 | 0.960 | 0.953 | 0.909 | 0.950 | 0.928 |
| conditions | 12 | 0.739 | 0.730 | 0.839 | 0.811 | 0.819 | 0.824 | 0.967 |
| multi section | 12 | 0.718 | 0.715 | 0.754 | 0.770 | 0.746 | 0.796 | 0.880 |
| ambiguous | 12 | 0.545 | 0.549 | 0.570 | 0.599 | 0.703 | 0.672 | 0.758 |

## Salary threshold case (AZ097)

> Maaşım yüksəkdirsə, haqq hesablanmasında həddin təsiri nədir?

Ask which insurance type and which limit the user means if the distinction matters. In the supplied medical-insurance PDF, Article 15-10, clause 15-10.1.2 on PDF page 14 establishes a wage-based premium for the covered groups, subject to its scope and exceptions. The 8,000 manat figure separates two wage bands: 2% on the part up to the threshold and 0.5% on the portion above it. The higher portion is still assessed. Salary is the calculation base, the premium is the result, and a payout or insured-amount limit is a distinct concept. The clause does not establish a general salary–premium rule across insurance products or any universal payout ceiling.

Query expansion produced calculation, premium, tariff, threshold, wages. The alternative group was threshold, sum_insured.

| Configuration | Indexed salary clause rank | Contrast passages in top 10 |
| --- | ---: | --- |
| A | — | — |
| B | — | — |
| C | — | premium |
| D | 14 | premium, sum-insured, own-limit |
| E | 2 | premium |
| F | 3 | premium, sum-insured |
| G | 7 | premium |

The indexed clause reached the top five in E, F. The clause and distinct insured-amount evidence met their top-five and top-ten cutoffs, respectively, in F.

The evidence assessment above is the benchmark's expected interpretation. The run evaluates retrieval and query expansion. Answer generation is outside the benchmark.

## Method

- A uses generic lowercasing and word tokens. B adds Azerbaijani casing, Unicode normalization, and canonical legal numbers and units. C adds the domain lemmatizer. D adds the production terminology and query expansion. All lexical runs use positive-IDF BM25 with k1=0.3 and b=0.0.
- E uses intfloat/multilingual-e5-large and in-memory Qdrant with a vector threshold of 0. F alternates BM25 and dense ranks with deduplication. G applies unit-weight RRF with k=60 and BAAI/bge-reranker-v2-m3 to the first 12 fused candidates. Each branch and output list is capped at 20. Exact article shortcuts are disabled.
- Grade 3 is direct evidence, grade 2 is material supporting evidence or a plausible alternative, and grade 1 is partial context. Recall counts all positively labeled passages. MRR uses the first relevant hit in the returned list. nDCG@5 uses exponential gain. Quality metrics are macro-averaged.
- Latency excludes indexing, model loading, and warm-up. F and G retrieval latency is the sum of measured lexical and dense stages plus the measured merge, representing serial stage cost. Reranking latency is measured separately. These timings exclude network and API overhead.
- Host: Windows AMD64, PyTorch 2.11.0+cpu, 4 Torch threads. Inference used the local model cache.

Reproduce with `python evaluation/benchmark_insurance.py`.
