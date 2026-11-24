"""Replay the immutable v1 benchmark and v2 extension against both verifiers."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from evaluation.benchmark_legal_verifier import CORPUS, check_corpus, run_case, summarize
from evaluation.gold_framework import HERE, digest, read
from evaluation.verify_legal_scope import verify_case as verify_v1
from evaluation.verify_legal_scope_v2 import verify_case as verify_v2


POLICY = HERE / "legal_verifier_hardening_policy_v2.json"
EXTENSION = HERE / "legal_verifier_adversarial_v2.json"
SCOPE_REASONS = {
    "wrong_insurance_type", "beneficiary_scope_violated", "event_outside_contract_period",
    "incorrect_payment_deadline", "termination_conflated_with_invalidity", "historical_source_used_as_current",
    "wrong_source_for_rule", "non_normative_or_mixed_authority", "requested_date_before_effectiveness",
    "temporal_evidence_conflicting", "temporal_evidence_missing", "contract_boundary_time_unverified",
}
MISSING_REASONS = {"beneficiary_scope_violated", "event_outside_contract_period",
                   "temporal_evidence_missing", "contract_boundary_time_unverified"}
INCOMPLETE_WITNESSES = {"land_bounded_fragment", "general_deadline_bounded_fragment"}


def trusted_fixture_profile(fixture, sources):
    context = fixture.get("temporal_context", {})
    profile = {
        "temporal_kind": "general_rule",
        "claim_kind": "source_description" if fixture["sources"] == ["explanatory"] else "legal",
        "complete_parts": ["Q1"] if not fixture.get("incomplete") else [],
        "allowed_document_ids": [source["document_id"] for source in sources.values()
                                 if source["document_name"] in fixture.get("allowed_documents", [])],
        "verified_absence_parts": ["Q1"] if fixture["id"] == "M12" else [],
        "conflicting_parts": ["Q1"] if fixture["id"] == "M13" else [],
    }
    if "contract_start" in context or "contract_termination" in context:
        profile["temporal_kind"] = "event"
    elif "requested_reference_date" in context and context.get("provision_effective_date"):
        profile["temporal_kind"] = "historical_effectiveness"
    elif "requested_reference_date" in context:
        profile["temporal_kind"] = "current_applicability"
    profile["date_evidence"] = {
        key: [{"evidence_id": f"fixture:{fixture['id']}:{key}:{index}", "value": v}
              for index, v in enumerate(value if isinstance(value, list) else [value], 1)]
        for key, value in context.items()
        if key in {"contract_start", "contract_termination", "insured_event_date", "requested_reference_date"}
        and value is not None
    }
    if profile.get("temporal_kind") == "historical_effectiveness":
        anchored = sources["amendment"]
        if "2020-ci il yanvarın 1-dən qüvvəyə minir" not in anchored["text"]:
            raise ValueError("Amendment effective-date anchor changed")
        profile["date_evidence"]["effective_from"] = [{"value": "2020-01-01", "evidence_id": anchored["passage_id"]}]
    return profile


def compare_case(fixture, corpus, policy):
    sources = corpus["sources"]
    evidence = {}
    def run_with(case, row, registry, review, *, hardened):
        review = deepcopy(review)
        if review:
            review["provenance"] = "synthetic_untrusted_model_assessment"
            if "assessment_reference_override" in fixture:
                if fixture["assessment_reference_override"] is None:
                    review["claims"][0].pop("assessed_passage_ids", None)
                else:
                    review["claims"][0]["assessed_passage_ids"] = fixture["assessment_reference_override"]
        if not hardened:
            try:
                result = verify_v1(case, row, registry, review)
            except KeyError as exc:
                if exc.args != ("assessed_passage_ids",):
                    raise
                result = {"claims": [], "verified_mode": None, "error": "missing_assessment_references"}
            evidence["old"] = result
            return result
        result = verify_v2(case, row, registry, review, policy=policy,
                           profile=trusted_fixture_profile(fixture, sources))
        evidence["new"] = result
        adapted = []
        for claim in result["claims"]:
            missing = claim["reason"] in MISSING_REASONS or claim["witness"] in INCOMPLETE_WITNESSES
            scope = claim["reason"] in SCOPE_REASONS or missing
            adapted.append({"citation_validity": {"valid": claim["citation_valid"]},
                            "legal_scope": {"status": "missing_conditions" if scope else "within_scope",
                                            "missing_conditions": [claim["reason"]] if missing else []}})
        return {"verified_mode": result["verified_mode"], "claims": adapted}
    old = run_case(fixture, sources, corpus["authority"], verifier=lambda *args: run_with(*args, hardened=False))
    new = run_case(fixture, sources, corpus["authority"], verifier=lambda *args: run_with(*args, hardened=True))
    return {"id": fixture["id"], "stratum": fixture["stratum"], "dimension": fixture["dimension"],
            "expected": fixture["expected"], "old": old["actual"], "new": new["actual"],
            "changed": [key for key in old["actual"] if old["actual"][key] != new["actual"][key]],
            "old_error": evidence["old"].get("error"), "hardened_decision": evidence["new"],
            "fixture_note": fixture["note"]}


def compare(corpus, policy, extension, snapshot=None):
    check_corpus(corpus, snapshot)
    if any(item["base_benchmark_sha256"] != digest(corpus) for item in (policy, extension)):
        raise ValueError("Policy and extension require the immutable v1 benchmark")
    fixtures = [*corpus["cases"], *extension["cases"]]
    if len({f["id"] for f in fixtures}) != len(fixtures):
        raise ValueError("Duplicate benchmark IDs")
    rows = [compare_case(fixture, corpus, policy) for fixture in fixtures]
    groups = {"all": rows, "original_v1": rows[:len(corpus["cases"])], **{
        name: [row for row in rows if row["stratum"] == name]
        for name in sorted({row["stratum"] for row in rows})
    }}
    metrics = {name: {version: summarize([{**row, "actual": row[version]} for row in group])
                      for version in ("old", "new")} for name, group in groups.items()}
    return {"expert_validated": False, "snapshot_checked": snapshot is not None, "metrics": metrics, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(read(CORPUS), read(POLICY), read(EXTENSION), read(args.snapshot) if args.snapshot else None)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
