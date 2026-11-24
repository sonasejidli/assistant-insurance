"""Deterministic evaluation of the existing authority layer, with no external services."""

import argparse
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree

from App import source_authority as layer
from evaluation.gold_framework import HERE, digest, read


ROOT = HERE / "source_authority_benchmark_v1"
SPLITS = ("baseline", "development", "stress")
MISSING = {"missing_field": True}


def value_at(record, path):
    for part in path:
        try:
            record = record[part]
        except (TypeError, IndexError, KeyError):
            return MISSING
    return record


def check_snapshot(corpus, snapshot):
    if snapshot is None:
        return
    ordered = [(h["metadata"]["chunk_id"], h["text"]) for doc in snapshot for h in doc["chunks"]]
    if digest(ordered) != corpus["snapshot_sha256"]:
        raise ValueError("Unexpected source snapshot")
    source_by_id = {h["metadata"]["chunk_id"]: (doc, h) for doc in snapshot for h in doc["chunks"]}
    for doc in corpus["documents"]:
        for hit in doc["chunks"]:
            parent, frozen = source_by_id[hit["metadata"]["chunk_id"]]
            if doc["metadata"] != parent["metadata"] or doc["doc"] != parent["doc"] or hit != frozen:
                raise ValueError("Extract differs from the indexed snapshot")


def select(corpus, fixture):
    docs = deepcopy(corpus["documents"])
    hits_by_id = {h["metadata"]["chunk_id"]: h for doc in docs for h in doc["chunks"]}
    selected = [hits_by_id[corpus["passages"][name]] for name in fixture["passages"]]
    return docs, selected


def pipeline(fixture, docs, hits):
    """Exercise the actual ask, evidence assembly, packing, binding and judge handoff."""
    from starlette.requests import Request
    from App import legal_answers, main, system

    draft = json.dumps({"evidence_status": "sufficient", "claims": [
        {"text": fixture["claim"], "source_ids": [fixture["marker"]]}
    ]})
    original = legal_answers.generate_legal_answer
    outcomes = {}
    for enabled in (False, True):
        prompt_items, judge_input = [], []
        def invoke(_prompt, data, **_):
            nodes = ElementTree.fromstring("<root>" + data.partition("\n</context>")[0].removeprefix("<context>\n") + "</root>")
            prompt_items.extend(dict(node.attrib) for node in nodes)
            return draft

        def judge(claims, evidence):
            judge_input.extend(evidence[marker]["passage_id"] for claim in claims for marker in claim.source_ids)
            return [fixture.get("judge_accepts", True)] * len(claims)

        def generate(*args, **kwargs):
            return original(*args, **{**kwargs, "judge": True})

        ranked_handoffs = []
        def search(*_args, **_kwargs):
            ranked_handoffs.append([hit["metadata"]["chunk_id"] for hit in hits])
            return hits, 1.0

        request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(
            retriever=SimpleNamespace(documents=docs, search=search)
        ))})
        with (
            patch.dict("os.environ", {"LEGAL_SOURCE_AUTHORITY": "1" if enabled else "0"}),
            patch.object(main, "STRUCTURED_ANSWERS", True),
            patch.object(main, "LEGAL_MULTIPART_COVERAGE", False),
            patch.object(main, "query_experiments", return_value={"provision": False}),
            patch.object(main, "generate_legal_answer", generate),
            patch.object(legal_answers, "API_KEY", "offline-fixture"),
            patch.object(legal_answers, "LLM_MODEL", "offline-fixture"),
            patch.object(system, "LLM_CONTEXT_WINDOW", 16384),
            patch.object(system, "LLM_MAX_OUTPUT_TOKENS", 1536),
            patch.object(legal_answers, "invoke", invoke),
            patch.object(legal_answers, "judge_claims", judge),
        ):
            response = main.ask(main.Question(question=fixture["question"], language="az"), request)
        outcomes["enabled" if enabled else "disabled"] = {
            "ranking": ranked_handoffs[0],
            "packed": {item["id"]: item for item in prompt_items},
            "returned_reference_ids": [ref["passage_id"] for ref in response.get("references", [])],
            "returned_references": response.get("references", []),
            "judge_reference_ids": judge_input,
            "authority_visible": "source_authority" in response,
            "mode": response.get("evidence_status"),
        }
    return outcomes


def annotation(fixture, docs, hits, catalog):
    timeline = layer.case_timeline(**fixture.get("timeline", {}))
    for index, override in fixture.get("metadata_overrides", {}).items():
        hits[int(index)]["metadata"].update(override)
    for index, override in fixture.get("provision_overrides", {}).items():
        hit = hits[int(index)]
        catalog["provisions"][hit["metadata"]["chunk_id"]] = {
            "anchors": [], "text_sha256": layer.text_digest(hit["text"]), **override,
        }
    for index, override in fixture.get("document_overrides", {}).items():
        docid = hits[int(index)]["metadata"]["document_id"]
        catalog["documents"].setdefault(docid, {}).update(override)
    items = [{"source_url": f"/fixture/{h['metadata']['chunk_id']}", "original_text": h["text"]} for h in hits]
    actual = layer.annotate(hits, items, docs, timeline, catalog)
    actual["conflict_statuses"] = [record["status"] for record in actual["conflicts"]]
    actual["potential_conflicts"] = sum(record["status"] == "potential_conflict" for record in actual["conflicts"])
    return actual


def invariant(fixture, docs, hits, catalog):
    before = annotation(fixture, docs, hits, deepcopy(catalog))
    changed = fixture["transform"]
    args = {**fixture}
    clock = date
    if changed == "rename":
        old, new = hits[0]["doc"], "unverified-looking-name.pdf"
        for doc in docs:
            if doc["doc"] == old:
                doc["doc"] = new
                for hit in doc["chunks"]:
                    hit["doc"] = new
    elif changed == "reverse_order":
        hits.reverse()
    elif changed == "scores":
        for rank, hit in enumerate(hits):
            hit["metadata"].update(reranker_score=100 - rank, rrf_score=0.00001 * rank)
    elif changed == "clock":
        class FutureDate(date):
            @classmethod
            def today(cls):
                return cls(2099, 1, 1)
        clock = FutureDate
    elif changed == "remove_context":
        hits.pop()
    elif changed == "citation_join":
        pass
    else:
        raise ValueError(f"Unknown metamorphic transform {changed}")
    with patch.object(layer, "date", clock):
        after = annotation(args, docs, hits, deepcopy(catalog))
    prior = {r["reference"]["passage_id"]: r for r in before["sources"]}
    current = {r["reference"]["passage_id"]: r for r in after["sources"]}
    return {
        "authority_unchanged": all(r["source_type"] == prior[pid]["source_type"] for pid, r in current.items()),
        "eligibility_unchanged": all(r["eligible_normative"] == prior[pid]["eligible_normative"] for pid, r in current.items()),
        "stable_ids": all(r["reference"]["document_id"] == prior[pid]["reference"]["document_id"] for pid, r in current.items()),
        "reference_expected": all(all(r["reference"][k] == h["metadata"].get(m) for k, m in
                                      (("passage_id", "chunk_id"), ("document_id", "document_id"),
                                       ("article", "article"), ("clause", "clause"), ("page", "page_number")))
                                  and r["reference"]["document"] == h["doc"]
                                  for r, h in zip(after["sources"], hits, strict=True)),
        "timeline_unchanged": before["timeline"] == after["timeline"],
        "sources": after["sources"],
    }


def evaluate(root, snapshot=None):
    corpus = read(root / "sources.json")
    spec = read(root / "expected.json")
    if digest(corpus) != spec["source_sha256"]:
        raise ValueError("Source fixture failed its lock")
    check_snapshot(corpus, snapshot)
    catalog = layer.load_catalog()
    rows = []
    for split in SPLITS:
        suite = read(root / f"{split}.json")
        if suite["schema_version"] != spec["schema_version"] or digest(suite) != spec["split_sha256"][split]:
            raise ValueError(f"Fixture split failed its lock: {split}")
        for fixture in suite["fixtures"]:
            docs, hits = select(corpus, fixture)
            runner = fixture.get("runner", "annotation")
            if runner == "pipeline":
                actual = pipeline(fixture, docs, hits)
            else:
                fn = invariant if runner == "invariant" else annotation
                actual = fn(fixture, docs, hits, deepcopy(catalog))
            checks = []
            for check in spec["cases"][fixture["id"]]:
                got = value_at(actual, check["path"])
                passed = got == check["expected"]
                checks.append({**check, "actual": got, "passed": passed})
            rows.append({**fixture, "split": split, "checks": checks, "observed": actual})
    if (len(rows) != len(spec["cases"])
            or len(rows) != len({row["id"] for row in rows})):
        raise ValueError("Source lock or expected fixture IDs failed")
    return {"schema_version": 1, "snapshot_verified": snapshot is not None, "legal_expert_validated": False,
            "metrics": {name: metrics(group, spec["metrics"]) for name, group in (
                ("all", rows),
                *[(split, [row for row in rows if row["split"] == split]) for split in SPLITS],
                *[(name, [row for row in rows if row["origin"] == name]) for name in ("source_derived", "synthetic_engineering")],
                *[(f"category_{name}", [row for row in rows if row["category"] == name])
                  for name in sorted({row["category"] for row in rows})],
            )}, "rows": rows}


def metrics(rows, names):
    result = {}
    for metric in names:
        eligible = [(row["id"], c) for row in rows for c in row["checks"] if c["metric"] == metric]
        # This metric counts error events instead of correct decisions.
        inverse = metric == "conflict_false_positive_rate"
        if inverse:
            numerator = sum(c["actual"] not in (0, MISSING) for _, c in eligible)
        else:
            numerator = sum(c["passed"] for _, c in eligible)
        failures = [{"id": key, "path": c["path"], "expected": c["expected"], "actual": c["actual"],
                     "failure_type": c["failure_type"], "reason": c["explanation"]}
                    for key, c in eligible if not c["passed"]]
        result[metric] = {"numerator": numerator, "denominator": len(eligible),
                          "percentage": round(100 * numerator / len(eligible), 6) if eligible else None,
                          "failed_fixture_ids": sorted({failure["id"] for failure in failures}), "failures": failures}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--failures-output", type=Path)
    args = parser.parse_args()
    report = evaluate(ROOT, read(args.snapshot) if args.snapshot else None)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    if args.failures_output:
        failures = [{"id": row["id"], "origin": row["origin"], "split": row["split"], "note": row["note"],
                     "requires_expert_review": row["requires_expert_review"],
                     "checks": [check for check in row["checks"] if not check["passed"]],
                     "observed": row["observed"]}
                    for row in report["rows"] if any(not check["passed"] for check in row["checks"])]
        with args.failures_output.open("x", encoding="utf-8") as stream:
            json.dump({"schema_version": 1, "failures": failures}, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")


if __name__ == "__main__":
    main()
