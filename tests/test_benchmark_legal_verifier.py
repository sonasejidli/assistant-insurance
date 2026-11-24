from collections import Counter
import unittest

from evaluation.benchmark_legal_verifier import CORPUS, benchmark, check_corpus, classify, summarize
from evaluation.gold_framework import HERE, read


class LegalVerifierBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.corpus = read(CORPUS)

    def test_fixtures_partition_and_classify_sources(self):
        check_corpus(self.corpus)
        cases = self.corpus["cases"]
        self.assertEqual(len({case["id"] for case in cases}), 32)
        self.assertEqual(Counter(case["stratum"] for case in cases), {"mechanical_controls": 18, "assumption_stress": 14})
        catalog = self.corpus["authority"]
        self.assertEqual({entry["class"] for entry in catalog.values()}, {
            "normative_legal_act", "government_resolution", "academic_textbook",
            "methodological_or_explanatory", "other",
        })
        self.assertEqual(classify("unlisted-government-document", catalog)["status"], "unclassified")
        self.assertEqual(self.corpus["sources"]["medical_roles"]["clause"], "15-2.2.1")

    def test_replay_keeps_expectations_distinct_from_supplied_assessments(self):
        report = benchmark(self.corpus)
        rows = {row["id"]: row for row in report["rows"]}
        self.assertEqual(rows["M01"]["actual"]["mode"], "FULL")
        self.assertFalse(rows["M09"]["actual"]["binding"])
        self.assertEqual(rows["M12"]["actual"]["mode"], "NOT_FOUND")
        self.assertEqual(rows["M02"]["expected"]["binding"], rows["S01"]["expected"]["binding"])
        self.assertFalse(rows["S01"]["expected"]["accepted_full"])
        self.assertEqual(report, benchmark(self.corpus))

    def test_date_inputs_and_distinct_temporal_reference_classes(self):
        cases = {case["id"]: case for case in self.corpus["cases"]}
        dates = cases["S07"]["temporal_context"]
        self.assertEqual(dates["publication_date"], "2019-08-21")
        self.assertEqual(dates["provision_effective_date"], "2020-01-01")
        self.assertEqual(dates["amendment_adoption_date"], "2019-06-27")
        self.assertEqual(cases["S09"]["claim"], cases["S14"]["claim"])
        self.assertNotEqual(cases["S09"]["temporal_context"]["insured_event_date"],
                            cases["S14"]["temporal_context"]["insured_event_date"])
        self.assertFalse(cases["S09"]["expected"]["accepted_full"])
        self.assertTrue(cases["S14"]["expected"]["accepted_full"])

    def test_metric_denominators(self):
        rows = [
            {"expected": {"accepted_full": False, "mode": None}, "actual": {"accepted_full": True, "mode": "FULL"}},
            {"expected": {"accepted_full": True, "mode": "FULL"}, "actual": {"accepted_full": False, "mode": "PARTIAL"}},
        ]
        scores = summarize(rows)
        self.assertEqual(scores["false_acceptance_rate"], {"numerator": 1, "denominator": 1, "value": 1})
        self.assertEqual(scores["false_rejection_rate"], {"numerator": 1, "denominator": 1, "value": 1})
        self.assertEqual(scores["mode_consistency"], {"numerator": 0, "denominator": 2, "value": 0})
        self.assertEqual(scores["missing_condition_detection"]["denominator"], 0)
        self.assertIsNone(scores["missing_condition_detection"]["value"])

    def test_exact_sources_match_local_snapshot_if_available(self):
        path = HERE.parent / ".venv/eval_corpus_snapshot.json"
        if not path.is_file():
            self.skipTest("Full indexed snapshot is a local artifact")
        check_corpus(self.corpus, read(path))
