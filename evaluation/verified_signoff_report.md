# Verified RAG sign-off diagnostics

## Container validation

Two isolated application containers using the packaged corpus and empty local Qdrant stayed unhealthy through 420 seconds. Both were running, with no OOM kill. Sample CPU was about 200% per container with two configured threads. Sample resident container memory was approximately 1.08–1.30 GiB. The engine exposed 28 CPUs and 15.47 GiB. The HTTP health check depends on completed FastAPI lifespan, and no health-check timing was changed.

| Startup stage | Instrumented full-corpus cold start |
|---|---:|
| Container start to FastAPI lifespan | 6.64 s |
| Retrieval configuration | 0.09 ms |
| Corpus discovery, parsing and chunking | 16.23 s |
| Embedding model initialization | 2.45 s |
| Embedding input preparation | 0.91 s |
| Local Qdrant client initialization | 14.80 ms |
| Collection lookup and initial validation | 0.31 ms |
| Existing vector reuse lookup | 0.45 ms |
| Encoding 4,355 unique inputs | Still running at the 420 s startup deadline |
| Readiness and health checks | 0/2 on empty storage |

The frozen corpus yielded 4,405 passages from 12 documents. PDF extraction warned about 93 pages without extractable text in one PDF. The implementation reported the need for OCR during its completed parsing stage. There was no OCR worker blocking startup. Encoding was CPU-active with an empty collection, well after parsing and dependency initialization completed. Collection creation and writes occur after encoding, so stopping an empty bootstrap during encoding leaves no completed collection to reuse.

### Targeted startup change

`App.prepare_index` performs the same index build before starting the API. It requires an explicit absolute local Qdrant directory and refuses a remote Qdrant URL. `RAG_REQUIRE_PREPARED_INDEX=1` validates the exact versioned collection and point fingerprints at startup and fails before encoding if points are missing. That flag and `RAG_STARTUP_DIAGNOSTICS=1` are opt-in. Default indexing and health logic are unchanged. When verified release is enabled, startup now loads the packaged verifier and source authority catalog before readiness.

The final Docker image built successfully with manifest `sha256:2df44b61b37ff4bbc77f5b0b12c1516d74b220a46fd65ad846264bfe1e788c2f`. Its four-passage public fixture reused the same prepared isolated volume across three containers.

| Four-passage container probe | Uvicorn lifespan | Docker health observed | Result |
|---|---:|---:|---|
| Release flag unset | 3.99 s | 18.98 s | HTTP probes passed, gate absent |
| Release flag 0 | 4.13 s | 19.02 s | HTTP probes passed, gate absent |
| Release flag 1 | 4.09 s | 19.02 s | HTTP probes passed, gate present |
| Enabled flag after restart | 4.16 s | 20.61 s | Same health and release disposition |

Prepared fixture health passed 3/3 plus restart 1/1, and the same four points validated on reuse. The network-disabled HTTP probes had no provider credential or released citations. Sample memory after HTTP was 1.09–1.14 GiB. The full-corpus preparation exercise used a separate fresh volume.

The isolated full-corpus preparation succeeded in **1,190.30 s** from preparation entry to close. It encoded 4,355 unique inputs in **1,135.13 s** and wrote and validated **4,560 vector points**. The write and final validation interval was approximately 12.56 s. The one-time job used 16 configured threads and sampled roughly 14 CPU cores and 1.37 GiB. The prepared index is a deployment prerequisite for the fast-start path. These times keep the cost of first-time index population visible.

| Prepared packaged corpus, final image | Uvicorn lifespan | Docker health observed | Result |
|---|---:|---:|---|
| Release flag unset | 15.26 s | 21.70 s | Healthy, 4,405 passages, `/ask` succeeded, gate absent |
| Release flag 0 | 15.18 s | 21.64 s | Healthy, 4,405 passages, `/ask` succeeded, gate absent |
| Release flag 1 | 15.11 s | 21.67 s | Healthy, 4,405 passages, `/ask` succeeded, gate present |
| Enabled flag after restart | 15.00 s | 22.73 s | Same health and `/ask` result on the retained volume |

Prepared full-corpus startup and health passed **3/3**, and restart passed **1/1**. On the enabled startup, verifier dependencies loaded in 11.30 ms, parsing and chunking took 10.86 s, model initialization 1.61 s, embedding input preparation 0.51 s, Qdrant open 0.50 s, collection validation 0.11 s, and BM25/graph initialization 1.38 s. Startup reused all verified points without encoding. Memory sampled after the probes was 1.38–1.40 GiB. The longest observed Docker readiness was 22.73 s within the original 420-second limit. The enabled HTTP smoke served a safe abstention with zero citations in the credential-free container. The validation used local Qdrant in an isolated volume. The production remote Qdrant deployment was outside the test.

Container evidence is under `.venv/signoff-container-instrumented.log`, `.venv/signoff-container-preparation.log`, and `.venv/signoff-full-prepared-smoke.json`.

## Historical live-provider root causes

The original safe artifacts are `.venv/readiness-live-approved.json` and `.venv/readiness-live-final.json`. They were preserved. These reports retained fixture/attempt IDs and a prompt fingerprint, and omitted correlation IDs, raw output, and fine-grained validation reasons.

| Run | Fixture/attempt | Last established stage and outcome |
|---|---|---|
| 1 | R01/1, R02/1, R06/1 | Provider request failed with HTTP 429 on each attempt. |
| 1 | R11/1, R11/2 | Provider returned a `length` finish. Both were truncated. Token usage was absent from these retained rows. |
| 2 | R01/1 | Structured output rejected as malformed. Finish `stop`, 2,841 tokens. |
| 2 | R01/2 | Draft reached the hardened verifier as FULL. The verifier recorded `no_independently_supported_fragment`, and the gate withheld. Finish `stop`, 2,507 tokens. The retained row does not identify the claim-level reason. |
| 2 | R02/1 | Transport returned and no schema/binding error was recorded by the attempt classifier. The request emitted NOT_FOUND before independent verification. Finish `stop`, 3,057 tokens. The retained row lacks the reason for the structured disposition. |
| 2 | R06/1, R11/1 | Provider request failed with HTTP 429 on each attempt. |

The shared prompt fingerprint identifies the prompt version, not a request. The two historical returns cannot be assigned retroactive trace IDs or more specific reasons. Five historical 429s establish rate limiting. The provider’s quota or other cause remains unknown.

## Deterministic offline

The positive controls use unchanged engineering fixtures through FastAPI HTTP serialization. W01 released **FULL 1/1**. C02 and E01 released **PARTIAL 2/2**. All **3/3** had hardened mode agreement, a supported fragment, and valid serialized document/passage references. E01 disclosed unestablished Q2 while retaining Q1 evidence. No legal labels were changed.

## Live-provider validation

The first positive-only run returned **4/4** completions with `stop` and failed structured parsing **4/4**. Both requests abstained. Request p50/p95 was **11,450.40/14,405.18 ms**. The follow-up diagnostic established that R02's two complete transport returns began with Markdown fences and failed with `json_invalid`. R01 passed citation binding, then its faithfulness judge returned a length finish. The diagnostic correlation IDs were `ee958bed2adf4d0eb90f362c6a817501` and `d290b417ad2f45f78cf32e392c8200f0`.

The opt-in path now removes one complete Markdown JSON wrapper before applying the existing strict schema. Extra prose, unterminated wrappers, and type errors remain invalid. Any structured completion with an explicit length finish is rejected before parsing, even if it looks like valid JSON. The configured prompts, model, generation cap, and judge cap were unchanged.

After the parser change, both generation attempts returned and passed binding. R01 also passed the faithfulness judge. Its draft FULL then reached the independent verifier, which recorded a valid citation but `no_independent_support` for claim `E2E-B01-C1` (trace `613d67f10d174cd284fc360bf743b367`). That is a correct safety abstention. R02 reached the faithfulness judge and received HTTP 429 (trace `1f9d6737923f413dac211bbbc8362b88`). No historical attribution is inferred from these new traces.

| Final positive-only run | Result |
|---|---:|
| Cases | 2 |
| Successful generation responses | 2/2 |
| Successful provider HTTP responses, including judging | 3/5 attempts |
| HTTP 429 responses | 2/5 attempts, both R02 judging |
| Correct verifier safety abstentions | 1/2 |
| FULL releases | 0/1 expected |
| PARTIAL releases | 0/1 expected |
| Malformed or truncated generation responses | 0/2 |
| Request latency p50 / p95 | 9,311.44 / 9,316.54 ms |
| Available token usage | 2,710 and 3,373 generation tokens, plus 350 judge tokens |
| Estimated cost | Unavailable |

The optional positive runner uses a maximum of one transport retry per request and five seconds of total wait. It honors Retry-After within that budget and records when the requested wait exceeds it. Schema/truncation retry remains bounded by the existing two-attempt generation loop. Replay makes no provider calls. Safe traces retain only identifiers, fixed dispositions, status/finish metadata, counts and timings.

On R02, the first 429 had no Retry-After value. The runner recorded a 0.430 s backoff and one retry. The second 429 exhausted the budget and stopped verification safely. Both final requests abstained with zero invalid or unsupported releases.

Reports are under `.venv/signoff-live-*.json`. A credential-value scan found zero matches across 3/3 new live reports.

## Regression and reproduction

All 215 tests passed, including the 211 pre-existing tests and four sign-off tests. The 56/56 serialized adversarial checks passed with zero unsupported FULL/PARTIAL and invalid citation releases, zero inconsistent modes, 0/4 fail-open verifier errors, and 0/8 cross-question witness reuse. Replays of the new capture were byte-identical. The 43-case verifier, 39-case source-authority, 53-case temporal, 15-case E2E and 15-case release reports reproduced byte-identically. The seven-case draft reproduced its retained report and proposed v2 was unchanged. The 108-query lexical ranking hash and all four locks matched. The experiments preserved the production Qdrant store.

The full retrieval run completed 108/108 queries. All seven profiles reproduced the immediately preceding readiness-run quality metrics. The hybrid/RRF/reranker profile was 0.950 Recall@5, 0.961 Recall@10, 0.941 MRR and 0.904 nDCG@5. The older checked-in report's D and F profile differences already appear in the pre-task readiness artifact. No reference report or label was regenerated.

The startup files changed are `App/observability.py`, `App/main.py`, `App/text_search.py`, `App/vector_store.py`, `App/prepare_index.py`, and `Dockerfile`. `App/legal_answers.py` handles provider protocol normalization and truncation and emits fixed diagnostic event fields. `evaluation/verified_live_provider.py` and `evaluation/verified_adversarial.py` capture safe live dispositions. `evaluation/verified_container_smoke.py` measures startup and HTTP replay against an isolated prepared volume. `tests/test_signoff_controls.py` covers positive HTTP release, prepared-index readiness, single-fence parsing and truncation.

```powershell
python -m unittest discover -s tests
python -m evaluation.verified_adversarial capture .venv/signoff-repro.json --snapshot .venv/eval_corpus_snapshot.json
python -m evaluation.verified_adversarial replay .venv/signoff-repro.json --output .venv/signoff-repro-results.json
python -m evaluation.verified_live_provider --allow-provider-calls --positive-only --snapshot .venv/eval_corpus_snapshot.json --output .venv/signoff-repro-live.json
python -m evaluation.evaluate_platform ci
python -m evaluation.benchmark_insurance --output .venv/signoff-repro-108.md

docker build -t insurance-verified-signoff:final .
python -m evaluation.verified_container_smoke insurance-verified-signoff:final --deadline-seconds 420
docker run --rm --network none --mount type=volume,source=insurance-signoff-repro,target=/tmp -e QDRANT_PATH=/tmp/signoff-db -e OMP_NUM_THREADS=16 -e RAG_STARTUP_DIAGNOSTICS=1 insurance-verified-signoff:final python -m App.prepare_index
python -m evaluation.verified_container_smoke insurance-verified-signoff:final --prepared-volume insurance-signoff-repro
docker run -d --name insurance-signoff-repro-api --network none --mount type=volume,source=insurance-signoff-repro,target=/tmp -e QDRANT_PATH=/tmp/signoff-db -e OMP_NUM_THREADS=2 -e RAG_STARTUP_DIAGNOSTICS=1 -e RAG_REQUIRE_PREPARED_INDEX=1 -e LEGAL_VERIFIED_RELEASE=1 insurance-verified-signoff:final
docker inspect --format '{{.State.Health.Status}}' insurance-signoff-repro-api
docker logs insurance-signoff-repro-api
docker restart insurance-signoff-repro-api
```

Production legal interpretation and broader witness coverage remain pending expert review.
