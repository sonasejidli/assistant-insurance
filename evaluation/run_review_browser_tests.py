"""Run the authenticated dashboard in a browser against disposable fixtures."""

import argparse
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Event, Thread
from zipfile import ZipFile

from playwright.sync_api import expect, sync_playwright
import uvicorn

from evaluation import expert_review as gate, gold_framework as gold
from evaluation.review_dashboard import ROLES, create_app


NAMES = dict(zip(ROLES, ("Reviewer A", "Reviewer B", "Adjudicator", "Release Operator")))
IDS = ("E2E-MP", "E2E-REJECT", "E2E-DISPUTE", "E2E-PENDING")
ROOT = Path(__file__).resolve().parents[1]
LOCKED = ("evaluation/gold_framework_review.pending.json", "evaluation/real_insurance_dataset.json",
          "evaluation/benchmark_lock.json", "evaluation/ci_lexical_baseline.json", "evaluation/insurance_queries.tsv",
          "evaluation/bm25_cases.json", "evaluation/reranker_cases.json", "evaluation/salary_evidence.json")
RATIONALE_A = "Reviewer A private fixture rationale"
RATIONALE_B = "Reviewer B independent fixture rationale"
RATIONALE_FINAL = "Adjudicator resolved the fixture disagreement"


def fixture():
    metadata = {"chunk_id": "E2E-source", "document_id": "E2E-document", "article": "1", "clause": "1.1", "page_number": 1}
    source = {"doc": "E2E fixture law", "text": "Sınaq fraqmenti. Bu mətn yalnız brauzer sınağı üçündür.", "metadata": metadata}
    evidence = {**metadata, "passage_id": "E2E-source", "parent_passage_id": "E2E-source",
                "document": source["doc"], "page": 1, "text": source["text"], "snapshot_verified": True}
    cases = {key: {"query": "Sınaq sualı " + key + "?", "category": "browser fixture", "style": "formal", "history": [],
                   "groups": ["formal"], "diagnostic": True, "status": "pending", "standalone": None,
                   "draft_part_parents": {}, "draft_evidence": []} for key in IDS}
    cases[IDS[0]].update(draft_evidence=[evidence], draft_part_parents={"Q1": ["E2E-source"], "Q2": ["E2E-source"]},
                         groups=["formal", "multipart"])
    return {"schema_version": 1, "dataset_sha256": "browser-fixture", "corpus_sha256": "browser-fixture",
            "queries": cases}, {"E2E-source": source}


@contextmanager
def live_server(app):
    ready = Event()

    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = Server(uvicorn.Config(app, access_log=False, log_level="error"))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            if not ready.wait(15) or not server.started:
                raise RuntimeError("Isolated review server did not start")
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(15)
            if thread.is_alive():
                raise RuntimeError("Isolated review server did not stop")


class Suite:
    def __init__(self, browser, origin, tokens, scratch, output, packet, source):
        self.browser, self.origin, self.tokens = browser, origin, tokens
        self.scratch, self.output, self.packet, self.source = scratch, output, packet, source
        self.sessions, self.results = {}, []

    def page(self, role):
        if role not in self.sessions:
            context = self.browser.new_context(base_url=self.origin)
            page = context.new_page()
            self.sessions[role] = context, page
            self.login(role, page)
        return self.sessions[role][1]

    def login(self, role, page):
        page.goto("/")
        if role == "anonymous":
            expect(page.get_by_role("heading", name="Review access")).to_be_visible()
            return
        page.get_by_label("Access token").fill(self.tokens[role])
        page.get_by_role("button", name="Open review workspace").click()
        expect(page.get_by_text(NAMES[role] + " ·", exact=False)).to_be_visible()
        expect(page.get_by_role("navigation", name="Cases").get_by_role("button")).to_have_count(4)

    def open_case(self, role, key):
        page = self.page(role)
        heading = page.locator("#detail h2")
        old_heading = heading.element_handle() if heading.count() else None
        page.get_by_role("navigation", name="Cases").get_by_role("button", name=key, exact=False).click()
        if old_heading is not None:
            page.wait_for_function("(heading) => !heading.isConnected", arg=old_heading)
        expect(page.get_by_role("heading", name="Sınaq sualı " + key + "?")).to_be_visible()
        return page

    def submit(self, page, decision, reason, multipart=False):
        page.get_by_label("Review decision").select_option(decision)
        page.get_by_label("Rationale").fill(reason)
        if decision == "annotate":
            page.get_by_label("Answerability").select_option("answerable" if multipart else "unanswerable")
            page.get_by_label("Expected answer or response").fill("Synthetic browser fixture response.")
            if multipart:
                for part in ("Q1", "Q2"):
                    page.get_by_label(part + " question").fill("Fixture " + part)
                    page.get_by_role("checkbox", name=part, exact=True).check()
                page.get_by_label("Relevance").select_option("3")
                page.get_by_role("checkbox", name="Required passage").check()
        save = page.get_by_role("button", name="Submit revision")
        old_button = save.element_handle()
        with page.expect_response(lambda response: response.request.method == "POST" and "/api/cases/" in response.url) as result:
            save.click()
        assert result.value.status == 200, f"Submit failed with HTTP {result.value.status}"
        page.wait_for_function("(button) => !button.isConnected", arg=old_button)
        expect(page.get_by_role("status")).to_have_text("Revision submitted.")

    def independent(self):
        page = self.open_case("reviewer_a", IDS[0])
        expect(page.get_by_text("Verified in frozen corpus")).to_be_visible()
        expect(page.get_by_text("Article 1 · Clause 1.1", exact=False)).to_be_visible()
        expect(page.get_by_text(self.source["E2E-source"]["text"])).to_be_visible()
        page.get_by_label("Review decision").select_option("annotate")
        expect(page.get_by_label("Q1 question")).to_be_visible()
        expect(page.get_by_label("Q2 question")).to_be_visible()
        self.submit(page, "annotate", RATIONALE_A, multipart=True)
        peer = self.open_case("reviewer_b", IDS[0])
        expect(peer.get_by_text(RATIONALE_A)).to_have_count(0)
        expect(peer.get_by_text("Revision history", exact=False)).to_have_count(0)
        expect(self.open_case("adjudicator", IDS[0]).get_by_text(RATIONALE_A)).to_have_count(0)
        self.submit(peer, "exclude", RATIONALE_B)

    def disagreement(self):
        page = self.open_case("adjudicator", IDS[0])
        expect(page.get_by_text("Disputed fields: decision")).to_be_visible()
        for name, reason in (("Reviewer A · Approve with labels", RATIONALE_A), ("Reviewer B · Reject", RATIONALE_B)):
            card = page.locator("#detail > details.review").filter(has=page.get_by_text(name, exact=True))
            card.get_by_text(name, exact=True).click()
            expect(card.get_by_text(reason, exact=True)).to_be_visible()
        peer = self.open_case("reviewer_a", IDS[0])
        expect(peer.get_by_text(RATIONALE_B)).to_have_count(0)
        expect(peer.get_by_text("Disputed fields:", exact=False)).to_have_count(0)
        # Browser request through the authenticated origin. No client-controlled role grants adjudication.
        response = self.sessions["reviewer_a"][0].request.post("/api/cases/" + IDS[0],
            headers=self.auth("reviewer_a"), data={"previous": 0, "decision": "exclude", "reason": "Stale revision",
                                                   "role": "adjudicator"})
        assert response.status == 409

    def adjudicate(self):
        page = self.open_case("adjudicator", IDS[0])
        self.submit(page, "annotate", RATIONALE_FINAL, multipart=True)
        expect(page.locator("#detail").get_by_text("Adjudicated", exact=False).first).to_be_visible()
        peer = self.open_case("reviewer_a", IDS[0])
        expect(peer.get_by_role("button", name="Submit revision")).to_have_count(0)

    def revisions(self):
        page = self.open_case("reviewer_a", IDS[1])
        self.submit(page, "defer", "Initial correction fixture")
        self.submit(page, "exclude", "Revised exclusion fixture")
        self.submit(self.open_case("reviewer_b", IDS[1]), "exclude", "Independent exclusion fixture")
        self.submit(self.open_case("reviewer_a", IDS[2]), "exclude", "Pending dispute A")
        self.submit(self.open_case("reviewer_b", IDS[2]), "defer", "Pending dispute B")
        page.reload()
        self.login("reviewer_a", page)
        page = self.open_case("reviewer_a", IDS[1])
        page.get_by_text("Revision history (2)").click()
        expect(page.get_by_text("Reviewer A · Request corrections", exact=True)).to_be_visible()
        expect(page.get_by_text("Reviewer A · Reject", exact=True)).to_be_visible()
        for method in ("PATCH", "DELETE"):
            assert self.sessions["reviewer_a"][0].request.fetch("/api/cases/" + IDS[1], method=method,
                                                                  headers=self.auth("reviewer_a")).status == 405

    def auth(self, role):
        return {"Authorization": "Bearer " + self.tokens[role]} if role in self.tokens else {}

    def bundle(self):
        page = self.page("coordinator")
        with page.expect_download() as event:
            page.get_by_role("button", name="Export bundle").click()
        with ZipFile(event.value.path()) as archive:
            raw = {name: archive.read(name) for name in archive.namelist()}
        assert set(raw) == {"reviewer-a.json", "reviewer-b.json", "adjudicator.json", "progress.json", "audit.json"}
        assert all(secret.encode() not in value for secret in self.tokens.values() for value in raw.values())
        decoded = {key: json.loads(value) for key, value in raw.items()}
        # Enumerate the exported schema to reject accidental credential, session, or private-profile fields.
        for name in ("reviewer-a.json", "reviewer-b.json", "adjudicator.json"):
            assert set(decoded[name]) == {"schema_version", "role", "packet_sha256", "reviewer", "expertise", "revision", "decisions"}
        for row in decoded["audit.json"]["entries"]:
            assert set(row) == {"id", "case_id", "role", "saved_at", "decision"} and row["case_id"] in IDS
            assert datetime.fromisoformat(row["saved_at"]).utcoffset() is not None
        return decoded

    def offline(self, bundle):
        finalized, report = gate.resolve(self.packet, [bundle["reviewer-a.json"], bundle["reviewer-b.json"]],
                                         bundle["adjudicator.json"], self.source)
        assert report == bundle["progress.json"]
        return finalized, gold.approved_queries(finalized, self.packet, self.source), report

    def export(self):
        bundle = self.bundle()
        finalized, approved, report = self.offline(bundle)
        assert report["release_counts"] == {"approved": 1, "rejected": 1, "disputed": 1, "pending": 1}, report["release_counts"]
        history = [row for row in bundle["audit.json"]["entries"] if row["case_id"] == IDS[0]]
        assert [(row["role"], row["decision"]["decision"], row["decision"]["reason"]) for row in history] == [
            ("reviewer_a", "annotate", RATIONALE_A), ("reviewer_b", "exclude", RATIONALE_B),
            ("adjudicator", "annotate", RATIONALE_FINAL)]
        try:
            gate.freeze_gold(finalized, approved, report, "browser-fixture")
        except ValueError as error:
            assert "Cannot freeze" in str(error)
        else:
            raise AssertionError("Unresolved cases passed release gate")
        self.submit(self.open_case("adjudicator", IDS[2]), "exclude", "Resolved fixture exclusion")
        for role in ("reviewer_a", "reviewer_b"):
            self.submit(self.open_case(role, IDS[3]), "exclude", "Resolved pending fixture")
        finalized, approved, report = self.offline(self.bundle())
        release = gate.freeze_gold(finalized, approved, report, "browser-fixture")
        assert set(release["queries"]) == {IDS[0]} and set(release["rejected_ids"]) == set(IDS[1:])
        return "Offline resolver matched export; unresolved freeze blocked; resolved fixture freeze passed in memory"

    def access(self):
        self.page("anonymous")
        api = self.sessions["anonymous"][0].request
        path = "/api/cases/" + IDS[0]
        assert api.get(path).status == 401
        assert api.post(path, data={"previous": 0, "decision": "exclude", "reason": "Fixture"}).status == 401
        for role in ("anonymous", *ROLES[:-1]):
            assert api.get("/api/export/bundle", headers=self.auth(role)).status == (401 if role == "anonymous" else 403)
        assert api.post(path, headers=self.auth("coordinator"), data={"previous": 0, "decision": "exclude",
                                                                     "reason": "Fixture"}).status == 403
        assert api.post("/api/release", headers=self.auth("coordinator")).status == 404
        assert api.get("/api/cases/AZR001", headers=self.auth("coordinator")).status == 404
        assert api.get("/api/dashboard", headers={"Authorization": "Bearer invalid-fixture-token"}).status == 401

    def run(self, name, roles, cases, action):
        row = {"scenario": name, "roles": list(roles), "cases": list(cases), "status": "PASS",
               "failure": None, "artifacts": [], "export_validation": None}
        # Start recording before the actions, after signing in. Failed login captures only a masked screenshot.
        traced = []
        try:
            for role in roles:
                self.page(role)
                context, _ = self.sessions[role]
                context.tracing.start(screenshots=True, snapshots=True)
                traced.append(role)
            row["export_validation"] = action()
        except Exception as error:
            row["status"] = "FAIL"
            message = str(error) or type(error).__name__
            for token in self.tokens.values():
                message = message.replace(token, "[redacted]")
            row["failure"] = message
            for role in roles:
                if role in self.sessions:
                    page = self.sessions[role][1]
                    name_png = f"{name[0]}-{role}.png"
                    try:
                        page.screenshot(path=self.output / name_png, mask=[page.locator("#token")], timeout=3000)
                        row["artifacts"].append(name_png)
                    except Exception:
                        pass
        finally:
            for role in traced:
                context, _ = self.sessions[role]
                if row["status"] == "PASS":
                    context.tracing.stop()
                    continue
                trace = self.scratch / "private-trace.zip"
                context.tracing.stop(path=trace)
                dest = f"{name[0]}-{role}-trace.zip"
                with ZipFile(trace) as raw, ZipFile(self.output / dest, "w") as clean:
                    for entry in raw.namelist():
                        content = raw.read(entry)
                        for token in self.tokens.values():
                            content = content.replace(token.encode(), b"[redacted]")
                        clean.writestr(entry, content)
                trace.unlink()
                row["artifacts"].append(dest)
        self.results.append(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for sanitized results")
    parser.add_argument("--channel", help="Installed Chromium channel, e.g. chrome or msedge")
    args = parser.parse_args()
    tokens = {role: os.environ.get("REVIEW_E2E_" + role.upper() + "_TOKEN", "") for role in ROLES}
    if len(set(tokens.values())) != 4 or any(len(value) < 32 or not value.isascii() or not value.replace("-", "").replace("_", "").isalnum()
                                            for value in tokens.values()):
        parser.error("Set four distinct high-entropy REVIEW_E2E_<ROLE>_TOKEN values (URL-safe, at least 32 characters)")
    args.output.mkdir(parents=True, exist_ok=False)
    before = {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in LOCKED}
    packet, source = fixture()
    accounts = {role: {"reviewer": NAMES[role], "expertise": "Isolated browser test account",
                       "token_sha256": sha256(tokens[role].encode()).hexdigest()} for role in ROLES}
    with TemporaryDirectory(prefix="review-browser-fixtures-") as folder:
        scratch = Path(folder)
        app = create_app(packet, source, scratch / "reviews.sqlite3", accounts)
        with live_server(app) as origin, sync_playwright() as playwright:
            with playwright.chromium.launch(channel=args.channel) as browser:
                suite = Suite(browser, origin, tokens, scratch, args.output, packet, source)
                scenarios = [
                    ("A Independent decisions", ROLES[:3], IDS[:1], suite.independent),
                    ("B Disagreement detection", ("reviewer_a", "adjudicator"), IDS[:1], suite.disagreement),
                    ("C Adjudication", ("reviewer_a", "adjudicator"), IDS[:1], suite.adjudicate),
                    ("D Append-only history", ROLES[:2], IDS[1:3], suite.revisions),
                    ("E Export and release gate", ROLES, IDS, suite.export),
                    ("F Access control and isolation", ("anonymous", "coordinator"), IDS, suite.access),
                ]
                for scenario in scenarios:
                    suite.run(*scenario)
                version = browser.version
    after = {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in LOCKED}
    report = {"browser": version, "accounts": NAMES, "isolated_database_removed": not scratch.exists(),
              "protected_files_unchanged": before == after, "scenarios": suite.results}
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in suite.results:
        print(row["status"], row["scenario"])
    return 0 if before == after and not scratch.exists() and all(row["status"] == "PASS" for row in suite.results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
