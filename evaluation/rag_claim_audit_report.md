# Claim and answer-mode audit

This offline review covers run `9d5817e013db4ad0a930be4f0445b015`. It compares the captured text with the frozen indexed corpus and the unchanged seven-case draft. Findings are source judgments for this run. Current legal effect and expert gold approval were outside the audit.

## Claim-level findings

The source IDs below refer to the exact passages packed for each answer. Passage text and locator metadata are preserved in the [audit extract](../.venv/rag-claim-audit-input.json). Each listed PDF page was checked against the source. Page numbers count from the first PDF page.

| Case and marker | Exact source locator | Material claims and support judgment |
| --- | --- | --- |
| AZ7-01 S2 | *Sığorta fəaliyyəti haqqında*, `sığorta 1.pdf`, Art. 81 §81.4, p. 47. Passage `001919fd-55d4-5cbb-b7c3-2452ff934522` | **Supported within life insurance.** On insurer bankruptcy or liquidation, life insurance reserves may be transferred to another insurer or returned to the insured, at the choice stated in the provision. This regulates reserves. It leaves the eventual payer for the user's unspecified claim unresolved. The indexed and packed locator says §81.1 because the chunk starts there. The operative language is §81.4 in the same chunk. |
| AZ7-01 S5 | Same law, Art. 119 §119.3, p. 79. Passage `3f0dd5fd-5ffe-5249-81a6-a0ef581f35ba` | **Partial for the general priority claim.** The source directly covers liquidation expenses and claims secured by the insurer's pledged or mortgaged property up to the security amount. It also specifies a ranking for the unpaid secured balance. General ordering of accepted creditor claims is established elsewhere in §119.1. The answer compresses these distinct rules. |
| AZ7-01 S1 | Same law, Art. 118 §118.2, p. 78. Passage `5abb8c6d-3360-56bf-8485-b3a40cacc243` | **Supported, peripheral.** The court considers the insolvency petition only when documents support the grounds. This procedural point does not resolve who pays. |
| AZ7-02 S1 | Occupational compulsory insurance law, `sığorta 3.pdf`, Art. 11 §11.8, p. 10. Passage `a57a82bb-11a3-59b9-ad6d-331cbd732955` | **Partial because scope was omitted.** Ordinary termination of the occupational compulsory contract does not release the insurer from paying the beneficiary for insured events during the period in force. The answer gives an unqualified “yes” for an unspecified contract and speaks directly of the user's entitlement. The cited clause does not establish a universal rule, beneficiary status, or the effect of invalidity from inception. |
| AZ7-02 S5 | *Sığorta fəaliyyəti haqqında*, `sığorta 1.pdf`, Art. 1 §1.1.19, p. 2. Passage `a4a6fb69-831c-5785-8e42-b9df4c459a8c` | **Supported as a timing condition.** The general definition places an insured event or condition during the contract's term. Timing alone does not establish coverage or the consequences of termination in every insurance regime. |
| AZ7-04 S1 | Occupational law, `sığorta 3.pdf`, Art. 7 §7.3, p. 7. Passage `b3845218-4ab9-57d4-93ca-9371f1e70c9b` | **Supported with the stated trigger.** If the obligated policyholder fails to insure, or contracts on less favorable terms, it owes at least the statutory coverage amount to the person who should have been insured when an insured event occurs. This supports the central conditional employer obligation. It does not establish an automatic insurer/Bureau payment or a filing procedure. The less favorable terms branch was omitted, though the question specifically asked about no contract. |
| AZ7-04 S4 | *Tibbi sığorta haqqında*, `sığorts 4.pdf`, Art. 15-2 §15-2.2.1, p. 9. Passage `86c37fdf-2f40-52b0-bf62-65cfb32fc3e9` | **Wrong regime for the associated claim.** The citation identifies an employer as policyholder for employees under the medical insurance regime. It does not establish the occupational duty asserted in this answer. Occupational §§3.1.1, 4.0–4.0.1 and 7.2.1 supply the relevant scope and duty. |
| AZ7-04 S5 | Occupational law, `sığorta 3.pdf`, Art. 11 §11.2, p. 10. Passage `18ac550f-6a5c-5b45-9c10-29a89ee57ee3` | **Supported for the refusal rule, qualified inference for its consequence.** The insurer cannot refuse the compulsory contract within the provision's scope. This supports saying refusal does not excuse the policyholder's duty in that regime, together with §7.3. The cited refusal clause does not show that coverage nevertheless exists or explain the worker's remedy. |
| AZ7-06 S1 | *Sosial sığorta haqqında*, `sığorta 7.pdf`, Art. 14 §14.5.2, p. 10. Passage `4e18a699-f743-5696-aaea-a2d980b7d60b` | **Supported, peripheral.** The 25% withholding rule for civil-law contracts excludes individual entrepreneurs. The exemption from this particular rule does not identify their own premium or deadline. |
| AZ7-06 S3 | *Tibbi sığorta haqqında*, `sığorts 4.pdf`, Art. 15-11 §15-11.4 first paragraph, p. 16. Passage `3738ecf7-3889-57a1-8078-4bff27027019` | **Overbroad and contradictory as stated.** Monthly calculation, declaration and payment by the 15th are supported for the applicable medical premium class. The text expressly excepts the specified sole-worker activities and qualifying transport class from that general mechanism. The answer applies it to sole workers as a group, strips the exceptions and fails to identify the medical regime. |
| AZ7-06 S6 | Same law and clause, continuation on p. 16. Passage `5322908c-f5a5-5213-85bd-fb9d57b4c8ff` | **Partial.** Payment at receipt issuance and at issuance of the Distinction Sign are both in the source. The first is limited to the cited Tax Code Art. 220.10 activities and the second to the applicable individual passenger or freight transport class under Art. 218.4.1. The answer generalizes both triggers and treats them as applying to the same broad group as the preceding monthly rule. Although the receipt names multiple contributions, this cited clause regulates compulsory medical insurance. S6 was packed via context expansion beyond the initial top five. |
| AZ7-07 S1, line 1 | *Sosial sığorta haqqında*, `sığorta 7.pdf`, Art. 14 §14.5.1-1.9, p. 10. Passage `408840aa-b5ca-50b7-ba73-3cd0b289a405` | **Partial.** The minimum monthly wage and land area are the correct bases. The answer generalizes from agricultural owner-users to all land users and drops the family-farm qualification and working-age limits (15 up to the pension-age threshold) for the member category. |
| AZ7-07 S1, line 2 | Same passage | **Supported within the eligible class.** The three area bands and rates match the source wording: 2%, 6%, and 10%. The answer does not resolve a personalized amount. |
| AZ7-07 S1, line 3 | Same passage | **Partial.** The outside-employment exclusion requires payment of compulsory state social insurance. The provision describes an assessed 61–100% impairment of bodily functions and disability established under age 18 in the family-farm member qualifications. The answer drops the insurance type, compresses the impairment test, and presents the exclusions without distinguishing the groups. |

The land-use flat 6% clause §14.5.6 is struck through in the source PDF and survived extraction. It appeared second in the retrieved list but the model did not cite or repeat it. The operative life-reserve §81.4 and the two medical §15-11.4 paragraphs are visible without strike-through on their cited pages. No other cited passage was demonstrated to be obsolete in the frozen edition. These checks do not establish currency outside that edition.

## Answer-mode analysis

Rows represent the unchanged draft expectation. Columns represent accepted run decisions. Recovery is reported outside the matrix.

| Draft expected | FULL | PARTIAL | NOT_FOUND |
| --- | ---: | ---: | ---: |
| FULL | 1 | 1 | 0 |
| PARTIAL | 2 | 1 | 0 |
| NOT_FOUND | 0 | 0 | 0 |

Agreement is **2/5**. AZ7-03 and AZ7-05 had no answer mode.

| Case | Expected → predicted | Why |
| --- | --- | --- |
| AZ7-01 | PARTIAL → PARTIAL | The model correctly signaled a limitation. It omitted the conditional Bureau route, regulator-directed contract transfer, accepted-claim priority classes and the dependence on available liquidation funds. No draft direct evidence reached the packed context. |
| AZ7-02 | PARTIAL → FULL | §11.8 was ranked and packed first. The missing issue was scope, including the unspecified insurance class and the distinction between termination and invalidity. The answer did retain the time-in-force condition. |
| AZ7-04 | PARTIAL → FULL | The employer's conditional liability is supported by §7.3, which the frozen draft omitted. The worker's information right under §6.1.3, court route under Art. 22 and any specialized filing or substitute-payer process still went unanswered. The medical citation also fails occupational attribution. This remains an overconfident answer to how to protect the worker's rights. The draft's unresolved portion should be narrowed during expert review to the procedure and any substitute-payer issue. |
| AZ7-06 | FULL → PARTIAL | The draft expects conditional treatment of ordinary and special social insurance payment, plus the occupational contract branch where the premium type is unclear. Neither method nor timing was grounded in the controlling draft passages. The medical text was used without identifying its regime and with incompatible payment instructions. PARTIAL was consistent with missing controlling evidence in the context. |
| AZ7-07 | FULL → FULL | Formal mode agreement masks incomplete eligibility. The clause supports the rate bands, but the generated answer omits ownership, family-farm membership and working-age qualifications. |

In this run, the legacy model chose whether to emit the `PARTIAL` prefix before validation. The legacy validator then checked recognized markers, packed-source membership, formatting and, when requested, multipart structure. The API recorded its final mode **after** validation and formatting from the accepted output or abstention path. The captured path did not execute decomposition or compute completeness against the draft sub-questions. Retrieval confidence alone did not drive the legacy mode. The structured path includes additional completeness checks, but it was not exercised here.

## Recovery responses

- **AZ7-03.** Provider calls returned twice, including one application format retry and no transport retries. Both captured visible outputs were exactly the empty string. Both recorded 1,536 output tokens and failed with `missing_or_invalid_source_markers`, followed by `AnswerFormatError`. This was the legacy text path. No structured JSON parsing was involved. Hitting the cap is verified. The capture lacks a finish reason, raw reasoning stream and token breakdown, so provider truncation or reasoning-budget exhaustion cannot be assigned as the root cause.
- **AZ7-05.** Three transport calls under one generation attempt returned HTTP status **429**, provider code **429**, message **`Provider returned error`**, and exception **`TooManyRequestsResponseError`**. No usable Retry-After value was captured. Delays were 0.8599011339886247 s and 1.325502036896682 s. The third call recorded `retry_budget_exhausted`. No model output or citation validation followed. The capture preserves these selected provider fields and does not contain the full HTTP body. The provider's quota cause is unverified.
- Both records have `decision_reason=answer_recovery`, null final mode, zero final claim bindings, and replay outcome `recovery`. Source previews in a recovery message do not make it an accepted answer.

## Retrieval diagnostics

Recall uses unchanged draft direct passages. Coverage records presence, not legal sufficiency. A clause appearing in multiple required part sets is counted once for passage recall and once per part for the presence columns. A candidate miss here means absent from both recorded top-50 branches. A downstream cutoff means observed in fusion but absent from top five. A null reranker score does not establish that BGE scored a candidate. All seven used one recorded retrieval branch.

| Case | Recall@5 | Draft evidence present by part | Candidate and ranking evidence |
| --- | ---: | --- | --- |
| AZ7-01 | 0/10 | Q1 0/10 | Nine candidate misses: compulsory §§32.1, 32.1.1, 33.1 and insurance activity §§112.2, 119.1, 119.1.1, 119.1.2, 119.1.3, 119.4. Occupational §18.12 was dense rank 8, absent from BM25, fusion 20, reranked 13 with a score. This is a residual cutoff after BGE improved its rank. |
| AZ7-02 | 1/1 | Q1 1/1 | §11.8 was BM25 21, dense 12, fusion 4 and reranked 1. Invalidity §11.9 is related evidence outside the direct denominator. The scope error cannot be explained by missing §11.8. |
| AZ7-03 | 1/4 | Insurer 1/2. Employer 0/3. | §124.1 was absent from BM25, dense 6, fusion 13 and reranked 2. Occupational Art. 23 appeared at dense 26 and fusion 52, with post-rerank position 52 and no BGE score. Occupational §§2.0.4 and 4.0.1 missed both candidates. |
| AZ7-04 | 0/6 | Worker protections 0/6. Unresolved procedure has no denominator. | §3.1.1 was dense 1, fusion 9 and reranked 9 with a score. §§4.0, 4.0.1, 6.1.3, 7.2.1 and Art. 22 missed both candidates. The controlling §7.3 ranked first in the final list but is absent from the frozen direct rubric. Reported zero recall therefore understates useful evidence. |
| AZ7-05 | 3/7 | Payout 2/5. Accident definition 2/3. | §§2.0.10, 2.0.12, 10.1.1 ended at 1, 2, 3. Their BM25 ranks were absent, 16, 18. Dense ranks were 1, 5, 14 and fusion 21, 5, 8. §§2.0.9, 5.1.1, 8.1.1 and 10.1.2 missed both candidate pools. Generation blocked on the provider after packing. |
| AZ7-06 | 0/7 | Method 0/7. Timing 0/4. | BM25 found social §§14.5.1-1, 14.6, 14.6-1 and occupational §§14.2, 14.3-1 at 5, 39, 25, 33, 50. Dense missed all five. Fusion positions 12, 76, 48, 64, 94 stayed unchanged after reranking. Only fusion rank 12 recorded a BGE score. Occupational §§3.1.7 and 4.0.5 missed both pools. |
| AZ7-07 | 1/1 | Q1 1/1 | §14.5.1-1.9 ranked first in every stage. Extracted historical §14.5.6 ranked second in the final list. The observed error was an eligibility omission despite direct passage presence. |

Mean draft Recall@5 remains **38.27%**. Passage presence by part above does not measure executed attribution. Decomposition was disabled, and replay's executed part coverage and attribution stayed at zero across the four multipart cases.

## Recommended next changes, ranked by evidence

1. Review the draft AZ7-04 label with a domain expert. Add §7.3 for the conditional employer obligation if approved, keep the remedy procedure unresolved to the extent sources do not establish it, and rescore only in a separately versioned draft.
2. Evaluate a claim-level scope and completeness gate before enabling FULL. Require the answer to name the insurance regime and preserve eligibility and exceptions. Use the wrong-regime AZ7-04 citation, incompatible AZ7-06 payment instructions, and AZ7-07 qualifiers as regression fixtures after review.
3. Capture supported finish and reasoning-token metadata on a controlled rerun. Test prompt and budget changes independently on AZ7-03 while holding the archived ranking fixed. Keep the observed 429s separate from the token-cap failure and preserve bounded retries.
4. Measure decomposition and attribution on the unchanged archive before testing ranking changes. Use the candidate misses and below-cutoff evidence above to define that experiment. Review extraction of struck-through language so historical text is visibly distinguished.

## Verification

The audit exporter checks the capture and draft against the frozen snapshot and resolves final markers to passage IDs. It performs no provider calls. The full regression suite ran **169 tests, all passing**, including the review dashboard and SQLite cleanup. The original 108-query benchmark, its four legacy fixture hashes, the seven-case draft, production settings and Qdrant data were preserved.
