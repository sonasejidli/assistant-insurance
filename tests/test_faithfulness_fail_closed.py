"""Exercise the real judge parser and serialized release boundary without provider calls."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from xml.etree import ElementTree

from App import legal_answers
from App.evaluation_capture import model_attempt
from evaluation.verified_adversarial import transport
from evaluation.verified_release_benchmark import execute, inputs


class FaithfulnessFailClosedTests(TestCase):
    @classmethod
    def setUpClass(cls):
        dataset, cls.corpus, *_ = inputs()
        cls.cases = {case["id"]: case for case in dataset["cases"]}

    def exercise(self, judge_response, *, finish_reason="stop", base_id="E2E-B01", multipart=False,
                 missing_marker=False, mutation=None):
        case = deepcopy(self.cases[base_id])
        if multipart:
            q2 = deepcopy(self.cases["E2E-B02"]["scripted_claims"][0])
            case["scripted_claims"].append({**q2, "part": "Q2"})
        invoke = legal_answers.invoke
        judge_inputs = []

        def provider(prompt, payload, *, tokens):
            if not payload.startswith("<context>\n"):
                judge_inputs.append(json.loads(payload))
                self.assertEqual(tokens, 220)
                return invoke(prompt, payload, tokens=tokens)
            attempt = model_attempt("offline-fixture", "structured-legal-1", prompt, payload)
            sources = ElementTree.fromstring("<packed>" + attempt["evidence_context"] + "</packed>")
            markers = {node.get("chunk_id"): node.get("id") for node in sources}
            claims = [{"text": spec["text"], "part": spec.get("part"),
                       "source_ids": ["S999" if missing_marker else markers[self.corpus["passages"][source]]
                                      for source in spec["sources"]]}
                      for spec in case["scripted_claims"]]
            output = json.dumps({"claims": claims, "evidence_status": case.get("scripted_status", "sufficient")})
            attempt.update(status="returned", output=output)
            return output

        def transport_stub(*_args, **_kwargs):
            if isinstance(judge_response, Exception):
                raise judge_response
            return SimpleNamespace(text=judge_response, response_metadata={"finish_reason": finish_reason})

        with (patch.object(legal_answers, "API_KEY", "offline-fixture"),
              patch.object(legal_answers, "OpenRouter"),
              patch.object(legal_answers, "ChatOpenRouter"),
              patch.object(legal_answers, "invoke_provider", side_effect=transport_stub)):
            row = execute({"id": "offline-judge", "mutation": mutation}, case, self.corpus, True,
                          transport=transport, provider=provider)
        return row, judge_inputs

    def assert_withheld(self, row):
        self.assertEqual(row["response"]["status"], 200)
        body = row["response"]["body"]
        self.assertIsNone(body["answer_mode"])
        self.assertIsNone(body["release_gate"]["verified_mode"])
        self.assertEqual(body["sources"], [])
        self.assertEqual(body["references"], [])
        self.assertEqual(body["release_gate"]["released_claims"], [])

    def assert_judge_failure(self, row, error_type):
        self.assert_withheld(row)
        self.assertIn({"stage": "faithfulness_error", "error_type": error_type}, row["stages"])
        self.assertNotIn("faithfulness_validation", {event["stage"] for event in row["stages"]})

    def test_length_finish_with_valid_json_still_abstains(self):
        row, inputs = self.exercise('{"supported":[true]}', finish_reason="length")
        self.assertEqual(len(inputs[0]), 1)
        self.assert_judge_failure(row, "TruncatedProviderOutput")

    def test_truncated_json_with_stop_is_rejected(self):
        row, _ = self.exercise('{"supported":[true')
        self.assert_judge_failure(row, "ValidationError")

    def test_missing_and_malformed_assessments_abstain(self):
        for output, error_type in (('{"supported":[]}', "ValueError"),
                                   ("{}", "ValidationError"),
                                   ('{"supported":[1]}', "ValidationError"),
                                   ('{"supported":[true],"explanation":"accepted"}', "ValidationError")):
            with self.subTest(output=output):
                row, _ = self.exercise(output)
                self.assert_judge_failure(row, error_type)

    def test_missing_evidence_reference_cannot_reach_judge(self):
        row, inputs = self.exercise('{"supported":[true]}', missing_marker=True)
        self.assertEqual(inputs, [])
        self.assert_withheld(row)
        self.assertEqual(row["response"]["body"]["delivery_status"], "verification_failed")
        self.assertIn("invalid_binding", [event.get("outcome") for event in row["stages"]])

    def test_missing_packed_evidence_still_fails_independent_binding(self):
        row, inputs = self.exercise('{"supported":[true]}', mutation="corrupt")
        self.assertEqual(len(inputs[0]), 1)
        self.assert_withheld(row)
        verdict = row["verified_release"]["verifier"]
        self.assertTrue(verdict["claims"])
        self.assertFalse(verdict["claims"][0]["citation_valid"])

    def test_incomplete_multipart_judgments_release_nothing(self):
        row, inputs = self.exercise('{"supported":[true]}', base_id="E2E-S04", multipart=True)
        self.assertEqual(len(inputs[0]), 2)
        self.assertTrue(all(item["sources"] for item in inputs[0]))
        self.assert_judge_failure(row, "ValueError")

    def test_provider_timeout_abstains(self):
        row, _ = self.exercise(TimeoutError())
        self.assert_judge_failure(row, "TimeoutError")
        self.assertEqual(row["response"]["body"]["delivery_status"], "provider_timeout")
        self.assertEqual(row["response"]["body"]["answer"], "")

    def test_bound_but_unsupported_claim_cannot_be_released(self):
        row, inputs = self.exercise('{"supported":[false]}')
        self.assertEqual(len(inputs[0]), 1)
        self.assert_withheld(row)
        self.assertEqual(row["response"]["body"]["delivery_status"], "verification_failed")

    def test_supported_claim_keeps_verified_citations(self):
        row, _ = self.exercise('{"supported":[true]}')
        body = row["response"]["body"]
        self.assertEqual(body["answer_mode"], "FULL")
        self.assertNotIn("delivery_status", body)
        self.assertTrue(body["sources"][0]["passage_id"])

    def test_verifier_exception_after_valid_judgment_still_abstains(self):
        with patch("evaluation.verify_legal_scope_v2.verify_case", side_effect=RuntimeError):
            row, inputs = self.exercise('{"supported":[true]}')
        self.assertEqual(len(inputs[0]), 1)
        self.assertIn({"stage": "faithfulness_validation", "accepted": 1, "evaluated": 1}, row["stages"])
        self.assert_withheld(row)
        self.assertEqual(row["verified_release"]["failure"]["stage"], "verification")
