"""Evaluate the existing offline gate against an independent, frozen fixture rubric."""

import argparse
import json
from pathlib import Path
from xml.etree.ElementTree import Element, tostring

from evaluation.gold_framework import HERE, digest, read
from evaluation.verify_legal_scope import answer_hash, verify_case


CORPUS = HERE / "legal_verifier_benchmark_v1.json"
AUTHORITY_TYPES = {
    "normative_legal_act", "government_resolution", "academic_textbook",
    "methodological_or_explanatory", "other",
}


def classify(document_id, catalog):
    entry = catalog.get(document_id)
    if entry is None:
        return {"class": "other", "status": "unclassified"}
    if entry["class"] not in AUTHORITY_TYPES:
        raise ValueError("Unknown source class")
    return {"class": entry["class"], "status": "documented", "basis": entry["basis"]}


def check_corpus(corpus, snapshot=None):
    sources = corpus["sources"]
    if corpus["schema_version"] != 1 or corpus["expert_validated"] is not False:
        raise ValueError("Expected the isolated technical benchmark")
    if digest(sources) != corpus["source_excerpt_sha256"]:
        raise ValueError("Exact passage fixture checksum mismatch")
    for document_id, entry in corpus["authority"].items():
        classify(document_id, corpus["authority"])
        if any(sources[key]["document_id"] != document_id for key in entry["anchors"]) or not entry["anchors"]:
            raise ValueError("Invalid classification anchors")
    if snapshot is not None:
        ordered = [(item["metadata"]["chunk_id"], item["text"]) for doc in snapshot for item in doc["chunks"]]
        if digest(ordered) != corpus["snapshot_sha256"]:
            raise ValueError("Benchmark requires the frozen indexed corpus")
        index = {item["metadata"]["chunk_id"]: (doc["doc"], item) for doc in snapshot for item in doc["chunks"]}
        for source in sources.values():
            name, chunk = index[source["passage_id"]]
            meta = chunk["metadata"]
            if (name != source["document_name"] or chunk["text"] != source["text"] or
                    any(meta.get(key) != source[key] for key in ("document_id", "article", "clause")) or
                    meta["page_number"] != source["page"]):
                raise ValueError("Fixture differs from indexed source")


def run_case(fixture, sources, authority, *, verifier=verify_case):
    refs = [sources[key] for key in fixture["sources"]]
    registry = {ref["passage_id"]: ref for ref in refs}
    bindings, packed, nodes = {}, [], []
    for i, ref in enumerate(refs, 1):
        marker = f"S{i}"
        bindings[marker] = {**ref, "page_number": ref["page"]}
        packed.append({"id": marker, "passage_id": ref["passage_id"]})
        attrs = {"id": marker, "document": ref["document_name"], "chunk_id": ref["passage_id"],
                 "document_id": ref["document_id"]}
        for field in ("article", "clause", "page", "version_id"):
            if ref[field] is not None:
                attrs[field] = str(ref[field])
        if i == 1:
            attrs.update(fixture.get("binding_mutation", {}))
        node = Element("source", attrs)
        node.text = ref["text"]
        nodes.append(tostring(node, encoding="unicode"))
    output = fixture["claim"] + " " + " ".join(f"[{marker}]" for marker in bindings)
    ids = list(registry)
    assessment = {
        "part": "Q1", "assessed_passage_ids": ids, "support": fixture["supplied_support"],
        "applicable_documents": fixture.get("allowed_documents", sorted({ref["document_name"] for ref in refs})),
        "insurance_type": fixture.get("insurance_type", "fixture"), "group": fixture.get("group", "fixture"),
        "temporal": fixture.get("temporal_context", {}), "rationale": "Supplied fixture assessment",
        "required_conditions": fixture.get("required_conditions", {}),
        "prohibited_patterns": fixture.get("prohibited_patterns", {}),
    }
    part = {"expected_mode": "FULL", "required_passage_ids": ids, "unresolved": []}
    review = {"answer_sha256": answer_hash(output), "claims": [assessment],
              "complete_parts": [] if fixture.get("incomplete") else ["Q1"],
              "conflicting_evidence_parts": ["Q1"] if fixture.get("supplied_conflict") else [],
              "no_answer_parts": ["Q1"] if fixture.get("supplied_absence") else []}
    case = {"id": fixture["id"], "domain_scope": "in_corpus", "parts": {"Q1": part}}
    row = {"decision_reason": "accepted_answer", "mode": "FULL", "ranked_passage_ids": ids,
           "source_bindings": bindings, "generation_attempts": [
               {"output": output, "sources": packed, "evidence_context": "".join(nodes)}
           ]}
    result = verifier(case, row, registry, None if fixture.get("omit_review") else review)
    claim = result["claims"][0] if result["claims"] else {}
    scope = claim.get("legal_scope", {})
    actual = {"accepted_full": result["verified_mode"] == "FULL", "mode": result["verified_mode"],
              "binding": claim.get("citation_validity", {}).get("valid"),
              "scope_violation": scope.get("status") in {"wrong_insurance_type", "contradictory", "missing_conditions"},
              "missing_condition": bool(scope.get("missing_conditions"))}
    return {"id": fixture["id"], "dimension": fixture["dimension"], "stratum": fixture["stratum"],
            "expected": fixture["expected"], "actual": actual,
            "mismatches": [key for key, expected in fixture["expected"].items() if actual[key] != expected],
            "authority": [classify(ref["document_id"], authority) for ref in refs],
            "temporal_context": fixture.get("temporal_context"), "note": fixture["note"]}


def summarize(rows):
    def rate(field, predicate, eligible):
        cohort = [row for row in rows if field in row["expected"] and eligible(row["expected"][field])]
        count = sum(predicate(row["expected"][field], row["actual"][field]) for row in cohort)
        return {"numerator": count, "denominator": len(cohort), "value": count / len(cohort) if cohort else None}

    return {
        "false_acceptance_rate": rate("accepted_full", lambda expected, actual: actual is True, lambda value: value is False),
        "false_rejection_rate": rate("accepted_full", lambda expected, actual: actual is False, lambda value: value is True),
        "scope_violation_detection": rate("scope_violation", lambda expected, actual: actual is True, lambda value: value is True),
        "missing_condition_detection": rate("missing_condition", lambda expected, actual: actual is True, lambda value: value is True),
        "citation_binding_accuracy": rate("binding", lambda expected, actual: expected == actual, lambda value: True),
        "mode_consistency": rate("mode", lambda expected, actual: expected == actual, lambda value: True),
    }


def benchmark(corpus, snapshot=None):
    check_corpus(corpus, snapshot)
    rows = [run_case(case, corpus["sources"], corpus["authority"]) for case in corpus["cases"]]
    return {"expert_validated": False, "snapshot_checked": snapshot is not None, "rows": rows,
            "metrics": {"all": summarize(rows), **{
                stratum: summarize([row for row in rows if row["stratum"] == stratum])
                for stratum in sorted({row["stratum"] for row in rows})
            }}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = benchmark(read(CORPUS), read(args.snapshot) if args.snapshot else None)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
