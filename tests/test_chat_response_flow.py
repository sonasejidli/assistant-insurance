import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from fastapi.testclient import TestClient

from App import main, verified_release
from evaluation.verified_release_benchmark import execute, inputs


class ChatResponseFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dataset, cls.corpus, *_ = inputs()
        cls.workplace = next(case for case in dataset["cases"] if case["id"] == "E2E-B01")

    def execute(self, case, request_id):
        def send(question, retriever):
            with patch.object(main.app.state, "retriever", retriever, create=True):
                client = TestClient(main.app, raise_server_exceptions=False)
                try:
                    response = client.post("/ask", json=question.model_dump(mode="json"),
                                           headers={"X-Request-ID": request_id})
                finally:
                    client.close()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["x-request-id"], request_id)
            self.assertEqual(response.headers["content-type"], "application/json")
            return response.json()

        return execute({"id": "chat-flow"}, case, self.corpus, True, transport=send)

    def test_internal_binding_retry_serializes_only_the_verified_final(self):
        case = deepcopy(self.workplace)
        attempts = 0

        def reject_first(output, _context):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                draft = json.loads(output)
                draft["claims"][0]["source_ids"] = ["S999"]
                return json.dumps(draft)
            return output

        case["_transform"] = reject_first
        row = self.execute(case, "welcome-turn")
        self.assertEqual(attempts, 2)
        self.assertIn("invalid_binding", [stage.get("outcome") for stage in row["stages"]])
        self.assertEqual(row["client_request_id"], "welcome-turn")
        self.assertEqual(row["response"]["answer_mode"], "FULL")
        self.assertTrue(row["response"]["sources"])
        self.assertNotIn("delivery_status", row["response"])
        self.assertNotIn("S999", str(row["response"]))

    def test_failed_turn_returns_one_notice_and_does_not_contaminate_next_turn(self):
        failed = deepcopy(self.workplace)
        failed["query"] = "Könüllü tibbi sığortanı istədiyim vaxt ləğv edə bilərəmmi?"
        failed["history"] = ["İş qəzası zamanı ziyanı kim ödəyir?"]

        def reject_all(output, _context):
            draft = json.loads(output)
            draft["claims"][0]["source_ids"] = ["S999"]
            return json.dumps(draft)

        failed["_transform"] = reject_all
        row = self.execute(failed, "failed-turn")
        self.assertEqual(len(row["generation_attempts"]), 2)
        self.assertEqual(row["response"]["delivery_status"], "verification_failed")
        self.assertEqual(row["response"]["answer"], "")
        self.assertEqual(row["response"]["sources"], [])
        self.assertIsNone(row["response"]["answer_mode"])
        next_row = self.execute(self.workplace, "independent-turn")
        self.assertNotEqual(row["trace_id"], next_row["trace_id"])
        self.assertEqual(next_row["client_request_id"], "independent-turn")
        self.assertEqual(next_row["response"]["answer_mode"], "FULL")
        self.assertNotIn("delivery_status", next_row["response"])

    def test_broad_workplace_question_does_not_inherit_narrow_release_profile(self):
        case = deepcopy(self.workplace)
        case["query"] = "İş qəzası zamanı ziyanı kim ödəyir?"
        profiles, _ = verified_release.configuration()
        self.assertIn(self.workplace["query"], profiles)
        self.assertNotIn(case["query"], profiles)
        row = self.execute(case, "broad-turn")
        self.assertEqual(row["verified_release"]["generated_mode"], "FULL")
        self.assertIsNone(row["response"]["answer_mode"])
        self.assertEqual(row["response"]["sources"], [])
