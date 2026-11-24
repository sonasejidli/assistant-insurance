import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from App import document_processing, legal_answers, legal_documents, legal_evidence, query_plan
from evaluation.evaluate_reliability_followup import claim_probes
from evaluation.prepare_staged_sources import health_excerpt


class ReliabilityFollowupTests(unittest.TestCase):
    def test_named_laws_with_shared_predicate_split_without_leaking_scope(self):
        parts = query_plan.decompose_v2("İcbari sığortada və iş qəzası sığortasında gecikmiş müraciətə hansı müddətlər tətbiq olunur?")
        self.assertEqual(len(parts), 2)
        self.assertIn("gecikmiş müraciətə", parts[0])
        self.assertIn("gecikmiş müraciətə", parts[1])
        self.assertNotIn("iş qəzası", parts[0])
        self.assertNotIn("İcbari", parts[1])

    def test_rewrite_keeps_explicit_conditions_and_original_text(self):
        text = "İş qəzasında əgər müddət keçibsə, ödəniş necə hesablanır və hansı sənədlər tələb olunur?"
        self.assertEqual(query_plan.decompose_v2(text), (text,))
        query = "İşdə qəza olub, pulu nə vaxt ala bilərəm?"
        self.assertTrue(query_plan.formal_variant(query).startswith(query))
        self.assertIn("peşə əmək qabiliyyətinin", query_plan.formal_variant(query))

    def test_guard_detects_units_deadline_qualifiers_and_wrong_article_binding(self):
        probes = claim_probes()
        self.assertTrue(all(row["guarded"] == row["expected_binding"] for row in probes))
        self.assertGreater(sum(row["baseline"] != row["expected_binding"] for row in probes), 0)

    def test_verified_group_reference_can_resolve_children_but_missing_root_cannot(self):
        doc = document_processing.process_document("Maddə 17. Sənədlər\n17.1. Sənədlər.\n17.1.1. Şəxsiyyət sənədi.\n17.2.1. Arayış.\n"
            "Maddə 18. Ödəniş\n18.1. Bu Qanunun 17.1-ci maddəsi və 17.2-ci maddəsi.", "example.txt")
        legal_documents.link_references([doc])
        hits = doc["chunks"]
        source = next(hit for hit in hits if hit["metadata"].get("clause") == "18.1")
        first, second = source["legal_references"]
        self.assertEqual(len(first["target_passage_ids"]), 2)
        self.assertEqual(second["resolution_status"], "unresolved")

    def test_staged_manifest_excludes_ocr_and_rejects_changed_source_bytes(self):
        with tempfile.TemporaryDirectory() as area:
            directory = Path(area)
            source = directory / "law.txt"
            source.write_text("Maddə 1. Test\n1.1. Qayda.", encoding="utf-8")
            (directory / "unreviewed-ocr.pdf").write_bytes(b"not indexed")
            manifest = {"law.txt": {"title": "Example", "legal_type": "law", "version_id": hashlib.sha256(source.read_bytes()).hexdigest()}}
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual([row["doc"] for row in document_processing.load_documents(directory, staged=True)], ["law.txt"])
            source.write_text("changed", encoding="utf-8")
            with self.assertRaises(ValueError):
                document_processing.load_documents(directory, staged=True)

    def test_health_html_extraction_does_not_mix_struck_provisions(self):
        raw = ("<body><p>Madd&#601; 53. H&#601;kim sirri</p><p>Qayda <s>repealed</s> saxlan&#305;l&#305;r.</p>"
               "<p>Madd&#601; 54. Next</p></body>").encode("cp1251")
        self.assertNotIn("repealed", health_excerpt(raw))
        self.assertNotIn("Next", health_excerpt(raw))

    def test_regulation_prose_preserves_clause_boundary_and_source_bytes(self):
        pages = ["Qaydalar\n2.1. Şərti məbləğ.\n2.2. Baza sığorta haqqı 50,0 manatdır.", "2.2. Cədvəl xanası."]
        doc = document_processing.process_document("", "tariff.pdf", pages=pages, prose_clause_pages=frozenset({1}))
        prose = next(hit for hit in doc["chunks"] if hit["metadata"].get("clause") == "2.2")
        self.assertEqual(prose["metadata"]["original_text"], "2.2. Baza sığorta haqqı 50,0 manatdır.")
        self.assertEqual(prose["metadata"]["page_number"], 1)
        self.assertIsNone(prose["metadata"]["article_number"])
        self.assertIsNone(doc["chunks"][-1]["metadata"].get("clause"))
