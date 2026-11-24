# Real Azerbaijani insurance evidence benchmark

**Exploratory draft.** 164 manually authored queries, including 150 provision-backed judgments and 14 coverage-gap controls.

The original 108-query benchmark is untouched. This suite quotes actual indexed text and keeps document, passage, and parent IDs. The evaluation used the entire frozen corpus. Labels were assigned before retrieving candidates. They are not necessarily exhaustive before expert review.

Before uses the archived one-vector-per-parent index and former follow-up behavior. After uses the archived tokenizer-split index and shared resolver. Dense search is exact on two isolated copies. Live Qdrant was only read for export. No vectors were merged across versions or written to application collections. This does not benchmark network or ANN latency or a fingerprint migration.

A, B, C, and D mean BM25, dense, RRF, and RRF plus reranking. Exact-article shortcuts are bypassed. Null ranks mean outside the measured top 50. Coverage gaps are excluded from relevance denominators.

## All queries, stages A–C

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 150 | 0.501 | 0.574 | 0.627 | 0.738 | 0.462 | 0.448 |
| bm25 | after | 150 | 0.494 | 0.582 | 0.648 | 0.746 | 0.463 | 0.453 |
| dense | before | 150 | 0.485 | 0.561 | 0.618 | 0.718 | 0.478 | 0.461 |
| dense | after | 150 | 0.482 | 0.561 | 0.619 | 0.718 | 0.471 | 0.458 |
| rrf | before | 150 | 0.586 | 0.648 | 0.723 | 0.769 | 0.525 | 0.518 |
| rrf | after | 150 | 0.590 | 0.658 | 0.730 | 0.776 | 0.531 | 0.527 |

## Paired reranking sample, stages A–D (15 queries)

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 14 | 0.579 | 0.643 | 0.671 | 0.671 | 0.451 | 0.465 |
| bm25 | after | 14 | 0.650 | 0.664 | 0.714 | 0.750 | 0.508 | 0.513 |
| dense | before | 14 | 0.479 | 0.479 | 0.543 | 0.579 | 0.529 | 0.472 |
| dense | after | 14 | 0.550 | 0.550 | 0.586 | 0.621 | 0.546 | 0.510 |
| rrf | before | 14 | 0.543 | 0.543 | 0.657 | 0.671 | 0.577 | 0.500 |
| rrf | after | 14 | 0.586 | 0.586 | 0.700 | 0.714 | 0.630 | 0.552 |
| reranked | before | 14 | 0.529 | 0.543 | 0.657 | 0.671 | 0.591 | 0.520 |
| reranked | after | 14 | 0.586 | 0.586 | 0.700 | 0.714 | 0.684 | 0.596 |

Stage D uses the same declared sample on both sides. A full stage D pass remains pending.

## Category-level results

### Payment exclusions

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 16 | 0.500 | 0.500 | 0.500 | 0.719 | 0.562 | 0.495 |
| bm25 | after | 16 | 0.500 | 0.500 | 0.500 | 0.719 | 0.562 | 0.495 |
| dense | before | 16 | 0.438 | 0.469 | 0.500 | 0.656 | 0.380 | 0.370 |
| dense | after | 16 | 0.438 | 0.469 | 0.500 | 0.656 | 0.380 | 0.370 |
| rrf | before | 16 | 0.469 | 0.562 | 0.625 | 0.688 | 0.504 | 0.464 |
| rrf | after | 16 | 0.469 | 0.562 | 0.625 | 0.688 | 0.504 | 0.464 |
| reranked | before | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 1.000 | 0.613 |
| reranked | after | 1 | 0.500 | 0.500 | 0.500 | 0.500 | 1.000 | 0.613 |

### Legal periods

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 15 | 0.700 | 0.767 | 0.933 | 0.933 | 0.625 | 0.640 |
| bm25 | after | 15 | 0.700 | 0.767 | 0.933 | 0.933 | 0.625 | 0.640 |
| dense | before | 15 | 0.633 | 0.767 | 0.767 | 0.867 | 0.640 | 0.651 |
| dense | after | 15 | 0.633 | 0.767 | 0.767 | 0.867 | 0.640 | 0.651 |
| rrf | before | 15 | 0.733 | 0.800 | 0.933 | 1.000 | 0.628 | 0.657 |
| rrf | after | 15 | 0.733 | 0.800 | 0.933 | 1.000 | 0.628 | 0.657 |
| reranked | before | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| reranked | after | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

### Personal medical data

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 16 | 0.500 | 0.594 | 0.625 | 0.719 | 0.440 | 0.436 |
| bm25 | after | 16 | 0.500 | 0.594 | 0.625 | 0.719 | 0.440 | 0.436 |
| dense | before | 16 | 0.469 | 0.594 | 0.594 | 0.656 | 0.448 | 0.459 |
| dense | after | 16 | 0.469 | 0.594 | 0.594 | 0.656 | 0.448 | 0.459 |
| rrf | before | 16 | 0.562 | 0.562 | 0.688 | 0.750 | 0.546 | 0.509 |
| rrf | after | 16 | 0.562 | 0.562 | 0.688 | 0.750 | 0.546 | 0.509 |
| reranked | before | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| reranked | after | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

### Casco compulsory

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 15 | 0.467 | 0.633 | 0.733 | 0.767 | 0.277 | 0.347 |
| bm25 | after | 15 | 0.467 | 0.633 | 0.733 | 0.767 | 0.277 | 0.347 |
| dense | before | 15 | 0.333 | 0.400 | 0.467 | 0.700 | 0.348 | 0.346 |
| dense | after | 15 | 0.333 | 0.400 | 0.467 | 0.700 | 0.348 | 0.346 |
| rrf | before | 15 | 0.567 | 0.633 | 0.700 | 0.767 | 0.408 | 0.456 |
| rrf | after | 15 | 0.567 | 0.633 | 0.700 | 0.767 | 0.408 | 0.456 |
| reranked | before | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| reranked | after | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

### Limits calculations

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 16 | 0.646 | 0.771 | 0.792 | 0.875 | 0.690 | 0.631 |
| bm25 | after | 16 | 0.646 | 0.771 | 0.792 | 0.875 | 0.690 | 0.631 |
| dense | before | 16 | 0.656 | 0.719 | 0.719 | 0.781 | 0.659 | 0.646 |
| dense | after | 16 | 0.656 | 0.719 | 0.719 | 0.781 | 0.659 | 0.646 |
| rrf | before | 16 | 0.781 | 0.844 | 0.844 | 0.844 | 0.749 | 0.729 |
| rrf | after | 16 | 0.781 | 0.844 | 0.844 | 0.844 | 0.749 | 0.729 |
| reranked | before | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| reranked | after | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

### Reinsurance

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 14 | 0.357 | 0.429 | 0.500 | 0.750 | 0.327 | 0.328 |
| bm25 | after | 14 | 0.357 | 0.429 | 0.500 | 0.750 | 0.327 | 0.328 |
| dense | before | 14 | 0.607 | 0.714 | 0.750 | 0.750 | 0.666 | 0.605 |
| dense | after | 14 | 0.607 | 0.714 | 0.750 | 0.750 | 0.666 | 0.605 |
| rrf | before | 14 | 0.714 | 0.750 | 0.750 | 0.750 | 0.407 | 0.481 |
| rrf | after | 14 | 0.714 | 0.750 | 0.750 | 0.750 | 0.407 | 0.481 |
| reranked | before | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| reranked | after | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

### Claims compensation

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 16 | 0.544 | 0.575 | 0.606 | 0.752 | 0.594 | 0.525 |
| bm25 | after | 16 | 0.544 | 0.575 | 0.606 | 0.752 | 0.594 | 0.525 |
| dense | before | 16 | 0.294 | 0.356 | 0.575 | 0.775 | 0.349 | 0.298 |
| dense | after | 16 | 0.294 | 0.356 | 0.575 | 0.775 | 0.349 | 0.298 |
| rrf | before | 16 | 0.544 | 0.700 | 0.700 | 0.762 | 0.499 | 0.507 |
| rrf | after | 16 | 0.544 | 0.700 | 0.700 | 0.762 | 0.499 | 0.507 |
| reranked | before | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| reranked | after | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

### Exceptions qualifications

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 14 | 0.614 | 0.736 | 0.774 | 0.810 | 0.610 | 0.562 |
| bm25 | after | 14 | 0.614 | 0.736 | 0.774 | 0.810 | 0.610 | 0.562 |
| dense | before | 14 | 0.579 | 0.674 | 0.688 | 0.738 | 0.657 | 0.578 |
| dense | after | 14 | 0.579 | 0.674 | 0.688 | 0.738 | 0.657 | 0.578 |
| rrf | before | 14 | 0.660 | 0.683 | 0.848 | 0.876 | 0.806 | 0.672 |
| rrf | after | 14 | 0.660 | 0.683 | 0.848 | 0.876 | 0.806 | 0.672 |
| reranked | before | 1 | 0.200 | 0.200 | 0.800 | 1.000 | 1.000 | 0.339 |
| reranked | after | 1 | 0.200 | 0.200 | 0.800 | 1.000 | 1.000 | 0.339 |

### Informal morphology

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 14 | 0.357 | 0.357 | 0.429 | 0.464 | 0.235 | 0.261 |
| bm25 | after | 14 | 0.357 | 0.357 | 0.429 | 0.464 | 0.235 | 0.261 |
| dense | before | 14 | 0.464 | 0.536 | 0.643 | 0.643 | 0.311 | 0.351 |
| dense | after | 14 | 0.464 | 0.536 | 0.643 | 0.643 | 0.311 | 0.351 |
| rrf | before | 14 | 0.357 | 0.429 | 0.607 | 0.714 | 0.299 | 0.318 |
| rrf | after | 14 | 0.357 | 0.429 | 0.607 | 0.714 | 0.299 | 0.318 |
| reranked | before | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.071 | 0.000 |
| reranked | after | 1 | 0.000 | 0.000 | 1.000 | 1.000 | 0.071 | 0.000 |

### Conversational

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 14 | 0.286 | 0.336 | 0.350 | 0.564 | 0.193 | 0.205 |
| bm25 | after | 14 | 0.214 | 0.429 | 0.571 | 0.643 | 0.212 | 0.255 |
| dense | before | 14 | 0.393 | 0.393 | 0.493 | 0.600 | 0.333 | 0.311 |
| dense | after | 14 | 0.357 | 0.393 | 0.500 | 0.607 | 0.256 | 0.275 |
| rrf | before | 14 | 0.457 | 0.493 | 0.529 | 0.529 | 0.381 | 0.368 |
| rrf | after | 14 | 0.500 | 0.607 | 0.607 | 0.607 | 0.440 | 0.459 |
| reranked | before | 5 | 0.340 | 0.380 | 0.380 | 0.380 | 0.240 | 0.266 |
| reranked | after | 5 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.477 |

### Coverage gap

| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | before | 0 | — | — | — | — | — | — |
| bm25 | after | 0 | — | — | — | — | — | — |
| dense | before | 0 | — | — | — | — | — | — |
| dense | after | 0 | — | — | — | — | — | — |
| rrf | before | 0 | — | — | — | — | — | — |
| rrf | after | 0 | — | — | — | — | — | — |
| reranked | before | 0 | — | — | — | — | — | — |
| reranked | after | 0 | — | — | — | — | — | — |

## Performance

Both sides used 4 Torch threads, 2 repeated runs per case and an 8-candidate rerank shortlist. Pair order alternated by query. Token counts include special tokens. Pipeline timing ends after evidence packing and excludes generation. Cold observations share a process. Warm summaries exclude the first query on each side.

| Version and sample | Retrieval p50 / p95 ms | Reranking p50 / p95 ms | Pipeline p50 / p95 ms | BM25 / dense candidates median | Query tokens median | Reranked pairs / pair tokens median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| before (A–C only) | 90.81 / 120.18 | — | 91.57 / 121.40 | 50 / 50 | 28 | — |
| after (A–C only) | 90.39 / 121.88 | — | 91.14 / 123.16 | 50 / 50 | 28 | — |
| before (A–D) | 94.48 / 115.04 | 4180.81 / 5672.18 | 4264.73 / 5774.93 | 50 / 50 | 29 | 8 / 192 |
| after (A–D) | 93.82 / 117.40 | 4352.69 / 5977.82 | 4406.41 / 6060.66 | 50 / 50 | 28 | 8 / 199.5 |

Process initialization included 2055 ms for embedding, 1174 ms for reranker setup, and 28061 ms for both archives. The JSON records individual first-query timings. The exploratory run does not establish a speed improvement.

## Failure diagnosis

Counts and examples identify observed symptoms to review. Low rank alone cannot distinguish query normalization, extraction, chunking, or missing labels. The review schema permits all requested failure categories and requires evidence.

- **Before** dense retrieval (46), hybrid fusion (9), lexical retrieval (7), reranking (1), coverage gap (14)
- **After** dense retrieval (44), hybrid fusion (11), lexical retrieval (6), query resolution (2), coverage gap (14)

| ID | Query | After diagnosis | Observation |
| --- | --- | --- | --- |
| AZR002 | Qəzada baqajdakı nağd pulum itib, icbari sığortadan həmin pulu ala bilərəm? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR004 | Hadisəyə görə işə gedə bilmədim və gəlirimi itirdim, bu itkini icbari sığorta ödəyir? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR019 | İcbari sığorta üzrə üçillik tələbi sığortalıdan başqa hansı şəxslər irəli sürə bilərlər? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR020 | İcbari sığorta tələbini irəli sürmə müddəti ilə sığortaçının sonuncu sənəddən sonra cavab müddəti necə fərqlənir? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR032 | Sığortalının adı və ünvanı hansı hüquqi məxfilik kateqoriyasına daxildir? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR036 | Sığortaçının şəxsi məlumatımı başqa adama verməsi üçün mənim şifahi razılığım kifayətdir? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR048 | Sığorta dərsliyinin lüğətində KASKO üzrə sığorta obyekti kimi nə göstərilir? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR049 | Dərslikdə KASKO və karqo sığortası obyektlərinə görə necə fərqləndirilir? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR064 | Maşınla özgəsinin hasarını vurmuşam. İcbari məsuliyyət sığortasının əmlak üzrə həddi nədir? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR074 | İstehsalat riskinin icbari sığorta tarifinə yuxarı hədd və haqqın əməkhaqqı fonduna görə hesablanması necə birlikdə tətbiq olunur? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR087 | Təkrarsığorta müqavilələri ötürülərkən iştirakçıların mənafeləri lazımi qaydada nəzərə alınmırsa, Mərkəzi Bank nə edir? | hybrid_fusion | Required evidence entered the candidate pools but did not reach the packed context. |
| AZR089 | Sığorta dərsliyinin lüğətində risksizləşdirmə zəncirində riski ötürən ilk sığortaçı hansı terminlə adlandırılır? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR094 | İcbari sığorta tələbində şəhadətnamə, sığortanın növü və sığortalının kimliyi üzrə hansı məlumatlar yazılmalıdır? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR096 | İcbari ödəniş üçün sığortaçı qanunda yazılmayan əlavə sənədi məndən istəyə bilərmi? | hybrid_fusion | Required evidence entered the candidate pools but did not reach the packed context. |
| AZR112 | İcbari avtomobil sığortasında yol-nəqliyyat hadisəsi arayışına ehtiyac qalmaması üçün bütün şərtlər hansılardır? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR113 | İki icbari sığortalı maşın, xəsarət yoxdur, ziyan min manatdan azdır, amma təqsirlə bağlı mübahisəmiz var. Arayışdan imtina etmək olarmı? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR124 | Masinla basqasinin seyine ziyan vursam, icbari en cox ne qeder verir? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR125 | Maaşım səkkiz mini ötübsə tibbi sığortaya tutulan pulun faizi artıq hissədə necə dəyişir? | lexical_retrieval | Required parent(s) outside the BM25 top 50 |
| AZR138 | Bəs istisnalar necə? | dense_retrieval | Required parent(s) outside the dense top 50 |
| AZR139 | Bəs bu halda? | query_resolution | The resolver asked for clarification before retrieval. |

The [per-query results](real_insurance_draft_results.json) retain ranks for every labeled parent, actual packed passage IDs, and archive compatibility checks.

## Answer review

Answer packet capture outcomes: generation_service_error (6), blocked_by_missing_evidence (1).
The generation provider rate-limited 6 requests. See the [answer review packet](real_insurance_answer_review.json) for the per-query status.

Factual correctness, evidence and citation coverage, legal qualifications, invented provisions, and abstention require human judgment. A structural citation check does not count as approval.
