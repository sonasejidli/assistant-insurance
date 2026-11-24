"""Validate an already-built local API image in isolated, disposable containers."""

import argparse
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4

DOCKER_HTTP = """
import json, sys, urllib.request
def fetch(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("http://127.0.0.1:8000" + path, data,
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))
health = fetch("/health")
answer = fetch("/ask", {"question": "Sığorta ödənişi nə vaxt verilir?", "language": "az"})
print(json.dumps({"health": health, "gate": "release_gate" in answer,
                  "mode": answer.get("answer_mode"), "sources": len(answer["sources"])}))
"""


def docker(*args, timeout=95):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True, timeout=timeout).stdout.strip()


def healthy(name, deadline_seconds):
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        health = docker("inspect", "--format", "{{.State.Status}} {{.State.Health.Status}}", name)
        if health == "running healthy":
            return
        if not health.startswith("running "):
            raise RuntimeError(f"Container stopped before health check: {health}")
        time.sleep(3)
    raise TimeoutError("Docker health check timed out")


def startup_events(name):
    logs = subprocess.run(["docker", "logs", name], capture_output=True, encoding="utf-8", errors="replace",
                          check=True, timeout=30)
    return [json.loads(line.split("rag_startup ", 1)[1]) for line in (logs.stdout + logs.stderr).splitlines()
            if line.startswith("INFO:App.observability:rag_startup ")]


def smoke(image, *, deadline_seconds=420, fixture_corpus=None, prepared_volume=None):
    rows = []
    for value in (None, "0", "1"):
        name = "verified-release-smoke-" + uuid4().hex[:10]
        command = ["run", "--detach", "--name", name, "--network", "none",
                   "--env", "QDRANT_PATH=/tmp/signoff-db" if prepared_volume else "QDRANT_PATH=/tmp/validation-qdrant",
                   "--env", "OMP_NUM_THREADS=2", "--env", "STRUCTURED_ANSWERS=1"]
        if prepared_volume:
            command += ["--mount", f"type=volume,source={prepared_volume},target=/tmp",
                        "--env", "RAG_REQUIRE_PREPARED_INDEX=1", "--env", "RAG_STARTUP_DIAGNOSTICS=1"]
        if fixture_corpus is not None:
            command += ["--mount", f"type=bind,source={fixture_corpus.resolve(strict=True)},target=/app/data/index,readonly"]
        if value is not None:
            command += ["--env", f"LEGAL_VERIFIED_RELEASE={value}"]
        started = time.monotonic()
        docker(*command, image)
        try:
            healthy(name, deadline_seconds)
            initial_ready = round(time.monotonic() - started, 2)
            initial = json.loads(docker("exec", name, "python", "-c", DOCKER_HTTP))
            row = {"flag": value, "initial": initial, "initial_healthy_seconds": initial_ready,
                   "expected_gate": value == "1"}
            if value == "1":
                packaged = docker("exec", name, "python", "-c",
                                  "from App.verified_release import configuration; "
                                  "from evaluation.verify_legal_scope_v2 import verify_case; "
                                  "print(bool(configuration()[0]) and callable(verify_case))")
                row["packaged_verifier"] = packaged == "True"
                restarted = time.monotonic()
                docker("restart", name)
                healthy(name, deadline_seconds)
                row["restart_healthy_seconds"] = round(time.monotonic() - restarted, 2)
                row["after_restart"] = json.loads(docker("exec", name, "python", "-c", DOCKER_HTTP))
            if prepared_volume:
                row["startup_stages"] = startup_events(name)
                row["resource_sample"] = docker("stats", "--no-stream", "--format", "{{.CPUPerc}} {{.MemUsage}}", name)
            row["passed"] = (initial["gate"] == row["expected_gate"] and initial["health"]["chunks"] > 0
                             and (value != "1" or row["packaged_verifier"] and initial["mode"] is None
                                  and initial["sources"] == 0)
                             and row.get("after_restart", initial) == initial)
            rows.append(row)
        finally:
            docker("rm", "--force", "--volumes", name)
    return {"mode": "container_validation", "corpus": "fixture" if fixture_corpus else "packaged",
            "rows": rows, "passed": sum(row["passed"] for row in rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--fixture-corpus", type=Path, help="Read-only public fixture corpus for a fast smoke run")
    parser.add_argument("--prepared-volume", help="Isolated Qdrant volume prepared at /tmp/signoff-db")
    parser.add_argument("--deadline-seconds", type=int, default=420)
    args = parser.parse_args()
    if args.deadline_seconds < 1:
        parser.error("--deadline-seconds must be positive")
    result = smoke(args.image, deadline_seconds=args.deadline_seconds, fixture_corpus=args.fixture_corpus,
                   prepared_volume=args.prepared_volume)
    print(json.dumps(result, indent=2))
    raise SystemExit(result["passed"] != len(result["rows"]))
