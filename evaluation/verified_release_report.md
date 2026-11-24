# Verified answer release gate v1

Set `LEGAL_VERIFIED_RELEASE=1` to exercise the gate. The flag is off by default. When enabled, the request also runs source-authority checks and passes the generated draft through the existing hardened verifier before returning the response. See [the inspected request path](verified_release_baseline.md).

## Release behavior

The previous request path formatted the generation and citation check results and returned FULL or PARTIAL. The hardened verifier ran offline, so its decision was absent from the response path. A scripted faithfulness approval could therefore survive to serialization.

| Generated / hardened mode | Response |
|---|---|
| FULL / FULL | FULL only if every original claim is retained unchanged with its verified binding |
| FULL / PARTIAL | PARTIAL only with independently witnessed, scoped evidence |
| PARTIAL / FULL or PARTIAL | At most PARTIAL, with independently witnessed evidence |
| Withheld, or no releasable fragment | Existing recovery language and a null mode, except when the verifier explicitly establishes NOT_FOUND |

The capture retains the generated draft and mode, exact verifier result and reason, binding attributes before and after normalization, excluded or qualified claims, conflicts, and final serialized answer. The answer uses the verifier's witnessed fragment. Context remains available in source-authority metadata. Contextual passages cannot authorize a statutory claim. An unresolved conflict identifies its source evidence when available and yields no settled normative conclusion.

Packed XML omits absent article and clause attributes at the verifier boundary. This maps missing, empty, and whitespace-only metadata to the same representation while retaining actual article/clause values and exact document and passage identifiers. The frozen source records are untouched.

The opted-in planner preserves two or three explicitly punctuated questions as separate parts. The response reports supported-fragment coverage and part completeness separately. A sanitized land-user result withholds the generalized eligibility conclusion and identifies the applicability gap. The response also identifies unresolved remedy procedure, employer duty, contract/event dates, and potential conflicts when those gaps are known.

## Offline results

| Check | Result |
|---|---:|
| FULL without hardened FULL, gate disabled | 9 cases out of 15 |
| FULL without hardened FULL, gate enabled | 0 cases out of 15 |
| Final mode consistent with the fixture's release policy | 15/15 |
| Expected hardened mode | 15/15 |
| Unsupported released claims | 0/6 |
| Citation integrity among responses with released claims | 6/6 |
| Canonical and corrupted citation probes | 2/2 |
| Expected multipart coverage | 1/1 |
| Specific missing-information disclosure | 5/5 |
| Expected witness qualification | 1/1 |
| Expected abstentions | 9/9 |

R01 released FULL. R02, R04, R05, R10 and R11 released PARTIAL. R03 and R06–R09 withheld the generated drafts for unverified scope, lack of support or invalid binding. R12–R15 abstained under unresolved applicability or conflict, contextual-only evidence, or insufficient evidence. R11 retained coverage for Q1 and exposed the missing support for Q2. R08 bound the citation successfully after canonicalization and still withheld the unsupported draft. All 15 fixture checks passed. These counts measure behavior against the unchanged hardened verifier and the specified release policy.

Run locally with a new output directory and the existing corpus snapshot:

```text
python -m evaluation.verified_release_benchmark capture .venv/release-run --snapshot .venv/eval_corpus_snapshot.json
python -m evaluation.verified_release_benchmark replay .venv/release-run --output .venv/release-report.json
```

The benchmark uses recorded scripted generation, captures both flag settings, verifies capture checksums, and checks the serialized response on replay. Two replays were byte-identical. The 43-fixture hardened verifier comparison was byte-identical before and after. The frozen 15-case replay and the 53-fixture temporal/conflict report were byte-identical to their previous results. The 39-fixture report reproduced the current-layer metrics embedded in the retained 53-case report, including the legacy T11 and C06 expectation differences. The old 39-fixture expectations are preserved. The full suite passed 208/208, including the original 108 distinct queries and all four locked hashes. Seven-case draft and proposed v2, prompts, model settings, retrieval settings, and Qdrant data were untouched.

## Limits

This is an engineering benchmark. The deployment includes a small exact-question witness catalog. Unmatched wording, unreviewed conversational context, and supplied case dates can therefore trigger abstention even when a useful answer might exist. Explicit splitting is bounded to two or three independently punctuated questions. Five disclosure examples and one end-to-end multipart coverage check do not measure general-language coverage. The benchmark exercises real request and serialization code with scripted provider outputs. It has no live-provider or container-build result. Legal expert review remains necessary for the witnesses and scope, unresolved conflicts, date applicability, and broader question coverage.
