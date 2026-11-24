"""Public search candidates, separate from claim-level verification."""

import os
from urllib.parse import urlsplit

from App.azerbaijani import ascii_key, normalize_az


def enabled():
    return os.getenv("RAG_RETRIEVED_SOURCES") == "1"


def source_cards(items, authority):
    records = {record["reference"]["passage_id"]: record for record in authority["sources"]}
    cards = {}
    for item in items:
        pid = item["passage_id"]
        record = records.get(pid)
        if not pid or not record or pid in cards:
            continue
        ref = record["reference"]
        official = record["provenance"].get("official_locator")
        if official and urlsplit(official).scheme not in {"http", "https"}:
            official = None
        cards[pid] = {
            "id": pid, "passage_id": pid, "document_id": item["document_id"],
            "document": ref["document"], "law_name": item["document_title"],
            "article": item["article"], "clause": item["subparagraph"] or item["paragraph"] or item["clause"],
            "page": ref["page"], "text": item["original_text"], "url": ref["preview_url"],
            "official_url": official, "version_id": ref["version_id"],
            "source_type": record["source_type"], "issuing_authority": record.get("issuing_authority"),
            "temporal_status": record["temporal_status"],
            "legal_currency_verified": record["legal_currency_verified"],
            "effective_date": record["provision"].get("effective_date") if record["legal_currency_verified"] else None,
        }
    return list(cards.values())


def annotate(response, capture, question, language):
    cards = capture.get("retrieved_sources", [])
    citations = response["sources"]
    delivery = response.get("delivery_status")
    gate = response.get("release_gate") or {}
    route = response.get("intent")
    provider = delivery if delivery and delivery.startswith("provider_") else None
    if capture.get("generation_blocker") == "provider_not_configured":
        provider = "provider_not_configured"
    if citations and response.get("answer_mode") in {"FULL", "PARTIAL"}:
        status, reason = "verified", None
    elif route in {"clarification", "out_of_scope", "greeting", "general_conversation", "thanks", "goodbye", "bot_info"}:
        status, reason = "not_applicable", None
    else:
        status = "withheld"
        if provider:
            reason = "provider_unavailable"
        elif delivery == "internal_error":
            reason = "internal_error"
        elif delivery == "verification_failed" or gate.get("removed_claim_ids"):
            reason = "verification_rejected"
        elif not cards:
            reason = "no_relevant_passages"
        elif all(c["temporal_status"] in {
            "current_applicability_unverified", "transition_boundary_requires_review",
            "historical_text_effective_period_unverified", "effective_period_unknown",
        } for c in cards):
            reason = "source_version_unverified"
        else:
            reason = "insufficient_evidence"
    response.update(retrieved_sources=cards, verified_citations=citations, answer_status=status,
                    provider_status=provider, withheld_reason=reason)
    if language != "az" or status != "withheld" or delivery:
        return
    messages = {
        "provider_unavailable": "Cavab xidməti hazırda əlçatan deyil.",
        "no_relevant_passages": "Bu sorğuya uyğun pasaj tapılmadı.",
        "source_version_unverified": "Tapılan normanın sorğuya aid tarixdə tətbiqi təsdiqlənməyib.",
        "insufficient_evidence": "Tapılan pasajlar hüquqi nəticəni təsdiqləmək üçün kifayət etmir.",
        "verification_rejected": "Hazırlanan hüquqi cavab yoxlamadan keçmədi.",
    }
    text = messages.get(reason, response["answer"])
    folded = ascii_key(normalize_az(question))
    if status == "withheld" and cards and "elilli" in folded and "faiz" in folded:
        text += " Məbləği göstərmək üçün tətbiq olunan ödəniş rejimi və hüquqi cədvəl təsdiqlənməlidir."
    response["answer"] = text
