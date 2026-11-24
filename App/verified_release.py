"""Opt-in final response boundary around the unchanged hardened verifier."""

from contextlib import nullcontext
from functools import lru_cache, wraps
import json
import logging
import os
from pathlib import Path
from time import perf_counter
from xml.etree import ElementTree

from App.evaluation_capture import current, recording

log = logging.getLogger(__name__)


def enabled():
    return os.getenv("LEGAL_VERIFIED_RELEASE", "").casefold() in {"1", "true", "yes"}


@lru_cache(maxsize=1)
def configuration():
    root = Path(__file__).resolve().parents[1]
    return tuple(json.loads((root / path).read_text(encoding="utf-8")) for path in (
        "App/config/verified-release-v1.json", "evaluation/legal_verifier_hardening_policy_v2.json"
    ))


def canonical_packed(context):
    root = ElementTree.fromstring(f"<packed>{context}</packed>")
    before, after = [], []
    for node in root:
        before.append(dict(node.attrib))
        for key in ("article", "clause"):
            if key in node.attrib and not node.attrib[key].strip():
                del node.attrib[key]
        after.append(dict(node.attrib))
    return "".join(ElementTree.tostring(node, encoding="unicode") for node in root), before, after


def verifier_projection(question, capture, documents):
    from evaluation.verify_legal_scope import MARKER, answer_hash, source_registry
    from evaluation.verify_legal_scope_v2 import verify_case

    profiles, policy = configuration()
    # Only deployment configuration can establish a trusted question profile.
    scoped = profiles.get(question.question.strip(), {}) if (
        not question.history and (question.case_dates is None or not question.case_dates.model_dump(exclude_none=True))
        and (question.filters is None or not question.filters.model_dump(exclude_none=True))
        and not question.article and not question.compare_laws and question.mode == "question"
    ) else {}
    part_ids = set(capture.get("planned_parts", {})) or {"Q1"}
    reviewed = scoped.get("parts", {})
    trusted = bool(scoped) and part_ids == set(reviewed)
    parts = {key: reviewed[key] if trusted else {"required_passage_ids": [], "unresolved": ["scope_review_required"]}
             for key in sorted(part_ids | set(reviewed))}
    authority = capture.get("source_authority", {})
    conflicts = [item for item in authority.get("conflicts", []) if item["status"] == "potential_conflict"]
    if capture.get("decision_reason") == "conflicting":
        conflicts = conflicts or [{"status": "potential_conflict"}]
    profile = {"temporal_kind": scoped.get("temporal_kind") if trusted else None,
               "complete_parts": scoped.get("complete_parts", []) if trusted else [],
               "conflicting_parts": sorted(part_ids) if conflicts else []}
    attempt = None
    audit = {"before": [], "after": []}
    rendered = capture.get("release_rendered") or ""
    if rendered and capture.get("generation_attempts") and capture.get("citation_passages"):
        try:
            original = capture["generation_attempts"][-1]
            packed, audit["before"], audit["after"] = canonical_packed(original["evidence_context"])
            attempt = {**original, "output": rendered, "evidence_context": packed}
        except (ElementTree.ParseError, KeyError, TypeError):
            pass
    ids = set(capture.get("citation_passages", {}).values())
    registry = source_registry([doc for doc in documents
                                if any(hit["metadata"]["chunk_id"] in ids for hit in doc["chunks"])])
    refs = {marker: {**registry[pid], "page_number": registry[pid]["page"]}
            for marker, pid in capture.get("citation_passages", {}).items() if pid in registry}
    claims = []
    wrong_part = False
    assignments = attempt.get("claim_citations", []) if attempt else []
    for number, line in enumerate((line for line in rendered.strip().splitlines() if line and line != "PARTIAL"), 1):
        cited = list(dict.fromkeys(refs[m]["passage_id"] for m in MARKER.findall(line) if m in refs))
        claims.append({"assessed_passage_ids": cited})
        owners = [key for key, part in parts.items() if cited and set(cited) <= set(part["required_passage_ids"])]
        if len(owners) == 1:
            profile.setdefault("claim_parts", {})[str(number)] = owners[0]
        if number <= len(assignments) and (declared := assignments[number - 1].get("part")):
            wrong_part |= declared not in owners
    usable = attempt is not None and not wrong_part and capture.get("decision_reason") == "accepted_answer"
    result = verify_case({"id": scoped.get("id", "release-request"), "parts": parts},
                         {"decision_reason": "accepted_answer" if usable else "generation_unavailable",
                          "generation_attempts": [attempt] if usable else [], "source_bindings": refs},
                         registry, {"answer_sha256": answer_hash(rendered), "claims": claims,
                                    "provenance": "captured_citation_projection"}, policy=policy, profile=profile)
    audit["trusted_missing_information"] = scoped.get("missing_information", []) if trusted else []
    if wrong_part or reviewed and not trusted:
        audit["unresolved_parts"] = sorted(parts)
    return result, audit, conflicts


def disclosure(result, authority, conflicts, language, trusted_notices):
    az = language == "az"
    temporal = {item["temporal_status"] for item in authority.get("sources", [])}
    reasons = {claim["reason_code"] for claim in result["claims"]}
    rows = [{**notice, "text": notice["az"] if az else notice["en"]} for notice in trusted_notices]
    if conflicts:
        rows.append({"code": "unresolved_conflict",
                     "fields": [item for conflict in conflicts for item in conflict.get("missing_information", [])],
                     "text": "Müddəalar arasındakı mümkün ziddiyyət həll edilməyib. Hansı qaydanın tətbiq olunduğu hüquqi yoxlama tələb edir." if az else "The potential conflict is unresolved. Which rule applies requires legal review."})
    if reasons & {"temporal_evidence_missing", "temporal_evidence_invalid"} or temporal & {
        "effective_period_unknown", "current_applicability_unverified"
    }:
        rows.append({"code": "date_applicability_unverified", "text": "Hadisəyə və ya soruşduğunuz tarixə hansı müddəanın tətbiq olunduğu təsdiqlənməyib. Buna görə həmin tarix üçün ödəniş hüququ barədə nəticə müəyyən edilmir." if az else "The provision applicable to the event or requested date is unverified. Entitlement on that date cannot be established."})
    for part, data in result["parts"].items():
        if not data["complete"]:
            rows.append({"code": "part_not_established", "part": part,
                         "text": f"{part} — Bu hissə üzrə tam nəticəni təsdiqləyən uyğun dəlil çatışmır." if az else
                         f"{part} — Applicable evidence is insufficient to establish the full conclusion."})
    if not rows and result["verified_mode"] is None:
        rows.append({"code": "verified_support_unavailable",
                     "text": "Tətbiq şərtlərini təsdiqləyən kifayət qədər yoxlanmış dəlil yoxdur." if az else
                     "Verified evidence for the applicable conditions is insufficient."})
    return rows


def release(response, generated_mode, result, authority, conflicts, language, *, trusted_notices=(),
            unresolved_parts=()):
    from App.system import limited_answer

    eligible = {item["reference"]["passage_id"]: item["reference"]
                for item in authority.get("sources", []) if item["eligible_normative"]}
    retained, rejected, references = [], [], {}
    allowed = result["verified_mode"] in {"FULL", "PARTIAL"} and generated_mode in {"FULL", "PARTIAL"} and not conflicts
    for claim in result["claims"]:
        fragment = claim["supported_fragment"]
        refs = claim["evidence"]
        part = result["parts"].get(claim["part"], {})
        safe = (allowed and claim["status"] in {"supported", "partially_supported"}
                and not part.get("conflicting", False) and fragment and fragment in part.get("independently_supported_fragments", [])
                and claim["citation_valid"] and claim["witness"] and refs and all(
                    ref["valid"] and ref["source"]["passage_id"] in eligible for ref in refs
                ))
        if not safe:
            rejected.append(claim["claim_id"])
            continue
        markers = []
        for ref in refs:
            source = ref["source"]
            marker = ref["marker"]
            references[marker] = {"id": marker, "document_id": source["document_id"], "passage_id": source["passage_id"],
                                  "document": source["document_name"], "article": source["article"],
                                  "clause": source["clause"], "page": source["page"], "text": source["text"],
                                  "document_number": int(marker[1:]), "law_name": source["law_name"],
                                  "url": eligible[source["passage_id"]].get("preview_url")}
            markers.append(f"[{marker}]")
        retained.append({"id": claim["claim_id"], "part": claim["part"], "text": fragment, "markers": markers,
                         "qualified": fragment != claim["claim_text"]})
    if retained:
        mode = "FULL" if generated_mode == result["verified_mode"] == "FULL" and not rejected and not any(
            item["qualified"] for item in retained
        ) else "PARTIAL"
    else:
        mode = "NOT_FOUND" if result["verified_mode"] == "NOT_FOUND" and not conflicts else None
    display_parts = {**{part: {"complete": False} for part in unresolved_parts}, **result["parts"]}
    notices = disclosure({**result, "parts": display_parts}, authority, conflicts, language, trusted_notices) if mode != "FULL" else []
    lines = [f"{item['text']} {' '.join(item['markers'])}" for item in retained]
    answer = "\n".join(lines) if mode == "FULL" else limited_answer(language, "\n".join(lines))
    if notices:
        answer += "\n\n" + "\n".join(item["text"] for item in notices)
    final = {"answer": answer, "answer_mode": mode,
            "evidence_status": "conflicting" if conflicts else {"FULL": "sufficient", "PARTIAL": "partial"}.get(mode, "insufficient"),
            "sources": list(references.values()), "references": [
                {"document_id": ref["document_id"], "document_title": ref["law_name"],
                 "article": ref["article"], "paragraph": ref["clause"], "passage_id": ref["passage_id"],
                 "source_text": ref["text"], "source_url": ref["url"]} for ref in references.values()
            ],
            "disclaimer": response.get("disclaimer", ""), "warnings": [], "limits": [], "previews": [],
            "related_articles": [], "language": language, "source_authority": authority,
            "release_gate": {"generated_mode": generated_mode, "verified_mode": result["verified_mode"],
                             "verifier_reason": result["reason"], "missing_information": notices,
                             "removed_claim_ids": rejected, "released_claims": retained,
                             "part_coverage": {key: any(item["part"] == key for item in retained) for key in display_parts},
                             "part_completeness": {key: data["complete"] for key, data in display_parts.items()}}}
    failure = response.get("delivery_status")
    if mode is None and any(not claim["citation_valid"] for claim in result["claims"]):
        failure = failure or "verification_failed"
    if failure:
        from App.answer_recovery import answer_recovery

        final.update(answer_recovery(failure, language))
        final.pop("source_authority", None)
    return final


def abstain_on_failure(language):
    from App.answer_recovery import answer_recovery

    return {**answer_recovery("internal_error", language), "evidence_status": "insufficient",
            "release_gate": {"generated_mode": None, "verified_mode": None, "verifier_reason": "verification_unavailable",
                             "missing_information": [], "removed_claim_ids": [], "released_claims": [],
                             "part_coverage": {}, "part_completeness": {}}}


def enforce(function):
    @wraps(function)
    def wrapped(question, request):
        if not enabled():
            return function(question, request)
        from fastapi.encoders import jsonable_encoder
        from starlette.exceptions import HTTPException
        from starlette.responses import JSONResponse

        existing = current.get()
        with (nullcontext(existing) if existing is not None else recording()) as capture:
            started = perf_counter()
            response, result, audit, conflicts = {}, None, {}, []
            phase = "request"
            failure = None
            phase_started = started
            stage_ms = {}
            try:
                response = function(question, request)
                stage_ms[phase] = round((perf_counter() - phase_started) * 1000, 2)
                if capture.get("decision_reason") in {"social_response", "out_of_scope"} or (
                    capture.get("decision_reason") == "clarification" and not capture.get("release_rendered")
                    and not capture["generation_attempts"]
                ):
                    from App import retrieved_sources
                    if retrieved_sources.enabled():
                        retrieved_sources.annotate(response, capture, question.question, capture.get("release_language", "az"))
                    JSONResponse(jsonable_encoder(response))
                    return response
                phase = "verification"
                phase_started = perf_counter()
                retriever = getattr(request.app.state, "retriever", None)
                result, audit, conflicts = verifier_projection(question, capture, getattr(retriever, "documents", []))
                if not isinstance(result, dict) or result["verified_mode"] not in (None, "FULL", "PARTIAL", "NOT_FOUND"):
                    raise ValueError("Invalid verifier decision")
                stage_ms[phase] = round((perf_counter() - phase_started) * 1000, 2)
                phase = "release"
                phase_started = perf_counter()
                final = release(response, capture.get("mode"), result, capture.get("source_authority", {}), conflicts,
                                capture.get("release_language", "az"),
                                trusted_notices=audit.get("trusted_missing_information", []),
                                unresolved_parts=audit.get("unresolved_parts", []))
                stage_ms[phase] = round((perf_counter() - phase_started) * 1000, 2)
                phase = "serialization"
                phase_started = perf_counter()
                from App import retrieved_sources
                if retrieved_sources.enabled():
                    retrieved_sources.annotate(final, capture, question.question, capture.get("release_language", "az"))
                JSONResponse(jsonable_encoder(final))
                stage_ms[phase] = round((perf_counter() - phase_started) * 1000, 2)
            except Exception as exc:
                if phase == "request" and isinstance(exc, HTTPException) and 400 <= exc.status_code < 500:
                    raise
                failure = {"stage": phase, "error_type": type(exc).__name__}
                stage_ms[phase] = round((perf_counter() - phase_started) * 1000, 2)
                final = abstain_on_failure(capture.get("release_language", "az"))
            generated_mode = capture.get("mode")
            capture["verified_release"] = {"generated": response, "generated_mode": generated_mode,
                                           "generated_citations": capture.get("citation_passages", {}), "verifier": result,
                                           "citation_canonicalization": audit, "final": final, "enabled": True,
                                           "conflicts": conflicts, "language": capture.get("release_language", "az"),
                                           "stage_ms": stage_ms}
            if failure:
                capture["verified_release"]["failure"] = failure
            capture.update(answer=final["answer"], mode=final["answer_mode"], decision_reason="verified_release")
            capture["citation_passages"] = {source["id"]: source["passage_id"] for source in final["sources"]}
            if os.getenv("RAG_METRICS_LOG_ENABLED", "").casefold() in {"1", "true", "yes"}:
                gate = final["release_gate"]
                log.info("verified_release %s", json.dumps({
                    "request_id": capture.get("trace_id"), "release_version": 1,
                    "generated_mode": generated_mode, "verified_mode": gate["verified_mode"],
                    "final_mode": final["answer_mode"], "reason": gate["verifier_reason"],
                    "retained": len(gate["released_claims"]), "removed": len(gate["removed_claim_ids"]),
                    "released_citations": len(final["sources"]),
                    "candidate_count": len(capture.get("ranked_passage_ids") or []),
                    "conflicts": len(conflicts) if isinstance(conflicts, list) else 0, "stage_ms": stage_ms,
                    "failure_stage": failure["stage"] if failure else None,
                    "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                }))
            return final
    return wrapped
