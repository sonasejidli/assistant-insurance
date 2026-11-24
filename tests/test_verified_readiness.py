import json
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from App import main, verified_release
from evaluation.verified_adversarial import report, run
from evaluation.verified_live_provider import classify


class VerifiedReadinessTests(TestCase):
    def test_adversarial_serialized_release_and_replay(self):
        capture = run()
        first = report(deepcopy(capture))
        second = report(deepcopy(capture))
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        for row in first["rows"]:
            with self.subTest(fixture=row["id"]):
                self.assertTrue(row["passed"], row)
        row = next(row for row in first["rows"] if row["id"] == "F06")
        self.assertEqual(row["provider_outcomes"], ["retry_budget_exhausted"])

    def test_opt_in_and_safe_failure_logging(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        secret = "synthetic-secret-do-not-export"

        @verified_release.enforce
        def wrapped(question, _request):
            if verified_release.enabled():
                raise RuntimeError(secret)
            return {"answer": "unchanged"}

        question = main.Question(question="Sığorta ödənişi nə vaxt verilir?")
        with patch.dict("os.environ", {"LEGAL_VERIFIED_RELEASE": "0"}):
            self.assertEqual(wrapped(question, request), {"answer": "unchanged"})
        with patch.dict("os.environ", {"LEGAL_VERIFIED_RELEASE": "1", "RAG_METRICS_LOG_ENABLED": "1"}):
            with self.assertLogs("App.verified_release") as logs:
                response = wrapped(question, request)
        self.assertIsNone(response["answer_mode"])
        self.assertEqual(response["sources"], [])
        self.assertNotIn(secret, json.dumps(response) + str(logs.output))

    def test_provider_classification_uses_available_metadata(self):
        examples = [
            ({}, None, {"http_status": 429}, "rate_limit"),
            ({}, None, {"http_status": 401}, "provider_configuration"),
            ({}, None, {"error_type": "ReadTimeout"}, "timeout"),
            ({}, None, {"error_type": "ConnectError"}, "transport_failure"),
            ({"output": ""}, "invalid_schema", {}, "empty_output"),
            ({"output": "{"}, "invalid_schema", {}, "malformed_output"),
            ({"output": "{}"}, "invalid_binding", {}, "invalid_citation"),
            ({"output": "{", "finish_reason": "length"}, "invalid_schema", {}, "output_truncation"),
        ]
        for attempt, outcome, call, expected in examples:
            with self.subTest(expected=expected):
                self.assertEqual(classify(attempt, outcome, call), expected)
