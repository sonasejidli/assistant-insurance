import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from App import intent, main
from App.evaluation_capture import recording


QUESTION = "Əlillik müəyyən olunarsa, funksiyaların pozulma faizinə görə nə qədər ödənilir?"


class DisabilityPaymentIntentTests(unittest.TestCase):
    def test_payment_question_reaches_retrieval_and_safely_abstains(self):
        retriever = Mock(spec=["search", "documents"])
        retriever.documents = []
        retriever.search.return_value = ([], 0.0)
        with (
            patch.object(intent, "INTENT_LLM_ENABLED", False),
            patch.object(main.app.state, "retriever", retriever, create=True),
            patch.object(main, "query_experiments", return_value=dict.fromkeys(main.query_experiments(), False)),
            patch.dict("os.environ", {"LEGAL_VERIFIED_RELEASE": "1"}),
            recording() as trace,
        ):
            response = TestClient(main.app).post("/ask", json={"question": QUESTION, "language": "az"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(trace["route"], "insurance_question")
        self.assertEqual(trace["standalone_query"], QUESTION)
        retriever.search.assert_called_once_with(QUESTION)
        result = response.json()
        self.assertEqual(result["evidence_status"], "insufficient")
        self.assertNotIn(result["answer_mode"], {"FULL", "PARTIAL"})
        self.assertEqual(result["release_gate"]["released_claims"], [])
        self.assertEqual(result["sources"], [])

    def test_disability_or_payment_language_alone_does_not_match_the_rule(self):
        for question in (
            "Əlillik zamanı funksiyaların pozulma faizi necə ölçülür?",
            "Bu restoranda yeməyə görə nə qədər ödənilir?",
            "Sabah hava necə olacaq?",
            "Fransanın paytaxtı haradır?",
        ):
            with self.subTest(question=question):
                self.assertIn(intent.classify_intent_rule(question), {None, "out_of_scope"})
                with patch.object(intent, "INTENT_LLM_ENABLED", False):
                    response = TestClient(main.app).post("/ask", json={"question": question, "language": "az"})
                self.assertEqual(response.json()["intent"], "out_of_scope")
