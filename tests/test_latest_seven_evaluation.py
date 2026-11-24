import copy
import csv
import hashlib
from pathlib import Path
import unittest

from evaluation.evaluate_latest_seven import evaluate, score, validate
from evaluation.gold_framework import HERE, read


class LatestSevenEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = read(HERE / "latest_seven_dataset.json")
        cls.snapshot = HERE.parent / cls.dataset["snapshot"]

    def test_schema_and_unobserved_metrics(self):
        validate(self.dataset)
        report = evaluate(self.dataset, {})
        self.assertEqual(len(report["rows"]), 7)
        self.assertTrue(all(row == {"n": 0, "mean": None} for row in report["summary"].values()))
        self.assertTrue(all(row["error_labels"] is None for row in report["rows"]))

    def test_sources_match_frozen_export(self):
        if not self.snapshot.is_file():
            self.skipTest("Provide the frozen API export to run full source verification")
        documents = read(self.snapshot)
        validate(self.dataset, documents)
        altered = copy.deepcopy(self.dataset)
        altered["queries"][0]["evidence"][0]["page"] += 1
        with self.assertRaisesRegex(ValueError, "PDF locator mismatch"):
            validate(altered, documents)

    def test_multipart_mode_and_unresolved_evidence(self):
        for row_index, modes in ((3, ["FULL", "NOT_FOUND"]), (4, ["FULL", "PARTIAL"])):
            case = self.dataset["queries"][row_index]
            self.assertEqual([part["expected_mode"] for part in case["parts"].values()], modes)
            self.assertEqual(case["expected_mode"], "PARTIAL")
        altered = copy.deepcopy(self.dataset)
        altered["queries"][3]["parts"]["Q2"]["unresolved"] = []
        with self.assertRaisesRegex(ValueError, "unresolved"):
            validate(altered)
        land = self.dataset["queries"][6]
        self.assertEqual([ref["clause"] for ref in land["evidence"] if ref["role"] == "direct"], ["14.5.1-1.9"])
        self.assertEqual([ref["page"] for ref in land["evidence"] if ref["clause"] == "14.5.6"], [10, 11])

    def test_scoring_requires_attribution_and_respects_top_ten(self):
        case = self.dataset["queries"][4]
        ids = case["parts"]["Q2"]["required_passage_ids"]
        observed = {
            "query": case["query"], "answer": "Synthetic test fixture", "artifact": "unit test",
            "ranked_passage_ids": [f"irrelevant-{i}" for i in range(10)] + ids,
            "part_passage_ids": {"Q2": ids}, "mode": "FULL",
        }
        metrics, blocked = score(case, observed)
        self.assertEqual(metrics["mrr@10"], 0)
        self.assertEqual(metrics["recall@10"], 0)
        self.assertEqual(metrics["multipart_evidence_coverage"], 3 / 8)
        self.assertFalse(metrics["answer_mode_accuracy"])
        self.assertIn("citation_precision", blocked)
        observed["part_passage_ids"] = {"Q1": [ids[0]]}
        self.assertEqual(score(case, observed)[0]["multipart_evidence_coverage"], 0)

    def test_legacy_fixture_count_and_locked_hashes(self):
        with (HERE / "insurance_queries.tsv").open(encoding="utf-8", newline="") as stream:
            queries = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(len(queries), 108)
        self.assertEqual(len({row["id"] for row in queries}), 108)
        for name, expected in read(HERE / "benchmark_lock.json")["legacy"].items():
            actual = hashlib.sha256((HERE / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            self.assertEqual(actual, expected, name)

    def test_citation_review_is_bound_to_output_and_pipeline_errors_need_trace(self):
        case = self.dataset["queries"][6]
        supported, *related = case["evidence"]
        answer = "Synthetic test fixture"
        observed = {
            "query": case["query"], "answer": answer, "artifact": "unit test",
            "generation_review": {
                "status": "approved", "reviewer": "unit test", "expertise": "fixture",
                "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                "correct": False,
                "citations": [
                    {"part": "Q1", "passage_id": supported["passage_id"], "supports_claim": True},
                    {"part": "Q1", "passage_id": related[0]["passage_id"], "supports_claim": False},
                ],
            },
        }
        metrics, _ = score(case, observed)
        self.assertEqual(metrics["citation_precision"], 0.5)
        self.assertEqual(metrics["citation_completeness"], 1.0)
        self.assertFalse(metrics["answer_correctness"])
        observed["error_labels"] = [{"label": "Reranking failure", "evidence": "answer text"}]
        with self.assertRaisesRegex(ValueError, "evidence locator"):
            evaluate(self.dataset, {case["id"]: observed})
        observed["answer"] += " changed"
        with self.assertRaisesRegex(ValueError, "unbound"):
            score(case, observed)
