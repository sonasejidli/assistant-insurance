# Insurance answer quality draft v1.0.0

The 25 Azerbaijani questions are a separate engineering draft. They have source-verified references and author-drafted expected answers. Expert-approved labels total **0/25**. The 108-query retrieval benchmark, seven-case draft and proposed v2, frozen 15-case E2E benchmark, and verified release fixtures retain their original purposes and files.

## Corpus and categories

The frozen index contains **12 documents and 4,405 passages**. It covers seven laws, two Cabinet resolutions, one textbook, and two news summaries. The PDF inventory includes one additional scanned file whose 93 pages produced no text in the existing extractor. Its pages are outside this indexed corpus audit. The validator checks the existing ordered snapshot digest if a snapshot is supplied. Local extraction on Windows sorts document names differently, so it also checks an order-independent digest of all passage IDs and exact text. Both extractions matched all 4,405 passage IDs and texts. For each referenced document, the actual file bytes match the version digest in the existing authority catalog.

| Category | Cases | Expected modes | Distinct evidence references | Essential claims |
|---|---:|---|---:|---:|
| Simple | 5 | 5 FULL | 5 | 5 |
| Conditions and exceptions | 5 | 5 FULL | 5 | 5 |
| Multipart | 5 | 4 FULL, 1 PARTIAL | 10 | 10 |
| Multi-document | 5 | 5 FULL | 10 | 10 |
| Insufficient evidence | 5 | 5 NOT_FOUND | 6 contextual or boundary references | 0 |

The 11 multipart sub-questions break down into **10 FULL and 1 NOT_FOUND**. AQ-MULTIPART-002 requires two supported legal statements and abstention on the hypothetical family's actual payment date.

**19 source-derived cases** ask directly about indexed wording. **Six synthetic scenarios** introduce requests for private records that are unavailable in the snapshot. They comprise the five abstention cases and the partial multipart case. Their source references are real. No synthetic statute, actual personal record, amount, or filing outcome is asserted.

| Indexed source | Unique references |
|---|---:|
| Sığorta fəaliyyəti haqqında | 6 |
| İcbari sığortalar haqqında | 8 |
| Occupational compulsory insurance law | 2 |
| Auditor professional liability law | 4 |
| Military personnel personal insurance law | 3 |
| Sosial sığorta haqqında | 3 |
| Tibbi sığorta haqqında | 8 |
| Cabinet Resolution NK-2023-156 | 1 |
| Trend motor-insurance summary | 1 |

There are 34 statute references, one resolution reference and one contextual news reference across nine documents. The news passage helps identify the requested coefficient in AQ-ABSTENTION-005. It supplies no normative claim or personalized rating. Textbooks were reviewed in the inventory and are unnecessary for these expected legal claims.

## Schema and scoring limits

The versioned JSON has a passage registry and case records using the existing FULL/PARTIAL/NOT_FOUND names. An ID such as `AQ-MULTIPART-002` is stable. Required claims carry exact passage IDs, a part assignment when applicable, essential versus supplementary status, conditions and exceptions. The validator requires the draft answer to be composed entirely of the mapped claims and any mapped limitation. Document IDs, parent passage IDs, exact indexed text, articles, clauses, article titles, available sections and pages sit in the registry. Optional fields retain null when the index provides no value. Source type and source-file version hashes are verified against the authority catalog and files.

`supporting_passages` maps to claims. `related_passages` supplies context or justifies the boundary of an abstention; it is excluded from gold-relevance denominators. Dates distinguish indexed-text statements from event-date or current-law applicability. AQ-CONDITION-005 records the seven-year period literally stated in §14.4 and leaves successor or current rates unresolved. AQ-MULTIDOC-003 states the text of the resolution's amendment and leaves its effective date unasserted.

The five NOT_FOUND questions each ask for an individual's actual contract value, transaction, coefficient, or administrative record. The inventory contains published laws, resolutions, a textbook and news, and the relevant provisions explain where the fact would come from. There are no corresponding personal contracts, ledgers, rating records, or application files. A retrieval miss would leave this determination unchanged.

### Review queue

All 25 cases are pending review. Three have explicit interpretation flags:

- **AQ-MULTIDOC-001** uses a statutory fallback for a definition. Review the interplay with the referenced Civil Code.
- **AQ-MULTIDOC-003** combines the statutory motor liability obligation and the inspection amendment. Review operative wording and dates before using the case for current applicability or real admission decisions.
- **AQ-MULTIDOC-005** compares a general special-law exception and a specific auditor provision. Review any proposed precedence or conflict inference.

## Proposed split

Use **10 dev cases** and **15 held-out test cases** from this draft. In each category, IDs 001 and 002 are dev, and 003 through 005 are proposed test. The proposed training split is empty. Freeze the test revision before model or policy changes and group future variants with their original questions. The validator rejects shared source provisions across these splits, exact normalized overlap with the 108-, seven-, and 15-case questions, and cross-split token-set Jaccard similarity of 0.80 or greater. This combines a lexical check with an authored scope review. Expert review can still identify closer semantic duplicates.

## Metric specification

Report numerator, denominator and unavailable counts separately. The tables below specify evaluation rules. This phase supplies draft labels, so it reports validation counts and existing regression results. Legal performance values require reviewed annotations of answer outputs and the relevant expected labels.

| Metric | Numerator | Denominator and eligibility |
|---|---|---|
| Answer accuracy | Cases with all essential conclusions correct, preserved material qualifications, and zero materially incorrect claims | Reviewed FULL/PARTIAL cases with usable response capture. Score an unjustified abstention as incorrect. Report provider/recovery failures separately. |
| Citation accuracy | Emitted citation occurrences that resolve to the exact document and passage and support the attached claim | All emitted citation occurrences with recorded binding and reviewed claim relation. Separately report binding-only numerator over all checkable occurrences, and report absent citations through completeness. |
| Claim-level evidence support | Material emitted legal claims supported within cited personal, material, and temporal scope | All reviewed emitted legal claims with an inspectable response and evidence. Mark a claim with missing supporting citations unsupported when a binding is required. Report unsupported, contradictory, partial or unreviewed counts separately. |
| Completeness | Essential expected claims addressed with their conditions and exceptions | All reviewed essential claims in FULL/PARTIAL cases. A missing response or omission contributes zero. The unresolved part of a PARTIAL case is evaluated under disclosure, outside legal-claim coverage. |
| Faithfulness | Material emitted factual or legal claims entailed by the exact generator input evidence | All reviewed emitted material claims with the generator's packed evidence captured. This measure evaluates grounding in the input. Source authority and legal accuracy remain separate. |
| Abstention accuracy | Cases that withhold the unestablished conclusion and identify the expected missing evidence | All reviewed cases or explicitly unresolved parts with a NOT_FOUND expectation. Accept the existing safe null-mode response only when it communicates the relevant gap. A provider outage alone is insufficient. Report false abstentions against reviewed answerable cases separately. |
| Multipart accuracy | Parts that meet their expected outcome, supply the necessary supported claims, and preserve any unresolved limitation | All reviewed parts of captured multipart questions. Also report whole-case numerator requiring every part to pass, over reviewed multipart cases. |
| Existing retrieval metrics | Use the existing retrieval scorer for Recall@5/10 and, where ranks and labels support them, MRR@10 and nDCG@10 | Use mapped relevant parent IDs from essential claims and eligible rank captures. Exclude abstention-only cases lacking positive references. Report ranking stages and missing ranks separately. Use a binary relevance grade for mapped essential references until graded judgments are reviewed. |

Keep citation binding, semantic citation support, unsupported claims and case completeness visible independently. Exclude denominators of zero from percentage reporting. A valid binding on an unsupported proposition remains a failed support check. Keep legal expert adjudication distinct from mechanical validation and user-response availability.

## Validate

```powershell
python -m evaluation.validate_answer_quality_draft
python -m evaluation.validate_answer_quality_draft --snapshot .venv/eval_corpus_snapshot.json
python -m unittest discover -s tests
```

Files added are `evaluation/answer_quality_draft_v1.json`, `evaluation/validate_answer_quality_draft.py`, this report, and `tests/test_answer_quality_draft.py`. No production, Qdrant, historical expected output, or benchmark data changes are part of this draft. No model or provider call is needed.

## Regression and preservation

The final draft passed validation against the frozen snapshot and independently extracted local sources. The full regression suite passed **237/237** tests, including six new draft validation tests. All **56/56** adversarial fixtures passed with zero unsupported releases, invalid-citation releases, or fail-open verifier errors. The full **108/108** retrieval run matched all seven preceding quality profiles. The lexical ranking hash remained `0e201d2ff20e9d1b97e4f7a9da7643c07600b1ee562620ec426193919c11723e`. All four locked fixture hashes matched. The 43-fixture verifier, 39- and 53-fixture authority/temporal reports, seven-case draft report, 15-case E2E replay, and 15-case release replay were byte-identical. The seven-case proposed v2 labels and historical input files matched their pre-change hashes.
