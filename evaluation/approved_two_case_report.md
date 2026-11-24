# Approved live legal qualification

## Preflight and isolation

The two exact control results reproduced their retained offline artifact before the live run. R01 (`E2E-B01`) required FULL under the existing occupational termination witness, with §11.8 on page 10, passage `a57a82bb-11a3-59b9-ad6d-331cbd732955`. R02 (`E2E-B02`) required PARTIAL under the occupational liability witness, with §7.3 on page 7, passage `b3845218-4ab9-57d4-93ca-9371f1e70c9b`. The remedy procedure is explicitly unresolved for R02. Both provisions use the existing general-rule temporal profile. The prepared index contained the exact texts and both controls retained their original evidence labels.

The run used the actual serialized FastAPI `/ask` ASGI route in the isolated Docker image. Startup validated and reused the prepared 4,560-point Qdrant index, and health reported 4,405 parent passages. Retrieval, reranking, generation instructions, citation binding, and independent legal verification used their normal implementations. The isolated runner enabled the verified release flag only in that container. Production configuration and Qdrant were outside the run.

Qdrant local mode reported exact vector search. The run exercised the real application release path with the isolated prepared index. Production remote Qdrant and its search tuning were outside the run.

OpenRouter model `baidu/ernie-5.5-flash-preview:free`, endpoint `https://openrouter.ai/api/v1/chat/completions`, 12-second timeout, 16,384 application context window and 1,536 generation cap matched the preceding qualification configuration. No prompt or model changes were made. The qualification set transport retries to zero, disabled SDK retries and redirects, and enforced a transport guard allowing at most one generation call and one distinct faithfulness call per attempted case. The questions matched local insurance intent rules and alternative query-generation paths were disabled in the inherited configuration.

## FULL case R01

| Stage | Observed result |
|---|---|
| Provider generation | HTTP 200, `stop`, 8,997.57 ms, generation ID `gen-1795444390-YvpAXgYtSRj2MRi8MrPN` |
| Structured validation and binding | The draft parsed and both claims passed generation-side citation binding. S1 bound to the expected §11.8 passage. S2 bound to the same law’s §2.0.12, page 2, passage `fdea4e0f-070c-5778-88a2-9c9fa4ae2ffd`. |
| Authority and temporal metadata | All packed passages were classified as eligible normative law, with `reference_date_unspecified`. The question asks about the general rule, and no individual event-date applicability was established. |
| Faithfulness | HTTP 200, `length` at the 220-completion-token cap, 3,750.13 ms, generation ID `gen-1795444399-AaQN8Wdo3kpU265TWVma`. The application raised `TruncatedProviderOutput`. |
| Independent verification | Null verdict, `generation_unavailable`, zero assessed claims. The two draft claims therefore have no independent support verdict. |
| Final serialized response | HTTP 200, null answer mode, zero released citations and claims. Offline release replay matched the captured response exactly. |

Application trace ID `c4075372f0e04f918311f8c175553b48`. End-to-end request work took approximately 51.67 seconds, excluding container startup. Provider-reported usage was 1,887 prompt and 1,259 completion tokens for generation, and 533 prompt and 220 completion tokens for faithfulness. These sum to **3,899 total tokens**. The provider reported 227 reasoning tokens alongside 220 completion tokens on the truncated call, so those counters are retained as observed and their relationship remains unverified. Neither call returned a 429. The failed faithfulness completion was sufficient to stop qualification.

## PARTIAL case R02

The stop rule prevented the R02 request after R01's truncated faithfulness completion. R02 had zero provider calls, no serialized live answer, no binding or independent live verdict, and no released claims or citations. Its offline prequalification remains unchanged. No replacement or compensating call was made.

## Result and artifacts

FULL did not qualify. PARTIAL remains unattempted. Live legal qualification therefore remains open, and legal expert review remains pending.

The sanitized run is in `.venv/approved-two-case-live.json` with SHA-256 `f24867fa6abfb2126f8821b853afb3fc53510c110208209761302fa377ef3b3e`. It contains the control evidence, provider metadata, redacted draft claims, packed passage associations, authority metadata, verifier outcome, final serialized response and exact replay result. The isolated launch and driver scripts are in `.venv/approved_two_case_launch.py` and `.venv/approved_two_case_driver.py`. No application, verifier, release policy or benchmark fixture files were modified.

## Post-run preservation

The full test suite passed **223/223**, and the serialized adversarial benchmark passed **56/56**. Unsupported FULL releases, unsupported PARTIAL releases, invalid citation releases and verifier/release inconsistencies were each **0/56**. Fail-open verifier errors were **0/4**. The 43-fixture verifier comparison and frozen 15-case release replay were byte-identical to the preceding reports. All four locked fixture hashes matched. The 108-query lexical rank hash remained `0e201d2ff20e9d1b97e4f7a9da7643c07600b1ee562620ec426193919c11723e`.

The full retrieval run completed **108/108** queries. All seven profiles matched the preceding quality scores. Hybrid RRF with contextual reranking retained Recall@5 0.950, Recall@10 0.961, MRR 0.941 and nDCG@5 0.904.
