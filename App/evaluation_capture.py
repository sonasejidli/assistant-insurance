"""Request-local recording for explicitly invoked offline evaluations."""

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from math import isfinite
from random import uniform
import re
from time import perf_counter, sleep


current = ContextVar("evaluation_capture", default=None)
resources = ContextVar("evaluation_resources", default=None)


@contextmanager
def recording(provider_timeout_ms=None, retry_policy=None):
    row = {"stages": [], "branches": [], "generation_attempts": []}
    if provider_timeout_ms is not None:
        row["provider_timeout_ms"] = provider_timeout_ms
    if retry_policy is not None:
        row["provider_retry_policy"] = retry_policy
        row["provider_calls"] = []
    with ExitStack() as stack:
        token = current.set(row)
        resource_token = resources.set({"stack": stack, "retry_count": 0, "wait_seconds": 0.0})
        try:
            yield row
        finally:
            resources.reset(resource_token)
            current.reset(token)


def passage_id(hit):
    return (hit.get("metadata") or {}).get("chunk_id")


def record(**fields):
    if (row := current.get()) is not None:
        row.update(fields)


def decision(mode, reason):
    record(mode=mode, decision_reason=reason)


def model_attempt(model, version, prompt, content, *, provider="openrouter"):
    if (row := current.get()) is None:
        return {}
    evidence, _, _ = content.partition("\n</context>")
    attempt = {
        "status": "started",
        "provider": provider, "model": model, "prompt_version": version,
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "evidence_context": evidence.removeprefix("<context>\n"),
        "sources": row.get("packed_sources"),
    }
    row["generation_attempts"].append(attempt)
    return attempt


def provider_options(api_key):
    row = current.get()
    if row is None or row.get("provider_timeout_ms") is None:
        return {}
    from openrouter import OpenRouter
    from openrouter.utils import BackoffStrategy, RetryConfig

    scope = resources.get()
    if "client" not in scope:
        scope["api_key"] = api_key
        scope["client"] = scope["stack"].enter_context(OpenRouter(
            api_key=api_key, timeout_ms=row["provider_timeout_ms"],
            retry_config=RetryConfig("none", BackoffStrategy(0, 0, 1, 0), False),
        ))
    return {"client": scope["client"]}


def retry_after_seconds(value):
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                return None
            seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if isfinite(seconds) else None


def provider_error(exc, api_key):
    response = getattr(exc, "raw_response", None)
    if response is None:
        response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    details = {"error_type": type(exc).__name__}
    if response is None and type(code := getattr(exc, "code", None)) is int and 400 <= code < 600:
        return {**details, "http_status": code}
    if type(status) is int:
        details["http_status"] = status
        for name in ("x-request-id", "x-openrouter-request-id", "x-generation-id"):
            request_id = response.headers.get(name)
            if (request_id and (not api_key or api_key not in request_id) and not request_id.startswith("sk-")
                    and re.fullmatch(r"[\w.:-]{1,100}", request_id)):
                details["provider_request_id"] = request_id
                break
        header = response.headers.get("retry-after")
        details["retry_after_seconds"] = retry_after_seconds(header)
        if status == 429:
            names = ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
                     "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests",
                     "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens")
            details["rate_limit"] = {name: int(value) for name in names if
                                     (value := response.headers.get(name)) and re.fullmatch(r"[0-9]{1,12}", value)}
        try:
            payload = response.json()
        except (ValueError, TypeError):
            return details
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            metadata = error.get("metadata")
            if isinstance(metadata, dict):
                limit_source = metadata.get("limit_source")
                if limit_source in ("upstream_provider_shared_pool", "openrouter_free_tier_per_minute",
                                    "openrouter_in_flight_budget", "openrouter_key_limit", "openrouter_credits"):
                    details["limit_source"] = limit_source
            if type(error.get("code")) in {int, str}:
                code = error["code"]
                if type(code) is int or re.fullmatch(r"[\w.-]{1,80}", code) and code != api_key:
                    details["provider_code"] = code
            if isinstance(error.get("message"), str):
                message = error["message"]
                if api_key:
                    message = message.replace(api_key, "[redacted]")
                message = re.sub(r"(?i)(?:bearer\s+\S+|sk-[\w-]{12,}|[\w.+-]+@[\w.-]+\.[a-z]{2,})",
                                 "[redacted]", message)
                details["provider_message"] = message[:1200]
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if isinstance(usage, dict):
            details["token_usage"] = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                                      if type(usage.get(key)) is int}
    return details


def invoke_provider(invoke, messages, *, config, purpose, attempt=None):
    row = current.get()
    policy = row.get("provider_retry_policy") if row is not None else None
    if policy is None:
        return invoke(messages, config=config)
    scope = resources.get()
    invocation = len(row["provider_calls"]) + 1
    generation_attempt = len(row["generation_attempts"]) if attempt else None
    retries = 0
    while True:
        if len(row["provider_calls"]) >= policy.get("max_calls", float("inf")):
            row["provider_budget_exhausted"] = True
            raise ProviderBudgetExceeded()
        call = {"purpose": purpose, "invocation": invocation, "transport_retry": retries,
                "generation_attempt": generation_attempt}
        row["provider_calls"].append(call)
        start = perf_counter()
        try:
            response = invoke(messages, config=config)
        except Exception as exc:
            error = provider_error(exc, scope.get("api_key"))
            status = error.get("http_status")
            # A read timeout can follow an accepted request. Do not resend it by default.
            retryable = status in policy["statuses"] or (
                status is None and policy["retry_connect"] and error["error_type"] in {"ConnectError", "ConnectTimeout"}
            )
            call.update(error, latency_ms=round((perf_counter() - start) * 1000, 2), retryable=retryable)
            if not retryable:
                call["outcome"] = "non_retryable"
                raise
            if len(row["provider_calls"]) >= policy.get("max_calls", float("inf")):
                row["provider_budget_exhausted"] = True
                call["outcome"] = "call_budget_exhausted"
                raise
            if scope["retry_count"] >= policy["max_retries"]:
                call["outcome"] = "retry_budget_exhausted"
                raise
            ceiling = min(policy["max_delay_seconds"], policy["base_delay_seconds"] * 2 ** scope["retry_count"])
            delay = max(error.get("retry_after_seconds") or 0.0, uniform(ceiling / 2, ceiling))
            if scope["wait_seconds"] + delay > policy["max_wait_seconds"]:
                call["outcome"] = "wait_budget_exhausted"
                raise
            call.update(outcome="retry_scheduled", delay_seconds=delay)
            scope["retry_count"] += 1
            scope["wait_seconds"] += delay
            retries += 1
            sleep(delay)
        else:
            call.update(outcome="returned", latency_ms=round((perf_counter() - start) * 1000, 2))
            return response


class ProviderBudgetExceeded(RuntimeError):
    """The opt-in evaluation exhausted its provider-call budget."""


def model_response(attempt, response):
    if attempt:
        attempt.update(status="returned", output=response.text)
        metadata = getattr(response, "response_metadata", None) or {}
        for source, target in (("model_name", "returned_model"), ("provider", "upstream_provider"),
                               ("finish_reason", "finish_reason")):
            if isinstance(metadata.get(source), str):
                attempt[target] = metadata[source]
