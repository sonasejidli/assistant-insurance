# Embedding truncation validation

## Model and index audit

The API uses `intfloat/multilingual-e5-large` at cached revision `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`. The Sentence Transformers module and tokenizer both specify 512 input tokens, including special tokens. The installed preprocessing code uses `longest_first` truncation. The tokenizer truncates from the right on a single passage. [E5 model card](https://huggingface.co/intfloat/multilingual-e5-large)

The former index stored 4,405 complete passages and one vector per passage. Counting the exact inputs, including article titles where inserted, the passage prefix, and special tokens, gave a 95th percentile of 498 and a maximum of 619. The old encoder omitted text from 155 inputs, all from `Sığorta kitab.pdf`. Heuristic checks flagged 29 omitted tails, with 19 numeric or threshold signals, 11 condition signals, two reference signals, and one exception signal. Categories overlap. A number alone can be a list marker. Manual review found substantive examples, including terms for life insurance premiums on PDF page 279 and a per-risk reinsurance liability limit on page 297.

The corrected index has 4,405 parents and 4,560 vector points. The maximum planned input is 512 tokens and all 155 split parents have continuous body coverage from their first through last character. The first child retains the parent point ID and its complete source text. Every child stores the parent ID, body offsets, source metadata, and original and effective token counts. The encoder also checks lengths immediately before encoding.

## Dense retrieval comparison

Exact Qdrant search ranked the same 4,405 parents at the configured threshold of 0.0. The baseline uses the deployed one-vector-per-parent collection `insurance_chunks_64393a257fd78e72bae8ced3`. The rebuilt collection `insurance_chunks_cf440db13ba21e18d71044eb` ranks each parent by its best child. The model and query wording were held constant. Rankings exclude BM25, reranking, and answer generation to isolate changes in dense retrieval.

| Judged evidence | Before | After |
| --- | ---: | ---: |
| Life insurance premium reserve, textbook PDF p. 279 | 57 | 55 |
| Insured risk list, textbook PDF p. 196 | 2,911 | 2,511 |
| Driver discounts, textbook PDF p. 239 | 144 | 134 |
| Legal expenses, textbook PDF p. 179 | 1,224 | 2,409 |
| Per-risk reinsurance liability, textbook PDF p. 297 | 1,484 | 1,597 |
| Motor property damage, law clause 56.1.2 | 11 | 11 |
| Subrogation, law clause 25.2 | 1 | 1 |
| Medical premium wage band, law clause 15-10.1.2 | 2 | 2 |

Hit rate at 50 was **0/5** for the textbook targets and **3/3** for the controls in both runs. Three textbook ranks improved and two fell. The textbook's extracted text uses a legacy Cyrillic encoding while the questions use modern Latin Azerbaijani. That difference may contribute to the weak ranks. The benchmark did not isolate it.

In a controlled Latin-script fixture, the same fictional exception contained both a water-level condition and a payment cap after token 512. Its parent ranked **4th and 3rd** for two queries with the old encoder and **1st for both** with child chunks. Targets of 512, 480, and 448 tied on the fixture. The tokenizer audit found that those targets would split 155, 283, and 358 real passages, respectively. The 512 default fixes all measured truncation and changes the fewest existing passage inputs. The shorter targets were not evaluated across the complete corpus.

All 93 regression tests passed. These include the encoder's overflow check, child coverage with bounded overlap, a searchable exception, stable parent IDs, and intact citation metadata.

With the original collection still available in the configured Qdrant instance, reproduce using:

```sh
python evaluation/evaluate_embedding_truncation.py --baseline insurance_chunks_64393a257fd78e72bae8ced3
```
