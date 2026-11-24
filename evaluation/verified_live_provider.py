"""Opt-in provider smoke run with frozen public questions and a redacted report."""

import argparse
import json
from pathlib import Path
from collections import Counter

from App import legal_answers
from App.evaluation_capture import current
from evaluation.verified_adversarial import FIXTURES, execute_attack, inputs, read


def classify(attempt, outcome=None, call=None):
    call = call or {}
    error = call.get("error_type", attempt.get("error_type", ""))
    if call.get("http_status") == 429:
        return "rate_limit"
    if call.get("http_status") in {401, 403}:
        return "provider_configuration"
    if "timeout" in error.casefold():
        return "timeout"
    if error in {"ConnectError", "ReadError", "WriteError", "RemoteProtocolError"}:
        return "transport_failure"
    if error or call.get("http_status"):
        return "transport_or_provider_error"
    if attempt.get("finish_reason") in {"length", "max_tokens", "max_output_tokens"}:
        return "output_truncation"
    if not (attempt.get("output") or "").strip():
        return "empty_output"
    return {"invalid_schema": "malformed_output", "invalid_binding": "invalid_citation"}.get(outcome, "returned")


def runner(snapshot=None, *, timeout_ms=12000, positive_only=False, observer=None, max_calls=None,
           max_retries=1, base_delay=0.5, max_wait=5, token_cap=None):
    if not legal_answers.API_KEY or not legal_answers.LLM_MODEL:
        return {"mode": "live_provider", "status": "unavailable_provider_configuration", "fixture_count": 0, "rows": []}
    dataset, corpus, *_ = inputs(snapshot)
    bases = {item["id"]: item for item in dataset["cases"]}
    fixtures = {item["id"]: item for item in read(FIXTURES)["cases"]}
    rows = []
    invoke = legal_answers.invoke
    model = legal_answers.LLM_MODEL
    for fid in (("R01", "R02") if positive_only else ("R01", "R02", "R06", "R11")):
        fixture = fixtures[fid]
        attempts = []

        def live(prompt, payload, **kwargs):
            capture = current.get()
            capture.setdefault("provider_calls", [])
            if observer is not None:
                capture["qualification_capture"] = True
            capture["provider_timeout_ms"] = timeout_ms
            capture["provider_retry_policy"] = {
                "statuses": (429,) if positive_only else (), "retry_connect": False, "max_retries": max_retries,
                "base_delay_seconds": base_delay, "max_delay_seconds": max(1, base_delay), "max_wait_seconds": max_wait,
            }
            if max_calls is not None:
                capture["provider_retry_policy"]["max_calls"] = max_calls
            if token_cap is not None:
                kwargs["tokens"] = min(kwargs["tokens"], token_cap)
            stage_start = len(capture["stages"])
            try:
                return invoke(prompt, payload, **kwargs)
            finally:
                if payload.startswith("<context>\n") and capture["generation_attempts"]:
                    usage = {key: value for entry in capture["stages"][stage_start:] if entry["stage"] == "legal_model"
                             for key, value in entry.items() if key in {"input_tokens", "output_tokens", "total_tokens"}
                             and type(value) is int}
                    attempts.append((capture, capture["generation_attempts"][-1], len(capture["provider_calls"]), usage))

        result = execute_attack({"id": fid}, bases[fixture["base"]], (fid, "live", fid, "live", None),
                                corpus, live_provider=live,
                                capture_observer=(lambda row: observer(fid, row)) if observer else None)
        summaries = []
        for index, (capture, attempt, call_index, usage) in enumerate(attempts):
            call = capture["provider_calls"][call_index - 1] if call_index else {}
            validation = [entry.get("outcome") for entry in capture["stages"] if entry["stage"] == "citation_validation"]
            finish = attempt.get("finish_reason")
            summaries.append({"attempt": index + 1, "classification": classify(
                attempt, validation[index] if index < len(validation) else None, call),
                "prompt_version": "structured-legal-1", "prompt_sha256": attempt.get("prompt_sha256"),
                "finish_reason": finish if finish in {"stop", "length", "max_tokens", "max_output_tokens",
                                                       "content_filter", "tool_calls", "error"} else None,
                "http_status": call.get("http_status"), "latency_ms": call.get("latency_ms"),
                "retry_after_seconds": call.get("retry_after_seconds"), "transport_outcome": call.get("outcome"),
                "token_usage": usage, "output_chars": len(attempt.get("output") or "")})
        calls = attempts[-1][0]["provider_calls"] if attempts else []
        transport = [{key: call[key] for key in ("purpose", "outcome", "http_status", "error_type", "latency_ms",
                                                  "retry_after_seconds", "delay_seconds", "rate_limit") if key in call}
                     for call in calls]
        result.update(attempts=summaries, provider="openrouter", model=model if model != legal_answers.API_KEY else None,
                      transport_calls=transport, transport_retries=sum(c.get("transport_retry", 0) > 0 for c in calls),
                      expected=fixture["final"], estimated_cost=None)
        rows.append(result)
    times = sorted(row["latency_ms"] for row in rows)
    return {"mode": "live_provider", "status": "completed", "fixture_count": len(rows), "rows": rows,
            "p50_ms": times[(len(times) - 1) // 2], "p95_ms": times[-1],
            "provider_outcomes": dict(Counter(attempt["classification"] for row in rows for attempt in row["attempts"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-provider-calls", action="store_true", required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--positive-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as stream:
        result = runner(read(args.snapshot) if args.snapshot else None, positive_only=args.positive_only)
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
