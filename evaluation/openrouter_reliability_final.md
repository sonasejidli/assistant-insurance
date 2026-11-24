# OpenRouter reliability diagnosis

## Provider/API validation

The configured runtime uses OpenRouter via `ChatOpenRouter` and the SDK at `https://openrouter.ai/api/v1/chat/completions`. The runtime selects `baidu/ernie-5.5-flash-preview:free` with temperature 0. The application requests JSON in the prompt and validates it locally; the probe uses that same mechanism. Production does not send a native JSON Schema response-format request through this path. The structured provider client uses a 12-second timeout. The application’s input-packing window is 16,384 tokens, generation requests at most 1,536 output tokens, and faithfulness requests at most 220. The runtime model overrides the code fallback `liquid/lfm-3-1.7b:free`. Production defaults were preserved.

The isolated run completed **3/3** sequential requests at concurrency 1 with no retries, redirects, or legal RAG calls. Each returned HTTP 200, valid Azerbaijani JSON and a `stop` finish. With a 128-token output cap, the calls used 49 prompt tokens each and 115, 115 and 111 completion tokens. Reasoning accounted for 104, 104 and 100 tokens respectively. Total usage was **488 tokens**. Latencies were 2,465.69, 3,007.73 and 2,437.29 ms. Each response exposed a generation ID. No Retry-After or quota counters appeared in the new successful responses.

## Rate limits

The runtime took its credential from `OPENROUTER_API_KEY`. A scan of the isolated artifact found zero matches for that credential. The production structured client still passes `retry_config=None` when no evaluation client is present; the probe explicitly disables SDK retries. The environment variables controlling the model and token settings are `LLM_MODEL`, `LLM_CONTEXT_WINDOW` and `LLM_MAX_OUTPUT_TOKENS`.

The older five-call legal capture contains **4/5 HTTP 429s**. R01 received two while generating after an earlier truncated completion. R02 received two during generation. The retries used approximately 0.269 and 0.387 seconds of jitter, then exhausted the one-retry allowance. No Retry-After or numeric counters were recorded. The later legal follow-up recorded **2/3 HTTP 429s**, one during R01 faithfulness after successful generation and binding, and one during R02 generation. That follow-up disabled transport retries.

The prior failure artifacts omit provider request identifiers and the value of `error.metadata.limit_source`. OpenRouter documents this field for distinguishing its own free-tier limiter from upstream shared capacity. The capture now retains documented limit-source values alongside allowlisted request/generation IDs, numeric quota headers, Retry-After, endpoint, model, stage, retry index, timestamp and latency. Arbitrary headers, response prose and credentials are excluded. The current isolated run saw zero 429s, so the cause of the historical failures remains **unknown**. The artifacts cannot identify account quota, upstream capacity, or concurrency as the cause. [OpenRouter rate-limit diagnosis](https://openrouter.ai/blog/tutorials/llm-api-rate-limits/)

The isolated command hard-caps client transport at three requests per execution and one per logical probe. It stops on the first unsuccessful probe. The existing legal evaluation retry policy remains bounded and uses Retry-After as a minimum delay subject to its wait budget. No production concurrency limit, retry increase, or model change was introduced.

## Truncation

The historical response reported 2,017 prompt tokens, **1,536 completion tokens**, 3,553 total tokens and `finish_reason=length`. It exhausted the requested completion limit and contained zero response-text characters. The capture lacks reasoning-token allocation. The new probes report reasoning usage, but they cannot resolve how the historical completion spent its tokens.

OpenRouter documents a **1,024,000-token context window** for this exact free model. The application’s configured packing window is separate. The historical token counts and length finish support completion-budget truncation, with no observed evidence of a context-window overflow. The application detects length before Draft JSON parsing. A new serialized `/ask` regression forces both structured attempts to truncate and confirms that neither binds a citation or releases any source or answer mode. [OpenRouter model configuration](https://openrouter.ai/baidu/ernie-5.5-flash-preview%3Afree)

## Release and legal status

No live legal requests were made in this task. The earlier live FULL and PARTIAL cases both abstained. The small-prompt API result supports proposing one separately approved two-case qualification run, while leaving repeatable legal throughput unproven. Any such run should remain sequential and bounded, with one prequalified FULL and one prequalified PARTIAL case and no transport retries. Production live-answer qualification remains open. Legal expert review remains pending.

## Files and reproduction

The full suite passed **223/223**, including the 222 existing tests. All **56/56** serialized adversarial cases passed. Unsupported FULL and PARTIAL releases, invalid citations, and verifier/release inconsistencies were **0/56**. Fail-open verifier errors were **0/4**. The frozen 43-fixture verifier output and 15-case release replay were byte-identical to the prior artifacts. All four fixture locks matched.

The full retrieval benchmark evaluated **108/108** queries. All seven profiles matched the preceding run's quality metrics. The RRF/reranker profile retained Recall@5 0.950, Recall@10 0.961, MRR 0.941 and nDCG@5 0.904. The CI lexical ranking hash remained `0e201d2ff20e9d1b97e4f7a9da7643c07600b1ee562620ec426193919c11723e`. New evidence is in `.venv/openrouter-final-probe.json`, `.venv/openrouter-final-adversarial.json` and `.venv/openrouter-final-retrieval108.md`; historical artifacts were preserved.

The changes are in `evaluation/provider_diagnostic.py`, `tests/test_provider_diagnostic.py`, and this report. Production definitions, Qdrant data, prompts, retrieval settings, citation behavior, verifier rules, and frozen datasets were preserved.

```powershell
python -m evaluation.provider_diagnostic --allow-provider-calls --max-requests 3 --output .venv/openrouter-probe-new.json
python -m unittest discover -s tests
python -m evaluation.verified_adversarial capture .venv/openrouter-adversarial-new --snapshot .venv/eval_corpus_snapshot.json
python -m evaluation.verified_adversarial replay .venv/openrouter-adversarial-new --output .venv/openrouter-adversarial-new.json
python -m evaluation.evaluate_platform ci
python -m evaluation.benchmark_insurance --output .venv/openrouter-retrieval-new.md
```
