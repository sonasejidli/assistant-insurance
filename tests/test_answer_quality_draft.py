from copy import deepcopy
from unittest import TestCase

from App.document_processing import load_documents
from evaluation.gold_framework import read
from evaluation.validate_answer_quality_draft import DRAFT, INDEX, validate


class AnswerQualityDraftTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = read(DRAFT)
        cls.documents = load_documents(INDEX, 1200)

    def test_draft_matches_actual_index(self):
        summary = validate(self.dataset, self.documents)
        self.assertEqual(summary["cases"], 25)
        self.assertEqual(summary["modes"], {"FULL": 19, "PARTIAL": 1, "NOT_FOUND": 5})
        self.assertFalse(summary["gold"])

    def assert_invalid(self, mutation, error):
        draft = deepcopy(self.dataset)
        mutation(draft)
        with self.assertRaisesRegex(ValueError, error):
            validate(draft, self.documents)

    def test_fabricated_reference_and_altered_text_are_rejected(self):
        self.assert_invalid(lambda d: d["cases"][0]["supporting_passages"].append("invented"),
                            "Unknown or overlapping evidence")
        self.assert_invalid(lambda d: next(iter(d["passages"].values())).update(text="altered"),
                            "Passage text or identity mismatch")
        self.assert_invalid(lambda d: next(iter(d["passages"].values())).update(page=999),
                            "Passage metadata mismatch")

    def test_claim_and_multipart_require_evidence(self):
        self.assert_invalid(lambda d: d["cases"][0]["required_claims"][0].update(passage_ids=[]),
                            "Claim without grounded evidence")
        self.assert_invalid(lambda d: d["cases"][10]["sub_questions"].pop(), "Malformed multipart")
        self.assert_invalid(lambda d: d["cases"][11].update(expected_mode="FULL"), "Multipart mode mismatch")

    def test_labels_cannot_silently_become_approved_gold(self):
        self.assert_invalid(lambda d: d.update(gold=True), "Draft version/status")
        self.assert_invalid(lambda d: d["cases"][0].update(expert_review_status="approved"), "Draft status")

    def test_insufficient_cases_require_a_documented_gap(self):
        self.assert_invalid(lambda d: d["cases"][-1].update(expected_abstention_reason=None),
                            "Missing abstention rationale")

    def test_unique_case_count_and_category_are_enforced(self):
        self.assert_invalid(lambda d: d["cases"].pop(), "Duplicate, empty, or missing cases")
        self.assert_invalid(lambda d: d["cases"][0].update(question_id=d["cases"][1]["question_id"]),
                            "Duplicate, empty, or missing cases")
        self.assert_invalid(lambda d: d["cases"][0].update(category="condition"), "Category counts")
