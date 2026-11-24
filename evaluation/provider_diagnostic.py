"""Opt-in, non-legal structured-output probe using the configured provider SDK."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from time import perf_counter

import httpx
from langchain_openrouter import ChatOpenRouter
from openrouter import OpenRouter
from openrouter.utils import BackoffStrategy, RetryConfig
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from App.settings import API_KEY, LLM_CONTEXT_WINDOW, LLM_MAX_OUTPUT_TOKENS, LLM_MODEL


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    greeting: str = Field(min_length=1)
    note: str | None = None


IDS = ("x-request-id", "x-openrouter-request-id", "x-generation-id")
COUNTERS = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
            "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
            "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens")
FINISH = {"stop", "length", "max_tokens", "max_output_tokens", "content_filter", "tool_calls", "error"}
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
LIMIT_SOURCES = {"openrouter_free_tier_per_minute", "upstream_provider_shared_pool",
                 "openrouter_in_flight_budget", "openrouter_key_limit", "openrouter_credits"}


def safe_metadata(response):
    headers = {}
    for name in IDS + COUNTERS:
        value = response.headers.get(name)
        pattern = r"[A-Za-z0-9_.:-]{1,100}" if name in IDS else r"[0-9]{1,16}(?:\.[0-9]{1,6})?"
        if (value and (not API_KEY or API_KEY not in value)
                and not value.startswith(("sk-", "or-v1-")) and re.fullmatch(pattern, value)):
            headers[name] = value
        elif name == "retry-after" and value:
            from App.evaluation_capture import retry_after_seconds
            seconds = retry_after_seconds(value)
            if seconds is not None:
                headers["retry-after-seconds"] = seconds
    url = response.request.url
    row = {"http_status": response.status_code, "headers": headers,
           "endpoint": ENDPOINT if (url.scheme, url.host, url.path) ==
           ("https", "openrouter.ai", "/api/v1/chat/completions") else None}
    try:
        data = response.read()
        body = json.loads(data)
    except (ValueError, httpx.HTTPError):
        return row
    if not isinstance(body, dict):
        return row
    generation_id = body.get("id")
    if (isinstance(generation_id, str) and (not API_KEY or API_KEY not in generation_id)
            and re.fullmatch(r"gen-[A-Za-z0-9_-]{1,96}", generation_id)):
        row["generation_id"] = generation_id
    error = body.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if type(code) is int or code in ("rate_limit_exceeded", "insufficient_quota", "invalid_api_key"):
        row["provider_error_code"] = code
    metadata = error.get("metadata") if isinstance(error, dict) else None
    source = metadata.get("limit_source") if isinstance(metadata, dict) else None
    if isinstance(source, str) and source in LIMIT_SOURCES:
        row["limit_source"] = source
    choices = body.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice = choices[0]
        message = choice.get("message")
        row["finish_reason"] = choice.get("finish_reason") if choice.get("finish_reason") in FINISH else "unknown"
        row["refusal"] = bool(isinstance(message, dict) and message.get("refusal"))
    usage = body.get("usage")
    if isinstance(usage, dict):
        row["usage"] = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                        if type(usage.get(k)) is int}
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict) and type(details.get("reasoning_tokens")) is int:
            row["usage"]["reasoning_tokens"] = details["reasoning_tokens"]
    return row


def classify(row, output="", error=None):
    status = row.get("http_status")
    if status == 429:
        return "rate_limit"
    if status in (401, 403):
        return "authentication_or_access_failure"
    if status in (400, 404, 422):
        return "invalid_request_or_model"
    if error and "timeout" in type(error).__name__.lower():
        return "timeout"
    if status != 200:
        return "provider_or_transport_error"
    if error:
        return "malformed_response"
    finish = row.get("finish_reason")
    if finish in ("length", "max_tokens", "max_output_tokens"):
        return "truncated"
    if row.get("refusal") or finish == "content_filter":
        return "refusal"
    if finish != "stop":
        return "unexpected_finish"
    try:
        draft = Probe.model_validate_json(output)
    except ValidationError:
        return "malformed_response"
    return "success" if draft.greeting == "Salam, Azərbaycan!" else "unexpected_value"


def run(max_requests, tokens, timeout_ms):
    if not 1 <= max_requests <= 3:
        raise ValueError("The probe allows one to three requests")
    config = {"provider": "OpenRouter", "model": LLM_MODEL, "context_window": LLM_CONTEXT_WINDOW,
              "production_output_cap": LLM_MAX_OUTPUT_TOKENS, "probe_output_cap": tokens,
              "timeout_ms": timeout_ms, "max_requests": max_requests, "concurrency": 1, "retries": 0,
              "mechanism": "prompted JSON on chat completions"}
    if not API_KEY:
        return {**config, "status": "missing_credential", "attempts": []}
    attempts = []
    sent = 0
    for number in range(1, max_requests + 1):
        seen = {}
        started_at = datetime.now(timezone.utc).isoformat()

        def on_request(request):
            nonlocal sent
            if sent >= number or str(request.url) != ENDPOINT:
                raise RuntimeError("Diagnostic transport rejected an extra request or unexpected endpoint")
            sent += 1

        def observe(response):
            seen["http_status"] = response.status_code
            seen.update(safe_metadata(response))

        started = perf_counter()
        output, error = "", None
        try:
            with httpx.Client(event_hooks={"request": [on_request], "response": [observe]}, follow_redirects=False) as http:
                with OpenRouter(api_key=API_KEY, client=http, timeout_ms=timeout_ms,
                                retry_config=RetryConfig("none", BackoffStrategy(0, 0, 1, 0), False)) as sdk:
                    model = ChatOpenRouter(model=LLM_MODEL, api_key=API_KEY, client=sdk, temperature=0, max_tokens=tokens)
                    output = model.invoke('Return only the JSON object {"greeting":"Salam, Azərbaycan!"}. '
                                          'An optional "note" may be null.').text
        except Exception as exc:
            error = exc
        outcome = classify(seen, output, error)
        attempts.append({"endpoint": ENDPOINT, "model": LLM_MODEL, "stage": "isolated_structured_output",
                         "request_number": number, "retry_attempt": 0, "started_at": started_at,
                         **seen, "outcome": outcome, "error_type": type(error).__name__ if error else None,
                         "latency_ms": round((perf_counter() - started) * 1000, 2), "output_chars": len(output)})
        if outcome != "success":
            break
    return {**config, "status": attempts[-1]["outcome"], "transport_requests": sent, "attempts": attempts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-provider-calls", action="store_true", required=True)
    parser.add_argument("--max-requests", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--tokens", type=int, choices=(64, 128, 256), default=128)
    parser.add_argument("--timeout-ms", type=int, default=12000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1000 <= args.timeout_ms <= 20000:
        parser.error("Timeout must be 1000–20000 ms")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(run(args.max_requests, args.tokens, args.timeout_ms), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
