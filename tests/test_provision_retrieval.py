import unittest

from App.document_processing import process_document
from App.legal_answers import Claim, uncovered_group_parts
from App.legal_evidence import assemble_evidence
from App.query_plan import decompose_provisions, passage_key
from App.text_search import provision_candidates


class ProvisionRetrievalTests(unittest.TestCase):
    def test_named_definition_excludes_code_mentions_and_respects_eligibility(self):
        law = {"law_name": "Azərbaycan Respublikasının Mülki Məcəlləsi", "clause": "883.1"}
        entries = [{"text": "935.4. Bu Məcəllədə sığorta müqaviləsi qeyd olunur.", "metadata": law},
                   {"text": "883.1. Sığorta müqaviləsi tərəflərin razılaşmasıdır və ayrıca razılaşmadır.", "metadata": law}]
        query = "Mülki Məcəllədə sığorta müqaviləsi nədir?"
        self.assertEqual(provision_candidates(query, entries, [0, 1]), [1])
        self.assertEqual(provision_candidates(query, entries, [0]), [])
        self.assertEqual(provision_candidates(query, [*entries, entries[1]], [0, 1, 2]), [])

    def test_compound_tariff_preserves_base_amount_as_separate_request(self):
        query = "Avtomobil sahiblərinin icbari sığorta haqqı məbləğinin hesablanması qaydası və baza haqqı"
        formula, base = decompose_provisions(query)
        self.assertIn("hesablanması", formula)
        self.assertIn("baza sığorta haqqı", base)
        records = [{"text": "2.2. Baza sığorta haqqı 50,0 manat məbləğində müəyyən olunur.", "metadata": {
            "legal_document_type": "regulation", "law_name": "Avtonəqliyyat üzrə icbari sığorta haqqı qaydası", "clause": "2.2"}}]
        self.assertEqual(provision_candidates(base, records, [0]), [0])

    def test_document_list_recovers_siblings_and_reports_citation_gaps_by_part(self):
        source = process_document("Maddə 9. Tələb\n9.1. Aşağıdakı sənədlər tələb olunur:\n"
                                  "9.1.1. Ərizə.\n9.1.2. Müqavilənin surəti.", "example.txt")
        child = next(hit for hit in source["chunks"] if hit["metadata"].get("clause") == "9.1.1")
        question = "İcbari sığorta tələbi üçün hansı sənədlər tələb olunur?"
        package = assemble_evidence(question, [child], [source], associations={passage_key(child): {"Q1"}},
                                    part_questions={"Q1": question}, part_ids={"Q1"}, critical_groups=True)
        ids = package.required_part_passages["Q1"]
        self.assertEqual(len(ids), 3)
        self.assertFalse(package.missing_parts)
        evidence = {"S1": {"passage_id": child["metadata"]["chunk_id"]}}
        claim = Claim(text="Ərizə tələb olunur.", source_ids=["S1"], part="Q1")
        self.assertEqual(uncovered_group_parts(package.required_part_passages, [claim], evidence), {"Q1"})

    def test_exclusion_group_adds_matching_condition_only(self):
        source = process_document("Maddə 20. İmtina\n20.0. Sığortaçı aşağıdakı hallarda imtina edir:\n"
                                  "20.0.1. Hadisə qəsdən törədildikdə.\n20.0.2. Sənəd təqdim edilmədikdə.", "example.txt")
        root = next(hit for hit in source["chunks"] if hit["metadata"].get("clause") == "20.0")
        question = "Qəsdən törədilən hadisədə hansı halda ödənişdən imtina edilir?"
        package = assemble_evidence(question, [root], [source], associations={passage_key(root): {"Q1"}},
                                    part_questions={"Q1": question}, critical_groups=True)
        self.assertEqual({item["clause"] for item in package.items if item["passage_id"] in
                          package.required_part_passages["Q1"]}, {"20.0", "20.0.1"})

    def test_auditor_nonpayment_targets_condition_under_named_insurance_law(self):
        query = "Auditor sığortasında hansı halda sığorta haqqı ödənilmədikdə ödənişdən imtina mümkündür?"
        text = "11.1.1. sığortalı sığorta haqqını ödəmədikdə;"
        candidates = [{"text": text, "metadata": {"clause": "11.1.1", "law_name": title}}
                      for title in ("İcbari sığortalar haqqında", "Auditorun peşə məsuliyyətinin icbari sığortası haqqında")]
        self.assertEqual(provision_candidates(query, candidates, [0, 1]), [1])
