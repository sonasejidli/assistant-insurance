"""Opt-in, provenance-bound annotations for already selected evidence."""

from datetime import date
from functools import lru_cache
from hashlib import sha256
from itertools import combinations
import json
import os
from pathlib import Path
import re

from App.azerbaijani import normalize_az


CATALOG = Path(__file__).with_name("config") / "source-authority-v1.json"
NORMATIVE = {"law_or_code", "government_resolution_or_regulation", "other_normative_act"}
CONTEXTUAL = {"academic_textbook", "methodological_or_explanatory", "news_or_general_information"}


def enabled():
    return os.getenv("LEGAL_SOURCE_AUTHORITY", "").casefold() in {"1", "true", "yes"}


@lru_cache(maxsize=1)
def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def passage_ref(hit):
    meta = hit.get("metadata") or {}
    return {"passage_id": meta.get("chunk_id"), "document_id": meta.get("document_id"),
            "document": hit["doc"], "article": meta.get("article"), "clause": meta.get("clause"),
            "page": meta.get("page_number"), "version_id": meta.get("version_id"),
            "source_url": meta.get("source_url")}


def text_digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def iso(value):
    return date.fromisoformat(value).isoformat() if value is not None else None


def requests_current_law(question):
    return bool(re.search(r"\b(?:hazırda|bu gün|qüvvədə olan (?:qanun|qayda|norma|redaksiya)\w*|cari redaksiya|"
                          r"currently|current law|today|сегодня|действующ\w* (?:закон|норм)\w*)\b",
                          normalize_az(question)))


def case_timeline(*, requested_reference_date=None, insured_event_date=None, contract_start=None, contract_termination=None,
                  claim_notification_date=None, claim_date=None, current_requested=False):
    dates = {"requested_reference_date": iso(requested_reference_date), "insured_event_date": iso(insured_event_date),
             "contract_start": iso(contract_start), "contract_termination": iso(contract_termination),
             "claim_notification_date": iso(claim_notification_date), "claim_date": iso(claim_date)}
    start, end, event = (dates[key] for key in ("contract_start", "contract_termination", "insured_event_date"))
    if start and end and end < start:
        status = "inconsistent_asserted_contract_dates"
    elif not (start and end and event):
        status = "unknown"
    elif event in {start, end}:
        status = "boundary_time_unknown"
    elif event < start or event > end:
        status = "outside_asserted_contract_period"
    else:
        status = "inside_asserted_contract_period"
    return {"dates": dates, "provenance": "request_assertion", "case_facts_verified": False,
            "current_law_requested": current_requested,
            "date_provenance": {key: {"origin": "request_assertion", "verified": False, "input_field": f"case_dates.{key}"}
                                for key, value in dates.items() if value is not None},
            "contract_event_relationship": status}


def dates_at(provision, reference_date):
    if provision.get("historical_text"):
        return "historical_text_effective_period_unverified"
    if reference_date is None:
        return "reference_date_unspecified"
    start, end = provision.get("effective_date"), provision.get("repeal_effective_date")
    window = provision.get("rule_period")
    if window:
        lower, upper = window
        if reference_date in {lower, upper}:
            return "transition_boundary_requires_review"
        return "inside_documented_rule_period" if lower < reference_date < upper else "outside_documented_rule_period"
    if (start and reference_date < start) or (end and reference_date > end):
        return "outside_documented_effective_period"
    if start and end and start < reference_date < end:
        return "inside_documented_effective_period"
    return "effective_period_unknown"


def compare_periods(first, second):
    rule_windows = [entry.get("rule_period") for entry in (first, second)]
    effective_periods = [
        (entry.get("effective_date"), entry.get("repeal_effective_date")) for entry in (first, second)
    ]

    effective, invalid = interval_relationship(effective_periods)
    if invalid or effective == "no_temporal_overlap" or not all(rule_windows):
        return effective, "effective_period", invalid
    rule, invalid = interval_relationship(rule_windows)
    if effective == "boundary_time_unknown" and rule == "potential_temporal_overlap":
        return effective, "effective_period", []
    return rule, "rule_period", invalid


def interval_relationship(periods):
    invalid = []
    for index, (start, end) in enumerate(periods):
        try:
            if any(value is not None and date.fromisoformat(value).isoformat() != value for value in (start, end)):
                invalid.append(index)
            elif start and end and start > end:
                invalid.append(index)
        except (ValueError, TypeError):
            invalid.append(index)
    if invalid:
        return "unknown", invalid
    if not all(start and end for start, end in periods):
        return "unknown", []
    a, b = periods
    if a[1] < b[0] or b[1] < a[0]:
        return "no_temporal_overlap", []
    if a[1] == b[0] or b[1] == a[0] or a[0] == a[1] or b[0] == b[1]:
        return "boundary_time_unknown", []
    return "potential_temporal_overlap", []


def missing_conflict_information(provisions, timeline, basis):
    missing = []
    for index, provision in enumerate(provisions):
        if basis == "effective_period":
            for field in ("effective_date", "repeal_effective_date"):
                if provision.get(field) is None:
                    missing.append({"field": field, "reference_index": index,
                                    "reason": "No verified date for this provision in the evidence catalog."})
        for field in ("insurance_type", "person_group"):
            if not provision.get(field):
                missing.append({"field": field, "reference_index": index,
                                "reason": "The catalog does not establish this provision's scope."})
    dates = timeline["dates"]
    if any(dates.get(key) for key in ("insured_event_date", "contract_start", "contract_termination",
                                     "claim_notification_date", "claim_date")):
        for field in ("insured_event_date", "contract_start", "contract_termination"):
            if not dates.get(field):
                missing.append({"field": field, "reference_index": None,
                                "reason": "The request supplied case facts but omitted this date."})
    return missing


def conflict_records(records, timeline):
    reference_date = timeline["dates"]["requested_reference_date"]
    findings = []
    for a, b in combinations(records, 2):
        first, second = a["provision"], b["provision"]
        if (not first.get("issue") or first["issue"] != second.get("issue")
                or not first.get("rule_family") or not second.get("rule_family")
                or first["rule_family"] == second["rule_family"]):
            continue
        scope = [(first.get(key), second.get(key)) for key in ("insurance_type", "person_group")]
        if any(left and right and left != right for left, right in scope):
            continue
        relationship, basis, invalid = compare_periods(first, second)
        missing = missing_conflict_information((first, second), timeline, basis)
        if relationship == "boundary_time_unknown":
            missing.append({"field": "transition_boundary", "reference_index": None,
                            "reason": "Date-only intervals do not establish the treatment of a shared boundary day."})
        conflicting = [{"field": basis, "reference_index": index, "reason": "Period bounds are invalid or reversed."}
                       for index in invalid]
        if timeline["contract_event_relationship"] == "inconsistent_asserted_contract_dates":
            conflicting.append({"field": "asserted_contract_period", "reference_index": None,
                                "reason": "Asserted contract termination precedes the asserted start."})
        status = ("historical_comparison" if first.get("historical_text") or second.get("historical_text")
                  else "documented_transition" if basis == "rule_period"
                  and relationship in {"no_temporal_overlap", "boundary_time_unknown"}
                  else "temporally_disjoint" if relationship == "no_temporal_overlap" else "potential_conflict")
        findings.append({"status": status, "references": [a["reference"], b["reference"]],
                         "provisions": [first, second], "insurance_type": first.get("insurance_type"),
                         "person_group": first.get("person_group"), "requested_reference_date": reference_date,
                         "temporal_relationship": relationship, "temporal_basis": basis,
                         "scope_relationship": "same_cataloged_scope" if all(left and right for left, right in scope) else "unknown",
                         "missing_information": missing,
                         "conflicting_information": conflicting,
                         "requires_expert_review": status in {"potential_conflict", "historical_comparison"}
                         or (status == "documented_transition" and any(
                             record["temporal_status"] == "transition_boundary_requires_review" for record in (a, b))),
                         "resolution": None})
    return findings


def annotate(hits, items, documents, timeline, catalog=None):
    catalog = catalog if catalog is not None else load_catalog()
    by_id = {}
    for doc in documents:
        meta = doc.get("metadata") or {}
        pid_index = {hit.get("metadata", {}).get("chunk_id"): hit for hit in doc["chunks"]}
        by_id[meta.get("document_id")] = (meta, pid_index)
    reference_date = timeline["dates"]["requested_reference_date"]
    records = []
    for hit, item in zip(hits, items, strict=True):
        reference = {**passage_ref(hit), "preview_url": item["source_url"]}
        doc_meta, source_hits = by_id.get(reference["document_id"], ({}, {}))
        reference["version_id"] = reference["version_id"] or doc_meta.get("version_id")
        entry = catalog["documents"].get(reference["document_id"], {})
        indexed = source_hits.get(reference["passage_id"])
        match = indexed is not None and indexed["text"] == hit["text"] and indexed["doc"] == hit["doc"]
        version_matched = reference["version_id"] in {None, entry.get("version_id")}
        def anchor_matches(anchor):
            source = source_hits.get(anchor["passage_id"])
            return source is not None and text_digest(source["text"]) == anchor["text_sha256"]
        documented = bool(match and entry.get("source_type") in NORMATIVE | CONTEXTUAL and version_matched
                          and entry.get("anchors") and all(anchor_matches(a) for a in entry["anchors"]))
        classification = entry["source_type"] if documented else "unclassified"
        provenance = {"status": ("version_bound" if reference["version_id"] else "indexed_anchors_only")
                      if documented else "unverified", "anchors": entry.get("anchors", []) if documented else [],
                      "basis": entry.get("basis") if documented else None}
        provision_entry = catalog["provisions"].get(reference["passage_id"], {})
        provision = {}
        if (documented and provision_entry.get("text_sha256") == text_digest(hit["text"])
                and all(anchor_matches(a) for a in provision_entry["anchors"])):
            provision = provision_entry
        status = dates_at(provision, reference_date)
        if status == "reference_date_unspecified" and timeline["current_law_requested"]:
            status = "current_applicability_unverified"
        records.append({"reference": reference, "source_type": classification,
                        "issuing_authority": entry.get("issuing_authority") if documented else None,
                        "publisher": entry.get("publisher") if documented else None,
                        "document_dates": entry.get("dates", {}) if documented else {},
                        "provenance": {**provenance, "official_locator": entry.get("source_url") if documented else None},
                        "provision": provision, "temporal_status": status,
                        "legal_currency_verified": False,
                        "evidence_role": "normative" if classification in NORMATIVE else "contextual",
                        "educational_excerpt": item["original_text"] if classification in CONTEXTUAL else None})
    conflicts = conflict_records(records, timeline)
    blocked = {ref["passage_id"] for conflict in conflicts if conflict["status"] == "potential_conflict"
               for ref in conflict["references"]}
    for entry in records:
        entry["eligible_normative"] = (
            entry["evidence_role"] == "normative" and entry["reference"]["passage_id"] not in blocked
            and not entry["provision"].get("historical_text")
            and ((reference_date is None and not timeline["current_law_requested"]) or entry["temporal_status"] in
                 {"inside_documented_rule_period", "inside_documented_effective_period"})
        )
    return {"schema_version": 1, "timeline": timeline, "sources": records, "conflicts": conflicts}
