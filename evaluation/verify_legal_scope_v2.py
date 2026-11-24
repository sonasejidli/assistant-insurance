"""Opt-in verifier using a separate, trusted technical witness catalog."""

from datetime import date
import re
from xml.etree import ElementTree

from App.azerbaijani import normalize_az
from evaluation.verify_legal_scope import MARKER, answer_hash, normalize_xml_text


VERSION = "2.0"


def canonical(text):
    return " ".join(normalize_az(text).split())


def exact_binding(marker, bindings, entries, packed, registry):
    bind = bindings.get(marker, {})
    pid = bind.get("passage_id")
    source = registry.get(pid)
    node = packed.get(marker)
    if not source or node is None:
        return {"marker": marker, "valid": False, "reason": "missing_marker_or_passage"}
    fields = {"chunk_id": pid, "document": source["document_name"], "article": source["article"],
              "clause": source["clause"], "page": source["page"]}
    packed_text = normalize_xml_text(node.text)
    variants = {normalize_xml_text(source["text"])}
    if source.get("original_text"):
        variants.add(normalize_xml_text(source["original_text"]))
    valid = (source["passage_id"] == pid and entries.get(marker) == [pid]
             and all(node.get(key) == (None if value is None else str(value)) for key, value in fields.items())
             and node.get("document_id", source["document_id"]) == source["document_id"]
             and node.get("version_id", source["version_id"]) == source["version_id"]
             and bind.get("page_number") == source["page"]
             and all(bind.get(key) == source[key] for key in ("document_name", "law_name", "article", "clause", "text"))
             and packed_text in variants)
    return {"marker": marker, "valid": valid, "reason": "exact_binding" if valid else "binding_mismatch",
            "source": {**source, "packed_text": node.text, "packed_metadata": dict(node.attrib)}}


def temporal_check(profile):
    kind = profile.get("temporal_kind")
    if kind == "general_rule":
        return "not_required_for_general_proposition"
    if kind not in {"event", "historical_effectiveness", "current_applicability"}:
        return "temporal_evidence_missing"
    required = ("contract_start", "contract_termination", "insured_event_date") if kind == "event" else (
        "requested_reference_date", "effective_from")
    values = {}
    for key in required:
        evidence = profile.get("date_evidence", {}).get(key, [])
        if not evidence or any(not item.get("evidence_id") for item in evidence):
            return "temporal_evidence_missing"
        try:
            dates = {date.fromisoformat(item["value"]) for item in evidence}
        except (TypeError, ValueError, KeyError):
            return "temporal_evidence_invalid"
        if len(dates) != 1:
            return "temporal_evidence_conflicting"
        values[key] = dates.pop()
    if kind == "event":
        start, end, event = (values[key] for key in required)
        if end < start:
            return "temporal_evidence_conflicting"
        if event < start or event > end:
            return "event_outside_contract_period"
        if event in {start, end}:
            return "contract_boundary_time_unverified"
        return "temporal_applicability_established"
    if values["requested_reference_date"] < values["effective_from"]:
        return "requested_date_before_effectiveness"
    # An effective start does not establish current applicability.
    return "temporal_observation_matches" if kind == "historical_effectiveness" else "temporal_evidence_missing"


def independent_support(text, passages, policy, profile):
    normalized = canonical(text)
    ids = set(passages)
    witnesses = [w for w in policy["witnesses"] if normalized in {canonical(v) for v in w["statements"]}
                 and ids == set(w["passages"]) and all(
                     answer_hash(passages[pid]["text"]) == spec["sha256"]
                     and passages[pid]["document_id"] == spec["document_id"]
                     and spec["excerpt"] in passages[pid]["text"]
                     for pid, spec in w["passages"].items())]
    witness = witnesses[0] if len(witnesses) == 1 else None
    authority = {policy["authority"].get(s["document_id"], "unclassified") for s in passages.values()}
    if profile.get("claim_kind", "legal") == "legal" and authority - {"normative_legal_act", "government_resolution"}:
        return "unsupported", "non_normative_or_mixed_authority", None
    if set(profile.get("allowed_document_ids", [])) and any(
        s["document_id"] not in profile["allowed_document_ids"] for s in passages.values()
    ):
        return "unsupported", "wrong_insurance_type", None
    temporal = temporal_check(profile)
    if temporal in {"event_outside_contract_period", "requested_date_before_effectiveness",
                    "temporal_evidence_conflicting"}:
        return "contradictory", temporal, None
    if temporal in {"temporal_evidence_missing", "temporal_evidence_invalid", "contract_boundary_time_unverified"}:
        return "unverified", temporal, None
    for rule in policy["negative_rules"]:
        if set(rule["passages"]) <= ids and re.search(rule["pattern"], normalized):
            return rule["status"], rule["reason"], None
    if witness is None:
        return "unverified", "no_independent_support", None
    if witness["kind"] != profile.get("claim_kind", "legal"):
        return "unverified", "claim_kind_not_established", None
    if set(profile.get("required_scope", [])) - set(witness.get("scope", [])):
        return "unverified", "required_scope_not_established", None
    if profile["temporal_kind"] == "historical_effectiveness" and any(
        item["evidence_id"] not in passages or item["value"] != witness.get("effective_from")
        for item in profile.get("date_evidence", {}).get("effective_from", [])
    ):
        return "unverified", "effective_date_not_bound_to_witness", None
    return witness["status"], witness["rationale"], witness


def verify_case(case, row, registry, assessment, *, policy, profile):
    result = {"id": case["id"], "verifier_version": VERSION, "policy_version": policy["version"],
              "verified_mode": None, "claims": [], "parts": {}, "reason": "generation_unavailable",
              "temporal_evidence": {"kind": profile.get("temporal_kind"), "facts": profile.get("date_evidence", {})}}
    if row.get("decision_reason") != "accepted_answer":
        return result
    if case.get("domain_scope") == "out_of_domain":
        return {**result, "reason": "outside_indexed_legal_scope"}
    attempt = row["generation_attempts"][-1]
    output = attempt["output"]
    lines = [line for line in output.strip().splitlines() if line.strip() and line.strip() != "PARTIAL"]
    if not assessment or assessment.get("answer_sha256") != answer_hash(output):
        return {**result, "reason": "assessment_unbound"}
    reviewed = assessment.get("claims", [])
    if not lines or len(lines) != len(reviewed):
        return {**result, "reason": "assessment_count_mismatch"}
    try:
        nodes = list(ElementTree.fromstring("<packed>" + attempt["evidence_context"] + "</packed>"))
    except ElementTree.ParseError:
        return {**result, "reason": "invalid_packed_context"}
    packed = {node.get("id"): node for node in nodes}
    if len(packed) != len(nodes):
        return {**result, "reason": "duplicate_packed_markers"}
    entries = {}
    for item in attempt["sources"]:
        entries.setdefault(item["id"], []).append(item["passage_id"])
    for i, (line, observation) in enumerate(zip(lines, reviewed, strict=True), 1):
        refs = [exact_binding(marker, row["source_bindings"], entries, packed, registry)
                for marker in dict.fromkeys(MARKER.findall(line))]
        valid = bool(refs) and all(ref["valid"] for ref in refs)
        passages = {ref["source"]["passage_id"]: ref["source"] for ref in refs if ref["valid"]}
        expected_refs = observation.get("assessed_passage_ids")
        reliable_refs = (isinstance(expected_refs, list) and all(isinstance(x, str) for x in expected_refs)
                         and len(expected_refs) == len(passages) and set(expected_refs) == set(passages))
        text = MARKER.sub("", line.removeprefix("- ")).strip()
        part = profile.get("claim_parts", {}).get(str(i))
        if part is None and len(case["parts"]) == 1:
            part = next(iter(case["parts"]))
        if not valid or not reliable_refs:
            status, reason, witness = "unverified", "citation_invalid" if not valid else "assessment_references_invalid", None
        elif part not in case["parts"]:
            status, reason, witness = "unverified", "trusted_part_attribution_missing", None
        else:
            status, reason, witness = independent_support(text, passages, policy, profile)
        result["claims"].append({"claim_id": f"{case['id']}-C{i}", "claim_text": text, "part": part,
                                 "status": status, "reason_code": "independent_witness_matched" if witness else reason,
                                 "reason": reason,
                                 "witness": witness["id"] if witness else None,
                                 "supported_fragment": witness.get("supported_fragment") if witness else None,
                                 "citation_valid": valid, "evidence": refs,
                                 "assessment": {"provenance": assessment.get("provenance", "untrusted_unspecified"),
                                                "support_label": observation.get("support"),
                                                "referenced_passage_ids": expected_refs}})
    for part, spec in case["parts"].items():
        assigned = [claim for claim in result["claims"] if claim["part"] == part]
        conflict = any(claim["status"] == "contradictory" for claim in assigned) or part in profile.get("conflicting_parts", [])
        supported_ids = {ref["source"]["passage_id"] for claim in assigned if claim["status"] == "supported"
                         for ref in claim["evidence"]}
        complete = (not conflict and bool(assigned) and all(claim["status"] == "supported" for claim in assigned)
                    and set(spec["required_passage_ids"]) <= supported_ids
                    and part in profile.get("complete_parts", []) and not spec.get("unresolved"))
        result["parts"][part] = {"complete": complete, "conflicting": conflict,
                                 "independently_supported_fragments": [
                                     claim["supported_fragment"] for claim in assigned
                                     if claim["supported_fragment"] and not conflict
                                 ]}
    if result["parts"] and all(item["complete"] for item in result["parts"].values()) and all(
        claim["status"] == "supported" for claim in result["claims"]
    ):
        result.update(verified_mode="FULL", reason="all_parts_independently_supported")
    elif any(item["independently_supported_fragments"] for item in result["parts"].values()):
        result.update(verified_mode="PARTIAL", reason="only_bounded_fragments_verified")
    elif (result["parts"] and not any(item["conflicting"] for item in result["parts"].values())
          and all(claim["citation_valid"] for claim in result["claims"])
          and all(claim["status"] == "unsupported" for claim in result["claims"])
          and set(case["parts"]) <= set(profile.get("verified_absence_parts", []))):
        result.update(verified_mode="NOT_FOUND", reason="independent_absence_review")
    else:
        result["reason"] = "no_independently_supported_fragment"
    return result
