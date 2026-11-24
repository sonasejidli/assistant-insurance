# Reliability and source completeness

## Initial audit

- The six multipart diagnostic cases found every labeled parent in only one case. The splitter rejected whole questions when an alternative or pronoun appeared anywhere, and it copied the entire prefix before the first interrogative into later clauses. That prefix could carry a different product or legal condition. RRF balanced rankings from each sub-query, but its evidence associations meant only that a passage appeared in a sub-query result list.
- Cross-reference resolution looked up exact identifiers. A reference to the head of a numbered group could omit relevant descendants. The context builder did not reserve space for independently requested rules or label the unresolved parts explicitly.
- Structured answers checked whether a cited passage contained the same number. That check could admit a change from working days to calendar days or a number taken from an unrelated citation. The semantic stage relies on provider access. The last live provider check returned HTTP 429.
- The frozen corpus omitted a consolidated Civil Code, the general personal-data law, a separate clinical confidentiality source and the authoritative motor-premium rule. The 93-page scanned source had no searchable text. Its title and legal version cannot be inferred from its filename.

## Implementation and controls

| Area | Changes | Main files |
| --- | --- | --- |
| Multipart retrieval | `LEGAL_RETRIEVAL_V2` splits explicitly coordinated insurance scopes, carries forward the applicable topic for independent parts, preserves coupled conditions, and adds at most one deterministic formal-terminology search per part. Original queries stay in the pool. | `App/query_plan.py`, `App/main.py` |
| Evidence coverage | Verified root clauses can supply their indexed descendants. Reference-based parts can receive the related passage when its text matches the part. The API distinguishes candidate passage IDs from parts with a semantically accepted claim. | `App/legal_documents.py`, `App/legal_evidence.py`, `App/main.py` |
| Answer guards | `LEGAL_CLAIM_GUARDS` checks cited article identities and number–unit pairs, including working versus calendar days. Explicit requests for current law require a source with verified current status. Partial answers list unanswered parts. Semantic validation remains separate and can cause abstention. | `App/legal_answers.py`, `App/legal_evidence.py` |
| Source overlay | `STAGED_LEGAL_SOURCES` reads only hash-verified manifest entries, preserves original page numbers and serves source previews. The archive contains five staged evidence files with their version hashes. | `App/document_processing.py`, `App/text_search.py`, `App/main.py`, `data/staged_legal/manifest.json` |
| Verification | Added controlled retrieval, source discovery and binding probes, OCR tooling, regression tests and CI checks that hold the new settings off by default. | `evaluation/evaluate_reliability_followup.py`, `evaluation/prepare_staged_sources.py`, `evaluation/recover_scanned_source.py`, `tests/test_reliability_followup.py`, `.github/workflows/regression.yml` |

All new flags default to off. This work made no production Qdrant writes or configuration changes and kept the original E5 and BGE checkpoints.

## Sources staged for isolated evaluation

- **Civil Code.** Archived the full Central Bank copy, with optional indexing scoped to pages 165–174 and 343–376 for limitation and insurance provisions. Verified source anchors for Articles 373, 883 and 935 and preserved the original PDF page numbers. [Central Bank Civil Code copy](https://uploads.cbar.az/assets/dfb5731c1d05df8de8818c622.pdf)
- **Personal Data Act.** Archived the government PDF and verified Articles 13 and 14. Its exact applicable version remains unverified. [Official Personal Data Act](https://frameworks.e-qanun.az/19/19675.pdf)
- **Medical confidentiality.** Extracted Article 53 from e-Qanun's HTML and separately staged Article 1 of the later amendment. The manifest links the older article to the amendment with verified target IDs. The publication date is recorded separately from legal effect. The excerpts still require consolidated-version review. [Health Protection Act](https://frameworks.e-qanun.az/4/c_f_4078.html) · [Official amendment](https://president.az/az/articles/view/67550/print)
- **Compulsory motor tariff.** Archived the 20-page Central Bank rule. Verified its decision identifier, base-premium provision and coefficient-table anchor. Page citations point to the PDF because the extracted table structure still needs review. [Central Bank tariff rule](https://uploads.cbar.az/assets/0e36765b08e04f57f3b2df925.pdf)

## OCR recovery

The original PDF had visible typeset text stored as vector outlines. The first OCR method returned no text. The standalone Tesseract run with Azerbaijani and English language data recovered searchable text on **93 of 93 pages** at 200 dpi. The original stays intact. The derivative's hash and per-page character counts were verified. Pages contain 1,755–5,854 extracted characters, with a median of 4,627.

Visual comparison of page 11 preserved the original layout and exposed a risk that OCR text can read struck-through provisions as ordinary text. The recovered first page identifies the source as a version of the Insurance Activity Act already represented elsewhere in the corpus. The OCR derivative remains outside the staging manifest until version, strike-through, and substantive transcription review. Coverage figures measure searchable extraction. [Searchable derivative](../data/staged_legal/scanned-source-ocr.pdf) · [Page and hash audit](../data/staged_legal/scanned-source-ocr.json)

## Evaluation

The paired multipart test used the same six draft questions, twenty required part–passage associations, frozen E5 archive, and ten-parent output limit. It ran BM25 and dense RRF with assembly in a network-disabled container. BGE and hosted query rewriting were excluded from this diagnostic so the comparison measures query planning and evidence assembly.

| Check | Before | After |
| --- | ---: | ---: |
| Required part–passage associations found after assembly | 4/20 | 7/20 |
| Multipart questions with every association found | 1/6 | 1/6 |
| Correct accept or reject decision on controlled claim bindings | 3/7 | 7/7 |
| OCR pages with searchable extracted text | 0/93 | 93/93 |

The guarded bindings caught working-day changes, a unit change, a stripped deadline qualifier, and a cited reference to an article whose own text was missing. The live semantic-validation probe on a public claims provision returned HTTP 429. Semantic accuracy, abstention accuracy, and real-world answer quality remain unmeasured in this iteration. [Live probe](reliability_faithfulness_probe.json)

The three source PDFs, two extracted health-law excerpts, and OCR artifact have separate provenance. The staged-source benchmark measures BM25 discovery of actual documents and passage anchors. Its four probes have draft judgments and do not establish current legal applicability or jurisdictional completeness. [Per-case and source results](reliability_followup_results.json)

| Source probe | Required document rank | Required passage rank |
| --- | ---: | ---: |
| Civil Code insurance definition | 1 | 60 |
| Personal-data transfer | 1 | 1 |
| Medical confidentiality | 1 | 1 |
| Motor base premium | 1 | 126 |

All four documents were absent from the original corpus. The overlay added 887 searchable parents. The reference audit found ten named links to staged sources and two verified links from the health excerpt to the amendment. Splitting verified tariff prose into numbered clauses improved citation granularity, while the base-premium passage fell from rank 77 in the first overlay experiment to 126. This is a retrieval regression that requires further work before rollout. Median multipart retrieval and assembly time was 323 ms before and 907 ms after in the six-case offline run. These values are descriptive and exclude BGE, answer generation, and HTTP.

**Verification and readiness.** The 135 backend tests, nine cached frontend tests, and original 108-case lexical lock passed. The 164-case relevance dataset remains pending domain review. The new flags should stay off in production while multipart misses, Civil Code and tariff passage ranks, legal versions, OCR transcription, and live semantic calibration remain unresolved. Packaging changes in `Dockerfile` and `.dockerignore` include the proofed sources in the opt-in overlay and omit the unreviewed OCR derivative from the image.
