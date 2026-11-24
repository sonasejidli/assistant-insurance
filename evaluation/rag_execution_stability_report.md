# Seven-case RAG execution stability

## Baseline diagnosis

The baseline run was `2b8af1a8a58244569ff2345a47359394`. Its runner executed the cases sequentially with SDK retries disabled. Eleven provider calls were observed in the HTTP log. Seven returned HTTP 200 and four returned HTTP 429 Too Many Requests. The four 429s raised `TooManyRequestsResponseError` during the provider call, before a model output was available to validate. Historical response bodies and Retry-After headers were absent from the capture. The exact provider JSON error code and message and the rate-limit cause are therefore unavailable for that run.

| Case | Model attempts and final outcome |
| --- | --- |
| AZ7-01 | Two HTTP 200 outputs were empty and rejected. The second call was the application’s format retry. |
| AZ7-02 | The first call returned HTTP 429. The application returned recovery. |
| AZ7-03 | Two HTTP 200 outputs were empty and rejected. The second call was the application’s format retry. |
| AZ7-04 | The first HTTP 200 output contained 146 characters and no recognized source marker. Its format retry returned HTTP 429. |
| AZ7-05 | The first call returned HTTP 429. The application returned recovery. |
| AZ7-06 | Two HTTP 200 outputs were empty and rejected. The second call was the application’s format retry. |
| AZ7-07 | The first call returned HTTP 429. The application returned recovery. |

Four **cases** had rejected generation and seven individual outputs were rejected. All seven rejected outputs lacked recognized `[S#]` markers. All seven also recorded 1,536 output tokens, exactly the configured output cap. Six had empty visible responses. This establishes that the rejected calls reached the recorded token budget. The capture lacks finish reasons and a reasoning-token breakdown, so it cannot determine where those tokens went or establish truncation as the sole cause. The token-cap evidence concerns the HTTP 200s. It does not explain the HTTP 429s. The run was sequential, and the capture supplies no evidence about simultaneous requests elsewhere, provider quota usage, or a particular request limit.

## Execution changes

- `App/evaluation_capture.py` now records provider calls separately from generation attempts. It captures HTTP status, exposed provider error code and message, parsed Retry-After, retryability, delay, call latency, and budget outcome. It omits raw response bodies and request headers and redacts credential and email patterns from the selected message field.
- `App/system.py`, `App/legal_answers.py`, and `App/query_plan.py` use the evaluation transport wrapper when a capture policy is active. The existing legacy validator retains its rules and now records the rejection reason. The optional concise legacy evaluation prompt caps the answer at three factual lines, each ending in a source marker. It leaves the production prompt unchanged.
- `evaluation/rag_run.py` adds bounded query concurrency, configurable eligible HTTP statuses, per-question retry count and total waiting budgets, and a separate report for transport retries, format retries, recovery, accepted answers, and capture completeness. Ranking digests compare original ordered passage IDs. Offline replay reads saved data without provider calls.
- `tests/test_evaluation_provider_retry.py` and `tests/test_rag_run.py` cover Retry-After, shared budgets, permanent errors, ambiguous timeouts, redaction, and bounded concurrency.

The evaluation defaults are one worker, two transport retries per question, HTTP 429 eligibility, and a total retry wait budget of 25 seconds. Backoff uses exponential growth with jitter between half and all of the capped delay. A Retry-After value can extend that delay. If it exceeds the remaining wait budget, the request ends without retrying early. Connection-establishment retries and additional eligible HTTP statuses are explicit options. An ambiguous read timeout is terminal because the provider may already have accepted the request. The application’s single format retry remains separate and can make one fresh generation call. The provider retry wrapper is disabled in ordinary production requests.

## Rerun results

The rerun `9d5817e013db4ad0a930be4f0445b015` used the same archived vectors, retrieval configuration, model, and 1,536-token output budget. It ran sequentially with the two-retry policy and the opt-in concise prompt. This was a combined execution change, so the before/after results cannot isolate a prompt effect from provider response variability.

| Case | Rerun outcome | Transport retries |
| --- | --- | ---: |
| AZ7-01 | Accepted PARTIAL with bound citations | 0 |
| AZ7-02 | Accepted FULL with bound citations after two HTTP 429s | 2 |
| AZ7-03 | Recovery after both generated outputs were empty and lacked valid source markers. Each recorded 1,536 output tokens. | 0 |
| AZ7-04 | Accepted FULL with bound citations | 0 |
| AZ7-05 | Recovery after three HTTP 429s exhausted the transport retry budget | 2 |
| AZ7-06 | Accepted PARTIAL with bound citations | 0 |
| AZ7-07 | Accepted FULL with bound citations | 0 |

All five rerun rate-limit events recorded HTTP status and provider JSON code **429**, with the exact message **“Provider returned error”**. No usable Retry-After value was captured. That message does not identify a particular token limit, request limit, provider quota, or concurrent client. All five accepted answers recorded fewer than 1,536 output tokens. Their precise answers remain in the private run records.

| Metric | Baseline | Rerun |
| --- | ---: | ---: |
| Accepted generated answers | 0/7 | 5/7 |
| Recovery responses | 7/7 | 2/7 |
| Failed HTTP requests to the app | 0/7 | 0/7 |
| Transport retries | 0 | 4 |
| Application format retries | 4 | 1 |
| Rate-limited queries | 4/7 | 2/7 |
| Rate-limited provider calls | 4/11 | 5/12 |
| Request latency mean | 23.02 s | 16.65 s |
| Request latency p50 | 22.67 s | 15.12 s |
| Request latency p95 / p99 | 32.11 s / 32.11 s | 25.08 s / 25.08 s |
| Case records captured without omissions | 7/7 | 7/7 |
| Runtime citation validity | Unavailable | 100% on five eligible answers |
| Answer-mode availability | 0/7 | 5/7 |
| Draft answer-mode accuracy | Unavailable | 2/5 eligible answers |

Latency includes the full request and uses nearest-rank percentiles over seven cases. Runtime citation validity measures binding to packed passage IDs. Claim support, citation precision and completeness, and answer correctness remain unscored pending approved reviews.

All seven ordered passage rankings matched the baseline by SHA-256. Mean draft Recall@5 stayed **38.27%**. Recall@10, MRR@10, and nDCG@10 remain unavailable at the observed depth of five. Multipart decomposition stayed disabled for this comparison. There were no changes to BM25, E5, RRF, BGE, candidate pools, the Qdrant data, or production settings.

## Reproduce and verify

```powershell
python -m evaluation.rag_run capture --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl --concurrency 1 --max-retries 2 --concise-generation --report .venv/rag-stability-new.json
python -m evaluation.rag_run replay .venv/rag-runs/<run-id> --output .venv/rag-stability-new-replay.json
python -B -m unittest discover -s tests
```

The before and after operational replay artifacts are `.venv/rag-stability-before-final.json` and `.venv/rag-stability-after-final.json`. All **169 tests** passed, including the Windows SQLite cleanup and review-dashboard workflow. The seven-case draft and 108-query benchmark were preserved, and all four legacy fixture hashes verified.
