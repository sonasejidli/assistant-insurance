"""Summarize sanitized application traces without retaining request payloads."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def summarize(traces):
    traces = list(traces)
    timers = defaultdict(list)
    counts = Counter()
    routes = Counter()
    tokens = Counter()
    for trace in traces:
        timers["total"].append(trace["total_ms"])
        stages = trace["stages"]
        stage_names = {row["stage"] for row in stages}
        counts["empty_retrieval"] += bool(trace.get("empty_retrieval") or "empty_retrieval" in stage_names)
        counts["insufficient_evidence"] += trace.get("outcome") == "insufficient" or "insufficient_evidence" in stage_names
        counts["successful_expansion"] += any(row.get("generated_count", 0) or row.get("hypothesis") for row in stages)
        counts["citation_failure"] += any(row["stage"] == "citation_validation" and row.get("outcome", "").startswith("invalid") for row in stages)
        provider = [row.get("error_type", "") for row in stages if row["stage"] in {
            "provider_error", "rewriter_error", "faithfulness_error", "answer_error"}]
        counts["answer_validation_error"] += "AnswerFormatError" in provider
        provider = [error for error in provider if error != "AnswerFormatError"]
        counts["rate_limit"] += any("TooManyRequests" in error or "RateLimit" in error for error in provider)
        counts["other_provider_or_generation_error"] += any("TooManyRequests" not in error and "RateLimit" not in error for error in provider)
        counts["retrieval_infrastructure_error"] += "retrieval_error" in stage_names or "reranker_error" in stage_names
        for row in stages:
            if "latency_ms" in row:
                timers[row["stage"]].append(row["latency_ms"])
            if row["stage"] == "intent":
                routes[row["intent"]] += 1
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                tokens[key] += row.get(key, 0)
    latency = {}
    for stage, times in timers.items():
        times.sort()
        latency[stage] = {"n": len(times), "p50_ms": times[(len(times)-1)//2], "p95_ms": times[int((len(times)-1)*.95)]}
    return {"requests": len(traces), "counts": dict(counts), "rates_per_request": {
        key: value / len(traces) for key, value in counts.items()}, "latency": latency,
        "routing": dict(routes), "reported_tokens": dict(tokens)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    with args.log.open(encoding="utf-8") as file:
        print(json.dumps(summarize(json.loads(line.split("rag_request ", 1)[1])
                                   for line in file if "rag_request {" in line), indent=2))
