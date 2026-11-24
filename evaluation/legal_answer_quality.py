"""Capture and replay the independent end-to-end legal answer quality suite."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from statistics import mean

from App.azerbaijani import normalize_az
from evaluation.benchmark_source_authority import ROOT as SOURCE_ROOT, check_snapshot
from evaluation.compare_legal_verifiers import POLICY
from evaluation.gold_framework import HERE, digest, read, retrieval_scores
from evaluation.rag_run import load, save
from evaluation.verify_legal_scope import MARKER, answer_hash, normalize_xml_text, source_registry
from evaluation.verify_legal_scope_v2 import verify_case


DATASET = HERE / "legal_answer_quality_v1.json"
STAGES = ["question_understanding", "context_resolution", "query_decomposition", "retrieval_recall", "ranking",
          "reranking", "evidence_assembly", "source_authority", "temporal_applicability", "conflict_handling",
          "provider_or_infrastructure", "generation", "citation_binding", "claim_support",
          "mode_calibration", "uncertainty_communication", "expert_review"]


def inputs(snapshot=None):
    dataset, corpus, policy = read(DATASET), read(SOURCE_ROOT / "sources.json"), read(POLICY)
    if (dataset["schema_version"] != 1 or dataset["expert_validated"] is not False or
            digest(corpus) != dataset["sources_sha256"] or digest(policy) != dataset["policy_sha256"]):
        raise ValueError("Dataset provenance or policy lock mismatch")
    check_snapshot(corpus, snapshot)
    aliases = corpus["passages"]
    registry = source_registry(corpus["documents"])
    if len({case["id"] for case in dataset["cases"]}) != len(dataset["cases"]):
        raise ValueError("Duplicate fixture ID")
    for case in dataset["cases"]:
        if any(aliases[item["source"]] not in registry for item in case["required"]):
            raise ValueError("Unknown required passage")
        for claim in case["scripted_claims"]:
            for atom in claim.get("atoms", []):
                if atom["text"] not in claim["text"] or not set(atom["sources"]) <= set(claim["sources"]):
                    raise ValueError("Atomic fixture claim is not an exact bounded span")
    return dataset, corpus, policy, registry


def verified_response(case, row, aliases, policy, registry):
    if row.get("decision_reason") != "accepted_answer" or not row.get("generation_attempts"):
        return {"verified_mode": None, "reason": "no_accepted_claim_for_verification", "claims": []}
    rendered = row["rendered"]
    attempt = {**row["generation_attempts"][-1], "output": rendered}
    lines = [line for line in rendered.strip().splitlines() if line and line != "PARTIAL"]
    refs = {item["id"]: item["passage_id"] for item in attempt["sources"]}
    review = {"provenance": "fixture_projection_of_captured_markers", "answer_sha256": answer_hash(rendered),
              "claims": [{"assessed_passage_ids": list(dict.fromkeys(refs[m] for m in MARKER.findall(line)))}
                         for line in lines]}
    bound = {}
    for marker, pid in row.get("citation_passages", {}).items():
        source = registry[pid]
        bound[marker] = {**source, "page_number": source["page"]}
    parts = {part: {"required_passage_ids": sorted({aliases[item["source"]] for item in case["required"]
                                                  if item["part"] == part}),
                    "unresolved": case["unresolved"].get(part, [])}
             for part in case["parts"]}
    profile = {"temporal_kind": case.get("verifier_temporal_kind", "general_rule"),
               "complete_parts": case.get("verified_complete_parts", []),
               "claim_parts": {str(i): claim["part"] for i, line in enumerate(lines, 1)
                               for claim in case["scripted_claims"]
                               if MARKER.sub("", line.removeprefix("- ")).strip() == claim["text"]
                               and claim.get("part")}}
    # Request assertions are never supplied as verified date evidence.
    return verify_case({"id": case["id"], "parts": parts},
                       {**row, "source_bindings": bound, "generation_attempts": [attempt]},
                       registry, review, policy=policy, profile=profile)


def score_case(case, row, aliases, policy, registry):
    checks, unavailable = [], {}
    def check(metric, condition, stage, ref, expected=None, actual=None):
        checks.append({"metric": metric, "value": float(condition), "failure_stage": stage, "trace": ref,
                       "expected": expected, "observed": actual})

    def match(metric, actual, expected, stage, ref):
        check(metric, actual == expected, stage, ref, expected, actual)

    if case.get("expected_route"):
        match("understanding.route_accuracy", row.get("route"), case["expected_route"], "question_understanding", "route")
    if "expected_context" in case:
        match("context.exact_match", row.get("resolved_context"), case["expected_context"], "context_resolution", "resolved_context")
    if "expected_part_count" in case:
        match("decomposition.part_count_accuracy", len(row.get("planned_parts", {})), case["expected_part_count"],
              "query_decomposition", "planned_parts")
    if "expected_parts" in case:
        expected = case["expected_parts"]
        actual = [normalize_az(x) for x in row.get("planned_parts", {}).values()]
        remaining = set(expected)
        for part in actual:
            term = next((term for term in expected if term in remaining and term in part), None)
            if term is not None:
                remaining.remove(term)
            check("understanding.field_precision", term is not None, "query_decomposition", "planned_parts", expected, part)
        for term in expected:
            check("understanding.field_recall", term not in remaining, "query_decomposition", "planned_parts", term, actual)
        check("understanding.field_exact_match", not remaining and len(actual) == len(expected),
              "query_decomposition", "planned_parts", expected, actual)
    unavailable["understanding.entity_and_free_text_date_extraction"] = "No exposed entity or free-text date extraction output."
    authority = row.get("source_authority", {})
    timeline = authority.get("timeline", {})
    if "expected_event_relationship" in case:
        match("temporal.relationship_accuracy", timeline.get("contract_event_relationship"), case["expected_event_relationship"],
              "temporal_applicability", "source_authority.timeline.contract_event_relationship")
        for key in ("insured_event_date", "claim_notification_date", "claim_date", "contract_start",
                    "contract_termination", "requested_reference_date"):
            match("temporal.assertion_roundtrip", timeline.get("dates", {}).get(key), case.get("dates", {}).get(key),
                  "temporal_applicability", f"source_authority.timeline.dates.{key}")
    for source in authority.get("sources", []):
        if source["source_type"] in {"academic_textbook", "news_or_general_information"}:
            check("authority.context_ineligible", not source["eligible_normative"], "source_authority",
                  "source_authority.sources", False, source["eligible_normative"])
    for alias, wanted in case.get("expected_eligibility", {}).items():
        found = next((source["eligible_normative"] for source in authority.get("sources", [])
                      if source["reference"]["passage_id"] == aliases[alias]), None)
        match("authority.normative_eligibility", found, wanted, "source_authority", "source_authority.sources")
    if "expected_eligibility" in case:
        for source in authority.get("sources", []):
            if source["provision"].get("historical_text"):
                check("retrieval.historical_text_labeled", not source["eligible_normative"], "temporal_applicability",
                      "source_authority.sources", False, source["eligible_normative"])
    if "expected_conflict_count" in case:
        match("conflict.record_accuracy", len(authority.get("conflicts", [])), case["expected_conflict_count"],
              "conflict_handling", "source_authority.conflicts")

    required = {aliases[item["source"]] for item in case["required"]}
    final = row.get("ranked_passage_ids")
    assembled = [item["passage_id"] for item in row.get("assembled_evidence", [])]
    attempts = row.get("generation_attempts", [])
    packed = {item["passage_id"] for item in (attempts[-1].get("sources") or [])} if attempts else None
    branches = row.get("branches", [])
    for stage in ("bm25", "dense", "fusion", "reranked", "final", "assembly"):
        orders = ([list(dict.fromkeys(item["passage_id"] for item in branch[stage])) for branch in branches if stage in branch]
                  if stage not in {"final", "assembly"} else ([final] if stage == "final" and final is not None else
                  [assembled] if stage == "assembly" and "assembled_evidence" in row else []))
        if not required or not orders:
            unavailable[f"retrieval.{stage}"] = "Missing labeled passages or recorded rank list."
            continue
        for order in orders:
            scores = retrieval_scores(order, {pid: 1 for pid in required})
            scores["recall@20"] = len(required.intersection(order[:20])) / len(required)
            if stage == "final" and (row.get("retrieval_limit") or 0) < 10:
                for metric in ("recall@10", "recall@20", "mrr@20", "ndcg@10"):
                    scores.pop(metric)
                unavailable["retrieval.final.depth_10_20"] = "Final selection captured at depth five."
            for name, score in scores.items():
                checks.append({"metric": f"retrieval.{stage}.{name}", "value": score,
                               "failure_stage": None, "trace": f"branches.{stage}"})
    candidate_sets = {stage: {item["passage_id"] for branch in branches for item in branch.get(stage, [])}
                      for stage in ("bm25", "dense", "fusion", "reranked")}
    evidence = []
    for item in case["required"]:
        pid = aliases[item["source"]]
        if final is None:
            outcome, stage = "retrieval_not_observed", None
        elif pid in assembled:
            outcome, stage = ("passed_to_generation", None) if packed is not None and pid in packed else (
                "assembled_not_passed", "evidence_assembly") if packed is not None else ("assembled_generation_unobserved", None)
        elif pid in final:
            outcome, stage = "selected_not_assembled", "evidence_assembly"
        elif branches and all("bm25" in branch and "dense" in branch for branch in branches) and (
            pid not in candidate_sets["bm25"] | candidate_sets["dense"]):
            outcome, stage = "absent_from_candidate_pool", "retrieval_recall"
        elif pid in candidate_sets["fusion"]:
            fell = any(pid in {x["passage_id"] for x in branch.get("fusion", [])[:5]}
                       and pid not in {x["passage_id"] for x in branch.get("reranked", [])[:5]}
                       for branch in branches if "reranked" in branch)
            outcome, stage = "below_final_selection", "reranking" if fell else "ranking"
        elif pid in candidate_sets["bm25"] | candidate_sets["dense"]:
            outcome, stage = "candidate_missing_after_fusion", "ranking"
        else:
            outcome, stage = "retrieval_gap_stage_unverified", None
        evidence.append({**item, "passage_id": pid, "outcome": outcome})
        if final is not None:
            check(f"evidence.{item['component']}_coverage", pid in assembled, stage if pid not in assembled else None,
                  "assembled_evidence", pid, outcome)
    for part in case["parts"]:
        ids = {aliases[item["source"]] for item in case["required"] if item["part"] == part}
        if ids and final is not None:
            check("evidence.complete_parts", ids <= set(assembled) and not case["unresolved"].get(part), None,
                  "assembled_evidence", sorted(ids), assembled)
    unavailable["evidence.unsupported_inclusion"] = "No exhaustive relevance/insufficiency judgments for distractors."

    provider_failed = any(stage["stage"] in {"provider_error", "answer_error", "faithfulness_error"} for stage in row["stages"])
    if provider_failed:
        check("reliability.provider_success", False, "provider_or_infrastructure", "stages", True, False)
    else:
        check("reliability.provider_success", True, None, "stages")
    mode = None if provider_failed else row.get("mode")
    if case.get("expected_mode") is not None and not provider_failed:
        match("mode.accuracy", mode, case["expected_mode"], "mode_calibration", "mode")
        for name in ("FULL", "PARTIAL", "NOT_FOUND"):
            if mode == name:
                check(f"mode.false_{name.lower()}", mode != case["expected_mode"], None, "mode")
        if case["expected_mode"] == "NOT_FOUND":
            check("mode.appropriate_abstention", mode == "NOT_FOUND", "mode_calibration", "mode")
    else:
        unavailable["mode.accuracy"] = "No defensible three-mode label or technical provider failure."

    hardened = verified_response(case, row, aliases, policy, registry)
    for claim in hardened["claims"]:
        match("citations.binding_accuracy", claim["citation_valid"], True, "citation_binding", "hardened.claims")
    for reference in row.get("response", {}).get("references", []):
        source = registry.get(reference["passage_id"])
        exact = (source is not None and source["document_id"] == reference["document_id"]
                 and source["article"] == reference["article"] and source["clause"] == reference["paragraph"]
                 and normalize_xml_text(reference["source_text"]) in
                 {normalize_xml_text(source["text"]), normalize_xml_text(source["original_text"])})
        check("citations.reference_preservation", exact, "citation_binding", "response.references",
              reference["passage_id"], reference)
    labels = {item["text"]: item for item in case["scripted_claims"]}
    claims = []
    for claim in hardened["claims"]:
        label = labels.get(claim["claim_text"])
        for index, atom in enumerate(label.get("atoms", [label]) if label else [None], 1):
            status = atom["support"] if atom is not None else "unverifiable"
            ids = {aliases[name] for name in atom["sources"]} if atom else set()
            refs = [ref for ref in claim["evidence"] if not ids or ref.get("source", {}).get("passage_id") in ids]
            claims.append({"claim_id": f"{claim['claim_id']}-A{index}", "parent_claim_id": claim["claim_id"],
                           "exact_text": atom["text"] if atom else claim["claim_text"],
                           "supporting_passage_ids": sorted(ids), "references": refs,
                           "binding_valid": bool(refs) and all(ref["valid"] for ref in refs),
                           "label_status": status, "evaluation_reason": (
                               atom.get("reason", case["category"]) if atom else "No bound fixture judgment."),
                           "category": label["category"] if label else None, "assessment": atom,
                           "required_conditions": case["required_conditions"], "required_exceptions": case["exceptions"],
                           "conditions_included": atom.get("conditions_included") if atom else None,
                           "exceptions_included": atom.get("exceptions_included") if atom else None,
                           "temporal_status": [source["temporal_status"] for source in authority.get("sources", [])
                                               if source["reference"]["passage_id"] in ids]})
            check("claims.support_rate", status == "supported", "claim_support" if status != "supported" else None,
                  "hardened.claims", "supported", status)
            check("claims.unsupported_rate", status in {"unsupported", "contradicted"}, None, "hardened.claims")
            if atom is not None:
                check("claims.scope_violation_rate", atom.get("scope_violation", False), None, "hardened.claims")
                for key in ("conditions_included", "exceptions_included"):
                    if key in atom:
                        check(f"claims.{key}", atom[key], "claim_support", "hardened.claims", True, atom[key])
    if not claims:
        unavailable["claims.support_rate"] = "No accepted atomic claims available for review."
    if mode == "FULL":
        check("mode.full_not_verified", hardened["verified_mode"] != "FULL", None, "hardened.verified_mode")
        check("mode.unsupported_full", any(claim["label_status"] in {"unsupported", "contradicted"} or
                                          bool((claim["assessment"] or {}).get("scope_violation")) for claim in claims),
              None, "hardened.claims")
    if case.get("uncertainty_pattern") and not provider_failed:
        disclosure = bool(re.search(case["uncertainty_pattern"], normalize_az(row.get("answer") or "")))
        check("uncertainty.disclosure_accuracy", disclosure, "uncertainty_communication", "answer",
              case["uncertainty_pattern"], row.get("answer"))
    if not provider_failed:
        for field, metric in (("missing_info_pattern", "missing_information_communication"),
                              ("expert_disclosure_pattern", "expert_review_disclosure_accuracy")):
            if field in case:
                answer = row.get("answer") or ""
                check(f"uncertainty.{metric}", bool(re.search(case[field], normalize_az(answer))),
                      "uncertainty_communication", "answer", case[field], answer)
    if any(claim["label_status"] in {"unsupported", "contradicted"} for claim in claims):
        check("uncertainty.unsupported_certainty", mode == "FULL", None, "mode")
    unavailable["uncertainty.clarity"] = "No independent Azerbaijani clarity ratings."
    unavailable["cost.model_cost"] = "Scripted boundaries do not provide real usage or pricing."
    failures = [item for item in checks if item["value"] < 1 and item["failure_stage"]]
    earliest = min(failures, key=lambda item: STAGES.index(item["failure_stage"])) if failures else None
    return {"id": case["id"], "partition": case["partition"], "origin": case["origin"],
            "expert_review_status": case["expert_review_status"], "checks": checks, "unavailable": unavailable,
            "evidence": evidence, "claims": claims, "hardened": hardened, "observed_mode": mode,
            "earliest_failure": earliest, "requires_expert_review": bool(case["unresolved"]),
            "trace_id": row.get("trace_id"), "latency_ms": row.get("latency_ms"),
            "attempts": len(attempts), "format_retries": max(0, len(attempts) - 1), "provider_failure": provider_failed}


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        for item in row["checks"]:
            groups[item["metric"]].append((row["id"], item))
    output = {}
    for key, items in sorted(groups.items()):
        total = sum(item["value"] for _, item in items)
        adverse = key.startswith("mode.false_") or key.endswith(("unsupported_rate", "scope_violation_rate",
                                                               "unsupported_certainty", "unsupported_full", "full_not_verified"))
        failures = [{"id": id, **item} for id, item in items
                    if (item["value"] > 0 if adverse else item["value"] < 1)]
        output[key] = {"numerator": total, "denominator": len(items), "percentage": total * 100 / len(items),
                       "failed_fixture_ids": sorted({item["id"] for item in failures}), "failures": failures}
    return output


def capture_run(destination, dataset, corpus, policy, registry):
    from evaluation.legal_answer_quality_capture import capture_case

    destination.mkdir()
    save(destination / "manifest.json", {"schema_version": 1, "dataset_sha256": digest(dataset)})
    for case in dataset["cases"]:
        row = capture_case(case, corpus["documents"], corpus["passages"])
        row["hardened"] = verified_response(case, row, corpus["passages"], policy, registry)
        save(destination / f"{case['id']}.json", row)


def replay(directory, dataset, corpus, policy, registry):
    if load(directory / "manifest.json") != {"schema_version": 1, "dataset_sha256": digest(dataset)}:
        raise ValueError("Replay dataset mismatch")
    rows = []
    for case in dataset["cases"]:
        row = load(directory / f"{case['id']}.json")
        if row["query"] != case["query"]:
            raise ValueError(f"Replay question mismatch for {case['id']}")
        result = score_case(case, row, corpus["passages"], policy, registry)
        if result["hardened"] != row["hardened"]:
            raise ValueError(f"Hardened verification changed for {case['id']}")
        rows.append(result)
    groups = {"all": rows}
    for key in ("origin", "partition", "expert_review_status"):
        for value in sorted({row[key] for row in rows}):
            groups[f"{key}:{value}"] = [row for row in rows if row[key] == value]
    latencies = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
    return {"schema_version": 1, "expert_validated": False, "source_type": "offline_scripted_boundaries",
            "metrics": {name: aggregate(group) for name, group in groups.items()}, "rows": rows,
            "operational": {"captured": len(rows), "provider_failures": sum(r["provider_failure"] for r in rows),
                            "generation_attempts": sum(r["attempts"] for r in rows),
                            "format_retries": sum(r["format_retries"] for r in rows),
                            "latency_ms": {"count": len(latencies), "mean": mean(latencies) if latencies else None}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "replay"))
    parser.add_argument("run", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--historical-report", type=Path, help="Optional previous real-run replay summary")
    args = parser.parse_args()
    data = inputs(read(args.snapshot) if args.snapshot else None)
    if args.command == "capture":
        capture_run(args.run, *data)
        return
    report = replay(args.run, *data)
    if args.historical_report:
        prior = read(args.historical_report)
        usage = [usage for row in prior["rows"] for usage in row["operational"].get("model_usage", [])]
        report["historical_run"] = {"run_id": prior["run_id"], "summary": prior["summary"],
                                    "separate_cohort": True, "token_usage": {key: {
                                        "sum": sum(item.get(key, 0) for item in usage),
                                        "recorded_calls": sum(key in item for item in usage),
                                    } for key in ("input_tokens", "output_tokens", "total_tokens")},
                                    "estimated_cost": None}
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
    else:
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
