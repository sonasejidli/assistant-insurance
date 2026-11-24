import json
import unittest

from App.retrieved_sources import annotate, source_cards


class RetrievedSourcesTests(unittest.TestCase):
    def test_identity_and_optional_metadata_survive_serialization(self):
        item = dict(passage_id="p1", document_id="d1", document_title="Act", article="14",
                    subparagraph=None, paragraph=None, clause=None, original_text="Actual excerpt")
        authority = {"sources": [{
            "reference": {"passage_id": "p1", "document": "Act.pdf", "page": 2,
                          "preview_url": "/documents/Act.pdf/preview/0", "version_id": "v1"},
            "provenance": {}, "source_type": "law_or_code", "temporal_status": "reference_date_unspecified",
            "legal_currency_verified": False, "provision": {},
        }]}
        cards = json.loads(json.dumps(source_cards([item, item, {**item, "passage_id": "unknown"}], authority)))
        self.assertEqual([card["id"] for card in cards], ["p1"])
        self.assertEqual(cards[0]["article"], "14")
        self.assertEqual(cards[0]["text"], "Actual excerpt")
        self.assertEqual(cards[0]["url"], "/documents/Act.pdf/preview/0")
        for field in ("effective_date", "official_url", "clause"):
            self.assertIsNone(cards[0][field])

    def test_failures_preserve_candidates_without_releasing_claims(self):
        for delivery, expected in (("provider_timeout", "provider_unavailable"),
                                   ("verification_failed", "verification_rejected")):
            with self.subTest(delivery=delivery):
                response = dict(answer="", sources=[], answer_mode=None, delivery_status=delivery)
                capture = {"retrieved_sources": [{"id": "p1"}]}
                annotate(response, capture, "Sığorta", "az")
                self.assertEqual(response["withheld_reason"], expected)
                self.assertEqual(response["retrieved_sources"], [{"id": "p1"}])
                self.assertEqual(response["verified_citations"], [])
                self.assertEqual(response["answer"], "")

    def test_verified_citations_are_kept_separate(self):
        response = dict(answer="Verified [S1]", sources=[{"id": "S1"}], answer_mode="PARTIAL")
        annotate(response, {"retrieved_sources": [{"id": "p1"}]}, "Sığorta", "az")
        self.assertEqual(response["answer_status"], "verified")
        self.assertEqual(response["verified_citations"], [{"id": "S1"}])
        self.assertEqual(response["retrieved_sources"], [{"id": "p1"}])
