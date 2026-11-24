# Real insurance benchmark review and reproduction

The [dataset](real_insurance_dataset.json) contains 164 Azerbaijani queries. Of these, 150 have manually selected evidence from the indexed documents and 14 ask for private records or policy-specific terms absent from this corpus. The examples contain no real customer identifiers. The original 108-query fixture and results remain separate.

## Domain review

Use the [label review packet](real_insurance_label_review.json) alongside the dataset. The questions were written after reading the indexed provisions and before the evaluation run. The draft does not assume that a top-ranked passage is relevant or that the selected evidence is exhaustive. It also does not certify the source versions as current law.

- For each covered case, open the source preview, verify the provision's scope, and check whether the cited set answers the question. Add supported alternative evidence and distinguish necessary parents from supplementary context before approval.
- Check if the follow-up's expected standalone text preserves the referent, qualifiers, and units. Equivalent wording is acceptable.
- For coverage-gap controls, check that no indexed document provides the specific private record or contract term requested. General provisions about the same topic cannot establish the requested private fact.
- For a correction, update the source-aware dataset and create a fresh review packet for its new hash. Record the reviewer's identity, applicable expertise, and decision for each query. An approved report requires a complete approved sidecar for that exact dataset hash.
- Review the individual failure hypotheses in the results. Attach concrete evidence to the final category. For example, a PDF page image compared with its extracted text can establish an extraction failure. A correctly extracted rule missing from the vector index points to indexing or chunking. A low score alone establishes neither.

Passage and parent IDs intentionally refer to the API's canonical source passage. Dense children are internal views of the parent. The reviewer can open the full parent using the relative `source_url`. The evidence text matches the frozen indexed representation, which can differ in typography from the PDF. The textbook includes legacy Cyrillic text in its extracted layer.

## Answer review

The answer packet records the selected evaluation cases, exact context, expected sources, candidate answer or service error, and citation IDs. A case with incomplete required context is reported as blocked upstream. Examine factual correctness, evidence coverage, citation support, whether legal conditions and exceptions survive, whether any missing provision was invented, and whether abstention was appropriate. Mark each check as pass, fail, or not applicable with reviewer identity and notes. Only a human-reviewed answer set can yield a final quality score. A valid citation marker by itself confirms format and source ID only.

## Reproduction

Run from the repository root in an environment with the project dependencies and cached model revisions. The source names, passage IDs, and corpus hash are validated before scoring.

```sh
python evaluation/export_real_insurance_snapshot.py --api http://127.0.0.1:8000 --qdrant http://qdrant:6333 --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl --archives insurance_chunks_64393a257fd78e72bae8ced3 insurance_chunks_cf440db13ba21e18d71044eb
```

Use a host or container that can reach the supplied addresses. The export uses document reads, collection metadata reads, and Qdrant scroll only. It performs no writes to the indexed service. Keep the large vector snapshots outside version control. The benchmark can run offline after export.

```sh
python evaluation/evaluate_real_insurance.py --draft --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl --output evaluation/real_insurance_draft_results.json --rerank-depth 8 --rerank-ids AZR001 AZR017 AZR044 AZR049 AZR068 AZR082 AZR097 AZR112 AZR126 AZR137 AZR138 AZR139 AZR140 AZR149 AZR151
```

The measured run used A–C on all 164 cases and D on the declared 15-case sample. Omit `--rerank-ids` to evaluate D on all cases. For a final run, supply the completed `--reviews` sidecar, omit `--draft`, and use the production shortlist depth. Keep the corpus, candidate depths, model revisions, CPU thread count, and repetition count constant when comparing versions. This requires no service-side collection creation, reuse, or deletion.

```sh
python evaluation/render_real_insurance_report.py --dataset evaluation/real_insurance_dataset.json --results evaluation/real_insurance_draft_results.json --output evaluation/real_insurance_report.md
```

Use `evaluation/prepare_real_insurance_review.py --help` to recreate label and answer packets. Its optional `--generate` flag calls the configured answer provider for the explicitly selected cases. Keep generated answers and scores marked pending until reviewed.
