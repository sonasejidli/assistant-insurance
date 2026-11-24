import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from pydantic import ValidationError

from App import legal_answers, vector_store
from App.evaluation_capture import ProviderBudgetExceeded, invoke_provider, provider_error, recording
from evaluation.verified_qualification import prequalify, redact


class QualificationTests(TestCase):
    def test_existing_controls_prequalify(self):
        controls = prequalify(None)
        self.assertEqual({key: value["expected_mode"] for key, value in controls.items()},
                         {"R01": "FULL", "R02": "PARTIAL"})

    def test_draft_schema_and_wrapper_preserve_unicode_and_ids(self):
        body = {"evidence_status": "partial", "claims": [{"text": "Sığorta ödənişi", "source_ids": ["S1"]}]}
        with patch.dict("os.environ", {"LEGAL_VERIFIED_RELEASE": "1"}):
            for ascii_only in (True, False):
                raw = json.dumps(body, ensure_ascii=ascii_only)
                for output in (raw, "```json\n" + raw + "\n```"):
                    claim = legal_answers.validate_provider_json(legal_answers.Draft, output).claims[0]
                    self.assertEqual((claim.text, claim.source_ids, claim.part), ("Sığorta ödənişi", ["S1"], None))
            self.assertIsNone(legal_answers.validate_provider_json(
                legal_answers.Draft, json.dumps({**body, "clarification": None})).clarification)
            for bad in ("", "{", json.dumps({**body, "extra": True}), json.dumps({
                **body, "claims": [{**body["claims"][0], "id": "duplicate"}] * 2
            })):
                with self.subTest(bad=bad), self.assertRaises(ValidationError):
                    legal_answers.validate_provider_json(legal_answers.Draft, bad)
            bad_source = legal_answers.Claim.model_validate({**body["claims"][0], "source_ids": [""]})
            self.assertFalse(legal_answers.claim_is_bound(bad_source, {}, set()))

    def test_budget_blocks_additional_transport_and_headers_allowlist(self):
        policy = {"max_calls": 1}
        with recording(retry_policy=policy) as row:
            with patch("App.evaluation_capture.sleep") as sleep:
                self.assertEqual(invoke_provider(lambda *_a, **_k: "ok", [], config={}, purpose="generation"), "ok")
                with self.assertRaises(ProviderBudgetExceeded):
                    invoke_provider(lambda *_a, **_k: self.fail("Unexpected call"), [], config={}, purpose="judge")
                sleep.assert_not_called()
            self.assertTrue(row["provider_budget_exhausted"])
        response = SimpleNamespace(status_code=429, headers={
            "retry-after": "2", "x-ratelimit-limit-requests": "20", "authorization": "secret",
            "x-ratelimit-remaining-tokens": "not-a-number",
        }, json=lambda: {})
        metrics = provider_error(SimpleNamespace(response=response), None)
        self.assertEqual(metrics["retry_after_seconds"], 2)
        self.assertEqual(metrics["rate_limit"], {"x-ratelimit-limit-requests": 20})
        self.assertNotIn("secret", json.dumps(metrics))

    def test_redaction_excludes_credentials(self):
        self.assertEqual(redact("Bearer abc-123 test@example.com"), "[redacted] [redacted]")

    def test_prepared_guard_rejects_an_existing_point_with_incompatible_fingerprint(self):
        chunks = [{"doc": "public.txt", "text": "Text"}]
        configuration = {"dimensions": 2, "model_repository": "synthetic"}
        with TemporaryDirectory() as temp, patch.multiple(
            vector_store, QDRANT_URL="", QDRANT_PATH=str(Path(temp) / "qdrant")
        ):
            with patch.dict("os.environ", {"RAG_REQUIRE_PREPARED_INDEX": "0"}):
                index = vector_store.QdrantIndex(chunks, ["Text"], lambda *_a, **_k: [[1, 0]],
                                                 configuration=configuration)
                try:
                    index.client.set_payload(index.collection, {"embedding_fingerprint": "invalid"}, index.point_ids)
                finally:
                    index.close()
            with (patch.dict("os.environ", {"RAG_REQUIRE_PREPARED_INDEX": "1"}),
                  self.assertRaisesRegex(RuntimeError, "Incompatible point")):
                vector_store.QdrantIndex(chunks, ["Text"], lambda *_a, **_k: self.fail("Unexpected encoding"),
                                         configuration=configuration)
