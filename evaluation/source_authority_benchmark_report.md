# Source authority and temporal applicability benchmark v1

The offline benchmark measures the existing authority layer. The [pre-implementation record](source_authority_benchmark_baseline.md) documents the boundaries between source classification, temporal applicability, potential conflict detection, evidence eligibility and the separate hardened verifier. This work did not change those behaviors.

## Fixture inventory

There are **39 fixtures**, including **15 source-derived** and **24 synthetic engineering** fixtures. The locked layout keeps **15 baseline**, **11 development** and **13 stress** fixtures in separate files. The categories are **8 authority**, **14 temporal**, **8 conflict**, **4 eligibility** and **5 metamorphic reference or ranking invariants**. The clock invariant is counted under temporal. Shared source passages anchor distinct scenarios, and the benchmark does not train a model or tune production rules on any split.

The exact passage extract in sources.json includes original indexed text, stable IDs, page where available, article, clause and the available document and chunk metadata. It was checked against the complete frozen export. Each fixture names its passages, provenance category, rationale and expert-review status. The separate expected.json file supplies metric assertions, checksums, failure classes and explanations. Synthetic overlays represent test assumptions and do not change or purport to establish Azerbaijani law. In particular, the other-normative and standalone methodological categories have schema controls with no independently verified examples of those classes in this frozen corpus.

## Measured results

The rows count assertions. Multiple assertions can come from one fixture. The conflict false-positive rate counts erroneous flags, where a lower rate is better. The full JSON separates all metrics by fixture category, split and source origin. A group with an empty denominator is reported as unavailable.

| Metric | Numerator / denominator | Percentage | Failed fixture IDs |
| --- | ---: | ---: | --- |
| Source classification accuracy | 13/13 | 100% | — |
| Normative eligibility accuracy | 20/20 | 100% | — |
| Context preservation | 7/7 | 100% | — |
| Temporal relationship accuracy | 16/17 | 94.12% | T11 |
| Unknown-date and provenance preservation | 12/12 | 100% | — |
| Amendment relationship accuracy | 4/6 | 66.67% | T13 |
| Repeal relationship accuracy | 1/1 | 100% | — |
| Conflict detection recall | 4/4 | 100% | — |
| Conflict false-positive rate | 1/5 | 20% | C03 |
| Scope distinction accuracy | 10/11 | 90.91% | C03 |
| Exact reference preservation | 294/294 | 100% | — |
| Expert-review escalation and record completeness | 8/9 | 88.89% | C06 |

### Failed fixtures

| ID | Failure class | Expected and observed behavior |
| --- | --- | --- |
| T11 | Mechanical | The synthetic event falls inside the asserted contract, and the claim is filed after termination. The layer correctly reports the event in term but has no claim-filing-date field, so it cannot preserve or separately analyze that fact. The benchmark makes no determination about the claim's timeliness. |
| T13 | Metadata-related | The medical insurance passages at §§16-4.5 and 16-4.6 expressly contain separate commencement dates of 2024-01-01 and 2020-01-01, with stated exceptions. The current catalog has no provision-level anchors for either, so both effective dates are absent from the output. Applicability to a particular question still requires matching the named provisions and exceptions. |
| C03 | Metadata-related | Synthetic provisions use disjoint effective and repeal dates without rule-period fields. Conflict detection compares rule-period windows and raises a potential conflict despite the supplied disjoint periods. It leaves resolution null. This accounts for the conflict false positive and the scope distinction failure. |
| C06 | Metadata-related | With incomplete effective-period inputs, the synthetic conflict correctly preserves both references and is escalated. The record lacks the expected explicit missing-information list. It does preserve the raw date fields and does not choose a winner. |

## Integration and invariants

Four deterministic cases run the actual /ask route, evidence assembly, prompt packing, legal claim binding and the semantic judge handoff. Only the already-ranked retrieval handoff and the model and judge responses are stubbed. The ranking, passage IDs and document references stayed intact in both modes. The benchmark does not claim to rerun embedding, BGE inference, or Qdrant search.

- **E01** retained the eligible occupational norm and the textbook excerpt. Both modes reached the stubbed judge with the normative citation and returned its original reference.
- **E02 and E03** kept the textbook and news respectively in the enabled prompt, with context-only roles. Enabled mode excluded their proposed citations from legal binding and the judge. The disabled control returned a partial response with the intentionally optimistic judge stub. That control tests eligibility behavior and supplies no evidence of actual legal support.
- **E04** returned insufficient in both modes when the judge stub rejected the draft. Eligibility alone did not promote an unsupported claim.
- Renaming files, reversing rank order, perturbing candidate scores, removing contextual evidence and changing the wall clock did not change the authority of the applicable normative source or overwrite the asserted historical dates. The before/after hardened verifier check verifies the separate integration boundary.

## Metadata and expert review

The checked source evidence includes occupational §11.8, Cabinet Decision 156's repeal directive for Decision 196 annex item 1.1.1, the 1618-VQD adoption, publication and commencement distinctions, and §§14-1.1.1.1–14-1.1.1.2's documented subsidy intervals. Historical §14.5.6 relies on the earlier PDF strike-through audit. Its effective repeal date remains unknown. Source publication, adoption, effective date and case-event dates stayed separate. There is no independently verified current effective interval for the area-rate provision in T01. The lesser precision of the textbook's publication year and missing issuer or adoption values remain visible as unknown.

The fixture flags mark **14 cases** for expert review. **T01, T03, T05 and T07** concern currency, retroactivity or repeal commencement. **T08–T11** concern incomplete event records or the effect of filing after termination. **T13** concerns scope and exceptions of staged commencement. **C01, C03, C05, C06 and C07** concern overlapping or allegedly disjoint scopes, general against special provisions, missing dates, or the transition boundary. Synthetic conflict cases test technical behavior and assert no actual conflict between the cited documents. No case resolves a contradiction by publication date, hierarchy or ranking score.

## Files, reproduction and protection

New files are the [runner](benchmark_source_authority.py), [pre-implementation record](source_authority_benchmark_baseline.md), the [baseline](source_authority_benchmark_v1/baseline.json), [development](source_authority_benchmark_v1/development.json), [stress](source_authority_benchmark_v1/stress.json), [exact sources](source_authority_benchmark_v1/sources.json), [expected results](source_authority_benchmark_v1/expected.json), this report, and the [benchmark tests](../tests/test_benchmark_source_authority.py). No existing source, fixture, verifier, prompt, model configuration or production file was modified.

```powershell
python -m evaluation.benchmark_source_authority --snapshot .venv/eval_corpus_snapshot.json --output .venv/authority-replay.json --failures-output .venv/authority-replay-failures.json
python -m evaluation.compare_legal_verifiers --snapshot .venv/eval_corpus_snapshot.json --output .venv/verifier-comparison-replay.json
python -B -m unittest discover -s tests
```

The benchmark can also run from the checked-in extracts without the snapshot. The result then marks full-snapshot verification as unavailable. The program performs no external model or API calls. A second run against the snapshot produced byte-identical results. All **195 tests passed**, including four new benchmark tests. The 43-fixture verifier benchmark was executed before and after, with **byte-identical output** and SHA-256 **b323b62c159869b6b5464e658c5e70a467c2d48491b75c48f9936a61c84506f1**. The 108-query fixture and its four locked hashes, seven-case draft, proposed v2, and the 43 fixture expectations were preserved. Qdrant was not accessed or mutated. The layer remains opt-in through LEGAL_SOURCE_AUTHORITY=1.

The benchmark establishes only the observed engineering behavior. It has no legal expert validation, uses a small anchored corpus, and does not establish legal currency, conflict resolution or semantic faithfulness of live model answers.
