import unittest

from App.main import CaseDates
from App.source_authority import case_timeline, compare_periods
from evaluation.benchmark_source_authority_v2 import evaluate


class TemporalAuthorityV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = evaluate()
        cls.rows = {row["id"]: row for row in cls.report["rows"]}

    def test_claim_dates_round_trip_independently_with_request_provenance(self):
        values = CaseDates(insured_event_date="2025-04-12", claim_notification_date="2025-04-13",
                           claim_date="2025-07-01", contract_start="2025-01-01", contract_termination="2025-06-30")
        timeline = case_timeline(**values.model_dump(mode="json"))
        self.assertEqual(timeline["dates"]["claim_date"], "2025-07-01")
        self.assertEqual(timeline["dates"]["claim_notification_date"], "2025-04-13")
        self.assertEqual(timeline["contract_event_relationship"], "inside_asserted_contract_period")
        self.assertFalse(timeline["date_provenance"]["claim_date"]["verified"])
        self.assertFalse(timeline["case_facts_verified"])
        self.assertNotIn("claim_date", case_timeline()["date_provenance"])

    def test_temporal_labels_ignore_publication_and_amendment_dates(self):
        first = {"effective_date": "2020-01-01", "repeal_effective_date": "2024-01-01"}
        second = {"repeal_effective_date": "2027-01-01"}
        self.assertEqual(compare_periods(first, second)[0], "unknown")
        self.assertEqual(compare_periods(first, {**second, "amendment_date": "2023-01-01",
                                                  "publication_date": "2022-01-01"})[0], "unknown")
        self.assertEqual(compare_periods(first, {**second, "effective_date": "2025-01-01"})[0], "no_temporal_overlap")
        self.assertEqual(compare_periods(first, {**second, "effective_date": "2021-01-01"})[0],
                         "potential_temporal_overlap")
        shared = {"rule_period": ["2020-01-01", "2027-01-01"]}
        self.assertEqual(compare_periods({**first, **shared}, {**second, **shared, "effective_date": "2025-01-01"})[0],
                         "no_temporal_overlap")

    def test_missing_and_conflicting_information_are_distinct(self):
        unknown, = self.rows["V2-C03"]["observed"]["conflicts"]
        inconsistent, = self.rows["V2-C06"]["observed"]["conflicts"]
        self.assertEqual(unknown["missing_information"][0]["reference_index"], 1)
        self.assertEqual(unknown["missing_information"][0]["field"], "effective_date")
        self.assertEqual(unknown["conflicting_information"], [])
        self.assertEqual(inconsistent["missing_information"], [])
        self.assertEqual(inconsistent["conflicting_information"][0]["reference_index"], 1)
        self.assertTrue(inconsistent["requires_expert_review"])
        self.assertIsNone(inconsistent["resolution"])

    def test_v2_passes_without_replacing_original_fixture_expectations(self):
        self.assertEqual(len(self.rows), 53)
        for key in ("T11", "T13", "C03", "C06"):
            self.assertTrue(all(check["passed"] for check in self.rows[key]["checks"]), key)
        self.assertEqual(self.report["metrics"]["all"]["conflict_false_positive_rate"]["numerator"], 0)
        original = self.report["frozen_v1_expectations_on_current_layer"]
        self.assertEqual(original["temporal_relationship_accuracy"]["failed_fixture_ids"], ["T11"])
        self.assertEqual(original["expert_review_escalation_accuracy"]["failed_fixture_ids"], ["C06"])
