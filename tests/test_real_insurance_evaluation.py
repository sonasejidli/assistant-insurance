import json
from pathlib import Path
import tempfile
import unittest

from evaluation.build_real_insurance_dataset import digest
from evaluation.evaluate_real_insurance import diagnosis, quality, read_archives, verified_approval
from evaluation.prepare_real_insurance_review import label_review


class RealInsuranceEvaluationTests(unittest.TestCase):
    def test_draft_labels_never_count_as_expert_approved(self):
        dataset = {"queries": [{"id": "AZR001"}]}
        packet = label_review(dataset)
        self.assertFalse(verified_approval(dataset, packet))
        packet["queries"]["AZR001"].update(status="approved", reviewer="Test reviewer", expertise="Test expertise")
        self.assertTrue(verified_approval(dataset, packet))
        self.assertFalse(verified_approval({**dataset, "revision": 2}, packet))

    def test_recall_counts_each_required_parent_and_excludes_coverage_gaps(self):
        scores = quality({"first": 3, "second": None, "third": 21}, {"first": 3, "second": 2, "third": 1})
        self.assertAlmostEqual(scores["recall@20"], 1 / 3)
        self.assertAlmostEqual(scores["recall@50"], 2 / 3)
        self.assertAlmostEqual(scores["mrr@20"], 1 / 3)
        self.assertIsNone(quality({}, {}))

    def test_diagnosis_records_demoted_source_as_reranking_symptom(self):
        query = {"covered": True, "relevant_parent_passage_ids": ["p"]}
        category, reason = diagnosis(query, "resolved", {"rrf": {"p": 3}, "reranked": {"p": 9}}, [])
        self.assertEqual(category, "reranking")
        self.assertIn("top five", reason)

    def test_archives_remain_separate_and_reject_stale_source_text(self):
        chunks = [{"doc": "source", "text": "Evidence", "metadata": {"chunk_id": "parent"}}]
        rows = []
        for collection, vector in (("old", [1.0, 0.0]), ("new", [0.0, 1.0])):
            rows.extend([
                {"collection": collection, "points": 1, "vectors": {"size": 2, "distance": "Dot"}},
                {"vector": vector, "payload": {"chunk_id": "parent", "embedding_model": "test", "text": "Evidence"}},
            ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.jsonl"
            path.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
            before, after = read_archives(path, chunks, 2, "test")
            self.assertEqual(before.search([1, 0], [0], 1, score_threshold=0), [(0, 1.0)])
            self.assertEqual(after.search([1, 0], [0], 1, score_threshold=0), [])
            self.assertNotEqual(digest(before.vectors.tolist()), digest(after.vectors.tolist()))
            chunks[0]["text"] = "Changed"
            with self.assertRaisesRegex(ValueError, "Archive mismatch"):
                read_archives(path, chunks, 2, "test")
