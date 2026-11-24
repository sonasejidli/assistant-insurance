from copy import deepcopy
import unittest
from xml.etree import ElementTree

from evaluation.gold_framework import HERE, read
from evaluation.verify_legal_scope import (
    DRAFT, PROPOSAL, answer_hash, citation, proposed_impact, scope_result, source_registry, verify_case,
)


class LegalScopeTests(unittest.TestCase):
    def setUp(self):
        self.draft = read(DRAFT)
        self.assessments = read(HERE / "legal_scope_assessments_v1.json")["cases"]
        self.source = {"passage_id": "p", "document_id": "d", "document_name": "sığorta 3.pdf",
                       "law_name": "fixture law", "version_id": "v", "snapshot_document_sha256": "fixture",
                       "article": "11", "clause": "11.8", "page": 10, "text": "fixture source",
                       "original_text": "fixture source"}
        self.context = ('<source id="S1" document="sığorta 3.pdf" article="11" clause="11.8" '
                        'page="10" chunk_id="p" document_id="d" version_id="v">fixture source</source>')
        self.row = {"decision_reason": "accepted_answer", "mode": "FULL", "ranked_passage_ids": ["p"],
                    "source_bindings": {"S1": {**self.source, "page_number": 10}}}

    def test_valid_citation_is_independent_of_unsupported_claim(self):
        case = {"id": "fixture", "domain_scope": "in_corpus",
                "parts": {"Q1": {"expected_mode": "FULL", "required_passage_ids": ["p"], "unresolved": []}}}
        output = "Unsupported assertion [S1]"
        self.row["generation_attempts"] = [{"output": output, "sources": [{"id": "S1", "passage_id": "p"}],
                                            "evidence_context": self.context}]
        assessment = {"part": "Q1", "assessed_passage_ids": ["p"], "support": "absent",
                      "insurance_type": "occupational", "group": "fixture", "temporal": "fixture",
                      "applicable_documents": ["sığorta 3.pdf"], "rationale": "No such rule in passage."}
        review = {"answer_sha256": answer_hash(output), "claims": [assessment], "complete_parts": ["Q1"]}
        result = verify_case(case, self.row, {"p": self.source}, review)
        self.assertTrue(result["claims"][0]["citation_validity"]["valid"])
        self.assertEqual(result["claims"][0]["claim_support"], "absent")
        self.assertIsNone(result["verified_mode"])
        assessment["support"] = "complete"
        self.assertEqual(verify_case(case, self.row, {"p": self.source}, review)["verified_mode"], "FULL")
        case["parts"]["Q2"] = {"expected_mode": "PARTIAL", "required_passage_ids": [], "unresolved": ["procedure"]}
        self.assertEqual(verify_case(case, self.row, {"p": self.source}, review)["verified_mode"], "PARTIAL")
        assessment["assessed_passage_ids"] = ["other"]
        self.assertEqual(verify_case(case, self.row, {"p": self.source}, review)["claims"][0]["claim_support"], "unverified")

    def test_wrong_packed_version_fails_exact_binding(self):
        node = ElementTree.fromstring(self.context.replace('version_id="v"', 'version_id="other"'))
        attempt = {"sources": [{"id": "S1", "passage_id": "p"}]}
        self.assertFalse(citation("S1", self.row, attempt, {"S1": node}, {"p": self.source})["valid"])

    def test_termination_and_cross_regime_controls(self):
        rule = self.assessments["AZ7-02"]["claims"][0]
        result = scope_result("Müqavilənin qüvvədə olduğu dövrdə hadisə", [self.source], rule)
        self.assertIn("express occupational scope", result["missing_conditions"])
        duty = self.assessments["AZ7-04"]["claims"][1]
        self.assertEqual(scope_result("İşəgötürən", [{**self.source, "document_name": "sığorts 4.pdf"}], duty)["status"],
                         "wrong_insurance_type")

    def test_group_deadlines_and_exceptions(self):
        deadline, special = self.assessments["AZ7-06"]["claims"][1:]
        source = [{"document_name": "sığorts 4.pdf"}]
        bad = scope_result("İşçi cəlb etmədən çalışanlar 15-dən gec olmayaraq ödəyir.", source, deadline)
        self.assertEqual(bad["status"], "contradictory")
        self.assertIn("special activities and qualifying transport expressly excepted", bad["missing_conditions"])
        self.assertEqual(scope_result("Tibbi sığorta 220.10 üzrə qəbz və 218.4.1 üzrə nişan.", source, special)["status"],
                         "within_scope")
        self.assertEqual(scope_result("Tibbi sığorta qəbz alınanda.", source, special)["status"], "missing_conditions")

    def test_land_eligibility(self):
        rule = self.assessments["AZ7-07"]["claims"][0]
        source = [{"document_name": "sığorta 7.pdf"}]
        self.assertEqual(scope_result("Fiziki şəxslər üçün torpaq sahəsinə görə.", source, rule)["missing_conditions"],
                         ["ownership", "agricultural land", "family-farm membership", "age floor", "pension-age ceiling"])
        scoped = "Mülkiyyətində kənd təsərrüfatı torpağı və ailə kəndli təsərrüfatı üzvləri 15 yaş ilə pensiya yaşı arasında."
        self.assertEqual(scope_result(scoped, source, rule)["status"], "within_scope")

    def test_proposed_passage_changes_labels_without_mutating_original(self):
        proposal = read(PROPOSAL)
        new = proposal["changes"][0]["new_passages"][0]
        pid = new["passage_id"]
        before = deepcopy(self.draft)
        rows = [{"ranked_passage_ids": [pid] if case["id"] == "AZ7-04" else []} for case in self.draft["queries"]]
        result = proposed_impact(self.draft, rows, {pid: {**new, "document_name": new["document"]}}, proposal)
        self.assertEqual(result["per_case"][3]["original_recall@5"], 0)
        self.assertEqual(result["per_case"][3]["proposed_recall@5"], 1 / 7)
        self.assertEqual(self.draft, before)

    def test_captured_cases_when_local_artifacts_are_available(self):
        audit = HERE.parent / ".venv/rag-claim-audit-input.json"
        snapshot = HERE.parent / self.draft["snapshot"]
        if not (audit.is_file() and snapshot.is_file()):
            self.skipTest("Original run and frozen corpus are local artifacts")
        registry = source_registry(read(snapshot))
        rows = read(audit)["rows"]
        results = [verify_case(case, row, registry, self.assessments.get(case["id"]))
                   for case, row in zip(self.draft["queries"], rows, strict=True)]
        self.assertEqual([r["verified_mode"] for r in results],
                         ["PARTIAL", "PARTIAL", None, "PARTIAL", None, "PARTIAL", "PARTIAL"])
        self.assertEqual(sum(len(r["claims"]) for r in results), 14)
        self.assertTrue(all(claim["citation_validity"]["valid"] for r in results for claim in r["claims"]))
