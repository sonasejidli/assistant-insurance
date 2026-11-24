from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from evaluation import legal_answer_quality as quality


class LegalAnswerQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.run_path = Path(cls.temp.name) / "fixtures"
        cls.spec = quality.inputs()
        quality.capture_run(cls.run_path, *cls.spec)
        cls.report = quality.replay(cls.run_path, *cls.spec)
        cls.rows = {row["id"]: row for row in cls.report["rows"]}

    def test_exact_replay_does_not_execute_request_or_provider(self):
        with patch("evaluation.legal_answer_quality_capture.capture_case", side_effect=AssertionError("unexpected capture")):
            self.assertEqual(self.report, quality.replay(self.run_path, *self.spec))
        self.assertEqual(len(self.rows), 15)

    def test_actual_handoff_keeps_model_and_verifier_decisions_separate(self):
        supported = self.rows["E2E-B01"]
        self.assertEqual(supported["observed_mode"], "FULL")
        self.assertEqual(supported["hardened"]["verified_mode"], "FULL")
        unsafe = self.rows["E2E-S05"]
        self.assertEqual(unsafe["observed_mode"], "FULL")
        self.assertIsNone(unsafe["hardened"]["verified_mode"])
        self.assertEqual(unsafe["claims"][0]["label_status"], "unsupported")
        self.assertTrue(unsafe["claims"][0]["binding_valid"])

    def test_provider_failure_and_decomposition_are_not_retrieval_absence(self):
        timeout = self.rows["E2E-D02"]
        self.assertTrue(timeout["provider_failure"])
        self.assertIsNone(timeout["observed_mode"])
        self.assertEqual(timeout["earliest_failure"]["failure_stage"], "provider_or_infrastructure")
        multipart = self.rows["E2E-S04"]
        self.assertEqual(multipart["earliest_failure"]["failure_stage"], "query_decomposition")
        self.assertEqual(multipart["hardened"]["verified_mode"], "PARTIAL")

    def test_atomic_spans_and_unavailable_metrics(self):
        claim_spans = self.rows["E2E-B03"]["claims"]
        self.assertEqual(len(claim_spans), 2)
        self.assertNotEqual(claim_spans[0]["supporting_passage_ids"], claim_spans[1]["supporting_passage_ids"])
        self.assertIn("retrieval.final.depth_10_20", self.rows["E2E-B01"]["unavailable"])
        self.assertIn("understanding.entity_and_free_text_date_extraction", self.rows["E2E-B01"]["unavailable"])
