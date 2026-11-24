# Azerbaijani Insurance Legal Intelligence Platform · Readiness review

## Architecture

`/ask` resolves intent and conversation context, then optional planning decomposes or rewrites eligible questions and adds soft source routes. `TextRetriever` keeps exact article lookup and uses BM25 plus E5/Qdrant, RRF and BGE for hybrid search. Child hits resolve to canonical parents. Evidence assembly retains legal qualifications, source intervals, and verified references. Structured generation binds citations to packed source IDs. Deterministic checks precede separate semantic validation and abstention. The frontend continues to consume the existing answer and source fields.

- [Query understanding and routing](query_planning_report.md)
- [Legal evidence, structured answers and citation validation](legal_evidence_report.md)
- [Corpus coverage and historical versions](knowledge_base_coverage.md)

## Evaluation and release gates

The original 108-query benchmark and 164-case real-corpus file are content-locked. [Fixture fingerprints](benchmark_lock.json)

The [gold review packet](gold_review_packet.json) holds source IDs, articles, paragraphs, draft grades, coverage, history, and unanswered review fields. A domain expert must supply expected answers, qualifications, review history and an approval for each case. For corrections, preserve the existing dataset and use `--dataset` with an explicitly versioned source-label file and a new matching review packet. Record the reviewer, date, reason and affected fields in `revision_history`. The current draft has no expert approvals.

The platform evaluator reports the requested retrieval metrics by category and query and keeps per-passage ranks for component comparisons. It separately identifies missing candidates and BGE demotions. Draft coverage and multipart controls stay outside the gold aggregate, including when a gold benchmark is available. The [36-case answer judgment packet](answer_judge_review_packet.json) records human and automated grades against the same answer hashes and judge revision. The evaluator requires 30–50 approved examples and reports case counts, human pass rates, paired agreement, and false passes. Automated judgments do not replace expert judgments.

The push and pull-request workflow runs backend and frontend tests, fixture locks, an offline lexical ranking regression, and experimental-default checks. The protected scheduled workflow uses a dedicated isolated runner, reviewed inputs, current-commit answer judgments, and approved quality floors. It retains reports as GitHub Actions artifacts for 90 days. The observed lexical hash serves as a reproducibility check. Expert-approved production quality floors and protected-runner configuration are still pending.

### Draft diagnostic results

The frozen-index run included 17 negative controls and six multipart queries. Only one of the six multipart queries found and attributed every labeled parent to its intended part at the tested cutoff. Across the six cases, RRF Recall@10 was 0.190 and routed RRF reached 0.246. Adding verified reference targets left aggregate Recall@10 at 0.190. Negatives were inspected for retrieval behavior. Their abstention outcomes require generated answers and human evaluation. The run used exact search with the frozen E5 archive and four CPU threads. It did not run BGE or make rewriting-provider calls. [Per-query diagnostic results](phase8_draft_controls.json)

### Original regression and test results

The original paired rerun changed no top-20 ranks across 108 queries. Recall@5 was 0.948, Recall@10 0.958, MRR@20 0.941, and nDCG@5 0.903. The current path measured retrieval p50/p95 of 74/101 ms and reranking p50/p95 of 2,975/4,975 ms on the isolated fixture. These measurements do not establish a speed improvement or production latency. The 128 backend tests, nine cached frontend tests, and 108-case lexical ranking lock passed. [Original rerun report](phase8_original_regression.md) · [Per-query rerun results](phase8_original_results.json)

```sh
python -m evaluation.evaluate_platform ci
python -m evaluation.evaluate_platform retrieval --draft --suite controls --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl --output evaluation/phase8_draft_controls.json
python -m evaluation.evaluate_platform retrieval --rerank --reviews approved-cases.json --snapshot snapshot.json --vectors vectors.jsonl --output gold-results.json
python -m evaluation.evaluate_platform answers --reviews approved-answer-judgments.json --output answer-validation.json
```

## Observability and privacy

Langfuse is the selected integration. Its SDK is already a dependency and supports explicit observation metadata and project roles. Phoenix offers OpenInference/OpenTelemetry instrumentation and configurable authentication but would introduce a second tracing deployment. [Langfuse SDK](https://langfuse.com/docs/observability/sdk/instrumentation) · [Phoenix tracing](https://arize.com/docs/phoenix/learn/tracing/how-tracing-works) · [Phoenix authentication](https://arize.com/docs/phoenix/deployment/authentication)

HTTP traces use random request IDs and record stage durations, candidate ranks and scores, parent IDs, cross-reference targets, prompt versions, citation outcomes, evidence status, and provider token counts when reported. They capture text lengths and routing categories. Raw queries, history, generated variants, prompts, evidence text, answer text, and explicit filter values are excluded. LangChain callbacks that could capture raw messages are disabled. HTTP status failures, provider rate limits, and quality checks have separate events. `RAG_METRICS_LOG_ENABLED=true` emits structured logs, and `python -m evaluation.summarize_rag_telemetry APP_LOG` calculates rates and p50/p95. Langfuse export requires credentials and HTTPS. Both exports default off.

Before enabling telemetry, configure a dedicated project with least-privilege access and project-scoped keys, encrypted storage and backups, restricted log readers, and a verified deletion window. The proposed short retention is 30 days for request metadata. Configure deletion explicitly because access windows alone do not delete data. No production access, retention or storage policy was activated during this work. [Langfuse project roles](https://langfuse.com/docs/administration/rbac) · [Langfuse retention](https://langfuse.com/docs/administration/data-retention)

## Adoption decision

Keep the baseline E5 and BGE behavior and all experimental flags off. The original benchmarks, source snapshots, and production collections were preserved. Production readiness requires expert-approved relevance and answer judgments, a controlled full run, an agreed baseline policy, and verification of the deployment's telemetry permissions and retention. The provider rate limit from the earlier faithfulness probe remains an answer-evaluation gap. The source coverage matrix identifies OCR and legal-version gaps that still affect applicability and abstention.
