import unittest

from evaluation.benchmark_legal_verifier import CORPUS
from evaluation.compare_legal_verifiers import EXTENSION, POLICY, compare, compare_case
from evaluation.gold_framework import read
from evaluation.verify_legal_scope_v2 import temporal_check


class LegalVerifierV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = read(CORPUS)
        cls.policy = read(POLICY)
        cls.extension = read(EXTENSION)
        cls.result = compare(cls.corpus, cls.policy, cls.extension)
        cls.rows = {row["id"]: row for row in cls.result["rows"]}

    def test_all_original_and_adversarial_cases_compared(self):
        self.assertEqual(len(self.rows), 43)
        self.assertEqual(self.result["metrics"]["original_v1"]["old"]["false_acceptance_rate"]["numerator"], 12)
        self.assertEqual(self.result["metrics"]["all"]["new"]["false_acceptance_rate"]["numerator"], 0)
        self.assertEqual(self.result["metrics"]["all"]["new"]["citation_binding_accuracy"]["numerator"], 43)

    def test_optimistic_assessment_and_unrecognized_added_claim(self):
        claim = self.rows["S01"]["hardened_decision"]["claims"][0]
        self.assertEqual(claim["assessment"]["support_label"], "complete")
        self.assertEqual(claim["status"], "unsupported")
        self.assertEqual(claim["reason_code"], "payment_deadline_absent")
        self.assertIsNone(claim["supported_fragment"])
        self.assertIn("qüvvədə olduğu", claim["evidence"][0]["source"]["text"])
        original = self.corpus["cases"][0]
        changed = {**original, "claim": original["claim"] + " Sığortaçı faiz də ödəyir."}
        result = compare_case(changed, self.corpus, self.policy)
        self.assertIsNone(result["new"]["mode"])
        self.assertEqual(result["hardened_decision"]["claims"][0]["status"], "unverified")

    def test_paraphrase_unpaginated_and_wrong_regime(self):
        self.assertEqual(self.rows["V202"]["new"]["mode"], "FULL")
        self.assertEqual(self.rows["V203"]["new"]["mode"], "PARTIAL")
        self.assertTrue(self.rows["V203"]["new"]["binding"])
        self.assertEqual(self.rows["V207"]["hardened_decision"]["claims"][0]["reason_code"], "wrong_insurance_type")
        self.assertIsNone(self.rows["V208"]["new"]["mode"])

    def test_temporal_and_reference_failures_remain_distinct(self):
        reasons = {key: self.rows[key]["hardened_decision"]["claims"][0]["reason_code"] for key in (
            "V204", "V205", "V206", "V209", "V210", "V211",
        )}
        self.assertEqual(reasons, {"V204": "temporal_evidence_missing",
                                   "V205": "event_outside_contract_period",
                                   "V206": "temporal_evidence_conflicting",
                                   "V209": "assessment_references_invalid", "V210": "assessment_references_invalid",
                                   "V211": "contract_boundary_time_unverified"})
        self.assertIsNone(self.rows["M08"]["new"]["mode"])
        self.assertEqual(self.rows["S14"]["new"]["mode"], "FULL")
        self.assertEqual(temporal_check({"temporal_kind": "event", "date_evidence": {
            "contract_start": [{"value": "2025-01-01"}],
        }}), "temporal_evidence_missing")

    def test_supported_fragment_requires_a_bounded_witness(self):
        for key in ("M05", "M06", "M11"):
            result = self.rows[key]["hardened_decision"]
            self.assertTrue(result["parts"]["Q1"]["independently_supported_fragments"])
            self.assertFalse(result["parts"]["Q1"]["complete"])
            self.assertEqual(result["verified_mode"], "PARTIAL")
        self.assertFalse(self.rows["M08"]["hardened_decision"]["parts"]["Q1"]["independently_supported_fragments"])
