"""Render the held-out BGE policy experiment and compact per-query comparisons."""

import argparse
from pathlib import Path
import json
from statistics import mean, median, quantiles


KEYS = ("recall@5", "recall@10", "recall@20", "recall@50", "mrr@20", "ndcg@5", "ndcg@10")
EXPERIMENTS = ("A", "B", "C", "D")


def quality_table(rows):
    yield "| Experiment | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@5 | nDCG@10 |"
    yield "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    for experiment in EXPERIMENTS:
        values = [row["experiments"][experiment]["metrics"] for row in rows if row["covered"]]
        cells = " | ".join(f"{mean(row[key] for row in values):.3f}" if values else "—" for key in KEYS)
        yield f"| {experiment} | {len(values)} | {cells} |"


def percentile(values):
    return f"{median(values):.2f} / {quantiles(values, n=100, method='inclusive')[94]:.2f}" if len(values) > 1 else "—"


def render(data):
    rows = data["rows"]
    cats = list(dict.fromkeys(row["category"] for row in rows))
    lines = [
        "# BGE cross-encoder policy experiment", "",
        "**Recommendation:** Keep the baseline as the production default. The bounded BGE path is "
        "an opt-in guard against silent overlength truncation. The held-out sample and latency repetitions "
        "are too small to justify a production ranking or speed claim.", "",
        "Both paths use `BAAI/bge-reranker-v2-m3`. The experiment evaluates the policy, not a model replacement. "
        "See the [baseline audit](bge_reranking_audit.md) for the active revision, tokenizer, pair limit, "
        "parent resolution, score handling, and defaults.", "",
        "## Validation-only tuning", "",
        f"The split assigned {len(data['validation_ids'])} queries to validation and {len(data['heldout_ids'])} to held-out. "
        "Queries sharing labeled parents stay in the same partition. Label review is pending. The grid uses "
        "candidate inclusion and unreranked RRF metrics. Higher validation nDCG@10 selects the weights. "
        "The smallest pool within 0.03 of the selected weights' best candidate recall is selected. "
        "No held-out measurements select settings.", "",
        f"Selected BM25/dense weights **{data['selected_weights'][0]:.1f}/{data['selected_weights'][1]:.1f}**, "
        f"pool **{data['selected_pool']}**, RRF constant **{data['rrf_k']}**.", "",
        "| Weights BM25/dense | Candidate pool | Scored queries | Candidate recall | RRF nDCG@10 | All required at 5 / 8 / 10 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in data["validation_grid"]:
        weights = "/".join(f"{w:.1f}" for w in row["weights"])
        coverage = " / ".join(f"{row[f'all_required@{k}']:.3f}" for k in (5, 8, 10))
        lines.append(f"| {weights} | {row['pool']} | {row['n']} | {row['pool_recall']:.3f} | "
                     f"{row['ndcg@10']:.3f} | {coverage} |")
    lines.extend([
        "", "## Held-out comparison", "",
        f"This paired exploratory sample covers {len(rows)} held-out queries. It includes the source "
        "categories below, multi-parent labels, and an unanswerable control. The control is reported "
        "without a relevance denominator. The original 108-query fixture is untouched.", "",
        "- A uses equal RRF weights and the existing BGE scoring path.",
        "- B uses equal RRF weights and bounded BGE scoring.",
        "- C uses the selected RRF weights and the existing BGE scoring path.",
        "- D uses the selected RRF weights and bounded BGE scoring.",
        "",
        "All four experiments use the selected validation pool. A retains the baseline scoring policy, "
        "while the running service still uses its independent 24-parent default.",
        "", *quality_table(rows), "",
        "| Experiment | Selected-pool recall | All required in final context at 5 / 8 / 10 |",
        "| --- | ---: | ---: |",
    ])
    for experiment in EXPERIMENTS:
        results = [row["experiments"][experiment] for row in rows if row["covered"]]
        recall = mean(sum(r is not None for r in row["candidate_ranks"].values()) /
                      len(row["candidate_ranks"]) for row in results)
        selections = " / ".join(f"{mean(all(r['survives_top_k'].get(str(k), {}).values()) if r['survives_top_k'] else False for r in results):.3f}"
                                for k in (5, 8, 10))
        lines.append(f"| {experiment} | {recall:.3f} | {selections} |")
    lines.extend(["", "## Category results", ""])
    for cat in cats:
        group = [row for row in rows if row["category"] == cat]
        lines.extend([f"### {cat.replace('_', ' ').capitalize()}", "", *quality_table(group), ""])
    lines.extend([
        "## Per-query outcomes", "",
        "The following ranks are the best labeled-parent rank in each experiment. The [main run](bge_reranking_results.json) "
        "and [privacy run](bge_reranking_privacy_results.json) retain "
        "BM25, dense, RRF, candidate-pool, and final rank for each labeled parent, plus final selection "
        "at 5, 8, and 10. A dash means no labeled parent in the top 50.", "",
        "| ID | Query | A | B | C | D |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ])
    for row in rows:
        best = []
        for experiment in EXPERIMENTS:
            ranks = [rank for rank in row["experiments"][experiment]["final_ranks"].values() if rank is not None]
            best.append(str(min(ranks)) if ranks else "—")
        lines.append(f"| {row['id']} | {row['query']} | {' | '.join(best)} |")
    lines.extend(["", "## Failure and latency interpretation", ""])
    for old, new in (("A", "B"), ("C", "D"), ("A", "C"), ("B", "D")):
        improvements = regressions = admissions = losses = 0
        for row in rows:
            first, second = row["experiments"][old], row["experiments"][new]
            for key, rank in first["final_ranks"].items():
                after = second["final_ranks"][key]
                improvements += (after or 51) < (rank or 51)
                regressions += (after or 51) > (rank or 51)
                admissions += first["candidate_ranks"][key] is None and second["candidate_ranks"][key] is not None
                losses += first["candidate_ranks"][key] is not None and second["candidate_ranks"][key] is None
        lines.append(f"- {old} → {new}: {improvements} labeled-parent rank improvements, {regressions} regressions, "
                     f"{admissions} pool admissions, and {losses} pool losses.")
    lines.extend([
        "", "A versus B and C versus D hold retrieval constant. The reranking policy can only change ordering "
        "inside the selected pool. A versus C and B versus D change RRF weighting and may change candidate membership. "
        "A rank movement on a single colloquial or exception case cannot establish a general semantic gain.",
        "", "## Cases for follow-up", "",
    ])
    for row in rows:
        if not row["covered"]:
            lines.append(f"- {row['id']} is a coverage-gap control. This retrieval experiment did not test answer abstention.")
            continue
        first = row["experiments"]["A"]
        if not any(rank is not None for rank in first["candidate_ranks"].values()):
            lexical = sum(rank is not None for rank in row["bm25"].values())
            dense = sum(rank is not None for rank in row["dense"].values())
            lines.append(f"- {row['id']} had zero labeled parents in the equal-weight scoring pool. "
                         f"Its recorded BM25 and dense lists contained {lexical} and {dense} labeled parents, respectively.")
        elif row["id"] == "AZR141":
            for label in ("A", "D"):
                ranks = row["experiments"][label]["final_ranks"].values()
                display = ", ".join(str(rank) if rank is not None else "outside top 50" for rank in ranks)
                lines.append(f"- {row['id']} written-consent follow-up had labeled-parent ranks {display} in {label}.")
    lines.extend([
        "", "## CPU latency", "",
        "| Experiment | Uncached samples | Reranking p50 / p95 ms | Pipeline p50 / p95 ms |",
        "| --- | ---: | ---: | ---: |",
    ])
    for experiment in EXPERIMENTS:
        timings = [timing for row in rows for timing in row["experiments"][experiment]["uncached_timings"]]
        lines.append(f"| {experiment} | {len(timings)} | {percentile([t['rerank_ms'] for t in timings])} | "
                     f"{percentile([t['pipeline_ms'] for t in timings])} |")
    lines.extend([
        "", f"CPU only, {data['threads']} Torch threads. Ranking scores were computed in batches on the union of "
        "candidate parents for each policy and reused across its weight settings. Latency observations replayed "
        "each configuration independently without cached scores after model load. Pipeline timings end at final "
        "context selection. They exclude HTTP, startup, and answer generation. Pairwise p95 values from two samples are descriptive.",
        "", "The benchmark uses an isolated exact copy of the existing token-aware archive. The application service "
        "and its Qdrant collections were untouched. CUDA was unavailable in the audit environment. "
        "The device setting was tested at the model interface only.", "",
        "## Reproduction", "",
        "Use the frozen corpus export and archived vectors described in the [real-corpus report](real_insurance_report.md). "
        "Run the commands in an isolated environment with the project's dependencies and cached Hugging Face weights. "
        "Set `RERANK_MODEL` to the local snapshot directory for the BGE commit in the audit to pin the checkpoint. "
        "The checks cover loading, batching, overlength refusal, preserving a late exception and source citations, "
        "and keeping shared legal parents out of both benchmark partitions.", "",
        "```sh",
        "python -m evaluation.evaluate_bge_reranking --dataset evaluation/real_insurance_dataset.json --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl --output evaluation/bge_reranking_results.json",
        "python -m evaluation.evaluate_bge_reranking --dataset evaluation/real_insurance_dataset.json --snapshot .venv/eval_corpus_snapshot.json --vectors .venv/real_eval_vectors.jsonl --latency-cases 0 --only-ids AZR036 AZR141 --output evaluation/bge_reranking_privacy_results.json",
        "python -m evaluation.render_bge_reranking_report --results evaluation/bge_reranking_results.json --additional evaluation/bge_reranking_privacy_results.json --output evaluation/bge_reranking_report.md",
        "```", "",
        "Keep `RERANK_MODE=baseline` for rollback. Before adoption, repeat the comparison with expert-approved "
        "judgments, a larger held-out sample, and representative deployment hardware.", "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--additional", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8"))
    if args.additional:
        other = json.loads(args.additional.read_text(encoding="utf-8"))
        keys = ("selected_weights", "selected_pool", "validation_ids", "heldout_ids", "archive")
        if any(data[key] != other[key] for key in keys):
            parser.error("Additional run must match the same frozen experiment")
        data["rows"].extend(other["rows"])
    args.output.write_text(render(data), encoding="utf-8")


if __name__ == "__main__":
    main()
