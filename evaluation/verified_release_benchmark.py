"""Offline comparison and exact replay of serialized release responses."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from App import source_authority, verified_release
from evaluation.gold_framework import HERE, digest, read
from evaluation.legal_answer_quality import inputs
from evaluation.rag_run import load, save

FIXTURES = HERE / "verified_release_benchmark_v1.json"


def serialize(payload):
    from fastapi.encoders import jsonable_encoder
    from starlette.responses import JSONResponse
    return json.loads(JSONResponse(jsonable_encoder(payload)).body)


def execute(fixture, base, corpus, enabled, *, transport=None, provider=None):
    from evaluation.legal_answer_quality_capture import capture_case

    case = deepcopy(base)
    if "status" in fixture:
        case["scripted_status"] = fixture["status"]
    mutation = fixture.get("mutation")
    if mutation == "exception":
        case["scripted_claims"] = [{"text": "Məcburi dövlət sosial sığorta haqqı növbəti ayın 15-dək ödənilir.",
                                   "sources": ["ordinary"]}]
    canonical = verified_release.canonical_packed
    annotate = source_authority.annotate
    def corrupt(context):
        normalized, before, _ = canonical(context)
        changed, _, after = canonical(normalized.replace('chunk_id="', 'chunk_id="synthetic-', 1))
        return changed, before, after

    def conflict(*args, **kwargs):
        result = annotate(*args, **kwargs)
        refs = [item["reference"] for item in result["sources"] if item["eligible_normative"]][:2]
        if len(refs) == 2:
            result["conflicts"] = [{"status": "potential_conflict", "references": refs, "resolution": None,
                                    "requires_expert_review": True, "missing_information": [
                                        {"field": "effective_date", "reference_index": 1, "reason": "Synthetic gap"}
                                    ]}]
        return result
    with (
        patch.dict("os.environ", {"LEGAL_VERIFIED_RELEASE": "1" if enabled else "0"}),
        patch.object(verified_release, "canonical_packed", corrupt if mutation == "corrupt" else canonical),
        patch.object(source_authority, "annotate", conflict if mutation == "conflict" else annotate),
    ):
        row = capture_case(case, corpus["documents"], corpus["passages"], transport=transport, provider=provider)
        if not enabled:
            from App.main import Question
            request = Question(question=case["query"], language="az", history=case.get("history", []),
                               case_dates=case.get("dates", {}))
            row["baseline_verifier"], _, _ = verified_release.verifier_projection(
                request, {**row, "release_rendered": row.get("rendered")}, corpus["documents"])
    if transport is None:
        row["serialized_response"] = serialize(row["response"])
    return row


def create(run, suite, dataset, corpus):
    run.mkdir()
    save(run / "manifest.json", {"suite": digest(suite), "dataset": digest(dataset)})
    by_id = {item["id"]: item for item in dataset["cases"]}
    for fixture in suite["cases"]:
        save(run / f"{fixture['id']}.json", {
            name: execute(fixture, by_id[fixture["base"]], corpus, enabled)
            for name, enabled in (("disabled", False), ("enabled", True))
        })


def evaluate(run, suite, dataset):
    if load(run / "manifest.json") != {"suite": digest(suite), "dataset": digest(dataset)}:
        raise ValueError("Release capture digest mismatch")
    rows = []
    for fixture in suite["cases"]:
        capture = load(run / f"{fixture['id']}.json")
        enabled, disabled = capture["enabled"], capture["disabled"]
        audit = enabled["verified_release"]
        final, verdict = enabled["serialized_response"], audit["verifier"]
        replay = verified_release.release(
            audit["generated"], audit["generated_mode"], verdict, enabled["source_authority"], audit["conflicts"],
            audit["language"], trusted_notices=audit["citation_canonicalization"].get("trusted_missing_information", []),
            unresolved_parts=audit["citation_canonicalization"].get("unresolved_parts", []))
        if serialize(replay) != final:
            raise ValueError(f"Serialized release replay differs for {fixture['id']}")
        gate = final["release_gate"]
        expected = {key: fixture[key] for key in ("generated", "verified", "final")}
        actual = {"generated": audit["generated_mode"], "verified": verdict["verified_mode"], "final": final["answer_mode"]}
        checks = {key: expected[key] == actual[key] for key in expected}
        if "notice" in fixture:
            checks["missing_information"] = fixture["notice"] in {item["code"] for item in gate["missing_information"]}
        if "parts" in fixture:
            checks["multipart_coverage"] = fixture["parts"] == gate["part_coverage"]
        if "binding" in fixture:
            checks["citation_probe"] = bool(verdict["claims"]) and all(
                claim["citation_valid"] == fixture["binding"] for claim in verdict["claims"])
        if "qualified" in fixture:
            checks["qualification"] = any(claim["qualified"] for claim in gate["released_claims"])
        markers = {source["id"] for source in final["sources"]}
        witnessed = {claim["claim_id"] for claim in verdict["claims"] if claim["citation_valid"] and claim["witness"]
                     and claim["status"] in {"supported", "partially_supported"}}
        if gate["released_claims"]:
            checks["citation_integrity"] = all(marker[1:-1] in markers and claim["id"] in witnessed
                                               for claim in gate["released_claims"] for marker in claim["markers"])
        rows.append({"id": fixture["id"], "scenario": fixture["scenario"], "expected": expected, "observed": actual,
                     "checks": checks, "unsupported_claims": sum(item["id"] not in witnessed for item in gate["released_claims"]),
                     "before_unsupported_full": disabled.get("mode") == "FULL"
                     and disabled["baseline_verifier"]["verified_mode"] != "FULL",
                     "after_unsupported_full": final["answer_mode"] == "FULL" and verdict["verified_mode"] != "FULL",
                     "final": final, "verifier": verdict, "trace_id": enabled.get("trace_id"),
                     "citation_canonicalization": audit["citation_canonicalization"]})
    def ratio(key, predicate=lambda row: True):
        cohort = [row for row in rows if key in row["checks"] and predicate(row)]
        return {"numerator": sum(row["checks"][key] for row in cohort), "denominator": len(cohort),
                "failed_ids": [row["id"] for row in cohort if not row["checks"][key]]}
    return {"schema_version": 1, "expert_validated": False, "rows": rows, "metrics": {
        "before_unsupported_full": sum(row["before_unsupported_full"] for row in rows),
        "after_unsupported_full": sum(row["after_unsupported_full"] for row in rows),
        "unsupported_final_claims": sum(row["unsupported_claims"] for row in rows),
        "released_claims": sum(len(row["final"]["release_gate"]["released_claims"]) for row in rows),
        **{key: ratio(key) for key in ("final", "generated", "verified", "citation_integrity", "citation_probe",
                                       "multipart_coverage", "missing_information", "qualification")},
        "safe_abstention": ratio("final", lambda row: row["expected"]["final"] is None),
    }}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("capture", "replay"))
    parser.add_argument("run", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    suite = read(FIXTURES)
    dataset, corpus, *_ = inputs(read(args.snapshot) if args.snapshot else None)
    if args.command == "capture":
        create(args.run, suite, dataset, corpus)
        return
    text = json.dumps(evaluate(args.run, suite, dataset), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
