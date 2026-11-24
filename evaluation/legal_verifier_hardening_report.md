# Legal evidence verifier v2

Version 2 is an opt-in offline gate. It preserves the v1 verifier and the original 32-case benchmark, and adds an 11-case adversarial extension. Each fixture ran against both versions with the same claim, passage, and assessment inputs. The comparison also verified all fixture passages against the frozen indexed snapshot. No retrieval, provider, or production service was invoked.

## Validation and trust model

- The untrusted assessment must match the captured answer hash, enumerate the exact cited passage IDs for each claim, and match the packed context. Missing, substituted, or ambiguous references fail closed. The assessment's support label is recorded for audit. It never creates an independent witness.
- Citation checks bind the marker to packed text, stable passage and document identifiers, available article, clause and page metadata, and the recorded version when present. A missing page is valid for an unpaginated source. The audit stores the exact indexed and packed text, their metadata, the supplied assessment provenance, the witness, and the verifier version.
- Independent support uses a separate technical witness catalog. A witness ties a bounded proposition or explicitly reviewed paraphrase to exact passage IDs, passage hashes, document IDs and verbatim anchors. Deterministic exclusion rules cover the identified wrong regimes, beneficiaries, deadlines, and contract-period claims. Verified statuses distinguish supported, partially supported, unsupported, contradictory, and unverified.
- Date checks use distinct provenance-bearing records for contract start, contract termination, insured event, and the requested reference date when relevant. A dated effectiveness witness also binds the effective date to the cited amendment note. Missing dates, unresolved boundary times, conflicting records, and an event demonstrably outside the contract interval have different reason codes. The comparison uses hypothetical event-date records. It certifies no actual contract facts or current legal effect.
- FULL requires every material claim and all required passage coverage to pass under an independently supplied completeness profile, with no unresolved conflict. PARTIAL requires an independently bounded fragment for at least one nonconflicting part. The returned fragment is distinct from the original answer. The response is withheld when there is no independently supported fragment. NOT_FOUND requires a separate, independently supplied absence assessment for the relevant corpus or fixture question.

The policy and applicability profile are trusted configuration inputs and must be kept outside the model's output channel. The report does not imply that provenance IDs alone authenticate new case records. The caller must verify those records before supplying them.

## Old-versus-new results

| Metric | Original 32, v1 → v2 | Adversarial 11, v1 → v2 | Combined, v1 → v2 |
| --- | ---: | ---: | ---: |
| False acceptance as FULL | 12/26 → 0/26 | 5/10 → 0/10 | 17/36 → 0/36 |
| False rejection of expected FULL | 1/6 → 0/6 | 1/1 → 0/1 | 2/7 → 0/7 |
| Scope issue detection | 6/17 → 17/17 | 2/6 → 6/6 | 8/23 → 23/23 |
| Missing-condition detection | 4/4 → 4/4 | 1/1 → 1/1 | 5/5 → 5/5 |
| Citation binding accuracy | 31/32 → 32/32 | 9/11 → 11/11 | 40/43 → 43/43 |
| Exact mode consistency | 17/32 → 31/32 | 3/11 → 11/11 | 20/43 → 42/43 |

Scope issue detection includes missing applicability evidence, a distinct outcome from a proven contradiction. The one remaining exact-mode disagreement is **M04**. The frozen rubric expects PARTIAL. V2 withholds because §11.8 protects the beneficiary, while the submitted claim asserts entitlement for any person. The original expectation stays in the comparison. The extension's V208 explicitly tests withholding for this scenario.

## Changed decisions and evidence

The machine-readable comparison records exact passage IDs, indexed and packed text, recorded document and provision metadata, date evidence and per-claim rationale for every case. The following groups account for every changed mode.

| Cases | Old → hardened | Evidence and reason |
| --- | --- | --- |
| M04, V208 | PARTIAL → withheld | Occupational §11.8, PDF p. 10, limits the obligation to the beneficiary. The assertion about any person supplies no independently safe entitlement. |
| M08 | PARTIAL → withheld | Occupational §11.8, p. 10, expressly limits the preserved obligation to events while the contract was in force. The claim specifies an event after termination. |
| M15, V202 | PARTIAL → FULL | Social insurance §14.6, p. 11, explicitly excludes §14.5.1-1. Both audited paraphrases preserve the exception, monthly base, ordinary due date and non-cash payment. |
| M16, V203 | withheld → PARTIAL | Indexed Trend summary `Trend-4197840-avtomobil-sigortasi-2026.txt` is unpaginated. Its exact text and stable IDs support the limited claim that it is a news summary. |
| S01, V201 | FULL → withheld | Occupational §11.8 supplies no 30-day deadline. A complete assessment label supplies no legal evidence. |
| S02 | FULL → withheld | Social insurance §14.5.6, pp. 10–11, is visibly struck out in the earlier PDF audit. Neither the extracted wording nor the missing effective-date records proves present applicability. |
| S03 | FULL → withheld | §14.5.1-1.9, p. 10, supplies statutory wording but no independently verified effective period for the fixture's requested date. |
| S04, S05 | FULL → withheld | *Sığorta işi*, p. 82, is academic material. It supplies no compulsory legal rule. Adding occupational §11.8 does not extend that provision to all contracts. |
| S06 | FULL → withheld | Cabinet Resolution No. 156, p. 3, changes accident investigation documentation. Occupational §7.3, p. 7, is the separate source for conditional liability. |
| S07, S08 | FULL → withheld | Amendment note in *Sığorta fəaliyyəti haqqında*, p. 87, distinguishes 27 June 2019 adoption, 21 August 2019 publication and 1 January 2020 effectiveness. The fixture reference dates precede effectiveness. |
| S09, S10, V205 | FULL → withheld | Occupational §11.8, p. 10. The supplied event dates are after termination or before the contract starts. The in-term positive control S14 remains FULL. |
| S11 | FULL → withheld | Occupational §§11.8 and 11.9, p. 10, distinguish ordinary termination from invalidity at inception. The submitted claim treats those circumstances alike. |
| S12 | FULL → withheld | Social insurance §14.6, p. 11, uses the next month's 15th for the applicable class. The claim asserts the 20th. |
| V204, V206, V211 | FULL → withheld | Against occupational §11.8, the fixture respectively lacks an event date, contains conflicting event dates, or supplies a boundary date without enough timing evidence. |

Other category checks include wrong insurance type (V207, still withheld), a substituted assessment passage (V209, rejected), and missing assessment references (V210, v2 rejects explicitly where v1 raises an error). Withheld is a distinct decision from NOT_FOUND.

## Limits and reproduction

Binding, normalization, reproducible catalogue matching, date comparison, provenance joins, and mode gating are deterministic. The witness propositions, equivalence of the covered paraphrases, scope assigned to a particular law, and sufficient conditions for whole-claim support are documented technical readings, without expert legal approval. Unseen wording can be conservatively withheld. The benchmark and witness catalog were developed together, so the observed rates are regression results and do not estimate field performance. Legal experts still need to review broader paraphrases, legal hierarchy and conflict resolution, temporal boundary and transitional rules, evidence of applicability at a requested date, and whether particular claim procedures are fully established.

```powershell
python -m evaluation.compare_legal_verifiers --snapshot .venv/eval_corpus_snapshot.json --output .venv/legal-verifier-comparison-v2-replay.json
python -B -m unittest discover -s tests
```

All **186 regression tests passed**, including five new hardened-verifier tests and the review-dashboard workflow. A second comparison produced byte-identical JSON. The original 32-case corpus, original seven-case draft, proposed v2 labels, 108-query benchmark and its four locked hashes were preserved. The only change to the original benchmark runner is an optional verifier callback that defaults to v1.
