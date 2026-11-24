"""Opt-in, offline gate over frozen evidence and answer-bound legal assessments."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from statistics import mean
from xml.etree import ElementTree

from App.azerbaijani import normalize_az
from evaluation.evaluate_latest_seven import validate
from evaluation.gold_framework import HERE, digest, read
from evaluation.rag_run import DRAFT


MARKER = re.compile(r"\[(S[1-9]\d*)\]")
SUPPORT = {"complete", "partial", "contradictory", "absent"}
PROPOSAL = HERE / "legal_scope_proposed_v2.json"


def answer_hash(text):
    return sha256(text.encode("utf-8")).hexdigest()


def source_registry(documents):
    registry = {}
    for document in documents:
        snapshot_version = digest([(item["metadata"]["chunk_id"], item["text"]) for item in document["chunks"]])
        for item in document["chunks"]:
            meta = item["metadata"]
            pid = meta["chunk_id"]
            if pid in registry:
                raise ValueError(f"Duplicate indexed passage {pid}")
            registry[pid] = {
                "passage_id": pid, "document_id": meta["document_id"], "document_name": document["doc"],
                "law_name": meta["law_name"], "article": meta.get("article"), "clause": meta.get("clause"),
                "page": meta["page_number"], "version_id": meta.get("version_id") or document["metadata"].get("version_id"),
                "snapshot_document_sha256": snapshot_version, "text": item["text"],
                "original_text": meta.get("original_text"),
            }
    return registry


def citation(marker, row, attempt, packed, registry):
    binding = row["source_bindings"].get(marker)
    pid = binding["passage_id"] if binding else None
    node = packed.get(marker)
    source = registry.get(pid)
    if not binding or not source or node is None:
        return {"marker": marker, "valid": False, "reason": "Marker or passage unavailable"}
    entries = [entry["passage_id"] for entry in attempt["sources"] if entry["id"] == marker]
    version = node.get("version_id")
    valid = (entries == [pid] and normalize_xml_text(node.text) in
             {normalize_xml_text(source["text"]), normalize_xml_text(source["original_text"])}
             and binding["text"] == source["text"]
             and all(binding[key] == source[key] for key in ("document_name", "law_name", "article", "clause"))
             and binding["page_number"] == source["page"] and node.get("page") == str(source["page"])
             and node.get("clause") == source["clause"] and node.get("article") == source["article"]
             and node.get("document") == source["document_name"] and node.get("chunk_id") == pid
             and (node.get("document_id") in {None, source["document_id"]})
             and (version is None or version == source["version_id"]))
    return {"marker": marker, "valid": valid,
            "version_status": ("recorded_version_matched" if version else "frozen_snapshot_only") if valid else None,
            "reason": None if valid else "Packed passage, document or version differs from snapshot",
            "source": {key: value for key, value in source.items() if key not in {"text", "original_text"}}}


def normalize_xml_text(value):
    return (value or "").replace("\r\n", "\n").replace("\r", "\n")


def scope_result(text, sources, assessment):
    normalized = normalize_az(text)
    missing = [name for name, pattern in assessment.get("required_conditions", {}).items()
               if re.search(pattern, normalized) is None]
    wrong = bool(set(source["document_name"] for source in sources) -
                 set(assessment["applicable_documents"]))
    conflicts = [name for name, pattern in assessment.get("prohibited_patterns", {}).items()
                 if re.search(pattern, normalized)]
    return {"status": "wrong_insurance_type" if wrong else "contradictory" if conflicts else
            "missing_conditions" if missing else "within_scope",
            "insurance_type": assessment["insurance_type"], "person_or_group": assessment["group"],
            "conditions_and_exceptions": list(assessment.get("required_conditions", {})),
            "missing_conditions": missing, "conflicting_rules": conflicts,
            "temporal_applicability": assessment["temporal"]}


def verify_case(case, row, registry, review, *, additional=None):
    # A transport/format recovery carries no legal answer decision.
    if row["decision_reason"] != "accepted_answer":
        return {"id": case["id"], "observed_mode": row.get("mode"), "verified_mode": None,
                "availability": "generation_unavailable", "claims": [], "parts": {}}
    attempt = row["generation_attempts"][-1]
    output = attempt["output"]
    if review is None or review["answer_sha256"] != answer_hash(output):
        return {"id": case["id"], "observed_mode": row["mode"], "verified_mode": None,
                "availability": "answer_bound_assessment_missing", "claims": [], "parts": {}}
    nodes = list(ElementTree.fromstring("<packed>" + attempt["evidence_context"] + "</packed>"))
    packed = {node.attrib["id"]: node for node in nodes}
    if len(packed) != len(nodes):
        raise ValueError("Duplicate packed citation IDs")
    lines = [line for line in output.strip().splitlines() if line and line != "PARTIAL"]
    claims = []
    for index, (line, assessment) in enumerate(zip(lines, review["claims"], strict=True), 1):
        refs = [citation(marker, row, attempt, packed, registry) for marker in dict.fromkeys(MARKER.findall(line))]
        valid = bool(refs) and all(ref["valid"] for ref in refs)
        sources = [ref["source"] for ref in refs if ref["valid"]]
        assessed = valid and {source["passage_id"] for source in sources} == set(assessment["assessed_passage_ids"])
        if assessment["support"] not in SUPPORT or assessment["part"] not in case["parts"]:
            raise ValueError("Invalid claim assessment")
        scope = scope_result(line, sources, assessment)
        if not assessed:
            scope["status"] = "unverified"
        claims.append({"claim_id": f"{case['id']}-C{index}", "part": assessment["part"],
                       "claim_text": MARKER.sub("", line.removeprefix("- ")).strip(), "output_line": line,
                       "supporting_passage_ids": [source["passage_id"] for source in sources],
                       "citation_validity": {"valid": valid, "references": refs},
                       "claim_support": assessment["support"] if assessed else "unverified",
                       "material_to_resolution": assessment.get("material_to_resolution", True),
                       "legal_scope": scope, "rationale": assessment["rationale"]})
    parts = {}
    selected = set(row["ranked_passage_ids"])
    available = selected | {item["passage_id"] for item in attempt["sources"]}
    for part_id, part in case["parts"].items():
        required = set(part["required_passage_ids"]) | set((additional or {}).get(part_id, []))
        evidence = required & available
        assigned = [claim for claim in claims if claim["part"] == part_id]
        safe = [claim["claim_id"] for claim in assigned if claim["material_to_resolution"] and claim["claim_support"] == "complete"
                and claim["legal_scope"]["status"] == "within_scope"]
        complete = (case["domain_scope"] != "out_of_domain" and part["expected_mode"] == "FULL" and bool(safe)
                    and part_id not in review.get("conflicting_evidence_parts", [])
                    and all(claim["claim_support"] == "complete" and claim["legal_scope"]["status"] == "within_scope"
                            for claim in assigned)
                    and required <= {pid for claim in assigned for pid in claim["supporting_passage_ids"]}
                    and part_id in review.get("complete_parts", []))
        if case["domain_scope"] == "out_of_domain":
            availability = "outside_indexed_legal_scope"
        elif part_id in review.get("conflicting_evidence_parts", []):
            availability = "contradictory_evidence"
        elif required - registry.keys():
            availability = "not_indexed"
        elif required - available and not complete:
            availability = "not_retrieved"
        else:
            availability = "supported" if complete else "retrieved_but_insufficient" if evidence or assigned else "unresolved_corpus_coverage"
        fragments = [claim["claim_id"] for claim in assigned if claim["material_to_resolution"]
                     and claim["claim_support"] in {"complete", "partial"}
                     and claim["legal_scope"]["status"] in {"within_scope", "missing_conditions"}]
        if availability in {"contradictory_evidence", "outside_indexed_legal_scope"}:
            safe, fragments = [], []
        parts[part_id] = {"complete": complete, "availability": availability, "safe_claim_ids": safe,
                          "claims_with_supported_content": fragments,
                          "required_not_in_final_ranking": sorted(required - selected),
                          "required_not_retrieved": sorted((required & registry.keys()) - available),
                          "required_not_indexed": sorted(required - registry.keys()),
                          "unresolved": part["unresolved"]}
    mode = None
    if all(part["complete"] for part in parts.values()):
        mode = "FULL"
    elif any(part["claims_with_supported_content"] for part in parts.values()):
        mode = "PARTIAL"
    elif all(part["availability"] in {"retrieved_but_insufficient", "not_indexed", "unresolved_corpus_coverage"}
             and part_id in review.get("no_answer_parts", [])
             for part_id, part in parts.items()):
        mode = "NOT_FOUND"
    return {"id": case["id"], "observed_mode": row["mode"], "verified_mode": mode,
            "availability": "assessed_against_frozen_snapshot",
            "requires_revision": mode != row["mode"] or any(claim["claim_support"] != "complete" or
                                     claim["legal_scope"]["status"] != "within_scope" for claim in claims),
            "claims": claims, "parts": parts}


def proposed_impact(dataset, rows, registry, proposal):
    if proposal["base_dataset_sha256"] != digest(dataset):
        raise ValueError("Proposal does not match the frozen draft")
    changes = {change["case"]: change for change in proposal["changes"]}
    per_case = []
    for case, row in zip(dataset["queries"], rows, strict=True):
        old = set(case["required_passage_ids"])
        change = changes.get(case["id"])
        new = old.copy()
        if change:
            if change["previous_required_passage_ids"] != case["required_passage_ids"]:
                raise ValueError("Previous labels do not match the frozen draft")
            for part, ids in change["additional_by_part"].items():
                if part not in case["parts"] or not set(ids) <= registry.keys() or old.intersection(ids):
                    raise ValueError("Invalid proposed evidence")
                new.update(ids)
            if {ref["passage_id"] for ref in change["new_passages"]} != new - old:
                raise ValueError("Proposed source locators do not match additional labels")
            for ref in change["new_passages"]:
                source = registry[ref["passage_id"]]
                if ref["document"] != source["document_name"] or any(
                    ref[key] != source[key] for key in ("article", "clause", "page", "text")
                ):
                    raise ValueError("Proposed source locator differs from the index")
        ranked = set(row["ranked_passage_ids"][:5])
        per_case.append({"id": case["id"], "original_recall@5": len(old & ranked) / len(old),
                         "proposed_recall@5": len(new & ranked) / len(new)})
    return {"per_case": per_case, **{metric: mean(row[metric] for row in per_case)
                                    for metric in ("original_recall@5", "proposed_recall@5")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset, documents, audit = read(DRAFT), read(args.snapshot), read(args.audit)
    validate(dataset, documents)
    rows = audit["rows"]
    proposal = read(PROPOSAL)
    annotations = read(HERE / "legal_scope_assessments_v1.json")
    if audit["run_id"] != annotations["run_id"] or any(
        (case["id"], case["query"]) != (row["id"], row["query"])
        for case, row in zip(dataset["queries"], rows, strict=True)
    ):
        raise ValueError("Audit does not match the assessment cohort")
    registry = source_registry(documents)
    additions = {item["case"]: item["additional_by_part"] for item in proposal["changes"]}
    result = {"schema_version": 1, "expert_validated": False, "run_id": audit["run_id"],
              "proposed_label_impact": proposed_impact(dataset, rows, registry, proposal),
              "rows": [verify_case(case, row, registry, annotations["cases"].get(case["id"]),
                                   additional=additions.get(case["id"]))
                       for case, row in zip(dataset["queries"], rows, strict=True)]}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
