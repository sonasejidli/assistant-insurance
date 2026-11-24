# RAG run capture and replay

The original seven answers and traces could not be recovered from the supplied artifacts. The browser report records workflow and release-gate tests. Ordinary request telemetry optionally logs or exports metadata, including answer length and source count. The retriever's richer trace is request-local and is reset at the end of the request. None of those paths persists the exact returned answer, model attempts, final ranked passages and generator context together. The new captures are separate runs against the preserved seven-case draft.

## Run the evaluator

```powershell
python -m evaluation.rag_run capture --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl
python -m evaluation.rag_run replay .venv/rag-runs/<run-id> --output .venv/rag-replay.json
```

Capture is opt-in. The runner validates the existing draft against the exported corpus and verifies the archived vectors against the configured encoder. It uses the application query path, retrieval graph, and answer generators with a read-only, exact vector archive. It does not start the app lifespan or connect to Qdrant. This backend may differ from live Qdrant search. The command uses the after archive unless `--archive before` is supplied. The evaluation-only provider timeout defaults to 12 seconds per call and SDK retries are disabled. The pipeline's own answer-format retry still applies. Keep captures on an access-controlled local filesystem that supports hard links. If the capture runs under a different Windows identity, replay it as the capture owner.

## Capture schema version 1

Each run directory contains a manifest, one checksummed JSON record per finished query, and a completion marker written after the final query. The manifest binds the run to the draft dataset, ordered corpus, vector archive, configured model and retrieval parameters, feature flags, and UTC start time. An exclusive run directory rejects duplicate IDs. Records are flushed to disk before atomic publication, with no overwrite. Replay checks hashes and case identities. A process interruption leaves previously published cases readable. An in-flight case without a published record is missing.

| Record section | Fields |
| --- | --- |
| Identity and request | Run ID, request trace ID, case ID, UTC start, exact Azerbaijani input, resolved and normalized text, intent, planned and executed parts. |
| Retrieval | Selected passage IDs in original order, observed ranking depth, part assignments, and per-branch BM25 tokens, BM25/dense/fusion/reranker ranks and scores when produced. Branch filters, part IDs, and merge weights identify planned retrieval calls. |
| Generation | Assembled evidence, exact evidence block sent on each answer attempt, packed citation-to-passage and part mapping, prompt version and SHA-256, configured model and gateway, and upstream model/provider when reported. Includes exact raw generated text for each returned attempt and the exact user-facing answer when one was returned. |
| Decision and citations | Explicit answer mode and decision reason where applicable, emitted IDs and their passage bindings, plus runtime binding and faithfulness validation events. A fallback response may have source previews without a validated answer. |
| Operations | Request latency, per-stage latency, captured exception class and HTTP status when available. Fields unavailable due to a failed path are identified separately from capture omissions. |

The CLI runs only the supplied benchmark questions. It keeps the evaluation capture separate from ordinary telemetry and does not serialize credentials, environment dumps, request headers, conversation history, or exception bodies.

## Replay rules

Replay reads saved records without loading models or regenerating answers. Retrieval uses draft direct evidence labels and the original final ranking. The metric cutoff needs an observed ranking of that depth or a retrieval request at least that deep. Citation validity measures runtime binding of returned markers to packed passage IDs. It is distinct from claim-level citation precision and completeness. Those metrics and answer correctness require an approved review tied to the exact returned answer. Evidence support additionally requires `context_sha256` for the exact final packed evidence block. Pass the JSON review mapping by case ID with `--reviews`. It follows the existing draft evaluator's `generation_review` format. Multipart coverage compares executed sub-questions and assembled part-to-passage assignments with the rubric. A known undecomposed multipart query can score zero. Nonmatching part wording without a reliable alignment remains unscored. Mode accuracy uses explicit applicable modes and excludes provider or validation fallback paths.

## Verification

The first bounded run, `8089bdf26dd24c3b854552a4c49ad074`, saved all seven query records. It captured five final retrieval slots per case and had a mean draft Recall@5 of 0.3827 across all seven cases. Recall@10, MRR@10, and nDCG@10 were unavailable at that depth. Sub-question coverage and multipart evidence attribution were both 0 of 4 under this configuration, which did not execute decomposition. Provider connection errors occurred on all seven requests, after retrieval and context packing. Citation, generation, and mode metrics had zero eligible cases. Replay run twice on the same saved records produced identical JSON output.

The authorized provider run, `2b8af1a8a58244569ff2345a47359394`, also saved all seven records and reproduced the retrieval and multipart results. The legacy validator rejected generated attempts in AZ7-01, AZ7-03, AZ7-04, and AZ7-06. OpenRouter returned HTTP 429 on AZ7-02, AZ7-04, AZ7-05, and AZ7-07. All seven requests returned recovery responses, with mean request latency of 23.02 seconds. Replay found zero capture omissions and four attempts whose output the provider did not produce. Runtime citation validity and answer-mode accuracy had no eligible final answers. Claim-level citation precision, completeness, correctness, and evidence support had no approved review labels. The raw attempts remain in the private capture, and `.venv/rag-replay-provider-final.json` contains the operational outcomes without the answer text.

The Windows failure was traced to the dashboard test's direct `sqlite3.connect` call. The SQLite connection context manages the transaction and leaves the connection open. The test now closes the connection after the original append-only trigger assertion and transaction exit. The full suite passed all 164 tests, including the SQLite cleanup, locked benchmark checks, and capture tests for interrupted runs, duplicate IDs, stage failures, and deterministic replay. The 108-query benchmark, all four locked fixture hashes, and the seven-case draft were preserved. Production settings and Qdrant data were unchanged.
