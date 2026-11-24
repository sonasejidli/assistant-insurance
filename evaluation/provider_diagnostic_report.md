# Provider reliability and structured-output diagnosis

## Runtime configuration

The observed endpoint was `https://openrouter.ai/api/v1/chat/completions`. The application uses `ChatOpenRouter` and the OpenRouter SDK in chat-completions mode with temperature 0. Its structured path requests JSON in the prompt and validates it locally. The probe exercises that mechanism. Provider-native JSON Schema enforcement was outside the probe.

The runtime model was `baidu/ernie-5.5-flash-preview:free`, overriding the code fallback `liquid/lfm-3-1.7b:free`. The application context window was 16,384 and the generation output cap was 1,536. Structured generation uses a 12-second provider timeout and its separate faithfulness call requests at most 220 output tokens. Relevant settings are `OPENROUTER_API_KEY`, the fallback `EMBED_API_KEY`, `LLM_MODEL`, `LLM_CONTEXT_WINDOW`, and `LLM_MAX_OUTPUT_TOKENS`. A credential was available. Its value was excluded from output.

The prior qualification ran sequentially and allowed one transport retry per case with bounded jitter and a five-second total retry-wait budget. The diagnostic runs sequentially, disables SDK retries, and stops at the first unsuccessful request. The default is one request, with an absolute cap of three. Its timeout and small token ceiling are independently configurable. There is no new production concurrency limiter. These records establish 429s during sequential calls and provide no measurement of other account traffic, so concurrency has not been established as a contributor.

## Prior provider evidence

The previous legal qualification recorded four HTTP 429s across five transport calls. Their only recorded classification was rate limiting. Retry-After and the four requested numeric request/token counters were absent. Those artifacts did not retain error response request IDs, account credits, a model availability signal, or the provider error body. The observed retry delays were 0.269 and 0.387 seconds. Each second 429 exhausted the corresponding retry allowance. Existing qualification backoff uses valid Retry-After as a minimum, and refuses a retry if that minimum exceeds its wait budget.

The fifth call returned a length finish with **2,017 prompt and 1,536 completion tokens**, exactly the requested completion ceiling. Its content was empty. The application rejected the completion before JSON parsing and legal verification. The 3,553 total tokens were below the application’s configured window of 16,384. The old capture lacked a reasoning-token breakdown and the upstream model’s effective context limit, so the reason the completion spent its entire budget, including how much went to reasoning, remains unknown. The prompt’s size alone does not establish a context overflow.

## Isolated provider/API validation

The single 128-output-token probe returned **HTTP 200**, `stop`, and strict JSON containing the expected Azerbaijani Unicode greeting. It took **3,318.70 ms** with **49 prompt tokens and 86 completion tokens**, totaling **135**. The provider reported **75 reasoning tokens**. The response exposed generation ID `gen-1795442766-UqKHD5Vx2s6bAuBy6aYk` in the body and allowlisted header. No numeric quota counters were available. This single result establishes prompted-JSON compatibility for the probe and contemporaneous availability of the configured model. The reasoning share illustrates why a cap can be reached before visible text, without establishing that the same happened in the older completion.

Strict offline checks cover Unicode, required and optional fields, explicit null and empty handling, malformed/truncated JSON, refusals, unexpected finish reasons and the response-header allowlist. A length finish is classified as truncated even if the payload looks parseable.

## Live legal qualification

After the isolated success, one sequential two-case run made three transport calls and no transport retries. Both requests serialized as HTTP 200 with null modes and empty citations.

| Control | Observed stages | Final release |
|---|---|---|
| FULL R01 | Generation returned valid structured JSON with `stop`. Citation binding passed. The faithfulness request returned HTTP 429. Trace `1567dc440fba4bb981a23bb985115bed`. | 0/1 FULL, withheld with `generation_unavailable` |
| PARTIAL R02 | The generation request returned HTTP 429, before a structured draft or citation binding. Trace `e9432567635645cb8b8e5b1952a7b8dd`. | 0/1 PARTIAL, withheld with `generation_unavailable` |

The hardened verifier received no accepted draft for either case. The live legal run recorded **2/3 HTTP 429s**, zero timeouts, zero truncations, and zero transport retries. The completed generation used **2,561 tokens**. Legal request p50/p95 was **1,070.79 / 4,759.63 ms** across two requests. No cost estimate was available. Quota, concurrency, and whether throttling is temporary remain undetermined. The configured model can produce the small prompted-JSON response, while repeatable end-to-end qualification remains blocked by rate limits. No additional live qualification was attempted.

## Deterministic RAG regression

**222/222** tests passed, including all 220 existing tests. All **56/56** serialized adversarial fixtures passed. The locked 108-query lexical ranking hash and all four locked fixture hashes matched. The full dense and reranking benchmark remained unchanged on disk and was outside this diagnostic rerun. Frozen legal expectations and historical output files were preserved. The opt-in corpus controls still exercise the same deterministic FULL and PARTIAL paths.

## Reproduce

Use new artifact paths. The isolated command calls no RAG pipeline and never runs during startup or normal CI.

```powershell
python -m evaluation.provider_diagnostic --allow-provider-calls --output .venv/provider-probe-new.json
python -m unittest discover -s tests
python -m evaluation.evaluate_platform ci
```

After the isolated diagnostic succeeds, the existing opt-in legal runner can exercise the two frozen positive controls once:

```powershell
python -m evaluation.verified_qualification live .venv/provider-followup-new.json --snapshot .venv/eval_corpus_snapshot.json --allow-provider-calls --max-retries 0 --max-calls-per-case 3
python -m evaluation.verified_qualification replay .venv/provider-followup-new.json
```

The probe lives in `evaluation/provider_diagnostic.py`, accompanied by `tests/test_provider_diagnostic.py`. Production model selection, prompts, settings, Qdrant and legal verification were unchanged.
