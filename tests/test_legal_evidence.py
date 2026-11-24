import json
import unittest
from copy import deepcopy
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import numpy as np

from App import document_processing, legal_answers, legal_documents, legal_evidence, main, text_search, vector_store
from App.observability import retrieval_trace


SOURCE = """Sığorta haqqında
AZƏRBAYCAN RESPUBLİKASININ QANUNU
Qüvvəyə minmə tarixi: 2024-01-01
I fəsil Ümumi müddəalar
II bölmə Ödəniş qaydaları
Maddə 12. Sığorta ödənişi
12.1.1. Şərt ödənərsə, ödəniş 5 günə edilir. Bu Qanunun 15-3.1-ci maddəsinə əsasən.
Maddə 15-3. İstisnalar
15-3.1. Ödəniş üçün sənəd tələb olunur. Bu Qanunun 12.1.1-ci maddəsi tətbiq edilir.
15-3.2. Məcəllənin müvafiq maddəsinin tələbləri nəzərə alınır.
[1] Redaksiya qeydi.
"""


def indexed(text=SOURCE, name="law.txt"):
    return document_processing.process_document(text, name)


def clause(doc, number):
    return next(hit for hit in doc["chunks"] if hit["metadata"].get("clause") == number)


class LegalEvidenceTests(unittest.TestCase):
    def test_contextual_header_preserves_verified_hierarchy_and_original(self):
        doc = indexed()
        hit = clause(doc, "12.1.1")
        header = legal_documents.contextual_header(hit)
        self.assertIn("Sənəd: Sığorta haqqında", header)
        self.assertIn("Bölmə: II Ödəniş qaydaları", header)
        self.assertIn("Maddə: 12 — Sığorta ödənişi", header)
        self.assertIn("Bənd: 12.1.1", header)
        self.assertIn("2024-01-01", header)
        self.assertEqual(hit["metadata"]["paragraph_number"], "12.1")
        self.assertTrue(hit["metadata"]["original_text"].startswith("12.1.1."))
        self.assertEqual(doc["original_extracted_pages"], [SOURCE])
        self.assertEqual(doc["amendment_notes"], {"1": "Redaksiya qeydi."})

    def test_quality_flags_do_not_strip_numbering_notes_or_mixed_scripts(self):
        raw = "Maddə 12. Sığorta   закон\n12.1. Tə-\nləb �\n[4] Qeyd\n14\n"
        doc = indexed(raw)
        audit = doc["extraction_audit"][0]
        self.assertEqual(audit["possible_page_number_lines"], ["14"])
        self.assertEqual(audit["possible_broken_words"], 1)
        self.assertEqual(audit["malformed_characters"], 1)
        self.assertTrue(audit["mixed_latin_cyrillic"])
        self.assertEqual(doc["original_extracted_pages"], [raw])

    def test_annotation_only_keeps_vector_collection_but_new_input_changes_it(self):
        chunks = indexed()["chunks"]
        legacy = deepcopy(chunks)
        for hit in legacy:
            for key in legal_documents.APP_METADATA:
                hit["metadata"].pop(key, None)
        collections = []
        with patch.multiple(vector_store, QDRANT_PATH="", QDRANT_URL=""):
            for items, contextual in ((legacy, False), (chunks, False), (chunks, True)):
                texts = [text_search.embedding_passage_text(item, contextual=contextual) for item in items]
                index = vector_store.QdrantIndex(items, texts, lambda values, kind: np.asarray([[1.0, 0.0]] * len(values)),
                                                  configuration={"model_repository": "fixture", "dimensions": 2})
                self.addCleanup(index.close)
                collections.append(index.collection)
        self.assertEqual(collections[0], collections[1])
        self.assertNotEqual(collections[1], collections[2])

    def test_circular_expansion_is_bounded_and_unnumbered_is_unresolved(self):
        doc = indexed()
        legal_documents.link_references([doc])
        parent = clause(doc, "12.1.1")
        target = clause(doc, "15-3.1")
        unresolved = clause(doc, "15-3.2")["legal_references"][0]
        self.assertEqual(unresolved["resolution_status"], "unresolved")
        package = legal_evidence.assemble_evidence("Ödəniş üçün sənəd lazımdır?", [parent, parent], [doc])
        self.assertEqual(package.hits[:2], [parent, target])
        self.assertEqual(len({item["passage_id"] for item in package.items}), len(package.items))
        self.assertEqual(package.relationships[0]["referenced_article_id"], "15-3.1")
        self.assertEqual(package.items[1]["retrieval_source"], "cross_reference")

    def test_named_reference_resolves_only_when_identifiable(self):
        a = indexed(SOURCE.replace("Bu Qanunun 15-3.1-ci", "“Başqa sığorta” Qanununun 15-3.1-ci"))
        b = indexed(SOURCE.replace("Sığorta haqqında", "Başqa sığorta haqqında", 1), "other.txt")
        legal_documents.link_references([a])
        self.assertEqual(clause(a, "12.1.1")["legal_references"][0]["resolution_status"], "unresolved")
        legal_documents.link_references([a, b])
        ref = clause(a, "12.1.1")["legal_references"][0]
        self.assertEqual(ref["referenced_document_id"], b["metadata"]["document_id"])
        self.assertEqual(ref["target_passage_ids"], [clause(b, "15-3.1")["metadata"]["chunk_id"]])

    def test_conflicting_versions_kept_but_nonoverlapping_periods_are_distinct(self):
        newer = indexed(SOURCE.replace("5 günə", "7 günə"), "law@2025.txt")
        older = indexed()
        hits = [clause(doc, "12.1.1") for doc in (older, newer)]
        package = legal_evidence.assemble_evidence("Ödəniş?", hits, [older, newer], expand=False)
        self.assertEqual(len(package.items), 2)
        self.assertEqual(len(package.conflicts), 1)
        self.assertTrue(legal_evidence.disjoint_periods({"valid_until": "2023-12-31"}, {"effective_date": "2024-01-01"}))
        _, response = legal_answers.generate_legal_answer("Ödəniş?", package, "az")
        self.assertEqual((response.evidence_status, len(response.references)), ("conflicting", 2))

    def test_structured_checks_citations_numbers_negatives_and_judge(self):
        doc = indexed()
        selected = clause(doc, "12.1.1")
        package = legal_evidence.assemble_evidence("Ödəniş?", [selected], [doc], expand=False)
        evidence = {"S1": package.items[0]}
        for text, source in (("Ödəniş 9 günə edilir.", "S1"), ("Qanunda belə öhdəlik yoxdur.", "S1"),
                             ("Ödəniş 5 günə edilir.", "S100")):
            self.assertFalse(legal_answers.claim_is_bound(legal_answers.Claim(text=text, source_ids=[source]), evidence, set()))
        draft = json.dumps({"evidence_status": "sufficient", "claims": [{"text": "Şərt ödənərsə, ödəniş 5 günə edilir.",
                                                                           "source_ids": ["S1"]}]})
        with patch.object(legal_answers, "API_KEY", "test"), patch.object(legal_answers, "invoke", side_effect=[draft, '{"supported":[true]}']):
            legacy, response = legal_answers.generate_legal_answer("Ödəniş?", package, "az", judge=True)
        self.assertIn("[S1]", legacy)
        self.assertEqual(response.evidence_status, "partial")
        self.assertEqual(response.references[0].article, "12")
        self.assertEqual(response.references[0].paragraph, "12.1")
        self.assertEqual(response.references[0].passage_id, selected["metadata"]["chunk_id"])
        with patch.object(legal_answers, "API_KEY", "test"), patch.object(legal_answers, "invoke", side_effect=[draft, '{"supported":[false]}']):
            _, response = legal_answers.generate_legal_answer("Ödəniş?", package, "az", judge=True)
        self.assertEqual((response.evidence_status, response.references), ("insufficient", []))
        with patch.object(legal_answers, "API_KEY", "test"), patch.object(
            legal_answers, "invoke", side_effect=[draft, TimeoutError("judge unavailable")],
        ):
            _, response = legal_answers.generate_legal_answer("Ödəniş?", package, "az", judge=True)
        self.assertEqual((response.evidence_status, response.references), ("insufficient", []))

    def test_ask_structured_returns_compatible_insufficient_schema(self):
        retriever = SimpleNamespace(search=Mock(return_value=([], 0.0)))
        with patch.object(main, "STRUCTURED_ANSWERS", True), patch.object(main.app.state, "retriever", retriever, create=True):
            response = TestClient(main.app).post("/ask", json={"question": "Sığorta ödənişi necə hesablanır?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["evidence_status"], "insufficient")
        self.assertEqual(response.json()["sources"], [])

    def test_ask_repairs_invalid_reference_and_keeps_deterministic_source_ids(self):
        doc = indexed()
        hit = clause(doc, "12.1.1")
        metadata = hit["metadata"]

        def search(*args, **kwargs):
            retrieval_trace.set({(metadata["document_id"], metadata["chunk_id"]): [{"bm25_rank": 1}]})
            return [hit], 0.9

        retriever = SimpleNamespace(search=search, documents=[doc])
        draft = {"evidence_status": "sufficient", "claims": [{"text": "Şərt ödənərsə, ödəniş 5 günə edilir.",
                                                             "source_ids": ["S1"]}]}
        invalid = deepcopy(draft)
        invalid["claims"][0]["source_ids"] = ["S99"]
        outputs = [json.dumps(invalid), json.dumps(draft), '{"supported":[true]}']
        with patch.object(main, "STRUCTURED_ANSWERS", True), patch.object(main.app.state, "retriever", retriever, create=True), \
                patch.object(main, "generate_legal_answer", partial(legal_answers.generate_legal_answer, judge=True)), \
                patch.object(legal_answers, "API_KEY", "test"), patch.object(legal_answers, "invoke", side_effect=outputs):
            response = TestClient(main.app).post("/ask", json={"question": "Sığorta ödənişi hansı müddətdə edilir?"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["evidence_status"], "sufficient")
        self.assertEqual(body["references"][0]["document_id"], metadata["document_id"])
        self.assertEqual(body["references"][0]["passage_id"], metadata["chunk_id"])
        self.assertEqual(body["references"][0]["source_url"], body["sources"][0]["url"])
