# Expert review browser tests

The dashboard uses a standalone FastAPI service, bearer tokens assigned to four named roles, and an append-only SQLite revision store. The existing backend tests use FastAPI TestClient and the application frontend uses Vitest. No browser automation was configured for the dashboard. The new suite uses Playwright Python with headless Chromium or an installed Chrome channel. [Playwright tracing reference](https://playwright.dev/python/docs/api/class-tracing)

## Reproduce

Use the project Python environment and install the separate browser test dependency. Provision four distinct URL-safe, high-entropy test tokens through the environment or your test secret store. The runner uses them to configure the dashboard's real roles and SHA-256 credential checks. It never requires production reviewer credentials.

| Environment variable | Test account |
| --- | --- |
| `REVIEW_E2E_REVIEWER_A_TOKEN` | Reviewer A |
| `REVIEW_E2E_REVIEWER_B_TOKEN` | Reviewer B |
| `REVIEW_E2E_ADJUDICATOR_TOKEN` | Adjudicator |
| `REVIEW_E2E_COORDINATOR_TOKEN` | Release Operator (coordinator role) |

```sh
python -m pip install -r evaluation/requirements-browser.txt
python -m playwright install chromium
python -m evaluation.run_review_browser_tests --output .venv/review-browser-results
```

Use `--channel chrome` for an installed Chrome and a new output directory for each run. The runner starts the dashboard on an ephemeral loopback port, logs in through the token form in separate browser contexts, and uses a temporary SQLite database containing only four synthetic cases. Action synchronization uses DOM assertions, HTTP responses, and the actual form refresh. The report records scenario outcomes, roles, fixture IDs, failure details, artifact paths, and export validation. Failures retain screenshots and traces. Password fields are masked in explicit screenshots, and test tokens are redacted from diagnostics before traces are exported.

## Verification boundaries

The browser exercises the actual dashboard HTML and JavaScript, role authentication, independent submissions, adjudication, revision persistence, and an operator-initiated ZIP download. Supplementary requests from the browser test context check denied routes, impersonation, stale writes, and absent edit/delete endpoints. The offline check invokes the same resolver, source validator, and freeze function as the existing release CLI. The incomplete fixture must fail the gate. The fully resolved fixture must pass in memory. The production release CLI is not invoked, and no gold release is written.

The runner verifies raw hashes of the real review packet, corpus dataset, original benchmark fixtures, and lock files before and after execution. It checks that cleanup removed the temporary test database directory. It does not mount or open a real review database. All tests leave existing APIs, retrieval settings, models, and Qdrant collections untouched.

## Results

Two consecutive runs on Chrome 157.0.8103.79 passed all six scenarios. The four named test accounts authenticated against the real dashboard. Both runs verified that protected fixtures were unchanged and the disposable database directory was removed.

| Scenario | Roles exercised | Fixture IDs | Result |
| --- | --- | --- | --- |
| A. Independent decisions and source inspection | Reviewer A, Reviewer B, Adjudicator | E2E-MP | Pass |
| B. Disagreement and peer privacy | Reviewer A, Adjudicator | E2E-MP | Pass |
| C. Adjudication and locked reviewer decisions | Reviewer A, Adjudicator | E2E-MP | Pass |
| D. Append-only revisions and persistence after sign-in | Reviewer A, Reviewer B | E2E-REJECT, E2E-DISPUTE | Pass |
| E. ZIP export and offline release gate | All four roles | All four fixtures | Pass. Unresolved cohort blocked and resolved fixture passed in memory. |
| F. Access restrictions and isolation | Anonymous, all four authenticated roles | All fixtures and a real case ID used as a negative lookup | Pass |

The first development run found an ambiguous selector on the disagreement screen. The second found a case-selection timing race in the test. Both were corrected in the runner without editing dashboard behavior. The diagnostic reports include screenshot and trace filenames. The passing reruns retained no screenshots or traces. [First diagnostics](../.venv/review-browser-run-01/report.json) · [Second diagnostics](../.venv/review-browser-run-02/report.json) · [Passing run 1](../.venv/review-browser-run-03/report.json) · [Passing run 2](../.venv/review-browser-run-04/report.json)

The backend suite passed 154 tests in the isolated backend image. The existing frontend suite passed 19 Vitest tests. The original 108-query benchmark matched its locked lexical ranking hash. Browser coverage was run on Chrome with dedicated test accounts. Production sign-in and production release were outside the test scope.
