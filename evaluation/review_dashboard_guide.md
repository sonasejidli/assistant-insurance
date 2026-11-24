# Expert review dashboard

The dashboard is a separate local service for the frozen 173-case review packet. It displays the original Azerbaijani question, conversation history, draft standalone wording, source text and legal metadata. Source presence is shown separately from the reviewer’s relevance decisions. Source grades and required passages are blank on the first review.

## Start the local workspace

Use the project Python environment and the frozen corpus export. The service binds to loopback on port 8010. It does not start the RAG application, contact Qdrant, or call a model.

Create an accounts JSON file in a private location. It needs these four keys, each with a distinct real account holder, expertise, and a distinct, lowercase SHA-256 token digest. The sample values are placeholders.

```json
{
  "reviewer_a": {"reviewer": "<expert A>", "expertise": "<legal qualifications>", "token_sha256": "<digest A>"},
  "reviewer_b": {"reviewer": "<expert B>", "expertise": "<legal qualifications>", "token_sha256": "<digest B>"},
  "adjudicator": {"reviewer": "<expert C>", "expertise": "<legal qualifications>", "token_sha256": "<digest C>"},
  "coordinator": {"reviewer": "<coordinator>", "expertise": "<review administration>", "token_sha256": "<digest D>"}
}
```

Generate a distinct high-entropy token for each account. Give each person their own token privately and place only the digest in the config. The browser keeps its token in memory until sign-out or reload.

```sh
python -c "import hashlib,secrets; token=secrets.token_urlsafe(32); print(token); print(hashlib.sha256(token.encode()).hexdigest())"
python -m evaluation.review_dashboard --snapshot .venv/eval_corpus_snapshot.json --accounts .venv/review-accounts.json --database .venv/expert-review.sqlite3
```

Open [the local dashboard](http://127.0.0.1:8010/). Keep access to the account config, database, and exports restricted. For reviewers on other computers, use an approved private tunnel or an authenticated TLS reverse proxy. There is one named seat per role. The database binds its history to the packet and roster. Token rotation is possible without changing the roster.

## Review and adjudication

Reviewers use search and status filters to find cases. Each can approve with explicit labels, reject, or request corrections, with a required rationale. Choose the relevance of each supporting passage and mark required passages for the overall answer and the relevant sub-questions. Use frozen-corpus passage lookup to add missing candidates. The server validates legal source metadata and required assignments through the existing gold validator.

Reviewers can see their own decisions and revisions. The adjudicator can inspect both decisions once submitted, see the disputed fields, and issue a third decision with a rationale. A stale decision cannot be submitted. Once adjudicated, the two underlying reviewer decisions are locked, and the adjudicator can append a revised decision. Database transactions reject concurrent edits that target an outdated revision. Submitted revisions are append-only through the application.

The dashboard shows pending, approved, rejected, and disputed totals and a resolution progress bar. Corrections remain pending. A coordinator can export the progress report, complete revision trail, or a single consistent ZIP containing the two reviewer submissions, adjudicator submission, progress report, and audit trail.

## Export and gold release

The dashboard has no dataset release endpoint. A coordinator exports the bundle, and the authorized release operator runs the existing offline release commands with the exported reviewer files. Unresolved cases still block freeze, and the existing opt-in CI gates remain in place. Use the [gold review and release workflow](expert_review_workflow.md) for the exact release commands. The SQLite trail tracks application writes. Keep restricted backups and coordinator exports if tamper evidence beyond application controls is required.
The [authenticated browser suite and test report](review_browser_test_report.md) document the isolated test accounts, fixture workflow, and export checks.
