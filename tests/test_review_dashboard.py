from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase

from fastapi.testclient import TestClient

from evaluation import expert_review as workflow, gold_framework as gold
from evaluation.review_dashboard import ROLES, create_app


class ReviewDashboardTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "reviews.db"
        case = {"query": "Fixture question", "history": [], "category": "fixture", "style": "formal", "status": "pending",
                "groups": ["formal"], "standalone": None, "diagnostic": False, "draft_part_parents": {}, "draft_evidence": []}
        self.packet = {"schema_version": 1, "corpus_sha256": "fixture", "dataset_sha256": "fixture", "queries": {"q": case}}
        self.accounts = {role: {"reviewer": role, "expertise": "test fixture",
                                "token_sha256": hashlib.sha256(role.encode()).hexdigest()} for role in ROLES}
        self.client = TestClient(create_app(self.packet, {}, self.database, self.accounts))
        self.labels = {"answerability": "unanswerable", "expected_answer": "Fixture abstention", "groups": ["formal"],
                       "parts": {}, "standalone": None, "evidence": [], "required_passage_ids": [],
                       "required_qualifications": []}

    def headers(self, role):
        return {"Authorization": f"Bearer {role}"}

    def submit(self, role, decision, previous=0, hashes=None, labels=None):
        return self.client.post("/api/cases/q", headers=self.headers(role), json={
            "decision": decision, "previous": previous, "reason": role + " rationale", "labels": labels,
            "reviewed_decision_sha256": hashes})

    def case(self, role):
        return self.client.get("/api/cases/q", headers=self.headers(role)).json()

    def export(self, kind):
        response = self.client.get("/api/export/" + kind, headers=self.headers("coordinator"))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_roles_private_history_and_authoritative_exports_feed_release_gate(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.submit("coordinator", "exclude").status_code, 403)
        self.assertEqual(self.client.get("/api/export/audit", headers=self.headers("reviewer_a")).status_code, 403)
        self.assertEqual(self.submit("reviewer_a", "annotate", labels=self.labels).status_code, 200)
        self.assertEqual(self.case("reviewer_b")["history"], [])
        self.assertEqual(self.case("adjudicator")["peers"], {})
        self.assertEqual(self.submit("reviewer_b", "exclude").json()["status"], "disagreement")
        self.assertEqual(self.case("reviewer_b")["disputed_fields"], [])
        dispute = self.case("adjudicator")
        self.assertEqual(dispute["disputed_fields"], ["decision"])
        self.assertEqual(self.submit("adjudicator", "annotate", hashes=["stale"], labels=self.labels).status_code, 422)
        self.assertEqual(self.submit("adjudicator", "annotate", hashes=dispute["decision_hashes"],
                                     labels=self.labels).json()["status"], "adjudicated_approved")
        self.assertEqual(self.submit("reviewer_a", "exclude", previous=1).status_code, 409)
        audit = self.export("audit")
        self.assertEqual(len(audit["entries"]), 3)
        finalized, report = workflow.resolve(self.packet, [self.export("reviewer-a"), self.export("reviewer-b")],
                                             self.export("adjudicator"), {})
        self.assertEqual(report, self.export("progress"))
        approved = gold.approved_queries(finalized, self.packet, {})
        self.assertEqual(list(workflow.freeze_gold(finalized, approved, report, "fixture")["queries"]), ["q"])
        self.assertEqual(self.client.post("/api/release", headers=self.headers("coordinator")).status_code, 404)

    def test_revisions_are_append_only_and_invalid_labels_roll_back(self):
        self.assertEqual(self.submit("reviewer_a", "annotate", labels={**self.labels, "required_passage_ids": ["fake"]}).status_code, 422)
        first = self.submit("reviewer_a", "exclude").json()["revision"]
        self.assertEqual(self.submit("reviewer_a", "defer").status_code, 409)
        self.assertEqual(self.submit("reviewer_a", "defer", previous=first).status_code, 200)
        self.assertEqual(len(self.case("reviewer_a")["history"]), 2)
        self.assertEqual(self.case("reviewer_b")["history"], [])
        with closing(sqlite3.connect(self.database)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM revisions WHERE id = ?", (first,))
        submissions = [self.export("reviewer-a"), self.export("reviewer-b")]
        finalized, report = workflow.resolve(self.packet, submissions, self.export("adjudicator"), {})
        with self.assertRaisesRegex(ValueError, "Cannot freeze"):
            workflow.freeze_gold(finalized, {}, report, "fixture")
