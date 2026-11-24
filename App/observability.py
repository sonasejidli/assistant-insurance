import json
import logging
import os
import re
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from collections.abc import Mapping
from functools import wraps
from time import perf_counter
from uuid import uuid4
from starlette.datastructures import Headers

from App.evaluation_capture import current, record
from App.settings import LEGAL_EVIDENCE, STRUCTURED_ANSWERS

log = logging.getLogger(__name__)
request_trace = ContextVar("request_trace", default=None)


@contextmanager
def startup_stage(stage, **counts):
    if os.getenv("RAG_STARTUP_DIAGNOSTICS") != "1":
        yield
        return
    started = perf_counter()
    details = {"stage": stage, **counts}

    def emit(status, **values):
        log.info("rag_startup %s", json.dumps({**details, "status": status,
                                             "timestamp": datetime.now(timezone.utc).isoformat(), **values}))

    emit("started")
    try:
        yield
    except Exception as exc:
        emit("failed", error_type=type(exc).__name__, elapsed_ms=round((perf_counter() - started) * 1000, 2))
        raise
    else:
        emit("completed", elapsed_ms=round((perf_counter() - started) * 1000, 2))


def event(stage, **fields):
    if (capture := current.get()) is not None and stage != "retrieval_results":
        capture["stages"].append({"stage": stage, **fields})
    trace = request_trace.get()
    if trace is not None and len(trace["stages"]) < 160:
        trace["stages"].append({"stage": stage, **fields})


def stage_timing(name, *, capture_only=False):
    def decorate(function):
        @wraps(function)
        def timed(*args, **kwargs):
            if capture_only and current.get() is None:
                return function(*args, **kwargs)
            start = perf_counter()
            failure = {}
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                if (capture := current.get()) is not None:
                    failure["error_type"] = type(exc).__name__
                    attempts = capture["generation_attempts"]
                    if name in {"legacy_model_call", "legal_model_call"} and attempts and attempts[-1]["status"] == "started":
                        attempts[-1].update(status="failed", **failure)
                raise
            finally:
                event(name, latency_ms=round((perf_counter() - start) * 1000, 2), **failure)
        return timed
    return decorate


def model_usage(response):
    usage = getattr(response, "usage_metadata", None) or {}
    if not isinstance(usage, Mapping):
        return {}
    counts = {key: value for key, value in usage.items()
              if key in {"input_tokens", "output_tokens", "total_tokens"} and isinstance(value, int)}
    details = usage.get("output_token_details")
    if isinstance(details, Mapping) and type(details.get("reasoning")) is int:
        counts["reasoning_tokens"] = details["reasoning"]
    return counts


def export_trace(trace):
    if not (os.getenv("LANGFUSE_TRACING_ENABLED", "").lower() in {"1", "true", "yes"}
            and os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return
    endpoint = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")
    if endpoint and not endpoint.startswith("https://"):
        log.warning("Telemetry export disabled for a non-HTTPS endpoint")
        return
    try:
        from langfuse import get_client

        client = get_client()
        root = client.start_observation(name=trace["route"], metadata={
            key: value for key, value in trace.items() if key != "stages"
        })
        try:
            for row in trace["stages"]:
                span = root.start_observation(name=row["stage"], metadata={key: value for key, value in row.items() if key != "stage"})
                span.end()
        finally:
            root.end()
    except Exception as exc:
        log.warning("Telemetry export failed (%s)", type(exc).__name__)


def tracing_config() -> dict:
    trace = request_trace.get()
    return {"metadata": {"request_id": trace["request_id"]}} if trace else {}


def client_request_id(request) -> str | None:
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict):
        value = Headers(raw=scope.get("headers", [])).get("X-Request-ID", "")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            return value
    return None


retrieval_trace = ContextVar("retrieval_trace", default=None)


def capture_retrieval(function):
    @wraps(function)
    def traced(*args, **kwargs):
        token = retrieval_trace.set({} if LEGAL_EVIDENCE or STRUCTURED_ANSWERS else None)
        trace = {"request_id": uuid4().hex, "route": function.__name__, "stages": []}
        request = kwargs.get("request", args[1] if len(args) > 1 else None)
        if client_id := client_request_id(request):
            trace["client_request_id"] = client_id
            record(client_request_id=client_id)
        trace_token = request_trace.set(trace)
        record(trace_id=trace["request_id"])
        start = perf_counter()
        try:
            result = function(*args, **kwargs)
            if current.get() is not None:
                record(answer=result.get("answer"), citation_ids=[item["id"] for item in result.get("sources", [])],
                       status="returned", response_intent=result.get("intent"), delivery_status=result.get("delivery_status"))
            trace.update(outcome=result.get("delivery_status") or result.get("evidence_status") or result.get("intent") or "returned",
                         empty_retrieval=result.get("hits") == [], answer_chars=len(result.get("answer", "")),
                         cited_sources=len(result.get("sources", [])))
            return result
        except Exception as exc:
            record(status="failed", error_type=type(exc).__name__, status_code=getattr(exc, "status_code", 500))
            trace.update(outcome="request_failure", status_code=getattr(exc, "status_code", 500))
            raise
        finally:
            trace["total_ms"] = round((perf_counter() - start) * 1000, 2)
            record(latency_ms=trace["total_ms"])
            if os.getenv("RAG_METRICS_LOG_ENABLED", "").lower() in {"1", "true", "yes"}:
                log.info("rag_request %s", json.dumps(trace, ensure_ascii=False))
            if current.get() is None:
                export_trace(trace)
            request_trace.reset(trace_token)
            retrieval_trace.reset(token)
    return traced

