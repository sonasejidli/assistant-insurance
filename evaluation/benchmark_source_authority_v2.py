"""Run the explicitly versioned temporal cases alongside the frozen v1 benchmark."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from App import source_authority as layer
from evaluation import benchmark_source_authority as v1
from evaluation.gold_framework import HERE, digest, read


FIXTURES = HERE / "source_authority_benchmark_v2.json"


def evaluate(snapshot=None):
    suite = read(FIXTURES)
    corpus = read(v1.ROOT / "sources.json")
    expected = read(v1.ROOT / "expected.json")
    if suite["schema_version"] != 2 or suite["base_expected_sha256"] != digest(expected):
        raise ValueError("V2 requires the original locked v1 expectations")
    original = v1.evaluate(v1.ROOT, snapshot)
    catalog = layer.load_catalog()
    replacements = suite["revisions"]
    if not replacements.keys() <= {row["id"] for row in original["rows"]}:
        raise ValueError("Unknown v1 fixture in v2 revisions")
    rows = []
    for old in original["rows"]:
        revision = replacements.get(old["id"])
        if revision is None:
            rows.append(old)
            continue
        fixture = {key: value for key, value in old.items() if key not in {"checks", "observed"}}
        fixture.update(revision.get("fixture", {}))
        removed = revision.get("remove_paths", [])
        checks = [check for check in expected["cases"][old["id"]] if check["path"] not in removed]
        if len(expected["cases"][old["id"]]) - len(checks) != len(removed):
            raise ValueError("V2 can only replace an explicitly identified existing expectation")
        rows.append(check_fixture(corpus, catalog, fixture, checks + revision.get("checks", [])))
    for fixture in suite["new_cases"]:
        rows.append(check_fixture(corpus, catalog, {k: v for k, v in fixture.items() if k != "checks"},
                                  fixture["checks"]))
    if len(rows) != len({row["id"] for row in rows}):
        raise ValueError("Duplicate v2 fixture ID")
    groups = {"all": rows, "original_cohort": rows[:len(original["rows"])],
              "targeted": [row for row in rows if row["id"] in {"T11", "T13", "C03", "C06"}],
              "extension": rows[len(original["rows"]):]}
    groups.update({f"category_{name}": [row for row in rows if row["category"] == name]
                   for name in sorted({row["category"] for row in rows})})
    return {"schema_version": 2, "snapshot_verified": original["snapshot_verified"],
            "legal_expert_validated": False, "frozen_v1_expectations_on_current_layer": original["metrics"]["all"],
            "metrics": {key: v1.metrics(group, expected["metrics"]) for key, group in groups.items()}, "rows": rows}


def check_fixture(corpus, catalog, fixture, checks):
    docs, hits = v1.select(corpus, fixture)
    if fixture.get("synthetic_same_text"):
        if fixture["origin"] != "synthetic_engineering" or len(hits) != 2:
            raise ValueError("Identical-text overlays require a synthetic pair")
        hits[1]["text"] = hits[0]["text"]
    actual = v1.annotation(fixture, docs, hits, deepcopy(catalog))
    results = []
    for check in checks:
        value = v1.value_at(actual, check["path"])
        results.append({**check, "actual": value, "passed": value == check["expected"]})
    return {**fixture, "checks": results, "observed": actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(read(args.snapshot) if args.snapshot else None)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    main()
