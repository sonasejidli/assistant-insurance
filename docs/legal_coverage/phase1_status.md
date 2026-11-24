# Seven-question program status

The corpus audit and original-source archive are complete for the initial source set. Routing fixes are local. The seven-answer release is still incomplete.

| Area | Evidence and status |
|---|---|
| Baseline corpus | 4,405 parents loaded from the pinned RC. The prepared collection remains unchanged. See [inventory](indexed-inventory.json) and [coverage matrix](seven_question_coverage_matrix.md). |
| Official acquisition | 17 official responses archived separately, including the Civil Code, Labour Code, Cabinet No. 189, the accident investigation rules, the injury classification list, and original and amended disability criteria PDFs. See [manifest](acquired/manifest.json). Register pages are locator records. |
| Ingestion validation | All archive hashes matched. The three disability PDFs have readable text on 88/88, 63/63 and 63/63 pages. HTML probes detect tables and editorial deletions. The 189 consolidation has 51 HTML tables and 28,546 elements tagged as deletions. Counts are structural signals and do not validate individual rows or operative provisions. See [validation report](acquisition-validation.json). |
| Expanded index | Pending active/historical clause separation, amendment reconciliation and table/annex validation. No expanded index was prepared. |
| Routing | Seven exact questions and 35 paraphrases pass deterministic routing. All seven follow-up probes and five out-of-scope controls pass. Five of seven review probes pass. Ambiguous historic birth context and the unspecified refusal letter still require domain context or clarification. See [baseline](routing_probe_baseline.json), [results](routing_probe_results.json), and [probe definitions](routing_probe_cases.json). A routing pass does not establish legal evidence or an answer. |
| Verified legal evidence | Normative source leads and candidate provisions are identified in the matrix. Legal currency, historical intervals and applicable exceptions have not been fully approved. No legal gold claims or numerical outputs were assigned to the probes. |
| Citation and calculation | End-to-end citation validation on expanded evidence and a version-backed calculation implementation remain pending. No new amounts or formulas entered application code. |
| Frontend and providers | Expanded-corpus browser acceptance and live provider qualification were not run. Prior demo results are separate baseline evidence. |
| Deployment and rollback | The immutable RC, Q4 candidate and existing Qdrant indexes were preserved. No new image was built or deployed. The active stack needs no rollback from this work. The local routing change can be isolated by reviewing the current diff against the previously saved Q4 overlay. |
| Independent expert review | Pending. |

## Required next evidence

1. Obtain complete amendment texts for Cabinet No. 189 and close the effective-date intervals for the provisions used in Q1 and Q5.
2. Pin the relevant versions of the No. 187 annex and reconcile every applicable table against the official PDF. Preserve row and column scopes, classification conditions and source anchors.
3. Verify the applicable compensation schedules by insurance product. Reconcile the Civil Code and workplace provisions, and verify the No. 27 annex forms and the No. 269 classification list.
4. Produce a reviewed, isolated source corpus, then run the ingestion gate and prepare a new index under a distinct collection identity. Build deterministic calculations and legal gold cases from those reviewed versions.
5. Qualify the unchanged legal release process and actual frontend on that distinct candidate before claiming seven-question support.
