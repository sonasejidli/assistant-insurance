"""Bounded live qualification and offline replay against the frozen public controls."""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from App import legal_answers, verified_release
from evaluation.legal_answer_quality import inputs
from evaluation.rag_run import load, save
from evaluation.verified_adversarial import transport
from evaluation.verified_live_provider import runner
from evaluation.verified_release_benchmark import FIXTURES, execute, read, serialize

CASES = ("R01", "R02")
SECRET = re.compile(r"(?i)bearer\s+\S+|(?:sk-|or-v1-)[\w-]{10,}|[\w.+-]+@[\w.-]+\.[a-z]{2,}|"
                    r"(?:\+994|00994)[\d ()-]{9,20}")


def prequalify(snapshot):
    dataset, corpus, *_ = inputs(snapshot)
    configurations, _ = verified_release.configuration()
    cases = {item["id"]: item for item in dataset["cases"]}
    controls = {}
    for fixture in read(FIXTURES)["cases"]:
        if fixture["id"] not in CASES:
            continue
        base = cases[fixture["base"]]
        row = execute(fixture, base, corpus, True, transport=transport)
        body = row["response"]["body"]
        audit = row["verified_release"]
        verdict = audit["verifier"]
        profile = configurations[base["query"]]
        required = {pid for part in profile["parts"].values() for pid in part["required_passage_ids"]}
        sources = {item["reference"]["passage_id"]: item for item in body["source_authority"]["sources"]}
        claims = verdict["claims"]
        if not (row["response"]["status"] == 200 and verdict["id"] == profile["id"] and
                body["answer_mode"] == verdict["verified_mode"] == fixture["final"] and claims and
                all(claim["citation_valid"] and claim["witness"] and claim["supported_fragment"] for claim in claims)
                and {source["passage_id"] for source in body["sources"]} == required
                and all(sources[pid]["eligible_normative"] for pid in required)
                and (fixture["final"] != "PARTIAL" or body["release_gate"]["missing_information"])):
            raise ValueError(f"Prequalification failed for {fixture['id']}")
        controls[fixture["id"]] = {
            "question": base["query"], "expected_mode": fixture["final"], "witness_profile": profile["id"],
            "temporal": verdict["temporal_evidence"], "expected_claims": [
                {"witness": claim["witness"], "fragment": claim["supported_fragment"]} for claim in claims],
            "sources": body["sources"], "authority": [
                {key: sources[pid][key] for key in ("source_type", "temporal_status", "eligible_normative", "reference")}
                for pid in sorted(required)], "missing_information": body["release_gate"]["missing_information"],
        }
    if set(controls) != set(CASES):
        raise ValueError("Qualification controls missing")
    return controls


def redact(text):
    if legal_answers.API_KEY:
        text = text.replace(legal_answers.API_KEY, "[redacted]")
    return SECRET.sub("[redacted]", text)


def public_capture(row):
    audit = row["verified_release"]
    final = row["response"]["body"]
    verdict = deepcopy(audit["verifier"])
    for claim in (verdict or {}).get("claims", []):
        claim["claim_text"] = redact(claim["claim_text"])
    attempts = []
    for attempt in row["generation_attempts"]:
        output = attempt.get("output") or ""
        claims = [{"part": claim["part"], "citation_ids": [
            marker if re.fullmatch(r"S[0-9]{1,4}", marker) else "[invalid marker]"
            for marker in claim["citation_ids"]]} for claim in attempt.get("claim_citations", [])]
        attempts.append({
            "response_sha256": sha256(output.encode("utf-8")).hexdigest(),
            "output_chars": len(output), "prompt_sha256": attempt.get("prompt_sha256"),
            "claims": claims,
            "redacted_claim_texts": [redact(text) for text in attempt.get("draft_claims", [])],
            "packed_sources": [{key: source.get(key) for key in ("id", "passage_id", "document_id")}
                               for source in attempt.get("sources") or []],
        })
    return {
        "trace_id": row["trace_id"], "status": row["response"]["status"], "response": final, "attempts": attempts,
        "verifier": verdict, "generated_mode": audit["generated_mode"], "conflicts": audit["conflicts"],
        "canonicalization": {key: audit["citation_canonicalization"].get(key, []) for key in
                             ("trusted_missing_information", "unresolved_parts")},
        "language": audit["language"], "failure": audit.get("failure"), "stage_ms": audit.get("stage_ms", {}),
        "stage_timings": [{"stage": item["stage"], "latency_ms": item["latency_ms"]}
                          for item in row["stages"] if "latency_ms" in item],
        "ranked_passage_ids": row.get("ranked_passage_ids", []),
        "provider_budget_exhausted": row.get("provider_budget_exhausted", False),
    }


def replay(capture):
    result = {}
    for fid, row in capture["captures"].items():
        body = row["response"]
        notes = row["canonicalization"]
        if row["failure"]:
            rebuilt = verified_release.abstain_on_failure(row["language"])
        else:
            rebuilt = verified_release.release(
                {"disclaimer": body["disclaimer"]}, row["generated_mode"], row["verifier"],
                body["source_authority"], row["conflicts"], row["language"],
                trusted_notices=notes["trusted_missing_information"], unresolved_parts=notes["unresolved_parts"])
        if serialize(rebuilt) != body:
            raise ValueError(f"Offline release replay differs for {fid}")
        result[fid] = {"trace_id": row["trace_id"], "mode": body["answer_mode"],
                       "citations": len(body["sources"]), "exact_response": True}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prequalify", "live", "replay"))
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--allow-provider-calls", action="store_true")
    parser.add_argument("--max-calls-per-case", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--max-retries", type=int, choices=(0, 1), default=1)
    parser.add_argument("--base-delay", type=float, choices=(0.5, 1.0, 2.0), default=0.5)
    parser.add_argument("--max-wait", type=int, choices=range(0, 11), default=5)
    parser.add_argument("--timeout-ms", type=int, default=12000, metavar="1000..20000")
    parser.add_argument("--token-cap", type=int, default=1536, metavar="64..1536")
    args = parser.parse_args()
    if not 1000 <= args.timeout_ms <= 20000 or not 64 <= args.token_cap <= 1536:
        parser.error("Timeout must be 1000–20000 ms and token cap must be 64–1536")
    if args.command == "replay":
        print(json.dumps(replay(load(args.artifact)), indent=2, sort_keys=True))
        return
    if args.artifact.exists():
        parser.error("Artifact already exists")
    snapshot = read(args.snapshot) if args.snapshot else None
    controls = prequalify(snapshot)
    if args.command == "prequalify":
        save(args.artifact, controls)
        return
    if not args.allow_provider_calls:
        parser.error("Live qualification requires --allow-provider-calls")
    captures = {}
    budget = dict(max_calls=args.max_calls_per_case, max_retries=args.max_retries, base_delay=args.base_delay,
                  max_wait=args.max_wait, timeout_ms=args.timeout_ms, token_cap=args.token_cap)
    report = runner(snapshot, positive_only=True, observer=lambda fid, row: captures.update({fid: public_capture(row)}),
                    **budget)
    capture = {"schema_version": 1, "controls": controls, "captures": captures, "metrics": report, "budget": budget}
    save(args.artifact, capture)
    print(json.dumps(replay(capture), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
