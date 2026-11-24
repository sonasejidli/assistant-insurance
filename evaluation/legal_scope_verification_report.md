# Legal evidence verification

The opt-in offline verifier evaluates the frozen captured run `9d5817e013db4ad0a930be4f0445b015`. It emits a decision for review and does not modify the captured answer, serve a revised answer, or invoke a model. Production generation, retrieval, settings and Qdrant were unchanged.

## Three independent results

1. **Citation validity** compares the marker, passage ID, packed text and locator with the frozen corpus. It checks the recorded version ID when supplied. The observed legacy prompts omit explicit source versions, so all twelve bindings were verified to the frozen document fingerprint only. This identifies the indexed edition in this snapshot, without establishing effective law on another date.
2. **Claim support** uses technical assessments tied to the exact raw answer hash and exact cited passage IDs. The record preserves each claim line and its supporting or insufficient references. An unsupported assertion can retain a valid marker. The classifications are complete, partial, contradictory, absent or unverified. An unreviewed or changed answer receives no verified mode.
3. **Legal scope** reports the relevant regime, group, temporal applicability, required conditions and exceptions. Phrase checks flag missing scope and group rules or wrong-regime citations. They do not establish semantic entailment by themselves. The assessments document which parts of each line the source actually supports.

Completeness is checked per draft sub-question against recorded claim attribution, necessary passages, citation and scope checks, and explicit completeness assessment. FULL requires every part to pass. PARTIAL can indicate supported content alongside unresolved conditions, and does not approve the original wording. The output tracks claims safe under the applied checks separately from claims with only usable fragments. NOT_FOUND requires an explicit reviewed absence assessment. Missing retrieval, missing indexed evidence, insufficient retrieved evidence, conflicting evidence, scope exclusions and failed generation are separate availability states. No transport or validation recovery is treated as a legal answer.

## Captured result

All 12 distinct citation bindings passed. The five answers had 14 assessed claim lines, with six complete, six partial, one contradictory and one absent support assessment. Eight lines raised scope violations. The land rates had complete textual support and still failed the independent eligibility check. The two recovery cases remain without a verified mode.

| Case | Observed → verification outcome | Finding |
| --- | --- | --- |
| AZ7-01 | PARTIAL → PARTIAL | §81.4 addresses life-insurance reserves and §119.3 addresses expenses and secured claims. General creditor priority and the particular payer remain incompletely supported. |
| AZ7-02 | FULL → PARTIAL | Occupational §11.8 is the correct passage for its own regime and beneficiary. Its timing condition survives, while the answer generalizes the termination rule to an unspecified insurance contract. |
| AZ7-04 | FULL → PARTIAL | Occupational §7.3 supports the obligated policyholder's conditional liability. The medical §15-2.2.1 citation does not establish an occupational duty, and the claim procedure remains unresolved. |
| AZ7-06 | PARTIAL → PARTIAL | Compulsory medical §15-11.4 distinguishes the ordinary deadline from special receipt and transport-sign triggers. The answer generalized the deadline to expressly excepted groups. Its limited supported content requires revised scope before use. |
| AZ7-07 | FULL → PARTIAL | The rate bands match social insurance §14.5.1-1.9. The answer generalizes eligibility and omits ownership, family-farm membership and working-age conditions. |

## Proposed labels, revision 2

The proposed delta binds to the original draft hash. It records the previous AZ7-04 evidence labels, exact §7.3 text and locator, and the reason for adding it to Q2. The proposal changes Q2 from NOT_FOUND to PARTIAL and retains overall PARTIAL. The specialized remedy procedure and substitute-payer question remain open. The delta has no expert approval and was not merged.

On the same ordered top-five rankings, AZ7-04 rises from **0/6** to **1/7**. Aggregate draft Recall@5 remains **38.27%**. The separate proposed-label score is **40.31%**, an increase of **2.04 percentage points from the label change**. Rankings did not change.

## Reproduce and regress

```powershell
python -m evaluation.verify_legal_scope --audit .venv/rag-claim-audit-input.json --snapshot .venv/eval_corpus_snapshot.json --output .venv/legal-scope-verification-v1.json
python -B -m unittest discover -s tests
```

All **176 tests passed** locally, including seven new checks for the cited-but-unsupported assertion, wrong regime, packed version mismatch, missing exceptions, group deadlines, eligibility, scoped PARTIAL, and preservation of the frozen labels with newly proposed evidence. The captured-run check ran against the local artifacts. The 108-query benchmark and its four locked fixture hashes verified. This technical audit and its rule vocabulary apply to the reviewed cohort. Extending verification to new answers requires further answer- and passage-bound assessments. The findings have no legal expert validation.
