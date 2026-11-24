from copy import deepcopy
from unittest import TestCase

from evaluation import expert_review as workflow, gold_framework as gold


class ExpertReviewTests(TestCase):
    def setUp(self):
        case = {"status": "pending", "query": "case", "history": [], "category": "legal", "style": "formal",
                "groups": ["formal"], "diagnostic": False, "draft_evidence": [], "draft_part_parents": {}}
        self.packet = {"schema_version": 1, "dataset_sha256": "fixture", "corpus_sha256": "fixture", "queries": {"q": case}}
        self.labels = {"answerability": "unanswerable", "evidence": [], "required_passage_ids": [], "parts": {},
                       "expected_answer": "fixture abstention", "required_qualifications": [],
                       "groups": ["formal"], "standalone": None}

    def submission(self, name, decision=None, role="annotation"):
        return {**workflow.template(self.packet, role), "reviewer": name, "revision": "r1", "expertise": "fixture",
                **({"decisions": {"q": decision}} if decision is not None else {})}

    def test_no_draft_or_single_decision_can_approve_a_case(self):
        annotate = {"decision": "annotate", "reason": "fixture", "labels": self.labels}
        _, report = workflow.resolve(self.packet, [self.submission("a", annotate), self.submission("b")], None, {})
        self.assertEqual(report["approved"], 0)
        self.assertEqual(report["rows"]["q"]["status"], "one_review")
        final, report = workflow.resolve(self.packet, [self.submission("a", annotate), self.submission("b", annotate)], None, {})
        self.assertEqual(report["approved"], 1)
        self.assertEqual(final["queries"]["q"]["status"], "approved")
        self.assertEqual(len(final["queries"]["q"]["revision_history"]), 2)
        self.assertEqual(self.packet["queries"]["q"]["status"], "pending")

    def test_disagreement_requires_independent_and_revision_bound_adjudication(self):
        annotate = {"decision": "annotate", "reason": "fixture", "labels": self.labels}
        defer = {"decision": "defer", "reason": "needs checking", "labels": None}
        reviews = [self.submission("a", annotate), self.submission("b", defer)]
        _, report = workflow.resolve(self.packet, reviews, None, {})
        self.assertEqual(report["rows"]["q"]["disputed_fields"], ["decision"])
        self.assertEqual(report["unresolved_ids"], ["q"])
        decision = {**annotate, "reviewed_decision_sha256": [gold.digest(annotate), gold.digest(defer)]}
        with self.assertRaisesRegex(ValueError, "independent"):
            workflow.resolve(self.packet, reviews, self.submission("a", decision, "adjudication"), {})
        final, report = workflow.resolve(self.packet, reviews, self.submission("c", decision, "adjudication"), {})
        self.assertEqual(report["rows"]["q"]["status"], "adjudicated_approved")
        self.assertEqual([entry["reviewer"] for entry in final["queries"]["q"]["revision_history"]], ["a", "b", "c"])
        changed = deepcopy(reviews)
        changed[1]["decisions"]["q"]["reason"] = "different revision"
        with self.assertRaisesRegex(ValueError, "stale"):
            workflow.resolve(self.packet, changed, self.submission("c", decision, "adjudication"), {})

    def test_frozen_splits_reject_family_leakage_and_unapproved_cases(self):
        labels = {str(i): {"answerability": status, "query": f"question {i}"} for i, status in enumerate(
            ["answerable", "partially_answerable", "unanswerable"] * 2)}
        assignment = {"status": "approved", "review_sha256": gold.digest(self.packet), "split_version": "v1",
                      "reviewer": "fixture", "expertise": "fixture", "revision": "r1",
                      "cases": {key: {"split": "validation" if int(key) < 3 else "holdout", "family": key} for key in labels}}
        manifest = workflow.freeze_splits(self.packet, labels, assignment)
        self.assertEqual(manifest["splits"], {"validation": ["0", "1", "2"], "holdout": ["3", "4", "5"]})
        self.assertEqual(manifest["assignment_sha256"], gold.digest(assignment))
        assignment["cases"]["3"]["family"] = "0"
        with self.assertRaisesRegex(ValueError, "leaks"):
            workflow.freeze_splits(self.packet, labels, assignment)
        assignment["cases"]["3"]["family"] = "3"
        with self.assertRaisesRegex(ValueError, "Unapproved"):
            workflow.freeze_splits(self.packet, {key: row for key, row in labels.items() if key != "3"}, assignment)

    def test_gold_release_requires_resolved_cases_and_binds_adjudication(self):
        annotate = {"decision": "annotate", "reason": "fixture", "labels": self.labels}
        pending, report = workflow.resolve(self.packet, [self.submission("a", annotate), self.submission("b")], None, {})
        self.assertEqual(report["release_counts"], {"approved": 0, "pending": 1, "rejected": 0, "disputed": 0})
        with self.assertRaisesRegex(ValueError, "Cannot freeze"):
            workflow.freeze_gold(pending, {}, report, "v1")
        approved, report = workflow.resolve(
            self.packet, [self.submission("a", annotate), self.submission("b", annotate)], None, {})
        release = workflow.freeze_gold(approved, approved["queries"], report, "v1")
        self.assertEqual(release["adjudication_sha256"], gold.digest(report))
        self.assertEqual(release["gold_version"], "v1")
        report["review_sha256"] = "stale"
        with self.assertRaisesRegex(ValueError, "matching adjudication"):
            workflow.freeze_gold(approved, approved["queries"], report, "v1")
