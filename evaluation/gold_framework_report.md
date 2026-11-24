# Gold evaluation and calibration

## Dataset audit

The frozen repository dataset contains 150 questions with draft evidence and 14 draft coverage gaps. The framework also carries three negative-claim controls and six multipart controls, with original passage-to-part associations intact. The 164 existing review records are pending domain review. Gold coverage is **0/164 corpus questions and 0/9 controls**. The report [lists every pending ID](gold_framework_audit.json).

All 224 candidate labels match the frozen source by passage and parent ID, document ID, article, clause, and verbatim text. Eight rows have no source article and 21 have no source clause. These fields remain null where the source lacks numbering. Source identity checks establish provenance. Legal relevance, required provisions, conflicting authority, and the completeness of a proposed answer still require expert review.

| Group | Cases awaiting review |
| --- | ---: |
| Negative-claim controls | 3 |
| Multipart controls | 6 |
| Draft knowledge gaps | 14 |
| Informal Azerbaijani | 45 |
| Formal Azerbaijani | 98 |

The formal and informal groups include 10 and four draft knowledge gaps respectively. Other styles, including follow-ups, numeric phrasing, ASCII, and morphology, remain in the overall cohort. The 150 questions with evidence are not presumed fully answerable.

## Measured draft retrieval baseline

The numbers below were recomputed from the existing paired real-corpus run against draft labels. Its before/after configurations are described in the [original real-corpus report](real_insurance_report.md). Scores average the 150 corpus queries with evidence. Coverage-gap queries have no retrieval denominator.

| Stage | Recall@5 before → after | Recall@10 before → after | MRR@20 before → after | nDCG@10 before → after |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 0.501 → 0.494 | 0.574 → 0.582 | 0.462 → 0.463 | 0.448 → 0.453 |
| Dense | 0.485 → 0.482 | 0.561 → 0.561 | 0.478 → 0.471 | 0.461 → 0.458 |
| RRF | 0.586 → 0.590 | 0.648 → 0.658 | 0.525 → 0.531 | 0.518 → 0.527 |

After-config RRF Recall@10 was 0.683 for the 88 formal cases with evidence and 0.651 for the 41 informal cases with evidence. MRR@20 was 0.591 and 0.439, respectively. These are descriptive results for different mixes of questions. Draft failure tags identified 44 dense-retrieval failures, 11 hybrid-fusion failures, six lexical failures, two context-resolution failures, and 14 coverage gaps. The tags are triage evidence for reviewers. [Per-query draft measurements](real_insurance_draft_results.json)

The separate [multipart BGE run](multipart_completion_bge_results.json) measured 6/6 complete cases versus 1/6, and 20/20 versus 11/20 correct assignments, on draft judgments. Three negative-claim controls have no ranked relevant passages. They are scored through reviewed answer behavior once available. The seven legacy answer examples and the separate judge-review cohort remain pending. Gold faithfulness, answer relevancy, and answer-mode accuracy are unavailable.

## Reproduce and review

Use the existing frozen corpus export. The [pending review packet](gold_framework_review.pending.json) contains the source-verified draft labels and review fields for all corpus questions and controls. These commands regenerate it locally without a Qdrant connection.

```sh
python -m evaluation.gold_framework audit --snapshot .venv/eval_corpus_snapshot.json --output evaluation/gold_framework_audit.json
python -m evaluation.gold_framework packet --snapshot .venv/eval_corpus_snapshot.json --output review.pending.json
```

A domain expert should check each case against the full relevant source set, including alternative provisions and effective versions, then record reviewer, expertise, and revision history. Set `answerability` to `answerable`, `partially_answerable`, `unanswerable`, `ambiguous`, or `conflicting`. Write the expected answer, clarification, or abstention, and record required qualifications. Copy verified candidate evidence into the approved field only after review. An expert can add or correct source labels using the same frozen corpus. Use `required_passage_ids` for indispensable sources and preserve each multipart `Qn` in `parts` with its question and required passage IDs, including empty requirements for unresolved parts. Use an empty list for confirmed absence, and retain pending status while uncertainty remains. A passage can support more than one part if the reviewer approves both associations.

For paired scoring, record the same approved cohort from each isolated configuration. Each run JSON contains `review_sha256` (canonical benchmark digest of the approved packet), `corpus_sha256`, `evaluated_commit`, `configuration_id`, `score_version`, and `rows`. Record each row's `id`, ordered distinct `ranked_passage_ids`, `part_passage_ids` as a mapping from `Qn` to passage IDs, actual `mode`, and verbatim `answer`. Preserve the final candidate ranking as emitted by the evaluated system. Record modes as `FULL`, `PARTIAL`, `NOT_FOUND`, `CLARIFY`, or `CONFLICTING`. Optional `generation_review` records its `status`, reviewer, expertise, rubric version, SHA-256 of the exact UTF-8 answer, and Boolean or null `faithfulness` and `relevancy` judgments. Null is appropriate when a rubric dimension is inapplicable. Run evaluation records and expert judgments are controlled inputs. The scorer does not send the questions to a model.

```sh
python -m evaluation.gold_framework compare --snapshot .venv/eval_corpus_snapshot.json \
  --reviews review.approved.json --before before-run.json --after after-run.json \
  --output paired-report.json
```

The paired report presents independent retrieval, generation, and behavior sections, each with its scored denominator. Deltas use only cases scored in both runs. Per-query output records missing required passages, missing and extra multipart assignments, expected and actual modes, and unsafe FULL outcomes when the expert expected another mode.

## Calibration and CI

**Calibration is blocked.** There are zero approved labels, no approved confidence-score specification or threshold candidates, and no approved validation/holdout split. No threshold values were inferred or deployed.

With approved inputs, record each evaluated row's numeric `score` from the versioned confidence function. Supply `--split-manifest` from the expert workflow and `--policy` with the approved review and split-manifest hashes, reviewer, expertise, status, score version, configuration ID, candidate `full` and `partial` cutoffs, and maximum allowed unsafe FULL count. Both splits need FULL, PARTIAL, and NOT_FOUND labels. Clarification and conflict routing are scored separately. The runner selects only on validation, applies the chosen policy once to holdout, and reports baseline and candidate accuracy and unsafe FULL counts. A failed holdout does not retune the candidate. [Annotation, adjudication, and split instructions](expert_review_workflow.md)

The backend regression suite ran **148 tests** and the original 108-query lexical fixture matched its locked ranking hash. The controlled CI workflow archives the audit and optionally runs paired comparison and calibration when both readiness variables are enabled. Production settings, E5/BGE models, Qdrant collections, API contracts, and original benchmark files were preserved.

Production readiness still requires expert-approved answerability and required passages, a reviewed generation cohort, representative validation and untouched holdout runs, and independent confirmation of failure behavior for unsupported, ambiguous, or conflicting requests.
