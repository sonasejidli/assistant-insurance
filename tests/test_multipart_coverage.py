import json
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from App import legal_answers, legal_documents, legal_evidence, query_plan, text_search
from App.query_resolution import resolve_query
from evaluation.evaluate_platform import diagnostic_cases, read


class MultipartCoverageTests(TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.docs = read(root / "tests/fixtures/multipart_source_extracts.json")
        legal_documents.link_references(cls.docs)
        cls.chunks = [hit for doc in cls.docs for hit in doc["chunks"]]
        cls.cases = [case for case in diagnostic_cases(read(root / "evaluation/real_insurance_dataset.json")) if case.get("part_parents")]

    def package(self, case):
        seeds = {"MP01": {"Q1": "17.1.10"}, "MP02": {"Q1": "20.0"},
                 "MP03": {"Q1": "9.1.3", "Q2": "11.1.1"}, "MP05": {"Q2": "20.0"}}
        plan = query_plan.plan_query(resolve_query(case["query"], []), "az", forced=True, provision=True)
        parts = {part.id: part.question for part in plan.parts}
        hits, associations = [], {}
        for part, number in seeds.get(case["id"], {}).items():
            hit = next(hit for hit in self.chunks if hit["metadata"].get("clause") == number)
            hits.append(hit)
            associations[query_plan.passage_key(hit)] = {part}
        for part, question in parts.items():
            for i in text_search.scoped_obligations(question, self.chunks, range(len(self.chunks))) or ():
                hit = self.chunks[i]
                hits.append(hit)
                associations[query_plan.passage_key(hit)] = {part}
        return parts, legal_evidence.assemble_evidence(case["query"], hits, self.docs, associations=associations,
            part_questions=parts, part_ids=parts.keys(), critical_groups=True, multipart_coverage=True)

    def test_all_six_scoped_evidence_regressions(self):
        self.assertEqual(len(self.cases), 6)
        for case in self.cases:
            with self.subTest(case=case["id"]):
                _, package = self.package(case)
                actual = {item["passage_id"]: set(item["subquestions"]) for item in package.items}
                self.assertLessEqual(len(actual), 10)
                self.assertEqual(len(actual), len(package.items))
                self.assertFalse(package.missing_parts)
                for part, ids in enumerate(case["part_parents"], 1):
                    for identifier in ids:
                        self.assertEqual(actual.get(identifier), {f"Q{part}"})

    def test_citations_and_missing_part_gate_for_all_six(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                parts, package = self.package(case)
                first = next(i for i, item in enumerate(package.items, 1) if "Q1" in item["subquestions"])
                draft = {"evidence_status": "sufficient", "claims": [{"part": "Q1", "text": "Mənbədə bu hal üzrə müddəa verilir.",
                                                                        "source_ids": [f"S{first}"]}]}
                with patch.object(legal_answers, "API_KEY", "test"), patch.object(legal_answers, "invoke", return_value=json.dumps(draft)), \
                     patch.object(legal_answers, "judge_claims", return_value=[True]), \
                     patch.object(legal_answers, "supporting_stages", return_value=float("inf")):
                    _, answer = legal_answers.generate_legal_answer(case["query"], package, "az", subquestions=parts, judge=True)
                self.assertEqual(answer.evidence_status, "partial")
                self.assertTrue(any(text.startswith("Q2") for text in answer.limitations))
                self.assertEqual([ref.passage_id for ref in answer.references], [package.items[first-1]["passage_id"]])
                self.assertFalse(legal_answers.claim_is_bound(legal_answers.Claim(
                    part="Q1", text="Mənbədə müddəa verilir.", source_ids=["S999"]), {}, {"Q1", "Q2"}))

    def test_both_parts_mentioned_cannot_hide_missing_or_uncited_provisions(self):
        case = next(case for case in self.cases if case["id"] == "MP03")
        parts, package = self.package(case)
        claims = []
        for part in parts:
            first = next(i for i, item in enumerate(package.items, 1) if part in item["subquestions"])
            claims.append({"part": part, "text": "Mənbədə bu hal üzrə müddəa verilir.", "source_ids": [f"S{first}"]})
        draft = {"evidence_status": "sufficient", "claims": claims}
        for evidence in (package, replace(package, missing_parts={"Q1"})):
            with self.subTest(missing=evidence.missing_parts):
                with patch.object(legal_answers, "API_KEY", "test"), patch.object(legal_answers, "invoke", return_value=json.dumps(draft)), \
                     patch.object(legal_answers, "judge_claims", return_value=[True, True]), \
                     patch.object(legal_answers, "supporting_stages", return_value=float("inf")):
                    _, answer = legal_answers.generate_legal_answer(case["query"], evidence, "az", subquestions=parts, judge=True)
                self.assertEqual(answer.evidence_status, "partial")
                self.assertTrue(any(text.startswith("Q1") for text in answer.limitations))
                self.assertEqual(len(answer.references), 2)

    def test_complete_drafts_bind_every_labeled_passage_to_its_source(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                parts, package = self.package(case)
                citations = [(part, i, item) for part, ids in package.required_part_passages.items()
                             for i, item in enumerate(package.items, 1) if item["passage_id"] in ids]
                claims = [{"part": part, "text": "Mənbədə bu hal üzrə müddəa verilir.", "source_ids": [f"S{i}"]}
                          for part, i, _ in citations]
                draft = {"evidence_status": "sufficient", "claims": claims}
                with patch.object(legal_answers, "API_KEY", "test"), patch.object(legal_answers, "invoke", return_value=json.dumps(draft)), \
                     patch.object(legal_answers, "judge_claims", return_value=[True] * len(claims)), \
                     patch.object(legal_answers, "supporting_stages", return_value=float("inf")):
                    _, answer = legal_answers.generate_legal_answer(case["query"], package, "az", subquestions=parts, judge=True)
                self.assertEqual(answer.evidence_status, "sufficient")
                bound = {ref.passage_id: ref for ref in answer.references}
                self.assertTrue(set().union(*case["part_parents"]) <= bound.keys())
                for _, _, item in citations:
                    ref = bound[item["passage_id"]]
                    self.assertEqual((ref.document_id, ref.article, ref.paragraph, ref.source_text),
                                     (item["document_id"], item["article"], item["paragraph"], item["original_text"]))
