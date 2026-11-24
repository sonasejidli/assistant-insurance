# Live-provider verified answer qualification

## Historical FULL and PARTIAL

The prior FULL trace `613d67f10d174cd284fc360bf743b367` recorded generated FULL and an accepting faithfulness result. For claim `E2E-B01-C1`, the hardened verifier recorded a valid citation, no matched witness, and `no_independent_support`. It returned null mode and the gate withheld the answer. This establishes a correct release-policy abstention. The old capture omitted the claim text and its passage bindings, so it cannot establish which witness predicate failed or whether the underlying proposition exceeded the passage. For this reason there was no evidence-based change to the handoff, witness catalog, or legal verification.

The prior PARTIAL trace `1f9d6737923f413dac211bbbc8362b88` reached the judge after generation and binding, then received two HTTP 429s. Neither supplied Retry-After. The retry followed a 0.430 s bounded jitter delay and the second 429 exhausted the budget. The underlying quota, request limit, and token limit remain unknown. Request execution was sequential.

## Deterministic offline prequalification

Both questions were matched byte-for-byte to the existing catalog and exercised through the actual serialized FastAPI route. The evidence is from the same occupational compulsory insurance law with document ID `7da056dd-d9f8-501d-9a06-556083e2a0ed`.

| Control | Exact indexed reference | Witness and scope | Expected result |
|---|---|---|---|
| R01 | §11.8, page 10, `a57a82bb-11a3-59b9-ad6d-331cbd732955` | `occupational_termination_in_term`, obligation preserved subject to the event occurring while the contract was in force | FULL 1/1, Q1 complete |
| R02 | §7.3, page 7, `b3845218-4ab9-57d4-93ca-9371f1e70c9b` | `occupational_liability_fragment`, independently witnessed liability fragment | PARTIAL 1/1, remedy procedure unresolved and disclosed |

Both sources were classified `law_or_code` and were eligible normative evidence. The verifier used its existing `general_rule` temporal profile. The authority layer recorded `reference_date_unspecified`. Neither control asserts applicability to an individual event or requested date. The frozen preflight contains the exact questions, supporting text, passage identifiers and scope disclosures. The separate multipart positive control continues to pass.

Schema and release regressions cover objects with optional fields absent, explicit nulls, escaped and literal Azerbaijani, valid single fences, extra fields, malformed and truncated output, empty output, absent or empty citation metadata, invalid markers, duplicate citation attacks, and invalid provider-supplied claim IDs. The normalizer preserves claims and marker strings. No legal witness or production prompt changed.

## Controlled live provider

The run used the configured OpenRouter model `baidu/ernie-5.5-flash-preview:free` and the existing generation and judging prompts. It exercised the actual serialized `/ask` ASGI endpoint with frozen retrieval inputs and real provider calls. Deployment HTTP and live-provider qualification are separate checks. The runner allowed two sequential requests, at most four network calls per case, one 429 retry per case, five seconds of total retry wait per case, a 12-second per-call timeout, and an output ceiling of 1,536 tokens. A lower configured stage cap still applies.

| Metric | FULL case | PARTIAL case |
|---|---:|---:|
| Provider transport calls | 3 | 2 |
| Valid structured generation responses | 0/2 logical attempts | 0/1 logical attempt |
| Citation binding success | 0 evaluated | 0 evaluated |
| Hardened target-mode decisions | 0/1 | 0/1 |
| Target-mode releases | 0/1 | 0/1 |
| Safe null-mode abstentions | 1/1 | 1/1 |

FULL trace `89f657a919744e4baeb8859fe74a1720` received a length-truncated completion with 2,017 input and 1,536 output tokens, then HTTP 429 on the second generation attempt and its one transport retry. PARTIAL trace `11cec81afe90419294a4c2877ec57b20` received HTTP 429 during generation and again on retry. Both stopped before binding and independent support assessment. Both serialized as HTTP 200 with `answer_mode: null`, empty sources, null hardened mode, and `generation_unavailable`. No claim was released.

There were **4/5** HTTP 429 calls, **2/5** transport retries, **0/5** timeouts, **1/3** truncated logical generation attempts and **0/3** malformed logical attempts. Neither Retry-After nor any of the allowlisted numeric quota counters was present. The observed jitter delays were 0.269 s and 0.387 s. Request latency p50/p95 was **1,780.05/12,033.88 ms** over two requests. Usage was available for the truncated response, **3,553 tokens total**. Estimated cost was unavailable. Nothing in the captured provider responses identifies the quota being enforced.

The existing retry policy continues to use bounded exponential backoff and jitter. A valid Retry-After is a minimum delay. A delay beyond the configured wait budget results in no retry. The qualification runner adds a hard call cap that includes transport retries and judging. It leaves timeouts unretried. The artifact excludes authorization headers and raw provider prose. It stores response hashes and redacted atomic claim text when available, reference bindings, verdicts, timing, and exact safe serialized responses. Two offline replays reconstructed both serialized responses through the existing release boundary and produced byte-identical reports. A credential-value scan of the live artifact found zero matches.

## Deployment validation

The isolated prepared volume was checked with the existing collection compatibility and per-point validation logic. The manifest recorded **4,560 validated points** for collection `insurance_chunks_98d725206ef448d2d6a74976`. Its checksum is `1bef0bf6397a2765260e67098a54ccca030608da7c2dc48412c7223213dc4f91`. The manifest binds the parsed corpus, embedding configuration, versioned collection, and point ID set. It is a validation record rather than a byte checksum of the Qdrant volume.

The prepared-index guard was also exercised on an isolated empty store using the final image. It reported **0/4560 validated points** and failed before readiness. An isolated test altered a stored point fingerprint and confirmed that startup rejected it without re-encoding. Production data was untouched.

The current isolated prepared-volume deployment smoke passed **3/3** real HTTP flag checks and **1/1** restart. Docker health was observed at **43.70 s** with the release flag unset, **28.09 s** with flag 0, **27.95 s** with flag 1, and **29.09 s** after enabled restart. All runs reported 4,405 passages. The release gate appeared only with flag 1. The credential-free HTTP probes remained separate from live-provider qualification.

## Regression and preservation

All **220/220 tests passed**. All **56/56** serialized adversarial cases passed. Unsupported FULL, unsupported PARTIAL, invalid citation releases, verifier/release inconsistencies, and unsupported material claim releases were each **0/56**. Fail-open verifier errors were **0/4**. The 43-fixture verifier, 39-fixture authority, 53-fixture temporal, 15-case E2E and 15-case release comparisons reproduced byte-identically. The seven-case draft reproduced its retained report. Proposed v2 and all four locked hashes were preserved.

The full retrieval regression evaluated **108/108** queries. Every retrieval profile matched the preceding quality metrics. The hybrid RRF/reranker profile recorded Recall@5 0.950, Recall@10 0.961, MRR 0.941 and nDCG@5 0.904. The CI lexical rank hash matched its lock.

Changes are confined to the bounded/replayable qualification runner and test capture hooks, numeric rate-limit telemetry in `App/evaluation_capture.py`, the read-only index manifestation mode in `App/prepare_index.py`, and tests. The key local artifacts are `.venv/qualification-controls.json`, `.venv/qualification-live.json`, `.venv/qualification-index-manifest.json`, and `.venv/qualification-empty-index.log`.

## Reproduction

Run on an isolated volume and use fresh artifact names.

```powershell
python -m evaluation.verified_qualification prequalify .venv/qualify-controls.json --snapshot .venv/eval_corpus_snapshot.json
python -m evaluation.verified_qualification live .venv/qualify-live.json --snapshot .venv/eval_corpus_snapshot.json --allow-provider-calls
python -m evaluation.verified_qualification replay .venv/qualify-live.json
python -m unittest discover -s tests
python -m evaluation.verified_adversarial capture .venv/qualify-adversarial --snapshot .venv/eval_corpus_snapshot.json
python -m evaluation.verified_adversarial replay .venv/qualify-adversarial --output .venv/qualify-adversarial.json
python -m evaluation.evaluate_platform ci
python -m evaluation.benchmark_insurance --output .venv/qualify-retrieval.md

docker build -t insurance-qualification:local .
docker run --rm --network none --mount type=volume,source=insurance-qualification,target=/tmp -e QDRANT_PATH=/tmp/signoff-db insurance-qualification:local python -m App.prepare_index
docker run --rm --network none --mount type=volume,source=insurance-qualification,target=/tmp -e QDRANT_PATH=/tmp/signoff-db insurance-qualification:local python -m App.prepare_index --manifest
python -m evaluation.verified_container_smoke insurance-qualification:local --prepared-volume insurance-qualification
```

The smoke runner attaches the prepared persistent volume, sets the readiness guard, waits for the image health check, and sends a real HTTP `/ask` probe for each flag setting and after restart.

Live FULL and PARTIAL release remain open. The measured run exhausted the agreed two-case execution plan. Release policy, exact witness matching and source rules remain in force. Legal expert review remains pending.
