# Source authority and temporal applicability

Set LEGAL_SOURCE_AUTHORITY=1 to opt in for /ask. The default path, retrieval ranking and filters, Qdrant data and hardened verifier decisions are unchanged. The layer annotates assembled evidence and returned references. The opted-in legal answer path uses the existing structured generator and claim judge. It retains source order and excludes context-only sources from legal claim binding and from the judge's legal evidence. A textbook- or news-only result returns exact educational excerpts and source locators in the source_authority response field, alongside an insufficient legal answer.

## Catalog and provenance

The catalog is bound to document IDs, recorded source byte hashes where available, and exact indexed anchor hashes. Evidence of authority comes from enactment and signature blocks, Cabinet date and number, a publisher imprint and academic approval, or explicit news attribution. The frozen API export lacks embedded version IDs, so its checked classifications carry indexed_anchors_only. A runtime version mismatch yields unclassified. Unclassified evidence remains visible and cannot support a legal claim.

| Category | Frozen inventory |
| --- | --- |
| Laws and codes | Seven statutes. Anchored adoption dates and signed act dates are recorded separately. No separate code fixture appears in this export. |
| Government resolutions and regulations | Cabinet Decisions 149 and 156, with their printed decision dates and Cabinet issuance. |
| Other normative acts | The catalog supports this category. No separately verified example appears in the frozen inventory. |
| Academic textbooks | Sığorta işi, with academic approval and publisher imprint. Only the publication year is documented. |
| Methodological or explanatory materials | The catalog supports this category. No standalone official methodological source was verified. |
| News and general information | Two indexed Trend summaries with their stated publication dates. Their descriptions remain contextual. |

The response carries separate document and provision metadata, exact source and passage IDs, page where available, and the official locator when the bytes match the existing provenance registry.

## Dates and conflicts

The optional case_dates object accepts insured_event_date, contract_start, contract_termination, and requested_reference_date as ISO calendar dates. These are labeled request assertions. Existing filters.as_of can supply the reference date and retains its retrieval behavior. case_dates.requested_reference_date itself does not filter retrieval. The layer records the relationship between the asserted event and contract dates separately and keeps the timing of boundary-day events unknown.

- The indexed **1618-VQD** amendment note distinguishes adoption on **2019-06-27**, publication on **2019-08-21**, and effectiveness on **2020-01-01** for the named additions. A documented start alone does not establish applicability at a later date.
- Cabinet Decision **156** directs repeal of annex subparagraph **1.1.1** under Decision **196**. The directive and its act date are recorded. The repeal effective date is unknown.
- Social insurance §14.5.6 is visibly struck through in the earlier PDF audit. Its indexed text stays historical and its repeal date remains unknown. Comparison with §14.5.1-1.9 is flagged as historical review.
- Social insurance §§14-1.1.1.1 and 14-1.1.1.2 state successive subsidy periods for a specified group. These are recorded as rule periods. The shared transition boundary requires review.

The detector compares anchored provisions with the same reviewed issue and person-group scope and different rule families. It records exact references, applicable dates, insurance type, group, status and whether expert review is required. It does not choose a controlling source based on publication date or hierarchy. Unresolved potential conflicts block affirmative generation and are returned with their references. Historical comparisons and documented transitions remain distinct. The overlapping-issue fixture tests the detector without asserting that its selected source passages conflict in law.

Current-law requests without a documented date basis and dated questions whose effective period is unknown retain that uncertainty. The response and capture carry provision annotations separately from asserted case dates for downstream verification. Arbitrary semantic conflicts, priority, transitional interpretation and statutory currency still require expert review. No legal expert validation was performed.

## Regression

All **191 regression tests passed**, including five new source-authority tests. They cover version binding, educational context retention, acceptance of an eligible normative citation and rejection of context-only legal citations, multiple normative candidates, unresolved conflict, date separation, amendments and repeal, unknown effective periods, historical text, and transitional boundaries. No provider or Qdrant service is needed. The hardened verifier comparison against all 43 fixtures produced byte-identical results. The 108-query benchmark, four legacy fixture hashes, seven-case draft and proposed v2 were preserved.
