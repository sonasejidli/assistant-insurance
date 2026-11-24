from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import numpy as np
from starlette.requests import Request

from App import main, system, text_search
from App.evaluation_capture import record, recording
from App.observability import stage_timing
from evaluation.gold_framework import read
from evaluation.rag_run import DRAFT, capture_run, evaluate_case, load, replay, save


class RunCaptureTests(TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dataset = read(DRAFT)
        self.run_id = "a" * 32

    def capture(self, ask):
        return capture_run(self.root, self.run_id, self.dataset, {"fixture": True}, ask)

    def test_duplicate_and_atomic_publish(self):
        run = self.capture(lambda case: record(status="returned", answer="fixture"))
        target = run / "AZ7-01.json"
        original = target.read_bytes()
        with self.assertRaises(FileExistsError):
            self.capture(lambda case: self.fail("duplicate run executed"))
        with self.assertRaises(FileExistsError):
            save(target, {"answer": "replacement"})
        self.assertEqual(target.read_bytes(), original)
        target.write_bytes(original.replace(b"fixture", b"altered"))
        with self.assertRaisesRegex(ValueError, "checksum"):
            load(target)

    def test_configured_concurrency_is_bounded_and_keeps_case_records_separate(self):
        pair = Barrier(2, timeout=5)
        lock = Lock()
        active = maximum = 0

        def ask(case):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(active, maximum)
            if case["id"] in {"AZ7-01", "AZ7-02"}:
                pair.wait()
            record(status="returned", answer=case["id"])
            with lock:
                active -= 1

        run = capture_run(self.root, self.run_id, self.dataset, {"concurrency": 2}, ask)
        self.assertEqual(maximum, 2)
        for case in self.dataset["queries"]:
            key = case["id"]
            self.assertEqual(load(run / f"{key}.json")["answer"], key)

    def test_incomplete_run_and_failed_stage_are_distinct(self):
        @stage_timing("dense")
        def fail():
            raise RuntimeError("secret error details")

        def ask(case):
            if case["id"] == "AZ7-01":
                fail()
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.capture(ask)
        run = self.root / self.run_id
        report = replay(run, self.dataset)
        self.assertFalse(report["summary"]["operational"]["completion_recorded"])
        first, second, *_ = report["rows"]
        self.assertEqual(first["operational"]["status"], "failed")
        self.assertEqual(first["operational"]["stage_failures"][0]["error_type"], "RuntimeError")
        self.assertNotIn("secret error details", (run / "AZ7-01.json").read_text(encoding="utf-8"))
        self.assertEqual(second["operational"]["status"], "missing")
        self.assertIsNone(first["metrics"]["answer_behavior"]["answer_mode_accuracy"])
        self.assertIn("capture", second["unavailable"]["recall@5"])

    def test_replay_preserves_ranking_answer_and_metric_availability(self):
        def ask(case):
            ids = case["required_passage_ids"]
            record(status="returned", answer="  Azerbaijani fixture  \n", mode=case["expected_mode"],
                   ranked_passage_ids=ids[:5], retrieval_limit=5)

        run = self.capture(ask)
        target = run / "AZ7-01.json"
        before = target.read_bytes()
        with patch("App.main.ask", side_effect=AssertionError("replay regenerated")):
            first = replay(run, self.dataset)
            second = replay(run, self.dataset)
        self.assertEqual(first, second)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(load(target)["answer"], "  Azerbaijani fixture  \n")
        self.assertEqual(load(target)["ranked_passage_ids"], self.dataset["queries"][0]["required_passage_ids"][:5])
        self.assertIsNotNone(first["rows"][0]["metrics"]["retrieval"]["recall@5"])
        self.assertIn("depth 10", first["rows"][0]["unavailable"]["recall@10"])
        self.assertIsNone(first["rows"][0]["metrics"]["generation"]["answer_correctness"])

    def test_ask_captures_real_stage_outputs_and_exact_model_context(self):
        case = self.dataset["queries"][0]
        hit = {"doc": "fixture", "text": "Sığortaçı müflis olarsa, sığorta ödənişi.",
               "metadata": {"chunk_id": "passage-id", "document_id": "document-id"}}
        retriever = text_search.TextRetriever.__new__(text_search.TextRetriever)
        retriever.settings = text_search.RetrievalSettings()
        retriever.chunks, retriever.documents = [hit], []
        retriever.bm25 = text_search.RetrievalBM25.from_chunks([hit])
        retriever.vector_index = SimpleNamespace(search=lambda *args, **kwargs: [(0, 0.75)])
        retriever.graph = retriever._build_graph()
        request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(retriever=retriever))})
        query = f"  {case['query']}  "
        raw = "  Sığorta ödənişi. [S1]  "
        with (
            patch.object(text_search, "embed", return_value=np.ones((1, 1))),
            patch.object(system, "ChatOpenRouter") as provider,
            patch.object(system, "API_KEY", "never-capture-configured-secret"),
            patch.object(main, "STRUCTURED_ANSWERS", False),
            patch.object(main, "query_experiments", return_value={"provision": False}),
            recording() as row,
        ):
            provider.return_value.invoke.return_value = SimpleNamespace(text=raw)
            response = main.ask(main.Question(question=query, language="az"), request)
            supplied = provider.return_value.invoke.call_args.args[0][1].content
        self.assertEqual(row["query"], query)
        self.assertEqual(row["answer"], response["answer"])
        self.assertEqual(row["mode"], "FULL")
        self.assertEqual(row["ranked_passage_ids"], ["passage-id"])
        branch = row["branches"][0]
        self.assertEqual(branch["dense"][0], {"passage_id": "passage-id", "rank": 1, "score": 0.75})
        self.assertTrue(branch["bm25"])
        self.assertTrue(branch["fusion"])
        self.assertTrue(branch["reranked"])
        self.assertEqual(row["generation_attempts"][0]["output"], raw)
        self.assertEqual(row["generation_attempts"][0]["evidence_context"], supplied.split("\n</context>")[0][10:])
        self.assertEqual(row["citation_passages"], {"S1": "passage-id"})
        self.assertNotIn("never-capture-configured-secret", str(row))
        metrics, unavailable = evaluate_case(case, row, None)
        self.assertEqual(metrics["citation"]["citation_validity"], 1.0)
        self.assertIn("approved review", unavailable["citation_precision"])
        self.assertIn("approved review", unavailable["evidence_support"])
