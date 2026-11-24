# Legal source context, evidence assembly, and structured answers

## Phase 2 · Source context and references

The baseline embeds a passage with its article title and already maps child vectors back to a complete parent. `CONTEXTUAL_HEADERS=true` changes the embedding input to a compact header with extracted document, chapter, section, article, numbered clause, and explicit effective-date fields where available. The source text and preview IDs remain separate. Long passages still use the tokenizer-aware child planner. Annotation-only fields are excluded from the existing Qdrant payload fingerprint. A changed input creates a versioned collection through the existing indexer and can reuse vectors for identical inputs. Leave the flag off to use the baseline representation.

The reference graph resolves explicit same-document references and uniquely identifiable named documents to actual indexed provisions. It retains the source span, source and target IDs, type, and unresolved status. Unnumbered, ambiguous, and missing targets stay unresolved. Assembly expands relevant verified edges to a maximum depth of two and adds at most four targets. It keeps the original hits, deduplicates parent IDs, and stops revisiting already selected passages.

Across 4,405 extracted parents, the graph resolved 1,089 local mentions and 14 named-source mentions against the indexed target IDs. It left 139 mentions unresolved. These counts measure structural target matching. Legal relevance of the linked provisions still requires review.

The extraction audit retains original pages and records potential page numbers, malformed characters, mixed Latin/Cyrillic scripts, broken words, suspicious whitespace, and labeled notes. It preserves legal numbering, editorial notes, and amendment text. A bare number is flagged for review because extraction alone cannot distinguish every footer from legal content. `sığorta.pdf` had 93 pages with no extractable text. Those pages still require OCR before they can support an answer.

### Measured header comparison

Six fixed, provision-backed Azerbaijani queries used the same 57 real parent passages, including 48 distractors selected by stable ID hash. Both sides encoded the passages with the same cached E5 checkpoint and ranked by exact cosine similarity, taking the best matching child per parent. The comparison excludes BM25, BGE, and answer generation. The relevance labels remain pending domain-expert review.

| Dense representation | Recall@5 | Recall@10 | nDCG@10 | Child vectors | Mean input tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline article title | 0.833 | 0.917 | 0.883 | 59 | 139.2 |
| Contextual header | 1.000 | 1.000 | 0.911 | 60 | 163.4 |

One occupational exclusion passage moved from rank 22 to 5 and a limitation-period passage moved from 8 to 3. A privacy passage fell from rank 1 to 3. Actual maximum input lengths were 507 baseline and 502 with headers against the 512-token limit. These results justify a larger comparison and leave the production default in place. [Per-query results](contextual_headers_results.json)

## Phase 3 · Evidence assembly

`LEGAL_EVIDENCE=true` assembles canonical parents, local context, and relevant reference targets. It keeps source identity, original text, period metadata, retrieval branch ranks and scores where available, sub-question attribution, and linked provisions. The existing comparison mode retrieves each explicitly requested law independently. The Phase 1 routing and decomposition flags can add independent branches for recognized legal topics and multipart requests.

Version comparison uses documented legal identity, numbered provisions, and known applicable periods. Different texts for the same provision with unresolved timing are marked as a potential conflict. Known nonoverlapping periods are kept distinct. Document authority and dates are used only where recorded. The system leaves uncertain validity unknown and does not decide legal priority from rankings or document recency.

## Phase 4 · Structured generation and abstention

`STRUCTURED_ANSWERS=true` adds `references`, `limitations`, `evidence_status`, and `confidence` to legal answers. Existing `answer`, `sources`, and preview fields remain available to the frontend. The model supplies only source markers from the packed evidence. The server reconstructs each reference from canonical metadata and rejects unsupported marker IDs and numbers. Government-wide negative claims inferred from missing evidence are rejected. The existing source-backed salary calculation remains deterministic.

`LEGAL_FAITHFULNESS=true` uses a separate semantic check for conditions, exceptions, deadlines, and combined claims before returning generated legal statements. The structured path abstains if the judge is unavailable or no claim survives validation. A complete answer also requires requested article, document, and sub-question coverage where applicable and the configured minimum number of supporting retrieval stages (`LEGAL_MIN_SUPPORTING_STAGES`, default 1). The policy has no universal reranker-score threshold. Confidence remains capped at medium pending expert calibration. JSON validation and a judge decision do not establish legal correctness.

### Reproduction and expert calibration

```sh
python -m evaluation.evaluate_contextual_headers --output evaluation/contextual_headers_results.json
python -m evaluation.evaluate_legal_faithfulness --probe --output evaluation/legal_faithfulness_probe.json
python -m evaluation.evaluate_legal_faithfulness --reviewed approved-claims.json --output claim-validation-results.json
```

The reviewed-claims input requires `reviewer`, `status: "approved"`, and `claims` containing `id`, `text`, `passage_ids`, and a Boolean `supported` label for each claim. Include both supported statements and material omissions, altered thresholds, incorrect deadlines, conflicting versions, and unsupported negative claims. Use separate evaluation judgments before promoting a policy or changing production defaults.

The live probe used the indexed AZR097 claims provision. It passed the deterministic check, then the semantic-validation provider returned HTTP 429. No human-approved claim dataset was available, so there are no measured judge accuracy or calibration results. The isolated regression tests use controlled semantic responses to verify that unsupported claims are rejected and provider failures lead to abstention. [Probe output](legal_faithfulness_probe.json)

The backend suite passed 123 tests. The original 108-query fixture and production Qdrant collections were preserved. All four feature flags default to off.
