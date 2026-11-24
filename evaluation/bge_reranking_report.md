# BGE cross-encoder policy experiment

**Recommendation:** Keep the baseline as the production default. The bounded BGE path is an opt-in guard against silent overlength truncation. The held-out sample and latency repetitions are too small to justify a production ranking or speed claim.

Both paths use `BAAI/bge-reranker-v2-m3`. The experiment evaluates the policy, not a model replacement. See the [baseline audit](bge_reranking_audit.md) for the active revision, tokenizer, pair limit, parent resolution, score handling, and defaults.

## Validation-only tuning

The split assigned 54 queries to validation and 110 to held-out. Queries sharing labeled parents stay in the same partition. Label review is pending. The grid uses candidate inclusion and unreranked RRF metrics. Higher validation nDCG@10 selects the weights. The smallest pool within 0.03 of the selected weights' best candidate recall is selected. No held-out measurements select settings.

Selected BM25/dense weights **0.7/0.3**, pool **50**, RRF constant **60**.

| Weights BM25/dense | Candidate pool | Scored queries | Candidate recall | RRF nDCG@10 | All required at 5 / 8 / 10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.5/0.5 | 30 | 49 | 0.712 | 0.455 | 0.449 / 0.531 / 0.531 |
| 0.5/0.5 | 40 | 49 | 0.727 | 0.455 | 0.449 / 0.531 / 0.531 |
| 0.5/0.5 | 50 | 49 | 0.747 | 0.455 | 0.449 / 0.531 / 0.531 |
| 0.6/0.4 | 30 | 49 | 0.681 | 0.441 | 0.429 / 0.531 / 0.531 |
| 0.6/0.4 | 40 | 49 | 0.701 | 0.441 | 0.429 / 0.531 / 0.531 |
| 0.6/0.4 | 50 | 49 | 0.763 | 0.441 | 0.429 / 0.531 / 0.531 |
| 0.4/0.6 | 30 | 49 | 0.714 | 0.432 | 0.408 / 0.490 / 0.490 |
| 0.4/0.6 | 40 | 49 | 0.714 | 0.432 | 0.408 / 0.490 / 0.490 |
| 0.4/0.6 | 50 | 49 | 0.727 | 0.432 | 0.408 / 0.490 / 0.490 |
| 0.7/0.3 | 30 | 49 | 0.681 | 0.457 | 0.408 / 0.531 / 0.531 |
| 0.7/0.3 | 40 | 49 | 0.701 | 0.457 | 0.408 / 0.531 / 0.531 |
| 0.7/0.3 | 50 | 49 | 0.742 | 0.457 | 0.408 / 0.531 / 0.531 |

## Held-out comparison

This paired exploratory sample covers 15 held-out queries. It includes the source categories below, multi-parent labels, and an unanswerable control. The control is reported without a relevance denominator. The original 108-query fixture is untouched.

- A uses equal RRF weights and the existing BGE scoring path.
- B uses equal RRF weights and bounded BGE scoring.
- C uses the selected RRF weights and the existing BGE scoring path.
- D uses the selected RRF weights and bounded BGE scoring.

All four experiments use the selected validation pool. A retains the baseline scoring policy, while the running service still uses its independent 24-parent default.

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 14 | 0.679 | 0.714 | 0.714 | 0.714 | 0.645 | 0.607 | 0.621 |
| B | 14 | 0.679 | 0.714 | 0.714 | 0.714 | 0.645 | 0.607 | 0.621 |
| C | 14 | 0.679 | 0.750 | 0.750 | 0.750 | 0.714 | 0.640 | 0.669 |
| D | 14 | 0.679 | 0.750 | 0.750 | 0.750 | 0.714 | 0.640 | 0.669 |

| Experiment | Selected-pool recall | All required in final context at 5 / 8 / 10 |
| --- | ---: | ---: |
| A | 0.714 | 0.500 / 0.571 / 0.571 |
| B | 0.714 | 0.500 / 0.571 / 0.571 |
| C | 0.750 | 0.500 / 0.643 / 0.643 |
| D | 0.750 | 0.500 / 0.643 / 0.643 |

## Category results

### Payment exclusions

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 1.000 | 0.613 | 0.613 |
| B | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 1.000 | 0.613 | 0.613 |
| C | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 1.000 | 0.613 | 0.613 |
| D | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 1.000 | 0.613 | 0.613 |

### Legal periods

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| B | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| C | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| D | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

### Personal medical data

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 2 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| B | 2 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| C | 2 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| D | 2 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |

### Casco compulsory

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 2 | 0.250 | 0.250 | 0.250 | 0.250 | 0.500 | 0.307 | 0.307 |
| B | 2 | 0.250 | 0.250 | 0.250 | 0.250 | 0.500 | 0.307 | 0.307 |
| C | 2 | 0.250 | 0.250 | 0.250 | 0.250 | 0.500 | 0.307 | 0.307 |
| D | 2 | 0.250 | 0.250 | 0.250 | 0.250 | 0.500 | 0.307 | 0.307 |

### Limits calculations

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 0.333 | 0.307 | 0.307 |
| B | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 0.333 | 0.307 | 0.307 |
| C | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.387 | 0.387 |
| D | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.387 | 0.387 |

### Reinsurance

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.631 | 0.631 |
| B | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.631 | 0.631 |
| C | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.631 | 0.631 |
| D | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.631 | 0.631 |

### Claims compensation

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| B | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| C | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| D | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

### Exceptions qualifications

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.712 | 0.712 |
| B | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.712 | 0.712 |
| C | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.712 | 0.712 |
| D | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.712 | 0.712 |

### Informal morphology

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| B | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| C | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| D | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

### Conversational

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 3 | 0.667 | 0.833 | 0.833 | 0.833 | 0.567 | 0.541 | 0.606 |
| B | 3 | 0.667 | 0.833 | 0.833 | 0.833 | 0.567 | 0.541 | 0.606 |
| C | 3 | 0.667 | 1.000 | 1.000 | 1.000 | 0.833 | 0.667 | 0.804 |
| D | 3 | 0.667 | 1.000 | 1.000 | 1.000 | 0.833 | 0.667 | 0.804 |

### Coverage gap

| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0 | — | — | — | — | — | — | — |
| B | 0 | — | — | — | — | — | — | — |
| C | 0 | — | — | — | — | — | — | — |
| D | 0 | — | — | — | — | — | — | — |

## Per-query outcomes

The following ranks are the best labeled-parent rank in each experiment. The [main run](bge_reranking_results.json) and [privacy run](bge_reranking_privacy_results.json) retain BM25, dense, RRF, candidate-pool, and final rank for each labeled parent, plus final selection at 5, 8, and 10. A dash means no labeled parent in the top 50.

| ID | Query | A | B | C | D |
| --- | --- | ---: | ---: | ---: | ---: |
| AZR001 | İcbari sığortada hərbi əməliyyat və radioaktiv çirklənmə nəticəsində yaranan zərər üzrə imtina necə əsaslandırılır? | 1 | 1 | 1 | 1 |
| AZR017 | İcbari sığortada sağlamlığa və əmlaka vurulan zərər üzrə sığorta tələbinin iddia müddəti nə qədərdir? | 1 | 1 | 1 | 1 |
| AZR035 | Hüquqi şəxs olan faydalananın biznes sirri sığorta sirrinin tərkibinə daxildirmi? | 1 | 1 | 1 | 1 |
| AZR048 | Sığorta dərsliyinin lüğətində KASKO üzrə sığorta obyekti kimi nə göstərilir? | — | — | — | — |
| AZR063 | Standart və sərhəd avtoicbari müqavilələrində sağlamlıq zərəri üçün bir nəfərlik və bir hadisəlik hədd necə ayrılır? | 3 | 3 | 2 | 2 |
| AZR081 | Azərbaycandakı əmlak riskini yerli sığortaçıda təkrarsığortalayanda hansı brokerin vasitəçiliyi mümkündür? | 2 | 2 | 2 | 2 |
| AZR093 | Hadisəni sığortaçıya telefonda demişəm. Yazılı tələb blankını nə vaxta qədər göndərməlidir? | 1 | 1 | 1 | 1 |
| AZR109 | İcbari müqavilədə azadolma məbləğinin olmaması qaydasının Bakıdakı yaşayış əmlakı üçün istisnası nədir? | 2 | 2 | 2 | 2 |
| AZR123 | Sığorta pulumu gecikdiriblər, hər gec günə nə qədər faiz düşür? | 1 | 1 | 1 | 1 |
| AZR137 | Bu müddət neçə ildir? | 1 | 1 | 1 | 1 |
| AZR152 | Mənim QZ-478 nömrəli avtoicbari ödəniş işim indi hansı mərhələdədir? | — | — | — | — |
| AZR051 | KASKO-nun dərslikdəki obyekti ilə avtoicbari mülki məsuliyyət sığortasının qanundakı məqsədi necə fərqlənir? | 1 | 1 | 1 | 1 |
| AZR138 | Bəs istisnalar necə? | 5 | 5 | 1 | 1 |
| AZR036 | Sığortaçının şəxsi məlumatımı başqa adama verməsi üçün mənim şifahi razılığım kifayətdir? | — | — | — | — |
| AZR141 | Bəs yazılı razılıq nə vaxt lazımdır? | 2 | 2 | 2 | 2 |

## Failure and latency interpretation

- A → B: 0 labeled-parent rank improvements, 0 regressions, 0 pool admissions, and 0 pool losses.
- C → D: 0 labeled-parent rank improvements, 0 regressions, 0 pool admissions, and 0 pool losses.
- A → C: 2 labeled-parent rank improvements, 1 regressions, 1 pool admissions, and 0 pool losses.
- B → D: 2 labeled-parent rank improvements, 1 regressions, 1 pool admissions, and 0 pool losses.

A versus B and C versus D hold retrieval constant. The reranking policy can only change ordering inside the selected pool. A versus C and B versus D change RRF weighting and may change candidate membership. A rank movement on a single colloquial or exception case cannot establish a general semantic gain.

## Cases for follow-up

- AZR048 had zero labeled parents in the equal-weight scoring pool. Its recorded BM25 and dense lists contained 0 and 0 labeled parents, respectively.
- AZR152 is a coverage-gap control. This retrieval experiment did not test answer abstention.
- AZR036 had zero labeled parents in the equal-weight scoring pool. Its recorded BM25 and dense lists contained 0 and 1 labeled parents, respectively.
- AZR141 written-consent follow-up had labeled-parent ranks 8, 2 in A.
- AZR141 written-consent follow-up had labeled-parent ranks 8, 2 in D.

## CPU latency

| Experiment | Uncached samples | Reranking p50 / p95 ms | Pipeline p50 / p95 ms |
| --- | ---: | ---: | ---: |
| A | 2 | 34888.60 / 35409.24 | 35019.81 / 35531.83 |
| B | 2 | 26011.23 / 26954.26 | 26133.69 / 27081.44 |
| C | 2 | 33800.72 / 34303.52 | 33927.04 / 34423.70 |
| D | 2 | 23280.90 / 23662.60 | 23396.35 / 23781.02 |

CPU only, 4 Torch threads. Ranking scores were computed in batches on the union of candidate parents for each policy and reused across its weight settings. Latency observations replayed each configuration independently without cached scores after model load. Pipeline timings end at final context selection. They exclude HTTP, startup, and answer generation. Pairwise p95 values from two samples are descriptive.

The benchmark uses an isolated exact copy of the existing token-aware archive. The application service and its Qdrant collections were untouched. CUDA was unavailable in the audit environment. The device setting was tested at the model interface only.

## Reproduction

Use the frozen corpus export and archived vectors described in the [real-corpus report](real_insurance_report.md). Run the commands in an isolated environment with the project's dependencies and cached Hugging Face weights. Set `RERANK_MODEL` to the local snapshot directory for the BGE commit in the audit to pin the checkpoint. The checks cover loading, batching, overlength refusal, preserving a late exception and source citations, and keeping shared legal parents out of both benchmark partitions.

```sh
python -m evaluation.evaluate_bge_reranking --dataset evaluation/real_insurance_dataset.json --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl --output evaluation/bge_reranking_results.json
python -m evaluation.evaluate_bge_reranking --dataset evaluation/real_insurance_dataset.json --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl --latency-cases 0 --only-ids AZR036 AZR141 --output evaluation/bge_reranking_privacy_results.json
python -m evaluation.render_bge_reranking_report --results evaluation/bge_reranking_results.json --additional evaluation/bge_reranking_privacy_results.json --output evaluation/bge_reranking_report.md
```

Keep `RERANK_MODE=baseline` for rollback. Before adoption, repeat the comparison with expert-approved judgments, a larger held-out sample, and representative deployment hardware.
