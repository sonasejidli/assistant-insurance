import unittest

import httpx

from evaluation.provider_diagnostic import classify, safe_metadata
from App.legal_answers import TruncatedProviderOutput
from evaluation.verified_adversarial import transport
from evaluation.verified_release_benchmark import execute, inputs


class ProviderDiagnosticTests(unittest.TestCase):
    def test_strict_schema_and_completion_status(self):
        row = {"http_status": 200, "finish_reason": "stop"}
        greeting = '{"greeting":"Salam, Azərbaycan!"}'
        self.assertEqual(classify(row, greeting), "success")
        self.assertEqual(classify(row, greeting[:-1] + ', "note": null}'), "success")
        self.assertEqual(classify(row, greeting[:-1] + ', "note": ""}'), "success")
        for output in ("{}", "", "{", '{"greeting":null}', '{"greeting":""}', greeting[:-1] + ',"extra":1}'):
            self.assertEqual(classify(row, output), "malformed_response")
        self.assertEqual(classify({**row, "finish_reason": "length"}, greeting), "truncated")
        self.assertEqual(classify({**row, "finish_reason": "tool_calls"}, greeting), "unexpected_finish")
        self.assertEqual(classify({**row, "refusal": True}, greeting), "refusal")
        self.assertEqual(classify({}, error=httpx.ReadTimeout("private")), "timeout")

    def test_capture_only_allowlisted_metadata(self):
        response = httpx.Response(429, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
                                  headers={"Retry-After": "2", "X-Request-Id": "req-123", "Authorization": "secret"},
                                  json={"error": {"code": 429, "message": "private",
                                                  "metadata": {"limit_source": "upstream_provider_shared_pool",
                                                               "raw": "private"}}})
        row = safe_metadata(response)
        self.assertEqual(row["headers"], {"retry-after": "2", "x-request-id": "req-123"})
        self.assertEqual(row["provider_error_code"], 429)
        self.assertEqual(row["limit_source"], "upstream_provider_shared_pool")
        self.assertNotIn("private", str(row))
        self.assertEqual(classify(row), "rate_limit")

    def test_truncated_generation_never_reaches_binding_or_releases(self):
        dataset, corpus, *_ = inputs()
        base = next(case for case in dataset["cases"] if case["id"] == "E2E-B01")

        def truncated(*_args, **_kwargs):
            raise TruncatedProviderOutput()

        capture = execute({"id": "R01"}, base, corpus, True, transport=transport, provider=truncated)
        body = capture["response"]["body"]
        self.assertIsNone(body["answer_mode"])
        self.assertEqual(body["sources"], [])
        self.assertEqual([stage["outcome"] for stage in capture["stages"]
                          if stage["stage"] == "citation_validation"], ["truncated_output"] * 2)
