import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from App import legal_documents, main, observability, text_search
from evaluation.archive_legal_source import archive
from evaluation.check_quality_policy import validate
from evaluation.evaluate_platform import ROOT, answer_agreement, gold_approved, pending_answers, read, review_packet
from evaluation.summarize_rag_telemetry import summarize


class PlatformEvaluationTests(unittest.TestCase):
    def test_pending_gold_and_answer_packets_cannot_pass(self):
        dataset = read(ROOT / "real_insurance_dataset.json")
        gold = review_packet(dataset)
        self.assertEqual(len(gold["queries"]), 164)
        self.assertFalse(gold_approved(dataset, gold))
        answers = pending_answers(dataset)
        self.assertEqual(len(answers["examples"]), 36)
        with self.assertRaises(ValueError):
            answer_agreement(answers)

    def test_quality_policy_checks_approved_floors(self):
        policy = {"status": "approved", "reviewer": "fixture", "dataset_sha256": "test",
                  "retrieval_floors": {"rrf": {"recall@10": .8}}, "answer_floors": {"faithfulness": {"human_pass_rate": .9}}}
        retrieval = {"gold": True, "dataset_sha256": "test", "summary": {"overall": {"rrf": {"recall@10": .75}}}}
        self.assertEqual(len(validate(policy, retrieval, {"faithfulness": {"human_pass_rate": .95}})), 1)
        retrieval["gold"] = False
        with self.assertRaises(ValueError):
            validate(policy, retrieval, {})

    def test_http_trace_excludes_query_and_history(self):
        question = "Salam"
        history = "My medical record includes patient alice@example.test"
        with patch.object(observability, "export_trace") as exporter:
            response = TestClient(main.app).post("/ask", json={"question": question, "history": [history]})
        self.assertEqual(response.status_code, 200)
        trace = exporter.call_args.args[0]
        self.assertNotIn(question, repr(trace))
        self.assertNotIn(history, repr(trace))
        self.assertNotIn("alice@example.test", repr(trace))
        self.assertEqual(summarize([trace])["routing"], {"greeting": 1})

    def test_version_registry_is_bound_to_source_bytes_and_temporal_filter(self):
        body = b"Source text"
        document = {"metadata": {}, "chunks": [{"metadata": {}, "doc": "law.txt", "text": "Example"}]}
        provenance = {"version_id": hashlib.sha256(body).hexdigest(), "effective_from": "2023-01-01",
                      "effective_until": "2023-12-31", "source_url": "https://example.test/mandatory"}
        legal_documents.version_metadata(document, body, provenance)
        hit = document["chunks"][0]
        self.assertTrue(text_search.matches_filters(hit, {"as_of": "2023-06-01"}))
        self.assertFalse(text_search.matches_filters(hit, {"as_of": "2024-01-01"}))
        legal_documents.version_metadata(document, body + b" revision", provenance)
        self.assertIsNone(hit["metadata"]["source_url"])
        self.assertFalse(text_search.matches_filters(hit, {"as_of": "2023-06-01"}))

    def test_archiving_preserves_old_bytes(self):
        with tempfile.TemporaryDirectory() as area:
            directory = Path(area)
            source = directory / "source.txt"
            source.write_bytes(b"first")
            old, _ = archive(source, directory, "civil-code")
            source.write_bytes(b"second")
            new, _ = archive(source, directory, "civil-code")
            self.assertNotEqual(old, new)
            self.assertEqual(old.read_bytes(), b"first")
            self.assertEqual(new.read_bytes(), b"second")
