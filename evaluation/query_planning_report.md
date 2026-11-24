# Phase 1 · Query understanding

## Architecture and scope

`/ask` and `/search` already use `query_resolution.py` to pass a standalone query to `TextRetriever`. The retriever uses LangGraph for exact article lookup or BM25 and E5/Qdrant retrieval, followed by RRF, BGE, and parent selection. `document_processing.py` extracts legal hierarchy and same-document article links. `system.py` packs original evidence, follows bounded local references and neighbors, and validates source markers. Both frontends consume the existing API responses. The 108-query fixture and the separate 164-query real-corpus labels remain independent of the application index.

The new planner adds no index, model, or source format. It uses the existing rule classifier and optional classifier fallback, then selects an internal route. Greetings, general conversation and out-of-scope messages skip legal generation. Legal and insurance intents use retrieval. Unresolved references ask for clarification. Exact article lookup and explicit comparison still use their specialized paths. Follow-up history is retained for planning, while only the selected prior turn enters generation as context.

## Experimental controls

| Variable | Behavior when enabled |
| --- | --- |
| `QUERY_DECOMPOSITION` | Retrieve up to three independently recognizable requests and interleave their evidence. Passages found for multiple parts retain each association. A complete answer must include every part with an associated citation. |
| `QUERY_ROUTING` | Add focused searches based on insurance type or candidate law while retaining the search without inferred constraints. User-supplied filters still apply. Rule confidence, matched topics, legal subjects and executed filters appear in debug diagnostics. |
| `QUERY_EXPANSION` | Request up to three Azerbaijani reformulations per eligible part with one bounded provider call. Normalized equivalents are deduplicated and variants with different recognized topics or numerical values are rejected. The original standalone query always runs. |
| `QUERY_HYDE` | Request a short hypothetical document-style passage and embed it separately with the E5 passage prefix. BM25 and reranking still receive the standalone question. Only indexed parent passages can reach answer generation. |

All four flags default to off. Candidate lists are fused through weighted reciprocal rank using the existing `RRF_K`. The original list has weight 1.0, focused routes 0.5, alternatives 0.35, and the hypothetical branch 0.25. This preserves the established RRF and BGE behavior within each branch. Selected weights and the 50-candidate evaluation pool are benchmark settings. The running service configuration and its Qdrant collections were untouched.

The rules deliberately leave dependent clauses together. Topic matching and rewrite validation are lightweight heuristics. Candidate attribution checks source identity and completeness of answer structure. The benchmark does not verify that every factual clause is semantically entailed by its citations. Cross-document reference resolution is outside Phase 1. Existing same-document reference expansion is reused.

## Measured retrieval

The comparisons used 4,405 frozen parent passages, archived E5 child vectors, exact vector search, CPU with four Torch threads, BM25/dense weights 0.7/0.3, and the same current follow-up resolver. The tables measure the top 10 hits before BGE. Labels are provisional pending domain-expert review. The 14 coverage-gap controls have no relevance denominator.

| Policy | Queries scored | Recall@5 | Recall@10 | nDCG@10 | Median ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Standalone | 150 | 0.579 | 0.669 | 0.526 | 230 |
| Decomposition | 150 | 0.579 | 0.669 | 0.526 | 231 |
| Routing | 150 | 0.593 | 0.669 | 0.556 | 429 |

Routing changed nDCG@10 on 23 queries. Its gain at the top of the list came with additional retrieval runs. The timing columns are serial observations from one pass and exclude HTTP, reranking, and answer generation. [Per-query ranks](query_planning_results.json)

The 164-query set contained no questions that met the conservative decomposition rules. A separate three-question fixture combines existing source-backed judgments for compulsory claims, occupational insurance, and auditor insurance. It uses the original parent IDs and adds no evidence passages.

| Composite query | Source label cases | Relevant parents found by part, standalone | Relevant parents found and attributed by part, decomposed |
| --- | --- | --- | --- |
| MP01 | AZR095, AZR097 | 1, 1 | 1, 1 |
| MP02 | AZR010, AZR105 | 0, 0 | 1, 0 |
| MP03 | AZR106, AZR012 | 1, 0 | 1, 0 |

On this fixture, decomposition raised Recall@10 from 0.381 to 0.492 and nDCG@10 from 0.239 to 0.415. Two questions still missed every labeled parent for their second part. The three examples are a regression check, and the measured result does not establish production gains. [Composite results](query_planning_multipart_results.json)

The LLM comparison used three held-out questions. All six requests returned HTTP 429 with retries disabled. The expansion and HyDE runs accepted zero generated branches and fell back to the same standalone ranks. Recall@10 was 0.167 and nDCG@10 was 0.088 for each of the three configurations. This measures fallback behavior only. Successful expansion recall, candidate precision, and latency still require provider access and evaluation. [Provider trial](query_planning_llm_results.json)

Keep the retrieval experiments off in production. The current measurements cover the isolated retrieval stage and do not establish improvements in citation entailment or answer completeness. Validation included 114 backend tests and nine frontend tests.

## Reproduction

Run against the frozen corpus export and vector archive from the [real-corpus evaluation](real_insurance_report.md). The default command compares the original retrieval route, decomposition, and routing before reranking. Add `--multipart` for the three composite cases, or `--rerank` to include the existing BGE path. Add `--llm --only-ids AZR036 AZR048 AZR138` for the bounded provider comparison. LLM experiments send only benchmark questions or resolved sub-questions to the configured provider.

```sh
python -m evaluation.evaluate_query_planning --dataset evaluation/real_insurance_dataset.json --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl --output evaluation/query_planning_results.json
```
