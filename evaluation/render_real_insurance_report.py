"""Render a report from the frozen real-corpus run and review packets."""

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean, median, quantiles


KEYS = ("recall@5", "recall@10", "recall@20", "recall@50", "mrr@20", "ndcg@10")
STAGES = ("bm25", "dense", "rrf", "reranked")


def score_table(rows, stages):
    lines = [
        "| Stage | Version | Scored queries | R@5 | R@10 | R@20 | R@50 | MRR@20 | nDCG@10 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for stage in stages:
        for version in ("before", "after"):
            scores = [row["versions"][version]["metrics"].get(stage) for row in rows]
            scores = [score for score in scores if score is not None]
            values = " | ".join(f"{mean(score[k] for score in scores):.3f}" if scores else "—" for k in KEYS)
            lines.append(f"| {stage} | {version} | {len(scores)} | {values} |")
    return lines


def latency_cell(values):
    if not values:
        return "—"
    p95 = quantiles(values, n=100, method="inclusive")[94] if len(values) > 1 else values[0]
    return f"{median(values):.2f} / {p95:.2f}"


def latency_table(rows, sample, first_id):
    yield "| Version and sample | Retrieval p50 / p95 ms | Reranking p50 / p95 ms | Pipeline p50 / p95 ms | BM25 / dense candidates median | Query tokens median | Reranked pairs / pair tokens median |"
    yield "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    for label, group in (("A–C only", [r for r in rows if r not in sample]), ("A–D", sample)):
        for version in ("before", "after"):
            contexts = [row["versions"][version] for row in group if row["id"] != first_id]
            timings = [entry for result in contexts for entry in result["timings"]]
            if not timings:
                continue
            values = [latency_cell([t[k] for t in timings if t[k] is not None])
                      for k in ("retrieval_ms", "rerank_ms", "total_ms")]
            lex, dense = (median(r["candidate_counts"].get(stage, 0) for r in contexts) for stage in ("bm25", "dense"))
            tokens = median(r["query_tokens"] for r in contexts)
            pair_tokens = [n for result in contexts for n in result["reranker_input_tokens"]]
            pairs = median(len(r["reranker_input_tokens"]) for r in contexts)
            lengths = f"{pairs:g} / {median(pair_tokens):g}" if pair_tokens else "—"
            yield f"| {version} ({label}) | {' | '.join(values)} | {lex:g} / {dense:g} | {tokens:g} | {lengths} |"


def render(dataset, run, answers=None):
    rows = run["rows"]
    sample = [row for row in rows if row["id"] in run["rerank_ids"]]
    queries = {row["id"]: row for row in dataset["queries"]}
    categories = list(dict.fromkeys(row["category"] for row in rows))
    status = "Expert-reviewed" if run["expert_approved"] else "Exploratory draft"
    lines = [
        "# Real Azerbaijani insurance evidence benchmark", "",
        f"**{status}.** {len(rows)} manually authored queries, including "
        f"{sum(r['covered'] for r in rows)} provision-backed judgments and "
        f"{sum(not r['covered'] for r in rows)} coverage-gap controls.", "",
        "The original 108-query benchmark is untouched. This suite quotes actual indexed text and "
        "keeps document, passage, and parent IDs. The evaluation used the entire frozen corpus. "
        "Labels were assigned before retrieving candidates. They are not necessarily exhaustive before expert review.",
        "",
        "Before uses the archived one-vector-per-parent index and former follow-up behavior. After uses "
        "the archived tokenizer-split index and shared resolver. Dense search is exact on two isolated "
        "copies. Live Qdrant was only read for export. No vectors were merged across versions or written "
        "to application collections. This does not benchmark network or ANN latency or a fingerprint migration.",
        "",
        "A, B, C, and D mean BM25, dense, RRF, and RRF plus reranking. Exact-article shortcuts are bypassed. "
        "Null ranks mean outside the measured top 50. Coverage gaps are excluded from relevance denominators.",
        "",
        "## All queries, stages A–C", "", *score_table(rows, STAGES[:3]),
        "", f"## Paired reranking sample, stages A–D ({len(sample)} queries)", "", *score_table(sample, STAGES),
        "", "Stage D uses the same declared sample on both sides. A full stage D pass remains pending.",
        "", "## Category-level results", "",
    ]
    for category in categories:
        group = [row for row in rows if row["category"] == category]
        lines.extend([f"### {category.replace('_', ' ').capitalize()}", "", *score_table(group, STAGES), ""])
    lines.extend([
        "## Performance", "",
        f"Both sides used {run['threads']} Torch threads, {run['repeats']} repeated runs per case and "
        f"an {run['rerank_depth']}-candidate rerank shortlist. Pair order alternated by query. Token counts "
        "include special tokens. Pipeline timing ends after evidence packing and excludes generation. "
        "Cold observations share a process. Warm summaries exclude the first query on each side.", "",
        *latency_table(rows, sample, rows[0]["id"]),
    ])
    cold = run["cold"]
    lines.extend([
        "", f"Process initialization included {cold['embedding_load_ms']:.0f} ms for embedding, "
        f"{cold['reranker_load_ms']:.0f} ms for reranker setup, and {cold['index_load_ms']:.0f} ms for both "
        "archives. The JSON records individual first-query timings. The exploratory run does not establish a speed improvement.",
        "", "## Failure diagnosis", "",
        "Counts and examples identify observed symptoms to review. Low rank alone cannot distinguish query normalization, "
        "extraction, chunking, or missing labels. The review schema permits all requested failure categories and requires evidence.", "",
    ])
    for version in ("before", "after"):
        counts = Counter(row["versions"][version]["failure"] for row in rows if row["versions"][version]["failure"])
        lines.append(f"- **{version.title()}** " + ", ".join(f"{key.replace('_', ' ')} ({value})" for key, value in counts.items()))
    lines.extend(["", "| ID | Query | After diagnosis | Observation |", "| --- | --- | --- | --- |"])
    failures = [row for row in rows if row["covered"] and row["versions"]["after"]["failure"]]
    for category in categories:
        for row in [r for r in failures if r["category"] == category][:2]:
            version = row["versions"]["after"]
            reason = version["failure_evidence"].split(": ")[0]
            lines.append(f"| {row['id']} | {queries[row['id']]['query']} | {version['failure']} | {reason} |")
    lines.extend(["", "The [per-query results](real_insurance_draft_results.json) retain ranks for every labeled parent, "
                  "actual packed passage IDs, and archive compatibility checks.", "", "## Answer review", ""])
    if answers is not None:
        counts = Counter(row["status"] for row in answers["answers"])
        lines.append("Answer packet capture outcomes: " + ", ".join(f"{key} ({value})" for key, value in counts.items()) + ".")
        rate_limited = sum(row.get("error_type") == "TooManyRequestsResponseError" for row in answers["answers"])
        if rate_limited:
            lines.append(f"The generation provider rate-limited {rate_limited} requests. "
                         "See the [answer review packet](real_insurance_answer_review.json) for the per-query status.")
    else:
        lines.append("Answer scoring is pending.")
    lines.extend(["", "Factual correctness, evidence and citation coverage, legal qualifications, invented provisions, "
                  "and abstention require human judgment. A structural citation check does not count as approval.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "results", "output", "answers"):
        parser.add_argument(f"--{name}", type=Path, required=name != "answers")
    args = parser.parse_args()
    dataset, results = (json.loads(path.read_text(encoding="utf-8")) for path in (args.dataset, args.results))
    answers = json.loads(args.answers.read_text(encoding="utf-8")) if args.answers else None
    args.output.write_text(render(dataset, results, answers), encoding="utf-8")


if __name__ == "__main__":
    main()
