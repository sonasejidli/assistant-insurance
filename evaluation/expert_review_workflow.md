# Expert legal review and calibration

## Review and adjudication status

| Cohort | Cases | Awaiting first review | Expert-approved | Recorded disagreements |
| --- | ---: | ---: | ---: | ---: |
| Frozen corpus | 164 | 164 | 0 | 0 |
| Controls | 9 | 9 | 0 | 0 |

The corpus has 224 source-verified candidate evidence records across 150 questions. Fourteen questions have draft coverage-gap flags. The controls comprise three negative claims and six multipart questions, with 20 source-verified candidate records. **Source verification confirms what is present in the frozen extraction.** It supplies passage IDs and source metadata for inspection. It does not establish legal relevance, applicability, completeness, or absence of an obligation. Missing article or clause metadata stays null. [Frozen review packet](gold_framework_review.pending.json) · [Current coverage and unresolved IDs](expert_review_status.json)

## Independent annotation

1. Give each reviewer the same pending packet and a separate copy of the [annotation form](expert_annotation_template.json). Keep submissions separate until both are recorded. Each reviewer records their name or stable ID, relevant legal expertise, and submission revision. Retain previous revisions and never overwrite the frozen packet.
2. For each case, select `annotate`, `defer`, or `exclude` and write a reason. Use `defer` when evidence, version, or applicability cannot be verified. Use `exclude` for a specific evaluation defect and explain it. Leave unreviewed decisions null.
3. For `annotate`, fill `labels` using the eight fields below. Start from a source inspection. Draft grades and draft passage associations are suggestions and should not be submitted unchanged without verification.

| Field | Annotation |
| --- | --- |
| `answerability` | Choose `answerable`, `partially_answerable`, `unanswerable`, `ambiguous`, or `conflicting`. Use ambiguous when essential context is missing. Use conflicting when applicable provisions lead to incompatible answers and the evidence does not establish priority. |
| `evidence` | Record relevant source excerpts using `document_id`, `article`, `clause`, `passage_id`, `parent_passage_id`, verbatim `text`, and integer `relevance`. Use 3 for controlling or directly responsive text, 2 for substantive support, and 1 for relevant context. Exclude irrelevant passages. Review effective dates and source hierarchy when available. |
| `required_passage_ids` | Identify the minimum passages needed to justify the expected answer and its exceptions. Use an empty list when no passage is required to justify the expected behavior. |
| `parts` | Preserve each known `Qn`. Give it a standalone `question` and `required_passage_ids`. A passage can support several parts. Include unresolved parts with an empty list and describe the gap in the expected answer or qualifications. |
| `expected_answer` | Write the expected Azerbaijani answer, bounded partial answer, abstention, clarification, or conflict explanation. Distinguish corpus absence from a finding that no legal duty exists. |
| `required_qualifications` | Record legal scope, dates, conditions, exceptions, deadlines and units. Use an empty list when none are necessary. |
| `groups` | Preserve the packet's existing diagnostic groups. Add another supported group only when the reviewed question fits it. |
| `standalone` | Give the resolved standalone wording for a context-dependent query. Use null when no standalone rewrite is required or supportable. |

## Reconcile and adjudicate

Run reconciliation to record which cases have no review, one review, agreement, disagreement, deferral or exclusion. Two explicit agreeing expert annotations can pass the source and schema validation gate. Disagreement reports show the disputed fields, both reviewers' rationales and decision hashes. Keep submission files alongside the report so the adjudicator can inspect the actual proposed labels.

A third independent expert uses the [adjudication form](expert_adjudication_template.json) to approve a final annotation, defer the case, or exclude it. Copy both `decision_sha256` values from the report to `reviewed_decision_sha256`, in reviewer A/B order. This rejects decisions against stale reviews. If unresolved, retain the earlier records and leave the case outside gold scoring.

```sh
python -m evaluation.expert_review resolve --packet evaluation/gold_framework_review.pending.json \
  --snapshot .venv/eval_corpus_snapshot.json --annotation reviewer-a.json --annotation reviewer-b.json \
  --output approved-review.json --report adjudication-report.json
```

Re-run with `--adjudication adjudicator.json` as decisions arrive. The finalized review file preserves case-level revision history. The report retains excluded and deferred cases with their reasons while the scorer accepts only approved annotations.

## Freeze calibration and holdout after approval

Freeze a gold release only after the required cohort is resolved. A case can be left out only through an explicit expert exclusion. A missing or deferred review or an unresolved disagreement blocks release. Reuse the two submissions and add the adjudicator argument if needed.

```sh
python -m evaluation.expert_review freeze --packet evaluation/gold_framework_review.pending.json \
  --snapshot .venv/eval_corpus_snapshot.json --annotation reviewer-a.json --annotation reviewer-b.json \
  --gold-version v1 --output gold-release.json --report adjudication-report.json
```

Create an assignment with `status: "approved"`, reviewer, expertise, revision, `review_sha256` from the adjudication report, the canonical `gold_release_sha256`, a new `split_version`, and a `cases` mapping. Each assigned case has a `split` of `validation` or `holdout` and a stable `family`. Put paraphrases, related follow-ups, and variants of the same multipart question in one family. Duplicate normalized questions and shared family identifiers may not cross splits. Holdout observations must stay out of policy selection. Each split needs approved FULL, PARTIAL, and NOT_FOUND examples. Ambiguous and conflicting cases are evaluated separately for routing behavior.

```sh
python -m evaluation.expert_review splits --packet evaluation/gold_framework_review.pending.json \
  --snapshot .venv/eval_corpus_snapshot.json --approved approved-review.json \
  --release gold-release.json --assignment approved-split-assignment.json --output gold-splits.json
```

Bind the approved calibration policy to `review_sha256` and the canonical `split_manifest_sha256` using `evaluation.gold_framework.digest`. Record the confidence score version and configuration, approved candidate cutoffs, and the approved unsafe FULL budget. Keep the assignment, manifest, run exports, and policy together. If labels or split assignments change, issue a new version and re-evaluate.

```sh
python -m evaluation.gold_framework compare --snapshot .venv/eval_corpus_snapshot.json \
  --reviews approved-review.json --before before-run.json --after after-run.json \
  --policy approved-calibration.json --split-manifest gold-splits.json --output gold-paired.json
```

The report scores retrieval (Recall@5/10, MRR@20, nDCG@10 and multipart coverage), human-reviewed faithfulness, human-reviewed answer relevancy, and answer-mode accuracy separately. It selects cutoffs on validation and evaluates the selection on holdout without retuning on failure. The `holdout_performance` section reports holdout-only results for both recorded configurations plus the candidate threshold's holdout behavior. Threshold predictions do not change the recorded answer text or its human judgments. The [evaluation input format and draft baseline](gold_framework_report.md) describe the required run records. CI can regenerate the release, adjudication, and splits from submissions and archive the comparison when explicitly enabled.

**Current limitation:** No reviewer submissions or adjudications exist. No cases were approved, no calibration or holdout split was created, and no cutoff was inferred or deployed.

The original 108-query lexical benchmark remains locked. Workflow regression tests cover independent review, stale adjudication, split leakage, and release blocking on unresolved cases.
