from copy import deepcopy
import hashlib
from unittest import TestCase

from evaluation import gold_framework as gold


class GoldFrameworkTests(TestCase):
    def setUp(self):
        meta = {"chunk_id": "p", "document_id": "d", "article": "12", "clause": "12.1"}
        self.source = {"p": {"metadata": meta, "text": "source"}}
        evidence = {"passage_id": "p", "parent_passage_id": "p", "relevance": 3, "text": "source",
                    "document_id": "d", "article": "12", "clause": "12.1"}
        self.row = {"status": "approved", "reviewer": "test reviewer", "expertise": "test expertise",
                    "revision_history": ["test revision"], "answerability": "answerable", "query": "test",
                    "history": [], "category": "tests", "style": "formal", "diagnostic": False, "groups": ["formal"],
                    "evidence": [evidence], "required_passage_ids": ["p"], "expected_answer": "test answer",
                    "required_qualifications": [], "parts": {"Q1": {"question": "test part", "required_passage_ids": ["p"]}},
                    "draft_part_parents": {"Q1": ["p"]}}
        self.packet = {"schema_version": 1, "dataset_sha256": "dataset", "corpus_sha256": "corpus", "queries": {"a": self.row}}

    def test_pending_cases_are_excluded_and_invalid_source_approval_is_rejected(self):
        pending = deepcopy(self.packet)
        pending["queries"]["a"]["status"] = "pending"
        self.assertEqual(gold.approved_queries(pending, self.packet, self.source), {})
        self.assertEqual(gold.approved_queries(self.packet, self.packet, self.source), {"a": self.row})
        invalid = deepcopy(self.packet)
        invalid["queries"]["a"]["evidence"][0]["clause"] = "12.2"
        with self.assertRaises(ValueError):
            gold.approved_queries(invalid, self.packet, self.source)
        invalid = deepcopy(self.packet)
        invalid["queries"]["a"]["parts"] = {}
        with self.assertRaises(ValueError):
            gold.approved_queries(invalid, self.packet, self.source)

    def test_metrics_separate_evidence_generation_and_behavior(self):
        run = {"rows": [{"id": "a", "answer": "claim", "mode": "PARTIAL", "ranked_passage_ids": ["p"],
                         "part_passage_ids": {"Q2": ["p"]}, "generation_review": {
                             "status": "approved", "reviewer": "reviewer", "expertise": "expertise",
                             "answer_sha256": hashlib.sha256(b"claim").hexdigest(), "rubric_version": "1",
                             "faithfulness": False, "relevancy": True}}]}
        scored = gold.score_run(run, {"a": self.row}, self.source)
        row = scored["rows"]["a"]
        self.assertEqual(row["retrieval"]["recall@10"], 1)
        self.assertFalse(row["retrieval"]["complete_multipart_at_10"])
        self.assertEqual(row["missing_by_part_at_10"], {"Q1": ["p"]})
        self.assertEqual(row["extra_attributions_at_10"], [("Q2", "p")])
        self.assertEqual(row["generation"], {"faithfulness": False, "relevancy": True})
        self.assertFalse(row["behavior"]["answer_mode_accuracy"])
        run["rows"][0]["answer"] = "different"
        with self.assertRaises(ValueError):
            gold.score_run(run, {"a": self.row}, self.source)
        self.assertIsNone(gold.retrieval_scores(["p"], {}))
        with self.assertRaises(ValueError):
            gold.retrieval_scores(["p", "p"], {"p": 3})

    def test_calibration_does_not_retune_after_holdout_failure(self):
        labels = {str(i): {"answerability": status} for i, status in enumerate(
            ["answerable", "partially_answerable", "unanswerable"] * 2)}
        run = {"score_version": "fixture", "configuration_id": "fixture", "rows": [
            {"id": str(i), "mode": "NOT_FOUND", "score": value} for i, value in enumerate((.8, .5, .1, .8, .9, .1))]}
        policy = {"status": "approved", "reviewer": "reviewer", "expertise": "expertise",
                  "score_version": "fixture", "configuration_id": "fixture", "max_unsafe_full": 0,
                  "candidates": [{"full": .7, "partial": .4}, {"full": .95, "partial": .3}],
                  "splits": {"validation": ["0", "1", "2"], "holdout": ["3", "4", "5"]}}
        result = gold.calibrate(run, labels, policy)
        self.assertEqual(result["selected"], policy["candidates"][0])
        self.assertEqual(result["status"], "holdout_safety_failed")
        self.assertEqual(result["holdout_after"]["unsafe_full"], 1)
        policy["splits"]["holdout"][0] = "0"
        with self.assertRaises(ValueError):
            gold.calibrate(run, labels, policy)
