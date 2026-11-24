"""Gemini Developer API transport for legal answer drafts."""

import os
from time import perf_counter
from types import SimpleNamespace

from App.answer_recovery import DeliveryFailure, provider_failure
from App.evaluation_capture import model_attempt, model_response
from App.observability import event
from App.settings import GEMINI_MODEL, LLM_GENERATION_PROVIDER


TIMEOUT_MS = 12_000


class GeminiRequestFailed(RuntimeError):
    def __init__(self, delivery_failure: DeliveryFailure):
        super().__init__(delivery_failure)
        self.delivery_failure = delivery_failure


class IncompleteGeminiDraft(ValueError):
    """Gemini did not finish a non-empty answer draft."""


def enabled() -> bool:
    return LLM_GENERATION_PROVIDER == "gemini"


def api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return "" if key.startswith("gen-lang-client-") else key


def transport_schema(value):
    """Keep the Gemini JSON schema subset. Draft validation still enforces all constraints."""
    if isinstance(value, dict):
        return {key: transport_schema(child) for key, child in value.items()
                if key not in {"default", "pattern", "minLength", "maxLength"}}
    if isinstance(value, list):
        return [transport_schema(child) for child in value]
    return value


def generate(prompt, data, *, schema, tokens):
    from google import genai
    from google.genai import types

    attempt = model_attempt(GEMINI_MODEL, "structured-legal-1", prompt, data, provider="gemini")
    key = api_key()
    started = perf_counter()
    try:
        if not key or not GEMINI_MODEL:
            raise ValueError("Gemini API key or model is missing")
        options = types.HttpOptions(timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1))
        config = types.GenerateContentConfig(system_instruction=prompt, temperature=0, candidate_count=1,
                                             max_output_tokens=tokens, response_mime_type="application/json",
                                             automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                                             response_json_schema=transport_schema(schema.model_json_schema()))
        with genai.Client(api_key=key, enterprise=False, http_options=options) as client:
            response = client.models.generate_content(model=GEMINI_MODEL, contents=data, config=config)
    except Exception as exc:
        failure = provider_failure(exc, "generation", model=GEMINI_MODEL, api_key=key, provider="gemini")
        if attempt:
            attempt.update(status="failed", error_type=type(exc).__name__,
                           latency_ms=round((perf_counter() - started) * 1000, 2), transport_retries=0)
        raise GeminiRequestFailed(failure) from None

    candidates = response.candidates or []
    finish = candidates[0].finish_reason if candidates else getattr(response.prompt_feedback, "block_reason", None)
    finish = finish.value if finish else "missing"
    usage = response.usage_metadata
    tokens_used = {name: value for name, field in (
        ("input_tokens", "prompt_token_count"), ("output_tokens", "candidates_token_count"),
        ("total_tokens", "total_token_count"), ("reasoning_tokens", "thoughts_token_count"),
    ) if type(value := getattr(usage, field, None)) is int}
    elapsed = round((perf_counter() - started) * 1000, 2)
    # Never inspect or parse partial/blocked output. The local Draft parser sees only complete text.
    output = (response.text or "").strip() if len(candidates) == 1 and finish == "STOP" else ""
    model_response(attempt, SimpleNamespace(text=output, response_metadata={
        "finish_reason": finish, "model_name": response.model_version,
    }))
    if attempt:
        attempt.update(latency_ms=elapsed, usage=tokens_used, transport_retries=0)
    event("legal_model", provider="gemini", model=GEMINI_MODEL, purpose="generation",
          prompt_version="structured-legal-1", finish_reason=finish, latency_ms=elapsed, **tokens_used)
    if not output:
        if attempt:
            attempt["validation"] = "empty_output" if finish == "STOP" else "incomplete_output"
            if finish == "MAX_TOKENS":
                attempt["output_truncated"] = True
        raise IncompleteGeminiDraft()
    return output
