from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from App import legal_answers, main, source_authority as authority
from App.evaluation_capture import recording
from evaluation.benchmark_legal_verifier import CORPUS
from evaluation.gold_framework import read
from starlette.requests import Request


FIXTURES = read(CORPUS)["sources"]


def indexed_fixture(*keys):
    documents = {}
    catalog = {"documents": {}, "provisions": {}}
    hits = []
    for key in keys:
        source = FIXTURES[key]
        pid, did = source["passage_id"], source["document_id"]
        hit = {"doc": source["document_name"], "text": source["text"], "metadata": {
            **source, "chunk_id": pid, "page_number": source["page"], "insurance_type": "occupational",
        }}
        hits.append(hit)
        documents.setdefault(did, {"doc": hit["doc"], "metadata": hit["metadata"], "chunks": []})["chunks"].append(hit)
        catalog["documents"].setdefault(did, {
            "source_type": "academic_textbook" if key.startswith("textbook") else
            "government_resolution_or_regulation" if key == "amendment_resolution" else "law_or_code",
            "version_id": "fixture-version",
            "anchors": [{"passage_id": pid, "text_sha256": authority.text_digest(hit["text"])}],
        })
    return hits, list(documents.values()), catalog


def annotate(hits, documents, catalog, **dates):
    items = [{"source_url": f"/fixtures/{i}", "original_text": hit["text"]} for i, hit in enumerate(hits)]
    return authority.annotate(hits, items, documents, authority.case_timeline(**dates), catalog)


class SourceAuthorityTests(unittest.TestCase):
    def test_textbook_retained_and_unpinned_version_fails_closed(self):
        hits, documents, catalog = indexed_fixture("termination", "textbook_title")
        result = annotate(hits, documents, catalog)["sources"]
        self.assertEqual([x["evidence_role"] for x in result], ["normative", "contextual"])
        self.assertEqual(result[1]["educational_excerpt"], hits[1]["text"])
        self.assertEqual(result[1]["reference"]["passage_id"], hits[1]["metadata"]["chunk_id"])
        changed = deepcopy(hits)
        changed[0]["metadata"]["version_id"] = "unreviewed"
        self.assertEqual(annotate(changed, documents, catalog)["sources"][0]["source_type"], "unclassified")
        self.assertFalse(annotate(hits, documents, catalog, requested_reference_date="2025-05-01")["sources"][0]["eligible_normative"])
        self.assertTrue(authority.requests_current_law("Hazırda qayda necədir?"))
        self.assertFalse(authority.requests_current_law("Qüvvədə olan müqavilə üzrə ödəniş varmı?"))
        self.assertEqual(annotate(hits, documents, catalog, current_requested=True)["sources"][0]["temporal_status"],
                         "current_applicability_unverified")

    def test_competing_normative_candidates_do_not_resolve_by_hierarchy(self):
        hits, documents, catalog = indexed_fixture("termination", "amendment_resolution")
        # Hypothetical overlapping issue labels exercise conflict mechanics. The exact
        # fixture passages are not asserted to conflict as a matter of law.
        for index, hit in enumerate(hits):
            catalog["provisions"][hit["metadata"]["chunk_id"]] = {
                "anchors": [], "text_sha256": authority.text_digest(hit["text"]), "issue": "fixture issue",
                "rule_family": str(index), "insurance_type": "occupational", "person_group": "worker",
            }
        result = annotate(hits, documents, catalog)
        conflict, = result["conflicts"]
        self.assertEqual(conflict["status"], "potential_conflict")
        self.assertTrue(conflict["requires_expert_review"])
        self.assertIsNone(conflict["resolution"])
        self.assertTrue(all(not item["eligible_normative"] for item in result["sources"]))

    def test_asserted_dates_separated_from_reference_scope(self):
        result = authority.case_timeline(requested_reference_date="2025-07-01", insured_event_date="2025-06-22",
                                         contract_start="2025-01-01", contract_termination="2025-06-01")
        self.assertEqual(result["contract_event_relationship"], "outside_asserted_contract_period")
        self.assertEqual(result["dates"]["requested_reference_date"], "2025-07-01")
        self.assertFalse(result["case_facts_verified"])
        self.assertEqual(authority.dates_at({"effective_date": "2020-01-01"}, "2025-01-01"), "effective_period_unknown")
        self.assertEqual(authority.dates_at({"repeal_effective_date": "2020-01-01"}, "2025-01-01"),
                         "outside_documented_effective_period")

    def test_frozen_catalog_temporal_provenance(self):
        snapshot = Path(".venv/eval_corpus_snapshot.json")
        if not snapshot.is_file():
            self.skipTest("Frozen indexed export is a local artifact")
        documents = read(snapshot)
        locators = [(5, 4), (1, 10), (10, 61), (10, 69), (10, 79), (10, 80)]
        hits = [documents[doc]["chunks"][chunk] for doc, chunk in locators]
        report = annotate(hits, documents, authority.load_catalog(), requested_reference_date="2026-01-01")
        amendment, repeal, area, old, first, second = report["sources"]
        self.assertEqual(amendment["provision"]["amendment_publication_date"], "2019-08-21")
        self.assertEqual(amendment["provision"]["effective_date"], "2020-01-01")
        self.assertIsNone(repeal["provision"]["repeal_effective_date"])
        self.assertEqual(area["temporal_status"], "effective_period_unknown")
        self.assertFalse(old["eligible_normative"])
        self.assertTrue(all(x["temporal_status"] == "transition_boundary_requires_review" for x in (first, second)))
        self.assertEqual({c["status"] for c in report["conflicts"]}, {"documented_transition", "historical_comparison"})
        inside = annotate(hits[-2:], documents, authority.load_catalog(), requested_reference_date="2025-01-01")["sources"]
        self.assertEqual([entry["eligible_normative"] for entry in inside], [True, False])

    def test_opt_in_routes_context_and_blocks_context_only_citations(self):
        hits, documents, catalog = indexed_fixture("termination", "textbook_title")
        request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(
            retriever=SimpleNamespace(documents=documents, search=lambda *args, **kwargs: (hits, 1))
        ))})
        generated = json.dumps({"claims": [{"text": "Test claim based only on context.", "source_ids": ["S2"]}],
                                "evidence_status": "sufficient"})
        with (
            patch.object(authority, "enabled", return_value=True),
            patch.object(authority, "load_catalog", return_value=catalog),
            patch.object(main, "query_experiments", return_value={"provision": False}),
            patch.object(legal_answers, "API_KEY", "fixture"),
            patch.object(legal_answers, "invoke", return_value=generated) as invoke,
            patch.object(legal_answers, "judge_claims") as judge,
            recording() as trace,
        ):
            reply = main.ask(main.Question(question="Müqavilə ləğv edilərsə, ödəniş hüququ qalırmı?", language="az"), request)
            self.assertEqual(reply["delivery_status"], "verification_failed")
            self.assertEqual(reply["sources"], [])
            self.assertEqual(len(trace["source_authority"]["sources"]), 2)
            self.assertIn('authority_role="context_only"', invoke.call_args.args[1])
            judge.assert_not_called()

            invoke.return_value = json.dumps({"claims": [{"text": "Xitam sığortaçını öhdəlikdən azad etmir.",
                                                           "source_ids": ["S1"]}], "evidence_status": "sufficient"})
            judge.return_value = [True]
            reply = main.ask(main.Question(question="Müqavilə ləğv edilərsə, ödəniş hüququ qalırmı?", language="az"), request)
        self.assertEqual([ref["id"] for ref in reply["sources"]], ["S1"])
        self.assertEqual(list(judge.call_args.args[1]), ["S1"])
