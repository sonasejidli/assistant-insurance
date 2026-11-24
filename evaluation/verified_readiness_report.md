# Verified Legal RAG readiness audit

The production flag remains off by default. The release-boundary changes are confined to `App/verified_release.py`. The hardened verifier, witness catalog, prompts, source identifiers, retrieval configuration and production Qdrant data were preserved. [Pre-change baseline](verified_readiness_baseline.md)

## Files

- `App/verified_release.py` hardens finalization and records safe decision telemetry.
- `evaluation/verified_adversarial_v1.json` and `evaluation/verified_adversarial.py` define and run the versioned HTTP benchmark.
- `evaluation/verified_live_provider.py` runs the opt-in provider checks. `evaluation/verified_container_smoke.py` runs isolated container checks.
- `evaluation/legal_answer_quality_capture.py` and `evaluation/verified_release_benchmark.py` expose optional provider and HTTP seams and preserve historical replay.
- `tests/test_verified_readiness.py` verifies serialized replay, fail-closed handling, safe telemetry and provider classifications.

## Release-boundary findings

The initial serialized HTTP run found three failure cases that returned 500 instead of safe recovery. A verifier runtime exception escaped the narrow exception handler. Malformed verifier output and an unserializable response failed after that handler. Two planning attacks discarded the second part from the recovery response, and an incorrect model-supplied Q2 attribution was reassigned to Q1 by the integration. The initial date-modifier probe used the wrong input property and was corrected to `requested_reference_date` before scoring the final dataset.

The opted-in boundary now protects request execution, verification, release construction and serialization. Failures return the existing recovery language with null mode and no legal references. Explicit client HTTP errors retain their existing status. A contradiction between the model's explicit part label and catalog-bound evidence blocks release. A catalogued multipart question whose plan lost a part abstains and discloses both unresolved parts. The verbatim verifier outcome remains in request-local capture. The verifier's internal decision rules were untouched.

## Deterministic offline validation

The 56-fixture versioned benchmark sends HTTP requests through FastAPI and reads the serialized body. The frozen corpus, real packing, citation binding and hardened verifier run locally. Dense candidates, reranker scores and provider generation are scripted. Individual fault injections exercise the actual integration boundary. Fixture elements are stable ID, attack category, frozen base fixture, mutation and expected final mode.

| Attack class | Passed / fixtures |
|---|---:|
| Prompt injection | 4/4 |
| Citation manipulation | 8/8 |
| Legal scope | 7/7 |
| Temporal applicability and conflicts | 7/7 |
| Multipart association | 5/5 |
| Pipeline failures | 14/14 |
| Witness matching | 11/11 |

| Metric | Observed / examined |
|---|---:|
| Unsupported FULL releases | 0/56 |
| Unsupported PARTIAL releases | 0/56 |
| Verifier/release mode inconsistencies | 0/56 |
| Invalid citation releases | 0/56 |
| Unsupported material claim releases | 0/56 |
| Fail-open on verifier failure | 0/4 |
| Cross-question or lost-part witness reuse | 0/8 |
| Material multipart omissions | 0/5 |
| Correct abstentions | 52/52 |
| False witness acceptance with material or underspecified variants | 0/5 |
| Harmless linguistic variation coverage | 0/5 |

The four released responses were the exact-wording control and three independently supported partial responses. The citation check compares serialized passage IDs and document IDs to the verifier evidence. The synthetic 429 case exercises the existing provider retry-budget code. Truncation, malformed output, empty output, timeout and retry exhaustion have separate fixtures. No provider token usage or cost applies to deterministic fixtures.

All 56/56 HTTP requests returned 200. Measured harness latency was 40.31 ms p50 and 56.36 ms p95 across 56 requests. Two offline reads of the same checksummed capture produced byte-identical reports. The evaluator also reconstructs the answer from witnessed fragments and fixed recovery and disclosure text to detect any untracked prose in the serialized answer.

The exact-question control passed 1/1. The catalog still requires exact wording after trimming and rejects additional history, filters, specific article/comparison modes and supplied dates. Punctuation, morphology, word order, paraphrase and irrelevant context did not qualify for witness reuse. Changed groups, dates, material facts, negation and underspecified questions abstained. Approximate matching was left out because these fixtures cannot establish safe legal equivalence for unseen formulations.

## Container validation

Docker Engine 29.9.2 built the existing Dockerfile successfully. The final local image manifest was `sha256:37c45c9209a8ae8383d90b42b2c35425ce4218dcebf3e99bf619427137d3f32a`.

| Check | Observed / attempted |
|---|---:|
| Image build | 1/1 |
| Four-chunk public fixture startup and Docker health check | 3/3 |
| Serialized flag behavior, unset / 0 / 1 | 3/3 |
| Packaged policy and verifier import in enabled container | 1/1 |
| Restart with the same isolated Qdrant path | 1/1 |
| Packaged-corpus cold startup | 0/1 within 420 seconds |

The fixture runner used the real image, Uvicorn lifespan, local Qdrant, and image health command. It enabled structured answers for all three flag settings and mounted one existing public source read-only. It used no provider credentials and no network. Flag unset and flag 0 returned identical probe summaries. Flag 1 emitted the release gate and abstained with zero citations. The restarted enabled container returned the same health and release summary. This probes restart functionality and scope isolation. It does not check every persisted vector or touch the production collection. The missing-policy and provider-configuration paths were exercised by deterministic fault injection and classifier tests.

The separate packaged-corpus run with an empty isolated index logged document/embedding preparation and reached the 420-second health deadline without passing. The runner cleaned up the disposable container. The remaining packaged-corpus flag and restart probes were therefore unmeasured. The fixture-corpus result covers the runtime gate and startup plumbing. Packaged-corpus readiness remains open.

## Live-provider integration

The configured OpenRouter model was `baidu/ernie-5.5-flash-preview:free`. The runner sends four frozen public benchmark questions through the real provider abstraction with a bounded timeout, local deterministic retrieval inputs, and transport retries disabled. It records response metadata without raw text, headers or provider error messages. The capture separates structured/schema retry attempts from transport retries.

| Run | Provider outcomes per attempt | Final accepted | Null abstentions | Request p50 / p95 |
|---|---|---:|---:|---:|
| First network-enabled run | HTTP 429 3/5, length finish 2/5 | 0/4 | 4/4 | 1,406.10 / 19,831.42 ms |
| Second network-enabled run | HTTP 429 2/5, malformed 1/5, returned without transport/schema error 2/5 | 0/4 | 4/4 | 1,543.54 / 14,015.33 ms |

Each run made five generation attempts across four fixtures, including one structured retry and zero transport retries. Both had zero supported legal claims released. In the second run, token metadata was available for 3/5 attempts. Reported total tokens were 2,841, 2,507 and 3,057. Estimated cost was unavailable. The two returned provider attempts did not yield released legal answers. HTTP 429 establishes rate limiting, with no verified cause. An initial sandboxed run saw 4/4 connection failures before the network-enabled runs.

## Audit and privacy

The release gate emits optional allowlisted decision telemetry using the existing metrics-log flag. It includes the request correlation ID, release version, generated/verified/final modes, fixed reason code, counts, failure stage, and request, verification, release and serialization latency. The live report stores model/prompt identity, prompt fingerprint, HTTP status, classified failures, per-attempt finish reason and available token usage. Stored adversarial captures use public fixtures and safe response projections. Default logging contains no prompts, answer text, credentials, or sensitive headers from the gate. A credential-value scan found zero matches across 3/3 live reports. Request-local detailed replay can retain original content in existing explicit evaluation capture, so operators should use controlled storage for captures outside the public fixture suite.

## Regression and preservation

The suite passed 211/211 tests, including all 208 pre-existing tests. The frozen 43-fixture verifier, 39-fixture authority report, 53-fixture temporal/conflict report, 15-case E2E replay and 15-case verified release replay reproduced byte-identically. A fresh release-v1 capture differed only in newly generated trace IDs. Its serialized decisions and metrics were unchanged. The 108-query CI lexical comparison reproduced the locked ranking hash, and all 4/4 fixture hashes passed. The seven-case draft replay matched the retained report, and proposed v2 labels remain unchanged. No historical artifact was overwritten.

The full retrieval runner processed 108/108 queries with cached E5 and reranker models and an isolated Qdrant index. The hybrid/RRF/reranker row reproduced Recall@5 0.950, Recall@10 0.961, MRR 0.941 and nDCG@5 0.904 from the same runner's retained report. The separate historical multipart experiment used its own comparison harness. [Retained full retrieval report](insurance_benchmark_report.md)

Local outputs are retained under `.venv` as `readiness-adversarial-complete-report.json`, `readiness-live-approved.json`, `readiness-live-final.json`, `readiness-container-fixture.json`, `readiness-108-retrieval.md` and `readiness-complete-tests.log`.

## Reproduce

Use the repository's Python dependencies and a fresh destination for each output. The snapshot in these examples is the existing frozen corpus snapshot.

```powershell
python -m unittest discover -s tests
python -m evaluation.verified_adversarial capture .venv/adversarial-v1.json --snapshot .venv/eval_corpus_snapshot.json
python -m evaluation.verified_adversarial replay .venv/adversarial-v1.json --output .venv/adversarial-v1-report.json
python -m evaluation.verified_live_provider --allow-provider-calls --snapshot .venv/eval_corpus_snapshot.json --output .venv/live-provider-report.json
docker build --tag insurance-verified-readiness:final .
python -m evaluation.verified_container_smoke insurance-verified-readiness:final
# Faster isolated check. Use a new directory.
New-Item -ItemType Directory .venv/public-container-corpus
Copy-Item data/index/Trend-4197840-avtomobil-sigortasi-2026.txt .venv/public-container-corpus
python -m evaluation.verified_container_smoke insurance-verified-readiness:final --fixture-corpus .venv/public-container-corpus
python -m evaluation.compare_legal_verifiers --snapshot .venv/eval_corpus_snapshot.json --output .venv/verifier-regression.json
python -m evaluation.benchmark_source_authority --snapshot .venv/eval_corpus_snapshot.json --output .venv/authority-regression.json
python -m evaluation.benchmark_source_authority_v2 --snapshot .venv/eval_corpus_snapshot.json --output .venv/authority-v2-regression.json
python -m evaluation.legal_answer_quality replay .venv/legal-answer-quality-v1-audit --snapshot .venv/eval_corpus_snapshot.json --historical-report .venv/rag-stability-after-final.json --output .venv/e2e-regression.json
python -m evaluation.verified_release_benchmark replay .venv/verified-release-audit --output .venv/release-regression.json
python -m evaluation.evaluate_platform ci
python -m evaluation.benchmark_insurance --output .venv/retrieval-108-regression.md
```

## Remaining limits

Production sign-off remains open for packaged-corpus startup and successful live FULL/PARTIAL release. Provider-controlled failure coverage is deterministic offline and opportunistic live. The verifier timeout fixture injects a timeout exception, and the synchronous verifier has no wall-clock watchdog. Evidence is limited to the fixed witness catalog and selected attacks. Interpretation of laws, applicability and potential conflicts remains pending expert legal review.
