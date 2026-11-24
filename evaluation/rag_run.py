"""Capture the draft cohort on archived vectors or replay a saved run offline."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
from statistics import mean
from math import ceil, isfinite
from tempfile import NamedTemporaryFile
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4

from App.evaluation_capture import recording
from evaluation.evaluate_latest_seven import ANSWER_MODES, evidence_pairs, score, validate
from evaluation.gold_framework import HERE, digest, read, retrieval_scores


DRAFT = HERE / "latest_seven_dataset.json"
ID = re.compile(r"[a-f0-9]{32}")
PIPELINE_SETTINGS = (
    "TOP_K", "LLM_MODEL", "LLM_CONTEXT_WINDOW", "LLM_MAX_OUTPUT_TOKENS",
    "EMBED_MODEL", "EMBED_MODEL_REVISION", "EMBED_TARGET_TOKENS", "EMBED_OVERLAP_TOKENS",
    "RERANK_MODEL", "RERANK_MODE", "RERANK_DEVICE", "RERANK_BATCH_SIZE", "RERANK_MAX_TOKENS",
    "BM25_K1", "BM25_B", "CONTEXTUAL_HEADERS", "LEGAL_EVIDENCE", "STRUCTURED_ANSWERS",
    "LEGAL_FAITHFULNESS", "LEGAL_MIN_SUPPORTING_STAGES", "LEGAL_RETRIEVAL_V2",
    "LEGAL_PROVISION_RETRIEVAL", "LEGAL_MULTIPART_COVERAGE", "LEGAL_CLAIM_GUARDS",
    "STAGED_LEGAL_SOURCES", "QUERY_DECOMPOSITION", "QUERY_ROUTING", "QUERY_EXPANSION", "QUERY_HYDE",
)
METRICS = {
    "retrieval": ("recall@5", "recall@10", "mrr@10", "ndcg@10"),
    "citation": ("citation_precision", "citation_completeness", "citation_validity"),
    "generation": ("answer_correctness", "evidence_support"),
    "answer_behavior": ("answer_mode_accuracy",),
    "multipart": ("subquestion_coverage", "multipart_evidence_coverage"),
}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, payload):
    """Publish one immutable checksummed JSON record, even with competing writers."""
    temp = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            json.dump({"sha256": digest(payload), "payload": payload}, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
    finally:
        if temp is not None:
            temp.unlink()


def load(path):
    envelope = read(path)
    if digest(envelope["payload"]) != envelope["sha256"]:
        raise ValueError(f"Capture checksum mismatch in {path.name}")
    return envelope["payload"]


def capture_run(root, run_id, dataset, configuration, ask_case):
    if not ID.fullmatch(run_id):
        raise ValueError("Run ID must be 32 lowercase hexadecimal characters")
    validate(dataset)
    root.mkdir(parents=True, exist_ok=True)
    run = root / run_id
    run.mkdir(mode=0o700)  # Exclusive reservation. A second run cannot overwrite it.
    manifest = {
        "schema_version": 1, "run_id": run_id, "started_at": now(), "configuration": configuration,
        "dataset_sha256": digest(dataset), "corpus_sha256": dataset["corpus_sha256"],
        "case_ids": [case["id"] for case in dataset["queries"]],
    }
    save(run / "manifest.json", manifest)
    def capture_case(case):
        start = perf_counter()
        with recording(configuration.get("provider_timeout_ms"), configuration.get("provider_retry_policy")) as row:
            if configuration.get("concise_generation"):
                row["concise_generation"] = True
            row.update(case_id=case["id"], query=case["query"], started_at=now(), run_id=run_id)
            try:
                ask_case(case)
            except Exception as exc:
                row.setdefault("status", "failed")
                row.setdefault("error_type", type(exc).__name__)
            row.setdefault("latency_ms", round((perf_counter() - start) * 1000, 2))
        save(run / f"{case['id']}.json", row)
    workers = configuration.get("concurrency", 1)
    if workers == 1:
        for case in dataset["queries"]:
            capture_case(case)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(capture_case, dataset["queries"]))
    save(run / "completed.json", {"run_id": run_id, "finished_at": now()})
    return run


def aligned_parts(case, row):
    executed = row.get("executed_parts")
    if executed is None:
        return None, "Missing executed decomposition"
    if len(case["parts"]) < 2:
        return None, "Single-part rubric"
    if not executed or list(executed.values()) == [row.get("standalone_query")]:
        return {}, None
    mapping = {}
    for observed_id, question in executed.items():
        matches = [expected_id for expected_id, part in case["parts"].items()
                   if " ".join(question.casefold().split()) == " ".join(part["question"].casefold().split())]
        if len(matches) != 1 or matches[0] in mapping.values():
            return None, "Executed and rubric parts require reviewed alignment"
        mapping[observed_id] = matches[0]
    return mapping, None


def evaluate_case(case, row, review):
    scores = {axis: dict.fromkeys(names) for axis, names in METRICS.items()}
    blocked = {metric: "Missing case capture" for names in METRICS.values() for metric in names}
    if row is None:
        return scores, blocked

    order = row.get("ranked_passage_ids")
    grades = {item["passage_id"]: item["relevance"] for item in case["evidence"] if item["role"] == "direct"}
    for name in METRICS["retrieval"]:
        cutoff = 5 if name == "recall@5" else 10
        if order is None or any(not pid for pid in order) or len(order) != len(set(order)):
            blocked[name] = "Missing or unusable final passage IDs"
        elif not grades:
            blocked[name] = "No direct evidence labels"
        elif len(order) < cutoff and (not row.get("retrieval_limit") or row["retrieval_limit"] < cutoff):
            blocked[name] = f"Final ranking did not observe depth {cutoff}"
        else:
            result = retrieval_scores(order[:10], grades)
            scores["retrieval"][name] = result["mrr@20" if name == "mrr@10" else name]

    mapping, reason = aligned_parts(case, row)
    required = evidence_pairs(case)
    blocked["subquestion_coverage"] = reason
    blocked["multipart_evidence_coverage"] = reason or "Missing evidence assignments or direct part labels"
    if mapping is not None:
        scores["multipart"]["subquestion_coverage"] = len(set(mapping.values())) / len(case["parts"])
        if required and row.get("assembled_evidence") is not None:
            pairs = {(mapping[part], item["passage_id"]) for item in row["assembled_evidence"]
                     for part in item["parts"] if part in mapping}
            scores["multipart"]["multipart_evidence_coverage"] = len(pairs & required) / len(required)

    events = row.get("stages", [])
    degraded_generation = any(event["stage"] in {"provider_error", "faithfulness_error", "answer_error"} for event in events)
    blocked["answer_mode_accuracy"] = "Missing applicable answer mode or generation failed"
    if (row.get("status") == "returned" and not degraded_generation
            and row.get("mode") in ANSWER_MODES and case["domain_scope"] == "in_corpus"):
        scores["answer_behavior"]["answer_mode_accuracy"] = row["mode"] == case["expected_mode"]

    blocked["citation_validity"] = "Requires emitted citations and recorded binding validation with packed source IDs"
    attempts = row.get("generation_attempts", [])
    binding = [event["outcome"] for event in events if event["stage"] == "citation_validation"]
    markers = row.get("citation_ids")
    if (markers and attempts and binding and attempts[-1].get("sources") is not None
            and row.get("citation_passages") is not None and not degraded_generation):
        context = {item["id"]: item["passage_id"] for item in attempts[-1]["sources"]}
        references = row.get("citation_passages", {})
        scores["citation"]["citation_validity"] = sum(
            binding[-1] == "bound" and marker in references and bool(context.get(marker))
            and context[marker] == references[marker] for marker in markers
        ) / len(markers)
    elif markers == []:
        blocked["citation_validity"] = "No emitted citations"

    for axis, fields in (("citation", ("citation_precision", "citation_completeness")),
                         ("generation", ("answer_correctness", "evidence_support"))):
        for field in fields:
            blocked[field] = "Requires an approved review of the exact returned answer"
    if review is not None and isinstance(row.get("answer"), str):
        reviewed, reasons = score(case, {"query": row["query"], "answer": row["answer"],
                                         "artifact": row["run_id"], "generation_review": review})
        for field in ("citation_precision", "citation_completeness", "answer_correctness"):
            axis = "generation" if field == "answer_correctness" else "citation"
            scores[axis][field] = reviewed[field]
            blocked[field] = reasons.get(field)
        if type(review.get("evidence_support")) is bool:
            context = attempts[-1].get("evidence_context") if attempts else None
            if context is None:
                blocked["evidence_support"] = "Missing captured generator context"
            elif review.get("context_sha256") != sha256(context.encode("utf-8")).hexdigest():
                raise ValueError(f"Evidence support review does not match captured context for {case['id']}")
            else:
                scores["generation"]["evidence_support"] = review["evidence_support"]
    return scores, {key: reason for key, reason in blocked.items()
                    if all(section.get(key) is None for section in scores.values())}


def replay(run, dataset, reviews=None):
    validate(dataset)
    manifest = load(run / "manifest.json")
    if (manifest["schema_version"] != 1 or manifest["run_id"] != run.name
            or manifest["dataset_sha256"] != digest(dataset)
            or manifest["corpus_sha256"] != dataset["corpus_sha256"]
            or manifest["case_ids"] != [case["id"] for case in dataset["queries"]]):
        raise ValueError("Capture is incompatible with this draft dataset")
    reviews = reviews or {}
    if set(reviews) - set(manifest["case_ids"]):
        raise ValueError("Unknown review case ID")
    complete = run / "completed.json"
    if complete.exists() and load(complete)["run_id"] != manifest["run_id"]:
        raise ValueError("Completion record belongs to another run")
    rows = []
    expected = {"trace_id", "query", "normalized_query", "planned_parts", "executed_parts",
                "ranked_passage_ids", "answer", "mode", "citation_ids", "latency_ms", "stages", "branches",
                "generation_attempts"}
    for case in dataset["queries"]:
        key = case["id"]
        path = run / f"{key}.json"
        row = load(path) if path.exists() else None
        if row is not None and (row.get("case_id"), row.get("run_id"), row.get("query")) != (
            key, manifest["run_id"], case["query"],
        ):
            raise ValueError(f"Capture identity mismatch for {key}")
        scores, blocked = evaluate_case(case, row, reviews.get(key))
        stages = row.get("stages", []) if row is not None else []
        missing = expected - (row.keys() if row is not None else set())
        if row is not None:
            if row.get("ranked_passage_ids") and "assembled_evidence" not in row:
                missing.add("assembled_evidence")
            if (row.get("decision_reason") == "accepted_answer" and not row.get("generation_attempts")
                    and row.get("generation_path") != "deterministic_calculation"):
                missing.add("generator_context_or_explicit_non_model_path")
            if (row.get("citation_ids") and "citation_passages" not in row
                    and row.get("decision_reason") != "answer_recovery"):
                missing.add("citation_passages")
            for index, attempt in enumerate(row.get("generation_attempts", ()), 1):
                missing.update(f"generation_attempts[{index}].{field}" for field in
                               {"output", "sources", "evidence_context", "prompt_sha256"} - attempt.keys())
        not_produced = set()
        if row is not None and (row.get("status") == "failed" or any(event.get("error_type") for event in stages)):
            not_produced = missing & {"answer", "mode", "citation_ids"}
            not_produced |= {field for field in missing if field.endswith("].output")}
        operational = {"status": row.get("status", "incomplete") if row is not None else "missing",
                       "latency_ms": row.get("latency_ms") if row is not None else None,
                       "missing_fields": sorted(missing - not_produced),
                       "not_produced_on_failed_path": sorted(not_produced),
                       "stage_failures": [event for event in stages if event.get("error_type")],
                       "stage_timings": [event for event in stages if "latency_ms" in event],
                       "citation_validation": [event for event in stages if event["stage"] in
                                               {"citation_validation", "faithfulness_validation"}]}
        if row is not None:
            attempts = row.get("generation_attempts", [])
            operational.update(
                decision_reason=row.get("decision_reason"),
                final_mode=row.get("mode"),
                ranking_sha256=digest(row["ranked_passage_ids"]) if "ranked_passage_ids" in row else None,
                outcome=("generated_answer" if row.get("decision_reason") == "accepted_answer"
                         and any("output" in attempt for attempt in attempts)
                         else "recovery" if row.get("decision_reason") == "answer_recovery"
                         else row.get("decision_reason") or row.get("status")),
                format_retries=max(0, len(attempts) - 1),
                provider_calls=row.get("provider_calls"),
                model_usage=[{key: event[key] for key in ("stage", "model", "input_tokens", "output_tokens", "total_tokens")
                              if key in event} for event in stages if event["stage"] in {"legal_model", "legacy_model"}],
                generation_attempts=[{"status": attempt.get("status"), "error_type": attempt.get("error_type"),
                                      "validation": attempt.get("validation"),
                                      "citation_ids": attempt.get("citation_ids"),
                                      "output_chars": len(attempt["output"]) if "output" in attempt else None,
                                      "finish_reason": attempt.get("finish_reason"),
                                      "output_returned": "output" in attempt} for attempt in attempts],
            )
        rows.append({"id": key, "metrics": scores, "unavailable": blocked, "operational": operational})
    summaries = {}
    for axis, names in METRICS.items():
        summaries[axis] = {}
        for name in names:
            values = [row["metrics"][axis][name] for row in rows if row["metrics"][axis][name] is not None]
            summaries[axis][name] = {"n": len(values), "mean": mean(values) if values else None}
    latencies = sorted(row["operational"]["latency_ms"] for row in rows if row["operational"]["latency_ms"] is not None)
    operations = [row["operational"] for row in rows]
    calls = [call for op in operations for call in (op.get("provider_calls") or [])]
    summaries["operational"] = {
        "captured": sum(row["operational"]["status"] != "missing" for row in rows),
        "expected": len(rows), "completion_recorded": complete.exists(),
        "captures_without_omissions": sum(not row["operational"]["missing_fields"] for row in rows),
        "captures_with_outputs_not_produced": sum(bool(row["operational"]["not_produced_on_failed_path"]) for row in rows),
        "failed_requests": sum(row["operational"]["status"] == "failed" for row in rows),
        "stage_failure_events": sum(len(row["operational"]["stage_failures"]) for row in rows),
        "successful_generated_answers": sum(op.get("outcome") == "generated_answer" for op in operations),
        "recovery_responses": sum(op.get("outcome") == "recovery" for op in operations),
        "format_retries": sum(op.get("format_retries", 0) for op in operations),
        "provider_call_count": len(calls) if any(op.get("provider_calls") is not None for op in operations) else None,
        "transport_retries": sum(call["transport_retry"] > 0 for call in calls) if calls else None,
        "rate_limited_calls": sum(call.get("http_status") == 429 for call in calls) if calls else None,
        "rate_limited_requests": sum(any(call.get("http_status") == 429 for call in op.get("provider_calls") or [])
                                     for op in operations) if calls else None,
        "latency_ms": {"n": len(latencies), "mean": mean(latencies) if latencies else None,
                       **{f"p{p}": latencies[ceil(p / 100 * len(latencies)) - 1] if latencies else None
                          for p in (50, 95, 99)}},
    }
    return {"schema_version": 1, "run_id": manifest["run_id"], "draft_only": True,
            "summary": summaries, "rows": rows}


def capture_archived(args, dataset):
    from starlette.requests import Request

    from App import embedding, main, settings, text_search
    from evaluation.evaluate_real_insurance import read_archives, verify_archives

    if not ID.fullmatch(args.run_id) or not 1 <= args.provider_timeout_ms <= 120_000:
        raise ValueError("Use a valid run ID and a provider timeout between 1 and 120000 ms")
    if (args.root / args.run_id).exists():
        raise FileExistsError(f"Run {args.run_id} already exists")
    documents = read(args.snapshot)
    validate(dataset, documents)
    chunks = [chunk for document in documents for chunk in document["chunks"]]
    encoder = embedding.embedding_configuration()
    archives = read_archives(args.vectors, chunks, encoder["dimensions"], encoder["model_repository"])
    archive = archives[0 if args.archive == "before" else 1]
    verify_archives([archive])
    with args.vectors.open("rb") as stream:
        archive_sha256 = file_digest(stream, "sha256").hexdigest()

    retriever = text_search.TextRetriever.__new__(text_search.TextRetriever)
    retriever.settings = settings.RetrievalSettings.from_env()
    retriever.chunks, retriever.documents, retriever.vector_index = chunks, documents, archive
    retriever.bm25 = text_search.RetrievalBM25.from_chunks(chunks)
    retriever.graph = retriever._build_graph()
    # No ASGI lifespan or Qdrant client is started by the isolated runner.
    def ask_case(case):
        request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(retriever=retriever))})
        return main.ask(main.Question(question=case["query"], language="az"), request)
    retry_policy = {"statuses": sorted(set(args.retry_status or [429])), "retry_connect": args.retry_connect,
                    "max_retries": args.max_retries, "base_delay_seconds": args.retry_base_delay,
                    "max_delay_seconds": args.retry_max_delay, "max_wait_seconds": args.retry_wait_budget}
    config = {"index_backend": "frozen_exact", "archive": archive.name, "archive_sha256": archive_sha256,
              "embedding_revision": encoder.get("model_revision"), "provider": "openrouter",
              "provider_timeout_ms": args.provider_timeout_ms, "provider_sdk_retries": False,
              "provider_retry_policy": retry_policy, "concurrency": args.concurrency,
              "concise_generation": args.concise_generation,
              "retrieval": asdict(retriever.settings), "settings": {key: getattr(settings, key) for key in PIPELINE_SETTINGS},
              "request": {"language": "az", "mode": "question", "history": []}}
    return capture_run(args.root, args.run_id, dataset, config, ask_case)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--snapshot", type=Path, required=True)
    capture.add_argument("--vectors", type=Path, required=True)
    capture.add_argument("--archive", choices=("before", "after"), default="after")
    capture.add_argument("--root", type=Path, default=Path(".venv/rag-runs"))
    capture.add_argument("--run-id", default=uuid4().hex)
    capture.add_argument("--provider-timeout-ms", type=int, default=12_000)
    capture.add_argument("--concurrency", type=int, default=1)
    capture.add_argument("--max-retries", type=int, default=2)
    capture.add_argument("--retry-status", type=int, choices=(408, 429, 500, 502, 503, 504), action="append")
    capture.add_argument("--retry-connect", action="store_true")
    capture.add_argument("--retry-base-delay", type=float, default=1)
    capture.add_argument("--retry-max-delay", type=float, default=8)
    capture.add_argument("--retry-wait-budget", type=float, default=25)
    capture.add_argument("--report", type=Path, help="Write a replay report after capture")
    capture.add_argument("--concise-generation", action="store_true", help="Use a shorter evaluation-only legacy prompt")
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("run", type=Path)
    replay_parser.add_argument("--reviews", type=Path)
    replay_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dataset = read(DRAFT)
    if args.command == "capture":
        delays = (args.retry_base_delay, args.retry_max_delay, args.retry_wait_budget)
        if (not 1 <= args.concurrency <= 7 or not 0 <= args.max_retries <= 8
                or not all(isfinite(value) and value > 0 for value in delays)
                or not args.retry_base_delay <= args.retry_max_delay <= args.retry_wait_budget <= 180):
            parser.error("Invalid concurrency or retry budget")
        if args.report and args.report.exists():
            parser.error("Report path already exists")
        run = capture_archived(args, dataset)
        if args.report:
            with args.report.open("x", encoding="utf-8") as stream:
                json.dump(replay(run, dataset), stream, ensure_ascii=False, indent=2)
        print(run)
        return
    report = replay(args.run, dataset, read(args.reviews) if args.reviews else None)
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
