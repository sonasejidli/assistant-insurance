"""Apply explicit expert-approved floors to reviewed evaluation results."""

import argparse
import json
import math
from pathlib import Path


def validate(policy, retrieval, answers):
    if (policy.get("status") != "approved" or not policy.get("reviewer") or not retrieval.get("gold")
            or policy.get("dataset_sha256") != retrieval.get("dataset_sha256")
            or not any(policy.get("retrieval_floors", {}).values()) or not any(policy.get("answer_floors", {}).values())):
        raise ValueError("An approved quality policy for this gold dataset is required")
    failures = []
    for thresholds, measurements in ((policy["retrieval_floors"], retrieval["summary"]["overall"]),
                                     (policy["answer_floors"], answers)):
        for group, metrics in thresholds.items():
            for metric, minimum in metrics.items():
                actual = measurements.get(group, {}).get(metric)
                if type(minimum) not in {int, float} or not 0 <= minimum <= 1:
                    raise ValueError(f"Invalid approved floor for {group}.{metric}")
                if type(actual) not in {int, float} or not math.isfinite(actual) or actual < minimum:
                    failures.append(f"{group}.{metric}: {actual} below approved floor {minimum}")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("policy", "retrieval", "answers"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    failures = validate(*(json.loads(path.read_text(encoding="utf-8")) for path in (args.policy, args.retrieval, args.answers)))
    if failures:
        raise SystemExit("\n".join(failures))
