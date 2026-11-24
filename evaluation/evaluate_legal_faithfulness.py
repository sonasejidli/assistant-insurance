"""Measure deterministic and semantic claim checks against approved source-bound labels."""

import argparse
import json
from pathlib import Path

from App.legal_answers import Claim, claim_is_bound, judge_claims
from App.text_search import load_chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--reviewed", type=Path, help="Human-approved claim judgments")
    inputs.add_argument("--probe", action="store_true", help="Check the validation provider using one indexed source")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.reviewed:
        review = json.loads(args.reviewed.read_text(encoding="utf-8"))
        rows = review.get("claims", [])
        if (not review.get("reviewer") or review.get("status") != "approved" or
                {type(row.get("supported")) for row in rows} != {bool} or {row["supported"] for row in rows} != {True, False}):
            parser.error("Provide expert-approved positive and negative claim judgments")
    else:
        dataset = json.loads(Path("evaluation/real_insurance_dataset.json").read_text(encoding="utf-8"))
        case = next(row for row in dataset["queries"] if row["id"] == "AZR097")
        evidence = case["evidence"][0]
        rows = [{"id": case["id"], "text": evidence["text"].split("\n", 1)[0],
                 "passage_ids": [evidence["parent_passage_id"]], "supported": None}]
    by_id = {chunk["metadata"]["chunk_id"]: chunk for chunk in load_chunks()}
    results = []
    for row in rows:
        evidence = {}
        for i, point_id in enumerate(row["passage_ids"], 1):
            hit = by_id[point_id]
            evidence[f"S{i}"] = {"original_text": hit["metadata"].get("original_text") or hit["text"]}
        text = " ".join(row["text"].split())
        claim = Claim(text=text, source_ids=list(evidence))
        bound = claim_is_bound(claim, evidence, set())
        semantic = error = None
        if bound:
            try:
                semantic, = judge_claims([claim], evidence)
            except Exception as exc:
                error = type(exc).__name__
        results.append({"id": row["id"], "expected_supported": row["supported"], "deterministic_pass": bound,
                        "semantic_pass": semantic, "pipeline_pass": (semantic if bound else False), "provider_error": error})
    scored = [row for row in results if row["pipeline_pass"] is not None and row["expected_supported"] is not None]
    confusion = {f"expected_{expected}_observed_{observed}": sum(r["expected_supported"] == expected and r["pipeline_pass"] == observed
                                                              for r in scored)
                 for expected in (False, True) for observed in (False, True)}
    result = {"expert_reviewed": bool(args.reviewed), "scored": len(scored), "confusion": confusion, "rows": results}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
