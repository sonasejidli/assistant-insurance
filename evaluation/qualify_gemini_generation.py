"""Run two source-derived fixtures through live Gemini generation and the existing release path."""

import json

from pydantic import ValidationError

from App import gemini_generation, legal_answers
from evaluation.verified_release_benchmark import execute, inputs


CASE_IDS = ("E2E-B01", "E2E-B02")


def summary(attempt):
    valid_json = False
    markers_bound = None
    if attempt.get("output"):
        try:
            draft = legal_answers.Draft.model_validate_json(attempt["output"])
        except ValidationError:
            pass
        else:
            valid_json = True
            packed = {source["id"] for source in attempt["sources"] or []}
            markers = {marker for claim in draft.claims for marker in claim.source_ids}
            markers_bound = markers <= packed if markers else None
    return {**{key: attempt.get(key) for key in ("status", "finish_reason", "latency_ms", "usage",
                                                   "transport_retries")},
            "valid_json": valid_json, "citation_markers_in_context": markers_bound}


def main():
    if not gemini_generation.enabled():
        raise SystemExit("Set LLM_GENERATION_PROVIDER=gemini for the qualification run.")
    if not gemini_generation.api_key():
        raise SystemExit("Qualification blocked: configure a Gemini Developer API key in GEMINI_API_KEY.")
    if not legal_answers.API_KEY or not legal_answers.LLM_MODEL:
        raise SystemExit("Qualification blocked: the existing OpenRouter judge is not configured.")

    dataset, corpus, *_ = inputs()
    cases = {case["id"]: case for case in dataset["cases"]}
    results = []
    for case_id in CASE_IDS:
        # execute enables the real release gate. Retrieval uses frozen fixture rankings.
        row = execute({"id": case_id}, cases[case_id], corpus, True, provider=legal_answers.invoke)
        attempts = [summary(attempt) for attempt in row["generation_attempts"] if attempt["provider"] == "gemini"]
        response = row["response"]
        audit = row["verified_release"]
        verification = audit.get("verifier") or {}
        results.append({"case": case_id, "attempts": attempts,
                        "rate_limited": response.get("delivery_status") == "provider_rate_limit",
                        "delivery_status": response.get("delivery_status"),
                        "failed_stage": (row.get("answer_failure") or {}).get("stage"),
                        "generated_mode": audit["generated_mode"], "verified_mode": verification.get("verified_mode"),
                        "verifier_reason": verification.get("reason"), "released_mode": response.get("answer_mode"),
                        "released_citations": len(response["sources"])})
    all_attempts = [attempt for result in results for attempt in result["attempts"]]
    print(json.dumps({
        "model": gemini_generation.GEMINI_MODEL, "judge_model": legal_answers.LLM_MODEL,
        "cases": results, "generation_attempts": len(all_attempts),
        "completed_case_count": sum(any(attempt["finish_reason"] == "STOP" and attempt["valid_json"]
                                        for attempt in result["attempts"]) for result in results),
        "valid_json_attempts": sum(attempt["valid_json"] for attempt in all_attempts),
        "rate_limited_cases": sum(result["rate_limited"] for result in results),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
