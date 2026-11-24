"""Probe offline intent planning without assigning legal gold answers."""

import json
from pathlib import Path
from unittest.mock import patch

from App import intent, query_plan
from App.query_resolution import resolve_query


ROOT = Path(__file__).resolve().parents[1] / "docs" / "legal_coverage"
IN_DOMAIN = ("insurance_question", "legal_question", "ambiguous_question")


def run(suite):
    rows = []

    def probe(kind, question, expected, domain=None, history=(), provisions=()):
        resolution = resolve_query(question, list(history), direct_article=False)
        route = query_plan.plan_query(resolution, "az").intent
        rows.append({
            "kind": kind, "query": question, "expected_domain": domain,
            "expected_provisions": provisions, "expected_routes": expected,
            "rule": intent.classify_intent_rule(question),
            "standalone": resolution.standalone, "route": route,
            "passed": route in expected,
        })

    with patch.object(intent, "INTENT_LLM_ENABLED", False):
        for group in suite["domains"]:
            for index, question in enumerate(group["queries"]):
                probe("exact" if index == 0 else "paraphrase", question, IN_DOMAIN,
                      group["domain"], provisions=group["provisions"])
            probe("followup", group["followup"], IN_DOMAIN, group["domain"],
                  history=[group["queries"][0]], provisions=group["provisions"])
        for question in suite["out_of_scope"]:
            probe("negative", question, ("out_of_scope",))
        for entry in suite["additional_review_cases"]:
            probe("review", entry["query"], IN_DOMAIN, entry["domain"])

    summary = {}
    for kind in ("exact", "paraphrase", "followup", "negative", "review"):
        cases = [row for row in rows if row["kind"] == kind]
        summary[kind] = {"total": len(cases), "passed": sum(row["passed"] for row in cases)}
    return {"method": "Offline intent planning only", "summary": summary, "rows": rows}


def main():
    suite = json.loads((ROOT / "routing_probe_cases.json").read_text(encoding="utf-8"))
    result = run(suite)
    (ROOT / "routing_probe_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main()
