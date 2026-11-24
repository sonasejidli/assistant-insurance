# Passage retrieval root causes and multipart coverage

## Scope

The original ranks 60 and 126 were whole-corpus BM25 passage ranks. Both documents placed first because a different passage from that document scored highest. This evaluation freezes the 4,405 original parents and adds 887 staged parents to an isolated exact index. The staged views use the same E5 representation. Fresh encoding probes verify compatibility with the archived vectors. RRF uses 0.7/0.3 BM25/dense weights, up to 50 candidates per branch, and the existing 50-candidate BGE evaluation shortlist. Production settings were untouched.

## Root causes

- **Civil Code Article 883.1.** The query's law-name terms match references in other provisions. The strongest original lexical hit was Article 935.4 from the same document. The definition itself ranked 60th lexically. The broad dense branch found it, but its dense-only evidence received insufficient fusion weight for the BGE shortlist. A law-only search serves as a diagnostic control for the scope mismatch.
- **Motor tariff clause 2.2.** The original question combines the calculation method with the base amount. Formula provisions and amendment notes contain more of the calculation vocabulary than the short operative clause. The base-premium clause missed both initial candidate lists. Explicit source filtering alone also missed it at the tested depth.
- **Rewriting and cross-references.** The old deterministic rewrite produced no alternative on these two probes and the tariff query stayed in one part. The broad reference expansion did not recover either missing anchor. Fixing the shortlist requires direct evidence of the requested clause before reranking or context expansion.
- **Multipart gaps.** Each retrieval lane previously attached candidate passages to a part. The controller knew when a part had zero candidates. It could not identify an incomplete document list or tell that an exception had been retrieved without its controlling rule. The six fixed cases also reveal misses that expansion cannot fix when the initiating clause never enters the candidate set.

## Changes

- `App/text_search.py` and `App/settings.py` add the `LEGAL_PROVISION_RETRIEVAL` option. The narrow provision branch admits a uniquely matching definition, motor base rate, or auditor nonpayment provision from the applicable source scope. It honors metadata eligibility, declines ambiguous matches, and reserves the result in final context. BGE still scores the admitted candidates with the same checkpoint.
- `App/query_plan.py` separates a calculation request from its base-premium request and uses bounded Azerbaijani wording alternatives for notification and document-triggered deadlines. The original query remains available for generation.
- `App/legal_evidence.py`, `App/legal_answers.py`, and `App/main.py` keep detected document-list items and controlling exclusions in their own source and numbered group. They record the required passage IDs per part, add eligible group members subject to a budget, and prevent a complete answer when known required passages are missing or uncited. Candidate association remains separate from semantic validation of a claim.
- `evaluation/trace_passage_retrieval.py`, `evaluation/evaluate_reliability_followup.py`, `tests/test_provision_retrieval.py`, and the CI default check cover the stage comparison, multipart recall, isolation, scope and completeness guard. The benchmark fixtures and production collections remain intact.

## Exact passage trace

| Query and setup | Full BM25 rank | Full E5 rank | Candidate order before BGE | After BGE | Final context |
| --- | ---: | ---: | ---: | ---: | ---: |
| Civil Code 883.1, broad baseline | 60 | 18 | 63 | 63, unscored | Missing |
| Civil Code 883.1, law-only baseline | 13 | 7 | 2 | 1 | 1 |
| Civil Code 883.1, broad with provision branch | 60 | 18 | 1 | 1 | 1 |
| Motor 2.2, broad baseline | 126 | 1,685 | Missing | Missing | Missing |
| Motor 2.2, law-only baseline | 57 | 91 | Missing | Missing | Missing |
| Motor 2.2, broad with provision branch | 126 | 1,685 | 1 | 3 | 1 |

Both anchors were eligible under broad retrieval. A law-only filter excluded competing documents but kept the actual anchors eligible. The new branch leaves the original lexical and dense scores intact. BGE placed the tariff clause third in the broad run, and the final context reservation retained it first alongside the calculation evidence. On these two case-driven probes, final passage Recall@5 and Recall@10 rose from **0/2 to 2/2**. That result measures the two reproduced failures. [Exact baseline trace](passage_trace_before_exact.json) · [Provision-branch BGE trace](passage_trace_after.json)

## Multipart results

The paired run covers six existing draft multipart questions and 20 labeled part–passage associations. All variants used the same overlay, exact E5 archive, BM25, RRF, and ten-parent retrieval limit. The multipart comparison excludes BGE. Recall is macro-averaged over the returned passage lists before assembly; coverage requires attribution to the intended part after assembly.

| Policy | Recall@5 | Recall@10 | Correct associations | Fully covered questions |
| --- | ---: | ---: | ---: | ---: |
| Original decomposition | 0.187 | 0.187 | 4/20 | 0/6 |
| Prior reliability policy | 0.312 | 0.312 | 6/20 | 1/6 |
| Provision branch and grouped assembly | 0.312 | 0.312 | 14/20 | 2/6 |

The auditor case recovered all five document-list passages and both nonpayment passages. Occupational notification, both limitation-period provisions, both occupational premium provisions, and the compulsory decision deadline still missed their labeled part. The per-query JSON retains their IDs and the retrieved parent lists. The coverage guard applies to detected requirement groups and preserves partial output when a controlling provision is missing or uncited. Completeness beyond those groups still requires judged answers and broader approved labels. [Final multipart results](multipart_provision_results.json)

The 140 backend tests and original 108-case lexical lock passed. Keep the provision option off in production while four multipart cases remain incomplete and broader gold evaluation is pending. Reproduce the exact traces in the isolated workspace with `python -m evaluation.trace_passage_retrieval --output evaluation/passage_trace_before_exact.json`, then repeat with `--provision` and a separate output. Add `--skip-bge` for the multipart comparison.
