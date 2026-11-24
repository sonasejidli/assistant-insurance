import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree

from google import genai
from google.genai import errors, types
from httpx import Response
from httpx2 import MockTransport, ReadTimeout, Response as SDKResponse

from App import gemini_generation, legal_answers
from App.evaluation_capture import recording
from App.system import NOT_FOUND
from evaluation.verified_release_benchmark import execute, inputs


create_sdk_client = genai.Client


def completion(text=None, finish="STOP"):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(
            finish_reason=finish,
            content=types.Content(parts=[types.Part(text=text)] if text is not None else []),
        )],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=400, candidates_token_count=70, total_token_count=485, thoughts_token_count=15,
        ),
        model_version="fixture-model",
    )


class GeminiGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dataset, cls.corpus, *_ = inputs()
        cls.cases = {case["id"]: case for case in dataset["cases"]}

    def setUp(self):
        self.enterContext(patch.object(gemini_generation, "LLM_GENERATION_PROVIDER", "gemini"))
        self.enterContext(patch.object(gemini_generation, "GEMINI_MODEL", "gemini-test"))
        self.enterContext(patch.dict("os.environ", {"GEMINI_API_KEY": "fixture-gemini-key"}))
        self.enterContext(patch.multiple(legal_answers, API_KEY="fixture-openrouter-key", LLM_MODEL="fixture-judge"))
        self.client = self.enterContext(patch.object(genai, "Client"))
        self.generate = self.client.return_value.__enter__.return_value.models.generate_content
        self.enterContext(patch.object(legal_answers, "OpenRouter"))
        self.openrouter = self.enterContext(patch.object(legal_answers, "ChatOpenRouter"))
        self.openrouter.return_value.invoke.return_value = SimpleNamespace(
            text='{"supported":[true]}', response_metadata={"finish_reason": "stop"},
        )

    def exercise(self, case="E2E-B01"):
        return execute({"id": "gemini-test"}, self.cases[case], self.corpus, True, provider=legal_answers.invoke)

    def draft_from_fixture(self, case):
        def generate(*, contents, **_):
            packed = contents.partition("\n</context>")[0].removeprefix("<context>\n")
            tags = ElementTree.fromstring(f"<packed>{packed}</packed>")
            markers = {tag.get("chunk_id"): tag.get("id") for tag in tags}
            claims = [
                {"text": row["text"], "source_ids": [markers[self.corpus["passages"][alias]] for alias in row["sources"]]}
                for row in self.cases[case]["scripted_claims"]
            ]
            return completion(json.dumps({"evidence_status": self.cases[case].get("scripted_status", "sufficient"), "claims": claims},
                                         ensure_ascii=False))
        return generate

    def test_gemini_draft_preserves_azerbaijani_citations_and_openrouter_judge(self):
        self.generate.side_effect = self.draft_from_fixture("E2E-B01")
        row = self.exercise()
        result = row["response"]
        self.assertEqual(result["answer_mode"], "FULL")
        expected = self.cases["E2E-B01"]["scripted_claims"][0]["text"]
        self.assertIn(expected, result["answer"])
        self.assertIn(f"[{result['sources'][0]['id']}]", result["answer"])
        self.assertEqual(result["sources"][0]["passage_id"], self.corpus["passages"]["statute"])
        request = self.generate.call_args.kwargs
        self.assertEqual(request["model"], "gemini-test")
        self.assertEqual(request["config"].response_mime_type, "application/json")
        self.assertIn("Azerbaijani", request["config"].system_instruction)
        self.assertEqual(request["config"].response_json_schema["$defs"]["Claim"]["required"], ["text", "source_ids"])
        self.assertEqual(request["config"].max_output_tokens, legal_answers.LLM_MAX_OUTPUT_TOKENS)
        options = self.client.call_args.kwargs["http_options"]
        self.assertEqual((options.timeout, options.retry_options.attempts), (12000, 1))
        self.openrouter.assert_called_once()
        self.assertEqual(self.openrouter.call_args.kwargs["api_key"], "fixture-openrouter-key")
        self.assertEqual(self.openrouter.call_args.kwargs["model"], "fixture-judge")
        self.assertEqual(self.openrouter.call_args.kwargs["max_tokens"], 220)
        attempt = row["generation_attempts"][0]
        self.assertEqual((attempt["provider"], attempt["finish_reason"]), ("gemini", "STOP"))
        self.assertEqual(attempt["usage"]["reasoning_tokens"], 15)

    def test_partial_and_not_found_use_existing_release_modes(self):
        self.generate.side_effect = self.draft_from_fixture("E2E-B02")
        result = self.exercise("E2E-B02")["response"]
        self.assertEqual(result["answer_mode"], "PARTIAL")
        self.assertTrue(result["sources"])
        self.generate.side_effect = None
        self.generate.return_value = completion('{"evidence_status":"insufficient","claims":[]}')
        row = self.exercise()
        self.assertEqual(row["verified_release"]["generated_mode"], "NOT_FOUND")
        self.assertEqual(row["response"]["sources"], [])
        self.assertIsNone(row["response"]["answer_mode"])

    def test_malformed_truncated_empty_and_blocked_drafts_cannot_release(self):
        valid_json = '{"evidence_status":"sufficient","claims":[{"text":"Sınaq iddiası.","source_ids":["S1"]}]}'
        for response, reason in (
            (completion('{"claims":'), "invalid_schema"),
            (completion(valid_json, "MAX_TOKENS"), "incomplete_output"),
            (completion(), "incomplete_output"),
            (completion(valid_json, "SAFETY"), "incomplete_output"),
        ):
            with self.subTest(response=response):
                self.generate.reset_mock()
                self.generate.return_value = response
                row = self.exercise()
                self.generate.assert_called()
                self.assertEqual(self.generate.call_count, 2)
                self.assertEqual(row["answer_validation"], reason)
                self.assertEqual(row["response"]["delivery_status"], "verification_failed")
                self.assertEqual(row["response"]["answer"], "")
                self.assertEqual(row["response"]["sources"], [])
                self.openrouter.assert_not_called()

    def test_provider_errors_keep_sources_and_answer_withheld_without_retry_or_fallback(self):
        body = {"error": {"code": 429, "message": "private rate limit"}}
        for error, status in (
            (errors.ClientError(429, body, Response(429, json=body, headers={"retry-after": "30"})), "provider_rate_limit"),
            (errors.ServerError(503, {"error": {"message": "private error"}}), "provider_unavailable"),
            (ReadTimeout("private timeout"), "provider_timeout"),
            (errors.ClientError(400, {"error": {"message": "API key not valid"}}), "internal_error"),
        ):
            with self.subTest(error=type(error).__name__):
                self.generate.reset_mock()
                self.generate.side_effect = error
                row = self.exercise()
                self.generate.assert_called_once()
                self.openrouter.assert_not_called()
                self.assertEqual(row["response"]["delivery_status"], status)
                self.assertEqual(row["response"]["answer"], "")
                self.assertEqual(row["response"]["sources"], [])
                self.assertEqual(row["answer_failure"]["stage"], "generation")
                self.assertEqual(row["answer_failure"]["model"], "gemini-test")
                if status == "provider_rate_limit":
                    self.assertEqual(row["answer_failure"]["retry_after_seconds"], 30)
                    self.assertNotIn("private rate limit", str(row["response"]))

    def test_existing_judge_can_withhold_a_successful_gemini_draft(self):
        self.generate.side_effect = self.draft_from_fixture("E2E-B01")
        self.openrouter.return_value.invoke.return_value.text = '{"supported":[false]}'
        row = self.exercise()
        self.generate.assert_called_once()
        self.openrouter.assert_called_once()
        self.assertEqual(row["response"]["delivery_status"], "verification_failed")
        self.assertEqual(row["response"]["sources"], [])
        self.assertIsNone(row["response"]["answer_mode"])

    def test_failed_retry_cannot_release_a_fragment_from_the_previous_draft(self):
        first = self.draft_from_fixture("E2E-B01")

        def draft_with_bad_binding(**kwargs):
            value = json.loads(first(**kwargs).text)
            value["claims"].append({"text": "Bu iddianın mənbəyi yoxdur.", "source_ids": ["S999"]})
            return completion(json.dumps(value, ensure_ascii=False))

        self.generate.side_effect = lambda **kwargs: (
            draft_with_bad_binding(**kwargs) if self.generate.call_count == 1 else completion('{"claims":')
        )
        row = self.exercise()
        self.assertEqual(self.generate.call_count, 2)
        self.assertEqual(row["generation_attempts"][0]["sources"], row["generation_attempts"][1]["sources"])
        self.assertEqual([attempt["validation"] for attempt in row["generation_attempts"]],
                         ["invalid_binding", "invalid_schema"])
        self.openrouter.assert_not_called()
        self.assertEqual(row["answer_validation"], "invalid_schema")
        self.assertEqual(row["response"]["delivery_status"], "verification_failed")
        self.assertEqual(row["response"]["sources"], [])

    def test_judge_rate_limit_is_attributed_to_openrouter_without_duplicate_calls(self):
        self.generate.side_effect = self.draft_from_fixture("E2E-B01")
        from httpx import HTTPStatusError, Request

        request = Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = Response(429, request=request, headers={"retry-after": "5"}, json={"error": {"code": 429}})
        self.openrouter.return_value.invoke.side_effect = HTTPStatusError("rate limited", request=request, response=response)
        row = self.exercise()
        self.generate.assert_called_once()
        self.openrouter.return_value.invoke.assert_called_once()
        self.assertEqual(row["response"]["delivery_status"], "provider_rate_limit")
        self.assertEqual(row["response"]["sources"], [])
        self.assertEqual(row["answer_failure"]["stage"], "faithfulness")
        self.assertEqual(row["answer_failure"]["provider"], "openrouter")
        self.assertEqual(row["answer_failure"]["retry_after_seconds"], 5)

    def test_missing_key_or_project_identifier_never_connects(self):
        for key in ("", "gen-lang-client-fixture"):
            with self.subTest(key=key), patch.dict("os.environ", {"GEMINI_API_KEY": key}):
                row = self.exercise()
                self.client.assert_not_called()
                self.openrouter.assert_not_called()
                self.assertEqual(row["response"]["delivery_status"], "internal_error")
                self.assertEqual(row["response"]["sources"], [])

    def test_openrouter_generation_still_runs_when_selected(self):
        draft = '{"evidence_status":"insufficient"}'
        self.openrouter.return_value.invoke.return_value.text = draft
        with patch.object(gemini_generation, "LLM_GENERATION_PROVIDER", "openrouter"), recording() as trace:
            self.assertEqual(legal_answers.invoke("prompt", "<context>\nsource", tokens=80), draft)
        self.client.assert_not_called()
        self.assertEqual(trace["generation_attempts"][0]["provider"], "openrouter")
        self.assertEqual(self.openrouter.call_args.kwargs["max_tokens"], 80)

    def test_sdk_serializes_existing_schema_and_uses_server_header(self):
        requests = []

        def transport(request):
            requests.append(request)
            return SDKResponse(200, json={
                "candidates": [{"finishReason": "STOP", "content": {"parts": [
                    {"text": '{"evidence_status":"insufficient","claims":[]}'},
                ]}}],
            })

        def client(**kwargs):
            options = kwargs["http_options"]
            options.client_args = {"transport": MockTransport(transport)}
            return create_sdk_client(**kwargs)

        self.client.side_effect = client
        output = legal_answers.invoke("Azerbaijani instructions", "<context>\n evidence", tokens=1536)
        self.assertEqual(legal_answers.Draft.model_validate_json(output).evidence_status, "insufficient")
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.headers["x-goog-api-key"], "fixture-gemini-key")
        self.assertNotIn("fixture-gemini-key", str(request.url))
        payload = json.loads(request.content)
        config = payload["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["responseJsonSchema"]["required"], ["evidence_status"])
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Azerbaijani instructions")
        self.openrouter.assert_not_called()
