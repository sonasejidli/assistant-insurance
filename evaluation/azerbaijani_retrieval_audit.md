# Azerbaijani retrieval audit

The audit used the running local API and the complete indexed corpus. The source directory contained 801 PDF pages and two text files. PDF extraction found text on 708 pages. All 93 pages of `sığorta.pdf` returned empty text and were excluded. The baseline index contained 4,376 passages.

## Baseline findings

| Probe | Observed result |
| --- | --- |
| Subrogation, AZ010 | The relevant clause 25.2 in `sığorta 2.pdf` ranked first in dense retrieval, fusion, and reranking. |
| Third-party motor property damage, AZ014 | Clause 56.1.2 in `sığorta 2.pdf` was absent from the first 50 BM25 results. Dense search found it at rank 11, fusion placed it at 22, and reranking moved it to 2. The intent rule did not identify the request as insurance, so the default `/ask` path could stop before retrieval. |
| Same motor question without Azerbaijani diacritics | The clause was absent from the first 50 results of both branches and could not reach the reranker. |
| Crash notification, AZ013 | The top five included passages on duties of the insurer. The corpus also contains clause 22.2.4 of the compulsory insurance law and clause 7.2.6 of the occupational insurance law, which address different notification duties. Preserve that scope when answering. |
| Doctor visit costs, AZ015 | The query lacked an explicit insurance keyword. The parser also indexed voluntary-health Article 13 text under Article 9 because it missed indented headings with spaced digits. The text and metadata were checked against PDF pages 6 and 7. |
| Salary threshold, AZ097 | The medical premium clause 15-10.1.2 ranked 10th in dense search, 20th in fusion, and 7th after reranking. The answer path's default five passages could omit it. The question itself does not specify which type of insurance applies. |
| Exact motor clause via `/ask` | An explicitly filtered lookup had the direct clause available, yet the API returned its generic insufficient-evidence response. A separate generation call with just that clause returned a valid cited answer. The earlier API response alone cannot identify whether the model declined, cited the wrong passages, or failed syntax checks. |

## Diagnosis and changes

- **Embedding quality.** The same multilingual E5 model retrieved formal wording and some conversational wording well. The plain-ASCII motor probe missed an indexed clause. This sample supports improving lexical coverage for colloquial queries. It is too small to compare embedding models reliably.
- **Model configuration and preprocessing.** The running service used `intfloat/multilingual-e5-large`. The code applies `query:` for questions and `passage:` for indexed passages, adds the article title to the passage when useful, and produces normalized float32 vectors. Those are the expected E5 retrieval prefixes. [E5 model card](https://huggingface.co/intfloat/multilingual-e5-large)
- **Thresholds.** The vector candidate threshold was 0.0 and the highest selected cosine scores in these probes ranged from 0.766 to 0.870. The old answer gate of 0.35 did not explain these results. It could still suppress a usable lexical result with low or missing vector similarity, so the application now passes usable hits to grounded generation. The vector branch retains its configurable threshold.
- **Chunking.** The parser now handles indented PDF article headings with spaced digits before splitting clauses. This restores article, clause, and page metadata for affected text. Page boundaries remain intact.
- **Qdrant.** The default and explicit exact searches returned the same set of 50 candidates for all six baseline probes. This rules out a candidate membership difference for those probes only. The installed client reported a version compatibility warning against the local server, but both query paths and exact article retrieval worked in this audit.
- **Reranking.** The cross-encoder ran successfully. It moved the motor clause from fused rank 22 to rank 2 and the medical premium clause from rank 20 to rank 7. Scoring the entire union was slow enough for some HTTP probes to time out. The API now reranks a configurable shortlist, keeps a place for leaders of each active branch, and retains fused order when the reranker fails.
- **Terminology and routing.** The lexical dictionary now maps colloquial accident reporting, third-party motor property damage, and doctor-visit cost questions to formal terms. It uses the same concept normalization for diacritic-free spelling. History can supply search context without turning a new follow-up into an exact lookup for the previous article.
- **Corpus coverage.** The extracted corpus contains the motor and medical provisions used above. The audit could not assess coverage on the 93 inaccessible pages. OCR text and review of its legal numbering would be needed before adding those pages to the index.
- **Evidence and fallback.** The service now distinguishes empty retrieval, the generation model's explicit no-evidence decision, and invalid answer formatting in logs. It retries invalid formatting once with the same citation requirements and a shorter prompt format. Repeated invalid output surfaces as an answer-service error. The model still decides whether retrieved passages answer the question.

## Verification on the rebuilt index

- The corrected PDF parser increased the index from 4,376 to 4,405 passages and recovered the Article 13 metadata for the voluntary medical service payment provision on PDF page 7.
- On the motor question without diacritics, BM25 recovered the target clause at rank 4 and the reranker placed it at rank 2. The embedding model was held constant. On the version with diacritics, the fused rank improved from 22 to 5 and the reranked position stayed at 2.
- The end-to-end motor request returned citations to clauses 56.1.2 and 58.3. The API logged an initial citation-format rejection and succeeded on the shorter retry. The exact filtered motor request also returned its source.
- The crash-notification search returned the occupational provision 7.2.6 at rank 1 and the compulsory insurance provisions 22.2.4 and 24.1.1 at ranks 4 and 5. Their applicability depends on the type of insurance and the role of the person reporting the incident.
- A question about payment for voluntary medical services returned a cited answer using the recovered clause 13.2.3. The broader doctor-cost question reached medical evidence, but OpenRouter rate-limited answer attempts with HTTP 429. The API surfaced an answer-service error. A deliberately unsupported question returned the insufficient-evidence response with no citations.
- The general salary question still placed the medical premium provision at rank 7 in the sampled shortlist. When the question named compulsory medical insurance and the 8,000-manat wage band, the same provision ranked first.
- All 90 regression tests passed. The deployed frontend proxy and API reported the rebuilt 4,405-passage index as healthy.
