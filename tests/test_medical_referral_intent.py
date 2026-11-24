import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from App import document_processing, intent, legal_answers, main, query_plan, system
from App.evaluation_capture import recording


MEDICAL_QUESTIONS = (
    "Hansı xidmətlər üçün poliklinikadan göndəriş almalıyam?",
    "Hansı xidmətlər üçün poliklinikadan göndəriş almalıyıq?",
    "İcbari tibbi sığorta ilə hansı tibbi xidmətlərdən istifadə edə bilərəm?",
    "Hansı tibbi xidmətlər üçün ailə həkiminin göndərişi lazımdır?",
    "Göndəriş olmadan hansı tibbi xidmətlərdən yararlanmaq mümkündür?",
    "Tibbi sığorta hansı xidmətləri qarşılayır?",
    "HANSI XIDMETLER UCUN POLIKLINIKADAN GONDERIS ALMALIYAM?",
)
UNRELATED_QUESTIONS = (
    "Sabah hava necə olacaq?",
    "Pasta necə bişirilir?",
    "Poçt göndərişini necə izləyə bilərəm?",
    "Poliklinikanın ünvanı haradadır?",
    "Hansı internet xidmətlərindən istifadə edə bilərəm?",
)


class MedicalReferralIntentTests(unittest.TestCase):
    def test_ask_distinguishes_missing_evidence_from_unrelated_questions(self):
        client = TestClient(main.app)
        experiments = dict.fromkeys(main.query_experiments(), False)
        with (
            patch.object(intent, "INTENT_LLM_ENABLED", False),
            patch.object(main, "query_experiments", return_value=experiments),
            patch.object(main, "STRUCTURED_ANSWERS", True),
            patch.object(main.verified_release, "enabled", return_value=False),
            patch.object(main.source_authority, "enabled", return_value=False),
            patch.object(main, "generate_legal_answer") as generate,
        ):
            for question in MEDICAL_QUESTIONS + UNRELATED_QUESTIONS:
                with self.subTest(question=question):
                    in_scope = question in MEDICAL_QUESTIONS
                    retriever = Mock(spec=["search"])
                    retriever.search.return_value = ([], 0.0)
                    with patch.object(main.app.state, "retriever", retriever, create=True), recording() as trace:
                        response = client.post("/ask", json={"question": question, "language": "az"})
                    self.assertEqual(response.status_code, 200)
                    result = response.json()
                    self.assertEqual(trace["route"], "insurance_question" if in_scope else "out_of_scope")
                    self.assertEqual(trace["standalone_query"], question)
                    self.assertEqual(result["sources"], [])
                    if in_scope:
                        retriever.search.assert_called_once_with(question)
                        self.assertEqual(trace["ranked_passage_ids"], [])
                        self.assertEqual(trace["mode"], "NOT_FOUND")
                        self.assertEqual(result["evidence_status"], "insufficient")
                        self.assertEqual(result["answer"], system.limited_answer("az"))
                    else:
                        retriever.search.assert_not_called()
                        self.assertEqual(result["intent"], "out_of_scope")
                        self.assertEqual(trace["decision_reason"], "out_of_scope")
                        self.assertIsNone(trace["mode"])
            generate.assert_not_called()

    def test_referral_rule_does_not_require_the_optional_model(self):
        with patch.object(query_plan, "classify_intent_llm", side_effect=AssertionError("Unexpected classifier call")):
            for question in MEDICAL_QUESTIONS:
                with self.subTest(question=question):
                    self.assertEqual(intent.classify_intent_rule(question), "insurance_question")
                    resolution = main.resolve_request(question, [], direct_article=False)
                    self.assertEqual(query_plan.plan_query(resolution, "az").intent, "insurance_question")

    def test_retrieved_but_insufficient_evidence_abstains(self):
        question = MEDICAL_QUESTIONS[0]
        document = document_processing.process_document(
            "Maddə 2. Sığorta müqaviləsi\n2.1. Müqavilə yazılı formada tərtib olunur.",
            "unrelated-insurance-fixture.txt",
        )
        passage = document["chunks"][-1]
        retriever = Mock(spec=["search", "documents"])
        retriever.documents = [document]
        retriever.search.return_value = ([passage], 0.8)
        with (
            patch.object(main.app.state, "retriever", retriever, create=True),
            patch.object(main, "query_experiments", return_value=dict.fromkeys(main.query_experiments(), False)),
            patch.object(main, "STRUCTURED_ANSWERS", True),
            patch.object(main.verified_release, "enabled", return_value=False),
            patch.object(main.source_authority, "enabled", return_value=False),
            patch.multiple(legal_answers, API_KEY="fixture", LLM_MODEL="fixture"),
            patch.object(legal_answers, "invoke", return_value='{"evidence_status":"insufficient","claims":[]}') as draft,
            recording() as trace,
        ):
            response = TestClient(main.app).post("/ask", json={"question": question, "language": "az"})
        draft.assert_called_once()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(trace["route"], "insurance_question")
        self.assertEqual(trace["ranked_passage_ids"], [passage["metadata"]["chunk_id"]])
        self.assertEqual(trace["mode"], "NOT_FOUND")
        self.assertEqual(trace["decision_reason"], "insufficient_evidence")
        self.assertEqual(response.json()["answer"], system.limited_answer("az"))
        self.assertEqual(response.json()["sources"], [])
