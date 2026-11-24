from unittest import TestCase
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from pydantic import ValidationError

from App import legal_answers, vector_store
from evaluation.verified_adversarial import report, run


class SignoffControls(TestCase):
    def test_only_complete_fenced_json_reaches_the_same_schema(self):
        fenced = '```json\n{"supported":[true]}\n```'
        with patch.dict("os.environ", {"LEGAL_VERIFIED_RELEASE": "1"}):
            self.assertEqual(legal_answers.validate_provider_json(legal_answers.JudgeResult, fenced).supported, [True])
            for invalid in (fenced[:-3], "commentary\n" + fenced, fenced.replace("true", '"true"')):
                with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                    legal_answers.validate_provider_json(legal_answers.JudgeResult, invalid)
        with patch.dict("os.environ", {"LEGAL_VERIFIED_RELEASE": "0"}), self.assertRaises(ValidationError):
            legal_answers.validate_provider_json(legal_answers.JudgeResult, fenced)

    def test_prepared_index_guard_never_encodes_and_reuses_validated_index(self):
        chunks = [{"doc": "public.txt", "text": "Text"}]
        settings = {"dimensions": 2, "model_repository": "synthetic"}
        with TemporaryDirectory() as temp, patch.multiple(
            vector_store, QDRANT_URL="", QDRANT_PATH=str(Path(temp) / "qdrant")
        ):
            with patch.dict("os.environ", {"RAG_REQUIRE_PREPARED_INDEX": "1"}):
                with self.assertRaisesRegex(RuntimeError, "0/1 validated points"):
                    vector_store.QdrantIndex(chunks, ["Text"], self.unexpected_embedding, configuration=settings)
            with patch.dict("os.environ", {"RAG_REQUIRE_PREPARED_INDEX": "0"}):
                vector_store.QdrantIndex(chunks, ["Text"], lambda *_args, **_kwargs: [[1, 0]],
                                         configuration=settings).close()
            with patch.dict("os.environ", {"RAG_REQUIRE_PREPARED_INDEX": "1"}):
                vector_store.QdrantIndex(chunks, ["Text"], self.unexpected_embedding, configuration=settings).close()

    def unexpected_embedding(self, *_args, **_kwargs):
        self.fail("Prepared-index readiness must not encode vectors")

    def test_exact_witness_releases_full_and_partial_through_http(self):
        rows = report(run(ids=("W01", "C02", "E01")))["rows"]
        for row in rows:
            with self.subTest(row=row["id"]):
                self.assertTrue(row["passed"], row)
                self.assertEqual(row["verified"], row["mode"])
                self.assertTrue(row["source_references"])
                self.assertTrue(row["retained_claims"])
                self.assertEqual(row["invalid_citations"], 0)
        multipart = next(row for row in rows if row["id"] == "E01")
        self.assertEqual(multipart["coverage"], {"Q1": True, "Q2": False})
        self.assertIn("Q2", multipart["disclosed_parts"])

    def test_valid_json_with_length_finish_cannot_be_returned(self):
        response = SimpleNamespace(text='{"claims":[]}', response_metadata={"finish_reason": "length"})
        with (patch.object(legal_answers, "ChatOpenRouter"),
              patch.object(legal_answers, "OpenRouter"),
              patch.object(legal_answers, "invoke_provider", return_value=response)):
            with self.assertRaises(legal_answers.TruncatedProviderOutput):
                legal_answers.invoke("prompt", "data", tokens=64)
