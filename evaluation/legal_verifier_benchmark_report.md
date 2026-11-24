# Legal evidence verifier validation benchmark v1

The opt-in benchmark exercises the existing offline verifier without changing it. It contains 32 isolated cases using 21 exact indexed passages from eight documents. The runner verified the passage text, IDs, documents, provisions and pages against the frozen snapshot. Claims and event dates used to challenge the verifier are test inputs. The source passages are unchanged.

The benchmark separates **18 mechanical controls**, which supply the relevant assessment or rule, from **14 assumption-stress cases**, which deliberately supply optimistic assessments and omit an enforcement rule. Two stress cases are positive temporal comparisons. The expected outcome is specified independently of the inputs passed to the verifier. These fixtures test behavior and expose trust boundaries. They are neither a representative rate estimate nor expert legal labels.

## Results

| Metric | Mechanical controls | Assumption stress | Combined |
| --- | ---: | ---: | ---: |
| False acceptance as FULL | 0/14 | 12/12 | 12/26 (46.15%) |
| False rejection of expected FULL | 1/4 | 0/2 | 1/6 (16.67%) |
| Scope violation detection | 6/6 | 0/11 | 6/17 (35.29%) |
| Missing-condition detection | 4/4 | Unavailable | 4/4 (100%) |
| Citation binding accuracy | 17/18 | 14/14 | 31/32 (96.88%) |
| Exact mode consistency | 15/18 | 2/14 | 17/32 (53.13%) |

Citation accuracy counts case-level agreement on whether all bindings are valid. Missing-condition detection counts the four fixtures explicitly labeled for that metric. Scope detection counts any emitted scope violation, including false positives tracked separately in the detailed result. A false acceptance is a FULL decision when the fixture disallows FULL. Exact mode consistency distinguishes withholding a decision from NOT_FOUND.

| Expected mode | FULL | PARTIAL | NOT_FOUND | Withheld |
| --- | ---: | ---: | ---: | ---: |
| FULL | 5 | 1 | 0 | 0 |
| PARTIAL | 0 | 4 | 0 | 1 |
| NOT_FOUND | 0 | 0 | 1 | 0 |
| Withheld | 12 | 1 | 0 | 7 |

### Where the verifier succeeded

- The exact cited positive control passed. The verifier rejected a substituted packed passage ID, an incorrect version ID, and a marker absent from the packed context.
- A valid citation with a supplied unsupported-claim assessment could not become FULL. A supplied absence assessment yielded NOT_FOUND. A supplied conflict prevented FULL without deciding legal priority.
- Explicit document allowlists blocked the medical-to-occupational substitution. Configured phrase rules flagged the wrong beneficiary, omitted owner and family-farm qualifications, omitted exceptions, and an incorrect deadline. The scoped general and special payment rules passed the positive control.

### False positives and false negatives

- **M15, false rejection and false scope flag.** The social insurance exception was expressed as `kənarda qalır`. A literal `istisna` pattern missed the paraphrase and downgraded the expected FULL to PARTIAL.
- **M16, false citation rejection.** The exact explanatory source has no page number. The verifier compares the absent packed page with the string representation of the null indexed page and rejects the binding. Expected PARTIAL was withheld.
- **M08, unsafe PARTIAL.** The claim describes an event after termination. The rule detected the missing in-term condition, but optimistic supplied support let the verifier infer usable content and emit PARTIAL. The benchmark expected withholding because the specific asserted outcome has no qualifying supported fragment.
- **S01–S12, false FULL acceptances.** When the supplied assessment was deliberately optimistic, the verifier did not independently detect unsupported claims, historical text used as current, missing date authority, academic or mixed-authority misuse, publication or adoption presented as effectiveness, an event before or after the contract period, termination conflated with invalidity from inception, or a wrong deadline with no configured textual check. Those failures are specific to the stress inputs. Production rates cannot be estimated from them.

## Source authority

The corpus carries a document-ID classification catalog with exact supporting anchors. Four sources are statutes, one is Cabinet Resolution No. 156, one is the indexed *Sığorta işi* textbook, one is an explanatory news summary, and one is other news reporting. Classification concerns source genre. Normative weight and applicability to a particular proposition are separate questions. An undocumented source returns unclassified. The explanatory news fixture does not represent official methodology.

The snapshot includes law names, some act numbers and adoption dates, and document IDs. This frozen export does not provide explicit version IDs for the relevant historical and dated passages. The production metadata helpers can carry legal type and date fields when supplied. The benchmark catalog is separate and the existing offline gate does not consume it. The textbook approval passage is academic provenance. The government resolution is authoritative for what it actually amends. The mixed resolution/statute fixture shows that the verifier currently accepts a claim attributing a statutory liability rule to an amendment about accident-investigation documentation when its assessment is optimistic.

## Temporal scope

The amendment note for 1618-VQD explicitly distinguishes **2019-06-27 adoption**, **2019-08-21 publication**, and **2020-01-01 effectiveness** of the additions identified in the note. The benchmark separately supplies the question's requested reference date. It checks an accurate claim, a claim using publication as effectiveness, and a claim using adoption as effectiveness. The current gate accepts all three under the stress assessment because it carries date context through without comparing it.

The contract cases supply separate hypothetical start, termination, event and reference dates. Identical claim wording received FULL with the event before, during, or after the contract. The dates are inputs to the fixtures, separate from the source text. No boundary-day convention is tested. Historical §14.5.6 is visibly struck through in the earlier PDF audit, but the exact indexed passage retains its text. The strike-through does not establish a repeal date. The paired land-use case also tests that the current applicability of another provision cannot be certified from a proposed reference date and missing effective-period evidence. No effective dates were inferred from filenames or years.

## Expert-review boundary and unresolved risks

Marker identity, fixture stability, arithmetic, explicit rule matching, and propagation of supplied judgments are mechanically testable. Determining whether a paraphrase preserves a legal exception, whether two provisions conflict in the same factual and temporal scope, what a resolution can establish, and whether an amendment or transitional rule governs the question requires reviewed authority and legal interpretation. The benchmark intentionally includes a supplied conflict control using different legal situations. It does not establish a real conflict between the cited clauses.

The principal unresolved risk is reliance on an optimistic assessment to mark a claim complete. Without independent support and applicability evidence, the current gate may produce FULL even with exact citations. Literal condition matching also creates false positives, and missing scope can be mistaken for a recoverable legal fragment. No result in this benchmark establishes legal correctness or expert certification.

## Reproduce

```powershell
python -m evaluation.benchmark_legal_verifier --snapshot .venv/eval_corpus_snapshot.json --output .venv/legal-verifier-benchmark-v1-replay.json
python -B -m unittest discover -s tests
```

The fixture includes exact excerpts and their checksum, so replay also works without the local snapshot. Omitting the snapshot skips comparison against the full index and marks that check as unavailable in the result. All **181 regression tests passed**, including five new benchmark tests and the review-dashboard workflow. The original draft, separate proposed v2, 108-query benchmark, four locked fixture hashes, production settings, retrieval components and Qdrant data were preserved.
