# End-to-end legal answer quality benchmark v1

The independent dataset contains **15 Azerbaijani requests**. Six frozen baseline questions are source-derived, four development controls and five stress cases are synthetic engineering fixtures. All are pending legal expert review. No expert-reviewed results are available. The labels describe bounded source or protocol expectations. They do not certify current law.

The [execution map](legal_answer_quality_baseline.md) was written before implementation. The harness uses the actual ask entry point, question resolution and planning, BM25, retrieval graph and RRF, evidence selection and assembly, authority and temporal annotations, structured claim binding and final rendering. Scripted dense candidates, reranker scores, provider responses and semantic-judge verdicts replace external or model-dependent boundaries. Their rates do not estimate E5, BGE, provider, or semantic judge accuracy. The captured rendered claims are projected into the existing hardened verifier without changing its rule set or replacing the user-facing answer.

## Results

Each ratio uses the recorded eligible denominator. Fractional ranking numerators are sums of per-query values. The detailed results include percentages, failed case IDs, trace paths and outputs, grouped by partition, source origin and review status. The baseline and synthetic three-mode accuracy scores were **4/4** and **3/5**, respectively.

| Area | Metric and result |
| --- | --- |
| Understanding | Route **1/1**, conversational context exact match **2/2**, part-term precision **1/1**, recall **1/2**, exact match **0/1**. The last three refer to the independently labeled multipart control. |
| Evidence | Main provision **8/8**, condition-passage coverage **5/5**, exception **2/2**, personal scope **2/2**, temporal scope **2/2**, cross-reference provision **1/1**, commencement/amendment **1/1**, repeal **1/1**, complete parts **6/15**. Presence in assembly does not establish legal sufficiency or that a cross-reference expansion was responsible. The denominator for completeness includes deliberately unresolved parts. |
| Claims | **7/10** exact claim spans had supported technical labels, **1/10** unsupported, one partial and one unverifiable. Scope violations **2/10**. Answer-level conditions **2/3** and exceptions **1/2** were retained on the labeled spans. The medical and repeal questions are statement-level fixtures and do not certify coverage or effective periods for other rules. |
| Citations | Hardened exact-binding **8/9** assessed claim lines. Final structured reference identity and text preservation **10/10**. The binding denominator is a different unit from the atomic-claim denominator. |
| Answer modes | Three-mode accuracy **7/9**. False FULL **2/4**, false PARTIAL **0/1**, false NOT_FOUND **0/4**, each restricted to predictions with applicable draft modes. Appropriate abstention **4/4**. **6/8** live FULL decisions did not receive hardened FULL, including out-of-witness and insufficient-scope results. **2/8** FULL decisions had an independently annotated unsupported assertion or material over-scope. |
| Uncertainty | General disclosure marker **5/7**. A fixture-specific missing-information marker appeared in **1/5**. Explicit expert-review disclosure **0/1**. The one accepted unsupported assertion was presented with FULL certainty (**1/1**). These are bounded communication checks, not qualitative clarity ratings. |
| Temporal and authority | Asserted date fields **6/6**, event/contract relationship **1/1**, expected normative eligibility **8/8**, contextual ineligibility **9/9**, historical exclusion and conflict-record count **1/1** each. Asserted dates do not become trusted case facts in the hardened gate. |
| Reliability | **15/15** captured requests, **14** scripted generation attempts, **1** format retry and **1** injected provider timeout. **14/15** requests were free of that error. The timeout is excluded from three-mode accuracy. Mean local harness latency was about **4.2 ms**, including the actual request graph with scripted model calls. |

| Rank stage | Recall@5 | Recall@10 | Recall@20 | MRR@20 | nDCG@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 14/14 | 14/14 | 14/14 | 11.25/14 | 11.8741/14 |
| Dense fixture boundary | 14/14 | 14/14 | 14/14 | 13/14 | 13.2619/14 |
| Fusion | 14/14 | 14/14 | 14/14 | 13/14 | 13.2619/14 |
| Reranked candidates | 14/14 | 14/14 | 14/14 | 13/14 | 13.2619/14 |
| Final selection | 14/14 | unavailable | unavailable | unavailable | unavailable |
| Assembly order | 14/14 | 14/14 | 14/14 | 13/14 | 13.2619/14 |

Candidate ranks measure the captured lists on a small, curated source extract. Final selection was captured at depth five. Assembly order is a diagnostic view, not an additional search ranking. This cohort did not show a required-passage candidate miss. The runner distinguishes absent candidate, below-cutoff ranking, selected-not-assembled, and assembled-not-packed states. It does not infer a parent-child or cross-reference cause without trace evidence.

## Earliest evidenced failure

| Case | Stage | Recorded cause |
| --- | --- | --- |
| E2E-B04 | Uncertainty communication | Follow-up context resolved and the request abstained, but the final wording did not identify the missing exception scope. |
| E2E-B06 | Citation binding | Decision 156's returned passage and text stayed intact. Packed XML had empty article and clause strings while the frozen metadata has nulls. The existing strict verifier withheld the claim. |
| E2E-D02 | Provider or infrastructure | Injected timeout during the generation attempt. Structured abstention is a technical outcome here. |
| E2E-S01 | Claim support | The answer generalized land-user liability and omitted the owner and family-farm limitations. The cited passage was nevertheless present. |
| E2E-S02 | Uncertainty communication | The authority layer blocked the historical text and the unverified current scoped provision. The user-facing abstention did not identify the unresolved effective period. |
| E2E-S03 | Claim support | The event was recorded outside the asserted term. The accepted answer repeated only the general in-term rule, without grounding its application to the request. The gate had no verified case facts and withheld. |
| E2E-S04 | Query decomposition | The plan merged the two material questions. The answer covered termination only. The independent gate returned PARTIAL. |
| E2E-S05 | Claim support | The deliberately optimistic judge stub passed an unconditional payment assertion with an exact scoped citation. The hardened gate withheld. |

E2E-B01, B02, B03, B05, D01, D03 and D04 had no earlier failure on their scored expectations. B05 had no exact hardened witness for its accepted commencement wording, so FULL remained unverified. It is an expert/witness-coverage gap, with no semantic failure inferred from the missing witness. Clarification and context-induced abstention are legitimate outcomes. The two-mode distinction between legally verified and simply emitted answers remains explicit in every row.

## Reproducibility and limits

The capture directory stores the original requests, context and observable plan, candidates, ranks and available scores, assembled and packed evidence, declared dates, authority and conflicts, raw attempts, rendered and final answers, citations, policy outputs, fixture configuration, observed error events and timing. Captures use the existing checksummed run storage. Replay imports neither the model harness nor the live pipeline and recomputes the existing hardened result, checking it against the stored result. Two replays of the same recorded run were byte-identical. Fresh captures produce new trace IDs and timing observations.

The prior real-provider seven-case rerun can be included as a separate operational reference. It recorded **12 calls**, **5 HTTP 429s**, **4 transport retries**, **1 format retry**, **2 recovery responses**, and **16.65 s mean request latency**. Seven calls reported usage totaling **17,509 input** and **7,008 output tokens**. Reliable price data was absent, so cost was not estimated. None of those observations contributes to this suite's metrics.

General entity extraction, free-text dates, exhaustive unsupported-inclusion judgments, document-level relevance for distractors, independent Azerbaijani clarity ratings and live answer faithfulness are unavailable in this suite. The authority check verifies the historical presentation and exclusion of the struck-through provision in the covered case. It does not establish general historical retrieval accuracy. Semantic support judgments are bounded technical annotations over exact scripted claims and do not establish legal expert validation. No production retrieval or generation behavior was changed.

## Files and regression

Added the execution map, versioned dataset, capture harness, replay and scoring runner, benchmark report, and four regression tests. No existing pipeline, prompt or benchmark file was edited.

```powershell
python -m evaluation.legal_answer_quality capture .venv/legal-quality-new --snapshot .venv/eval_corpus_snapshot.json
python -m evaluation.legal_answer_quality replay .venv/legal-quality-new --snapshot .venv/eval_corpus_snapshot.json --output .venv/legal-quality-report.json
python -B -m unittest discover -s tests
```

**203 tests passed, zero failed.** The 43-fixture hardened verifier comparison was byte-identical before and after. The original 39-fixture authority dataset, separate 53-fixture temporal suite, 108-query benchmark, four locked hashes, seven-case draft and proposed v2 were preserved. Qdrant collections, production defaults and actual prompt and model configuration were unchanged.
