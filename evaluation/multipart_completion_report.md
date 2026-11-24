# Multipart evidence completion

`LEGAL_MULTIPART_COVERAGE=1` opts into scoped provision selection and multipart evidence assembly. Production defaults, public response fields, Qdrant collections, E5/BGE models, and the original 108-query fixture were preserved. Evaluation used the archived corpus with the staged legal source overlay in a network-disabled container.

## Root causes

The six cases use 20 draft passage-to-sub-question judgments. Article and clause identifiers below are source identifiers. The raw report retains exact passage IDs, per-part ranks, and final citations.

| Case | Required evidence and failure mechanism |
| --- | --- |
| MP01 | Compulsory insurance 17.1.10 and 18.1 both survived. The identity passage inherited an extra deadline attribution through the cross-reference relationship. Assembly now preserves that relationship while retaining the requested owner. |
| MP02 | Occupational insurance 20.0 and 20.0.1 must stay together. Clause 20.0.1 was at BM25 50 and dense 20 in the broad branch. The separately requested insurer-notice clause 7.2.6 reached RRF 22 and dropped out of final evidence. The duty must still be described using the source's named legal capacity. |
| MP03 | Compulsory insurance 9.1 and its four qualifications, plus 11.1 and 11.1.1, are required. The broad branches missed several list members, 11.1 was dense rank 4 but RRF rank 53, and grouped provisions could fall below the final ten even when recovered later. |
| MP04 | The general compulsory insurance limitation provision (Article 74) was missed by both broad retrieval branches. The separate 18.11 rule reached dense rank 1 and RRF rank 51. A limitation period and rules on receiving a payment are distinct evidence obligations. |
| MP05 | The occupational tariff cap in 13.1 was missed by both broad branches. The formula in 14.1 reached RRF 24. The separate late-claim rule in 20.0.1 reached dense rank 6 and RRF rank 53, and its lead-in 20.0 fell outside the final ten. |
| MP06 | The 18.1 payment deadline reached dense rank 29 and RRF rank 76. The referenced 17.1.10 identity provision reached BM25 rank 17 and RRF rank 22 but missed the final ten. The actual deadline provision supplies the verified cross-reference seed. |

Ranks in this table are from the broad, pre-routing trace. The JSON distinguishes missing candidates from RRF rank, BGE eligibility, and final assembly. An out-of-shortlist candidate cannot be recovered by BGE on that branch. Scope checks were added to recovery candidates. The traced failures did not require changing model weights or Qdrant configuration.

In the full baseline with BGE, the missing top-ten assignments were MP02 Q1 (20.0), MP03 Q1 (9.1.1–9.1.4), MP04 Q1 (74), MP05 Q1 (13.1) and Q2 (20.0), and MP06 Q1 (18.1). Other cases of weak broad ranking were sometimes recovered by focused retrieval, reranking, or assembly. MP01 had both labeled passages and an incorrect extra association.

## Implementation

- `App/settings.py`, `App/query_plan.py`, and `App/main.py` wire the default-off flag into existing decomposition, retrieval, evidence assembly, and answer flow.
- `App/text_search.py` identifies independent requested obligations using source scope and operative text. A non-unique match cannot certify completeness. Formula and cap must come from the same source.
- `App/legal_evidence.py` prioritizes required provisions and list qualifications within ten distinct source passages, resolves verified links for the referenced identity rule, and derives per-part attribution from required provisions. Missing or ambiguous obligations mark the affected part incomplete.
- `App/legal_answers.py` includes affected sub-questions in partial-answer limitations. The existing structured guard also requires each required passage to be cited by the corresponding part before returning a complete answer.
- `tests/test_multipart_coverage.py` uses real frozen extracts in `tests/fixtures/multipart_source_extracts.json`. It checks exact attribution for each case, canonical citations, unknown citation rejection, and incomplete or uncited evidence handling even when a draft requests a sufficient status.

## Isolated retrieval results

Before and after use the existing provision planner and the same frozen corpus, with the new feature toggled. Both are scored on the first ten assembled candidates. Retrieval metrics are macro-averaged across the six cases. Earlier whole-package figures counted evidence outside that cutoff and are not comparable.

| Metric | BGE before | BGE after | RRF only before | RRF only after |
| --- | ---: | ---: | ---: | ---: |
| Complete cases | 1/6 | 6/6 | 1/6 | 6/6 |
| Correct passage-to-part assignments | 11/20 | 20/20 | 6/20 | 20/20 |
| Extra assignments on labeled passages | 3 | 0 | 1 | 0 |
| Passage Recall@5 | 0.5159 | 0.9524 | 0.3115 | 0.9524 |
| Passage Recall@10 | 0.5992 | 1.0000 | 0.3115 | 1.0000 |
| MRR@10 | 0.6944 | 1.0000 | 0.5833 | 1.0000 |
| nDCG@10 | 0.5631 | 1.0000 | 0.3606 | 0.9866 |

The alternate identity-document cases retain the verified 17.1 list introduction as supporting context. General sibling documentation and a continuation carrying the same extracted clause metadata were excluded after inspecting the evidence.

[BGE stage ranks, evidence IDs, and attribution](multipart_completion_bge_results.json) · [RRF-only stage ranks and attribution](multipart_completion_results.json)

Run with the existing verified exports at `.venv/eval_corpus_snapshot.json` and `.venv/real_eval_vectors.jsonl`, the staged source overlay, and cached model weights. The runner reads the exports locally and does not require a Qdrant endpoint.

```sh
python -m evaluation.evaluate_multipart_completion
python -m evaluation.evaluate_multipart_completion --bge
```

## Regression checks

- 144 backend tests and nine frontend tests passed. The controlled multipart tests passed for all six cases. All 20 labeled passages were cited with their canonical passage ID, document, article, paragraph, and source text. Fabricated IDs were rejected, and drafts missing required citations were blocked from returning a complete answer.
- The protected 108-query lexical ranking hash matched its stored baseline. The original benchmark replay with the multipart flag off reported zero top-20 ranking changes and unchanged Recall@5 (0.948), Recall@10 (0.958), MRR@20 (0.941), and nDCG@5 (0.903). The fixture and judgments were left unchanged. [Original benchmark replay](multipart_108_regression.md)
- `.github/workflows/regression.yml` checks that the experimental flag remains off by default.

## Limits

The six cases and the 164-query corpus dataset still require domain-expert review. Controlled citation tests validate provenance and enforce the completion gate using stubbed model responses. They do not establish live Azerbaijani answer faithfulness, legal correctness on unseen cases, or completeness of laws and historical versions absent from the corpus. The scoped rules intentionally abstain from certifying unsupported question types or ambiguous matches. Keep the experiment opt-in pending broader reviewed evaluation.
