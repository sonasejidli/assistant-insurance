import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from App import main, query_plan, query_resolution, verified_release
from App.evaluation_capture import record
from evaluation.legal_answer_quality import inputs
from evaluation.verified_release_benchmark import FIXTURES, create, evaluate, read


class VerifiedReleaseTests(unittest.TestCase):
    def test_optional_citation_metadata_round_trip(self):
        raw = ('<source document_id="doc" chunk_id="a"/>'
               '<source document_id="doc" chunk_id="b" article="" clause=" "/>'
               '<source document_id="doc" chunk_id="c" article="7" clause="7.3"/>')
        packed, before, after = verified_release.canonical_packed(raw)
        self.assertEqual(before[1]["article"], "")
        self.assertEqual(before[1]["clause"], " ")
        self.assertEqual(after, [
            {"document_id": "doc", "chunk_id": "a"},
            {"document_id": "doc", "chunk_id": "b"},
            {"document_id": "doc", "chunk_id": "c", "article": "7", "clause": "7.3"},
        ])
        self.assertEqual(verified_release.canonical_packed(packed)[1:], (after, after))

    def test_multipart_questions_remain_independent(self):
        questions = [
            "İşəgötürənin sığorta vəzifəsi nədir?",
            "Ailə üzvü tibbi sığortadan istifadə edə bilərmi?",
            "Müqavilə bitəndən sonra verilən ərizə necə qiymətləndirilir?",
        ]
        for count in (2, 3):
            with self.subTest(count=count):
                resolution = query_resolution.resolve_query(" ".join(questions[:count]), [])
                plan = query_plan.plan_query(resolution, "az", forced=True, preserve_explicit_parts=True)
                self.assertEqual(len(plan.parts), count)
        resolution = query_resolution.resolve_query("Bəs istisnalar necə?", [questions[0]])
        plan = query_plan.plan_query(resolution, "az", forced=True, preserve_explicit_parts=True)
        self.assertEqual(plan.resolution.history, (questions[0],))

    def test_model_clarification_cannot_bypass_gate(self):
        @verified_release.enforce
        def answer(question, request):
            record(decision_reason="clarification", release_rendered="Unsafe unsupported legal claim")
            return {"answer": "Unsafe unsupported legal claim"}

        with patch.dict("os.environ", {"LEGAL_VERIFIED_RELEASE": "1"}):
            result = answer(main.Question(question="Sığorta ödənişi nə vaxt verilir?"),
                            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))
        self.assertIsNone(result["answer_mode"])
        self.assertNotIn("Unsafe unsupported legal claim", result["answer"])
        self.assertEqual(result["sources"], [])

    def test_http_recovery_serializes_without_supported_mode(self):
        retriever = SimpleNamespace(search=lambda *args, **kwargs: ([], 0), documents=[])
        with (patch.dict("os.environ", {"LEGAL_VERIFIED_RELEASE": "1"}),
              patch.object(main.app.state, "retriever", retriever, create=True)):
            response = TestClient(main.app).post("/ask", json={"question": "Sığorta ödənişi nə vaxt verilir?"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["answer_mode"])
        self.assertEqual(response.json()["sources"], [])

    def test_frozen_capture_replays_deterministically(self):
        suite = read(FIXTURES)
        dataset, corpus, *_ = inputs()
        with TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            create(run, suite, dataset, corpus)
            report = evaluate(run, suite, dataset)
            self.assertEqual(report, evaluate(run, suite, dataset))
        self.assertEqual(len(report["rows"]), 15)
        self.assertEqual(report["metrics"]["after_unsupported_full"], 0)
        self.assertEqual(report["metrics"]["unsupported_final_claims"], 0)
        for case in report["rows"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(all(case["checks"].values()), case["checks"])
