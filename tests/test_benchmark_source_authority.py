from collections import Counter
import unittest

from evaluation.benchmark_source_authority import ROOT, check_snapshot, evaluate, metrics
from evaluation.gold_framework import HERE, digest, read


class SourceAuthorityBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = evaluate(ROOT)
        cls.rows = {row["id"]: row for row in cls.report["rows"]}

    def test_frozen_unique_splits_and_exact_index_extract(self):
        expected = read(ROOT / "expected.json")
        corpus = read(ROOT / "sources.json")
        self.assertEqual(digest(corpus), expected["source_sha256"])
        self.assertEqual(Counter(row["split"] for row in self.rows.values()),
                         {"baseline": 15, "development": 11, "stress": 13})
        self.assertEqual(Counter(row["origin"] for row in self.rows.values()),
                         {"source_derived": 15, "synthetic_engineering": 24})
        snapshot = HERE.parent / ".venv/eval_corpus_snapshot.json"
        if snapshot.exists():
            check_snapshot(corpus, read(snapshot))

    def test_pipeline_keeps_context_without_using_it_as_legal_evidence(self):
        for key in ("E02", "E03"):
            row = self.rows[key]["observed"]
            self.assertEqual(row["enabled"]["ranking"], row["disabled"]["ranking"])
            self.assertEqual(row["enabled"]["packed"]["S2"]["authority_role"], "context_only")
            self.assertEqual(row["enabled"]["judge_reference_ids"], [])
            self.assertEqual(row["enabled"]["returned_reference_ids"], [])
            self.assertTrue(row["disabled"]["returned_reference_ids"])
        self.assertTrue(self.rows["E01"]["observed"]["enabled"]["returned_reference_ids"])
        self.assertEqual(self.rows["E04"]["observed"]["enabled"]["returned_reference_ids"], [])

    def test_invariants_and_conflicts_keep_separate_evidence(self):
        for key in ("I01", "I02", "I03", "I04"):
            self.assertTrue(self.rows[key]["observed"]["authority_unchanged"])
        self.assertTrue(self.rows["T14"]["observed"]["timeline_unchanged"])
        self.assertTrue(self.rows["I05"]["observed"]["reference_expected"])
        for key in ("C01", "C05", "C06", "C07"):
            conflict, = self.rows[key]["observed"]["conflicts"]
            self.assertIsNone(conflict["resolution"])
            self.assertTrue(conflict["requires_expert_review"])

    def test_metric_denominators_and_error_direction(self):
        samples = [{"id": "sample", "checks": [
            {"metric": "conflict_false_positive_rate", "expected": 0, "actual": 1, "passed": False,
             "path": ["potential_conflicts"], "failure_type": "mechanical", "explanation": "Example"}
        ]}]
        scored = metrics(samples, ["conflict_false_positive_rate", "scope_distinction_accuracy"])
        self.assertEqual(scored["conflict_false_positive_rate"]["numerator"], 1)
        self.assertEqual(scored["conflict_false_positive_rate"]["failed_fixture_ids"], ["sample"])
        self.assertEqual(scored["scope_distinction_accuracy"]["denominator"], 0)
        self.assertIsNone(scored["scope_distinction_accuracy"]["percentage"])
