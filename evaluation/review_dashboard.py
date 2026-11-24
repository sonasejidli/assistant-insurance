"""Opt-in expert review service. Gold releases remain a separate CLI operation."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from evaluation import expert_review as workflow, gold_framework as gold


REVIEWERS = ("reviewer_a", "reviewer_b")
ROLES = (*REVIEWERS, "adjudicator", "coordinator")
ASSETS = Path(__file__).with_name("review_ui")


class Submission(BaseModel):
    previous: int = Field(ge=0)
    decision: str
    reason: str = Field(min_length=1, max_length=8000)
    labels: dict | None = None
    reviewed_decision_sha256: list[str] | None = None


def create_app(packet, source, database, accounts):
    if set(accounts) != set(ROLES):
        raise ValueError("Configure two reviewers, an adjudicator, and a coordinator")
    names = {workflow.reviewer({**acct, "revision": "account"}) for acct in accounts.values()}
    tokens = {acct["token_sha256"] for acct in accounts.values()}
    if len(names) != len(ROLES) or len(tokens) != len(ROLES) or any(
        len(value) != 64 or any(letter not in "0123456789abcdef" for letter in value) for value in tokens
    ):
        raise ValueError("Use distinct reviewer identities and SHA-256 token digests")
    packet_hash = gold.digest(packet)
    identity_hash = gold.digest({role: [account["reviewer"], account["expertise"]] for role, account in accounts.items()})

    @contextmanager
    def connect(*, write=False):
        conn = sqlite3.connect(database, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    with connect(write=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS binding (packet TEXT PRIMARY KEY, identities TEXT NOT NULL)")
        conn.execute("""CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY, case_id TEXT NOT NULL, role TEXT NOT NULL, saved_at TEXT NOT NULL, decision TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS revisions_case_role ON revisions (case_id, role, id)")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS revisions_no_update BEFORE UPDATE ON revisions
            BEGIN SELECT RAISE(ABORT,'Review history is append-only'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS revisions_no_delete BEFORE DELETE ON revisions
            BEGIN SELECT RAISE(ABORT,'Review history is append-only'); END""")
        binding = conn.execute("SELECT packet, identities FROM binding").fetchall()
        if binding and [tuple(row) for row in binding] != [(packet_hash, identity_hash)]:
            raise ValueError("Review database belongs to a different packet or reviewer roster")
        conn.execute("INSERT OR IGNORE INTO binding VALUES (?,?)", (packet_hash, identity_hash))

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def authenticate(authorization: str = Header(default="")):
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            fingerprint = hashlib.sha256(token.encode()).hexdigest()
            for role, account in accounts.items():
                if hmac.compare_digest(account["token_sha256"], fingerprint):
                    return role
        raise HTTPException(401, "Invalid review access token")

    def current(conn):
        latest = {role: {} for role in ROLES[:-1]}
        for row in conn.execute("SELECT * FROM revisions WHERE id IN (SELECT max(id) FROM revisions GROUP BY case_id, role)"):
            latest[row["role"]][row["case_id"]] = {"revision": row["id"], "saved_at": row["saved_at"],
                                                  "decision": json.loads(row["decision"])}
        return latest

    def projection(latest):
        exports = {}
        for role in ROLES[:-1]:
            account = accounts[role]
            exports[role] = {"schema_version": 1, "role": "adjudication" if role == "adjudicator" else "annotation",
                             "packet_sha256": packet_hash, "reviewer": account["reviewer"], "expertise": account["expertise"],
                             "revision": f"dashboard-{max((row['revision'] for row in latest[role].values()), default=0)}",
                             "decisions": {key: row["decision"] for key, row in latest[role].items()}}
        approved, report = workflow.resolve(packet, [exports[role] for role in REVIEWERS], exports["adjudicator"], source)
        return exports, approved, report

    def case_for(key):
        if key not in packet["queries"]:
            raise HTTPException(404, "Unknown case")
        return packet["queries"][key]

    @app.get("/")
    def index():
        return FileResponse(ASSETS / "index.html")

    @app.get("/assets/{name}")
    def assets(name: str):
        if name not in {"review.css", "review.js"}:
            raise HTTPException(404)
        return FileResponse(ASSETS / name)

    @app.get("/api/dashboard")
    def dashboard(role: str = Depends(authenticate)):
        with connect() as conn:
            latest = current(conn)
        _, _, report = projection(latest)
        rows = []
        for key, case in packet["queries"].items():
            rows.append({"id": key, "query": case["query"], "category": case["category"], "control": case["diagnostic"],
                         "status": report["rows"][key]["status"], "submitted": key in latest.get(role, {})})
        return {"role": role, "reviewer": accounts[role]["reviewer"], "counts": report["release_counts"],
                "source_checks": report["draft_source_checks"], "cases": rows}

    @app.get("/api/cases/{key}")
    def read_case(key: str, role: str = Depends(authenticate)):
        case = case_for(key)
        with connect() as conn:
            latest = current(conn)
            visible = (role,) if role in REVIEWERS else ROLES[:-1]
            history = [dict(row) for row in conn.execute("SELECT * FROM revisions WHERE case_id = ? ORDER BY id DESC", (key,))
                       if row["role"] in visible]
        _, _, report = projection(latest)
        peer = {actor: latest[actor][key] for actor in REVIEWERS if key in latest[actor]}
        can_see_peer = role == "coordinator" or (role == "adjudicator" and len(peer) == 2)
        if role == "adjudicator" and not can_see_peer:
            history = []
        return {"case": case, "status": report["rows"][key]["status"],
                "own": latest.get(role, {}).get(key), "history": [{**row, "decision": json.loads(row["decision"])} for row in history],
                "peers": peer if can_see_peer else {},
                "disputed_fields": report["rows"][key]["disputed_fields"] if can_see_peer else [],
                "decision_hashes": [gold.digest(peer[actor]["decision"]) for actor in REVIEWERS] if len(peer) == 2 and can_see_peer else [],
                "editable": (role in REVIEWERS and key not in latest["adjudicator"])
                or (role == "adjudicator" and (report["rows"][key]["status"] == "disagreement" or key in latest["adjudicator"]))}

    @app.get("/api/passages/{pid}")
    def passage(pid: str, role: str = Depends(authenticate)):
        if pid not in source:
            raise HTTPException(404, "Passage is outside the frozen corpus")
        hit = source[pid]
        info = hit["metadata"]
        return {"passage_id": pid, "parent_passage_id": info.get("parent_passage_id") or pid,
                "document": hit["doc"], "document_id": info["document_id"], "article": info.get("article"),
                "clause": info.get("clause"), "page": info.get("page_number"), "text": hit["text"],
                "snapshot_verified": True}

    @app.post("/api/cases/{key}")
    def submit(key: str, body: Submission, role: str = Depends(authenticate)):
        case = case_for(key)
        if role == "coordinator":
            raise HTTPException(403, "Coordinators have read and export access")
        decision = {"decision": body.decision, "reason": body.reason.strip(), "labels": body.labels}
        if role == "adjudicator":
            decision["reviewed_decision_sha256"] = body.reviewed_decision_sha256
        try:
            workflow.annotation({"decisions": {key: decision}}, key)
            if body.labels is not None:
                fixture = {**packet, "queries": {key: case}}
                checked = {**fixture, "queries": {key: {**case, **body.labels, "status": "approved",
                           "reviewer": accounts[role]["reviewer"], "expertise": accounts[role]["expertise"],
                           "revision_history": [{"decision": body.decision}]}}}
                gold.approved_queries(checked, fixture, source)
            with connect(write=True) as conn:
                latest = current(conn)
                previous = latest[role].get(key, {}).get("revision", 0)
                if previous != body.previous:
                    raise HTTPException(409, "A newer revision exists. Reload before submitting.")
                if role in REVIEWERS and key in latest["adjudicator"]:
                    raise HTTPException(409, "This case already has adjudication. Revisions require an adjudicator.")
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                revision = conn.execute("INSERT INTO revisions (case_id, role, saved_at, decision) VALUES (?,?,?,?)",
                                        (key, role, stamp, json.dumps(decision, ensure_ascii=False))).lastrowid
                _, _, report = projection(current(conn))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise HTTPException(422, f"Review validation failed: {exc}") from exc
        return {"revision": revision, "status": report["rows"][key]["status"]}

    @app.get("/api/export/{kind}")
    def export(kind: str, role: str = Depends(authenticate)):
        if role != "coordinator":
            raise HTTPException(403, "Only the coordinator can export review records")
        with connect() as conn:
            latest = current(conn)
            audit = [{**dict(row), "decision": json.loads(row["decision"])}
                     for row in conn.execute("SELECT * FROM revisions ORDER BY id")]
        submissions, _, report = projection(latest)
        files = {"reviewer-a": submissions["reviewer_a"], "reviewer-b": submissions["reviewer_b"],
                 "adjudicator": submissions["adjudicator"], "progress": report,
                 "audit": {"packet_sha256": packet_hash, "entries": audit}}
        if kind == "bundle":
            archive = BytesIO()
            with ZipFile(archive, "w") as bundle:
                for name, data in files.items():
                    bundle.writestr(f"{name}.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            return Response(archive.getvalue(), media_type="application/zip",
                            headers={"Content-Disposition": 'attachment; filename="review-bundle.zip"'})
        if kind not in files:
            raise HTTPException(404, "Unknown review export")
        return JSONResponse(files[kind], headers={"Content-Disposition": f'attachment; filename="{kind}.json"'})

    return app


def main():
    import uvicorn
    from evaluation.evaluate_platform import diagnostic_cases

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=gold.HERE / "gold_framework_review.pending.json")
    for name in ("snapshot", "accounts", "database"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    dataset = gold.read(gold.HERE / "real_insurance_dataset.json")
    documents = gold.read(args.snapshot)
    packet = gold.read(args.packet)
    if packet != gold.review_packet(dataset, documents, list(diagnostic_cases(dataset))):
        parser.error("Packet does not match the frozen corpus and controls")
    uvicorn.run(create_app(packet, gold.indexed_sources(documents), args.database, gold.read(args.accounts)),
                host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
