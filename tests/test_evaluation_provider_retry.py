from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx
from openrouter.errors import OpenRouterError

from App.evaluation_capture import invoke_provider, provider_error, recording, retry_after_seconds


def rejection(status, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    response = httpx.Response(status, headers=headers, json={"error": {"code": status, "message": "Provider response"}})
    return OpenRouterError("test response", response)


class EvaluationProviderRetryTests(TestCase):
    policy = {"statuses": [429], "retry_connect": False, "max_retries": 1,
              "base_delay_seconds": 1, "max_delay_seconds": 2, "max_wait_seconds": 5}

    def invoke(self, operation):
        return invoke_provider(operation, [], config={}, purpose="generation")

    def test_retry_after_is_honored_and_budget_is_shared(self):
        operation = Mock(side_effect=[rejection(429, "3"), "accepted", rejection(429)])
        with recording(retry_policy=self.policy) as row, patch("App.evaluation_capture.sleep") as sleep:
            self.assertEqual(self.invoke(operation), "accepted")
            with self.assertRaises(OpenRouterError):
                self.invoke(operation)
        sleep.assert_called_once_with(3)
        self.assertEqual([call["outcome"] for call in row["provider_calls"]],
                         ["retry_scheduled", "returned", "retry_budget_exhausted"])
        self.assertEqual(row["provider_calls"][0]["provider_message"], "Provider response")
        self.assertEqual(row["provider_calls"][0]["provider_code"], 429)
        self.assertEqual([call["transport_retry"] for call in row["provider_calls"]], [0, 1, 0])

    def test_wait_budget_does_not_shorten_retry_after(self):
        with recording(retry_policy=self.policy) as row, patch("App.evaluation_capture.sleep") as sleep:
            with self.assertRaises(OpenRouterError):
                self.invoke(Mock(side_effect=rejection(429, "12")))
        sleep.assert_not_called()
        self.assertEqual(row["provider_calls"][0]["outcome"], "wait_budget_exhausted")

    def test_permanent_errors_and_ambiguous_timeouts_do_not_resend(self):
        for error in (rejection(401), rejection(400), httpx.ReadTimeout("timeout")):
            with self.subTest(error=type(error).__name__):
                operation = Mock(side_effect=error)
                with recording(retry_policy=self.policy) as row, self.assertRaises(type(error)):
                    self.invoke(operation)
                self.assertEqual(operation.call_count, 1)
                self.assertEqual(row["provider_calls"][0]["outcome"], "non_retryable")

    def test_retry_dates_and_redacted_provider_payload(self):
        date = datetime.now(timezone.utc) + timedelta(minutes=2)
        self.assertGreater(retry_after_seconds(format_datetime(date, usegmt=True)), 100)
        self.assertIsNone(retry_after_seconds("NaN"))
        response = httpx.Response(429, json={"error": {"code": "quota", "message": "Limit for user@example.com key credential"},
                                            "user_id": "private-id"})
        error = provider_error(OpenRouterError("test", response), "credential")
        self.assertEqual(error["provider_message"], "Limit for [redacted] key [redacted]")
        self.assertNotIn("private-id", str(error))
