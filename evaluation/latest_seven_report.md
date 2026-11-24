# Seven Azerbaijani RAG queries

The seven original questions are preserved in `latest_seven_dataset.json`. The original answers, explicit answer modes, citations and request traces were unavailable for all seven. The open `.venv/review-browser-run-04/report.json` records review workflow tests using E2E fixtures. An exact-text search of 130 evaluation, test, corpus and local run files checked both UTF-8 and JSON-escaped forms and found no matching run records. The local API stdout log was empty and stderr contained startup information. No replay was used as a substitute for observation.

Each case has `observed: null` and `error_labels: null`. These values represent missing observations and unclassified failures. Case-level source notes describe what to check once the answers are recovered. Evidence and modes are draft corpus judgments pending expert review. No reference is represented as verified current law.

## Evidence and answer modes

The indexed source was the saved API export `.venv/eval_corpus_snapshot.json`, with 4,405 passages and ordered ID/text digest `3f88380b81d12e9d1e18831e6eb517caa9e54c02c504b0b73aad0e4e42162dec`. Each evidence entry includes the exact indexed passage, original text when available, law and file identifiers, article, clause, one-based PDF page and zero-based chunk ordinal. Related entries are excluded from scoring. Article-only provisions have a null clause. For Decision No. 156, the indexed metadata has no article or clause and the decision paragraphs are identified in the passage text.

| Case | Expected modes | Verified direct evidence | Source limits and answer checks |
| --- | --- | --- | --- |
| AZ7-01 Insurer insolvency | PARTIAL | **İcbari sığortalar haqqında**, `sığorta 2.pdf`, §§ 32.1, 32.1.1, 33.1, p. 21. **Occupational compulsory insurance law**, `sığorta 3.pdf`, § 18.12, p. 14. **Sığorta fəaliyyəti haqqında**, `sığorta 1.pdf`, § 112.2, p. 76 and §§ 119.1, 119.1.1, 119.1.2, 119.1.3, 119.4, p. 79. | The Bureau route is conditional. Check contractual transfer and liquidation as distinct cases. §§ 115.4, 116.1, 118.3 and 118.4 establish procedure, with no universal payout guarantee. |
| AZ7-02 Prior event after termination | PARTIAL | Occupational law § 11.8, p. 10. | The express rule covers an insured event during the contract's period in force. § 2.0.12 (p. 2) supplies the occupational definition. § 11.9 (p. 10) addresses invalidity from inception. The question leaves the contract class and kind of termination unspecified. |
| AZ7-03 Insurer and employer liability | FULL / FULL → FULL | Insurance activity law § 124.1, p. 80. Occupational law Art. 23, p. 15, § 2.0.4, p. 2, and § 4.0.1, p. 4. | The liability categories are supported for the insurer and for a covered employer acting as policyholder. Contracting and payout duties in §§ 7.2.1 and 9.2.2 do not establish specific penalties. A particular sanction depends on the applicable code and underlying violation. |
| AZ7-04 Employer did not contract | FULL / NOT_FOUND → PARTIAL | Occupational law § 3.1.1, p. 3, §§ 4.0 and 4.0.1, p. 4, § 6.1.3, p. 5, § 7.2.1, p. 6, and Art. 22, p. 15. | The employer duty, worker information right and dispute route including court are supported. A specialized complaint or substitute-payer procedure remains unresolved. The accident proof in § 10.1.1 and Bureau provisions in occupational § 18.12 and compulsory §§ 32.1, 32.1.1 and 32.1.3 do not establish automatic replacement coverage for employer non-insurance. |
| AZ7-05 Accident entitlement and qualifying events | FULL / PARTIAL → PARTIAL | Occupational law §§ 2.0.9, 2.0.10, 2.0.12, p. 2, § 5.1.1, p. 4, § 8.1.1, p. 7, and §§ 10.1.1, 10.1.2, p. 9. | The payout conditions, statutory definition and proof requirements are supported. A complete list of scenarios under the underlying investigation rules was unavailable. `NK-2023-156.pdf`, pp. 2–4, amends Decisions No. 27 and No. 196. Occupational §§ 20.0–20.0.3 concern payment refusal. |
| AZ7-06 Individual entrepreneur payment method and timing | FULL / FULL → FULL | **Sosial sığorta haqqında**, `sığorta 7.pdf`, § 14.5.1-1, p. 9, §§ 14.6 and 14.6-1, p. 11. Occupational law §§ 3.1.7 and 4.0.5, p. 4, §§ 14.2 and 14.3-1, p. 11. | The premium type is unspecified. The rubric requires conditional treatment of both indexed types, plus the special social contribution receipt or sign trigger. The ordinary social payment deadline does not apply to every category. The question asks for method and timing. A personal rate or amount is outside that rubric. |
| AZ7-07 Agricultural land contribution | FULL | Social insurance law § 14.5.1-1.9, p. 10. | The 2%, 6% and 10% bands apply within the provision's ownership, family-member and exclusion conditions. Related § 14.5.6 is struck through across PDF pp. 10–11, although its flat 6% text survived indexing. § 14.5.1-2 excludes the land category from the regional multipliers. The general term “use” does not establish ownership or family-farm status. |

All seven questions concern domains represented in the snapshot. AZ7-06 has an ambiguous premium type. The NOT_FOUND sub-question in AZ7-04 reflects an evidence gap within the occupational domain.

## Error classification

No observed errors or internal root causes can be established for these seven cases. The conditions in this table define the evidence needed for attribution once the corresponding request is available.

| Error label | Evidence needed |
| --- | --- |
| Retrieval miss | Recorded final ranks omit directly relevant passages. |
| Candidate recall failure | Recorded candidate IDs show the required evidence absent before reranking. |
| Reranking failure | The required evidence enters the reranker and drops below the evaluated cutoff after reranking. |
| Evidence assembly failure | Eligible retrieved evidence is missing from the recorded assembled context. |
| Multipart decomposition or attribution failure | The plan omits an explicit part or the trace assigns evidence to the wrong part. |
| Query normalization failure | A recorded rewrite or normalization loses material meaning and a trace or controlled comparison ties it to the failure. |
| Domain routing failure | The recorded route or filter excludes the applicable source or sends the query to another domain. |
| Unsupported inference | A specific generated claim extends beyond the supporting source. |
| Citation validation failure | A cited claim and source fail a support or reference check. Internal validator attribution also requires its recorded outcome. |
| Incomplete answer | A directly supported answer requirement is absent from the observed output. |
| Incorrect answer mode | The recorded mode disagrees with the applicable expected mode. |

## Reproduction and metric availability

```powershell
python -m evaluation.evaluate_latest_seven --snapshot .venv/eval_corpus_snapshot.json --output evaluation/latest_seven_metrics.json
python -m unittest discover -s tests -p test_latest_seven_evaluation.py -v
```

The validator checks the frozen digest and compares passage text, original text, article, clause, page and ordinal with the snapshot. The existing read-only exporter in `evaluation/export_real_insurance_snapshot.py` can produce a corpus export from the same indexed version. The verifier rejects a different snapshot.

All nine run metrics in `latest_seven_metrics.json` have zero scored cases and a null value. Recall@5, Recall@10, MRR@10 and nDCG@10 need rankings from the original run. Citation precision and completeness need the original output and reviewed claim-level citation judgments. Multipart coverage needs assembled passage attribution. Answer correctness needs an expert judgment bound to the exact answer. Mode accuracy needs the explicitly emitted mode and uses the provisional corpus rubric. The unresolved parts carry no gold passages and are excluded from passage denominators. This limited metric coverage cannot establish a complete answer.

To score a recovered original run, pass `--observations path/to/capture.json`. The JSON object is keyed by case ID. Each entry preserves the exact `query` and `answer` strings and an `artifact` locator. Optional fields are `ranked_passage_ids` (unique, in rank order), `part_passage_ids` (assembled passage IDs keyed by Q1, Q2, etc.), explicit `mode`, and `error_labels` (objects with `label` and an `evidence` locator). Pipeline errors also require the recorded `trace_stage`. A `generation_review` can include `correct` and `citations`, with one `supports_claim`, `part` and `passage_id` judgment per citation occurrence. It must include `status: "approved"`, `reviewer`, `expertise` and the SHA-256 of the UTF-8 answer in `answer_sha256`.

All six new tests passed, including full snapshot verification. The legacy fixture regression verifies all four locked fixture hashes and 108 unique benchmark IDs. The full suite ran 160 tests with the local dependency directories on `PYTHONPATH`. It reported one error in `test_revisions_are_append_only_and_invalid_labels_roll_back`, where Windows refused to remove an open temporary SQLite database (`WinError 32`). Work was confined to new evaluation and test files.
