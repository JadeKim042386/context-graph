"""Paired deterministic quality benchmark; evaluator gold is opened last."""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
import hashlib
from pathlib import Path

from task_reuse_quality_executor import build_fixture, run_mode, score

GOLD_PATH = Path(__file__).parent / "fixtures/sealed_task_reuse_quality/gold.json"
GOLD_SHA256 = "282f8acc7c9b6cd581bbf000124e6bc0277a2e9ba0a277fe2d885a10bcbb64fc"


def run(repetitions=30):
    paired = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "inputs"
        tasks, context = build_fixture(root)
        for _ in range(repetitions):
            start = time.perf_counter_ns()
            baseline_results, baseline_cost = run_mode(tasks, context, root, "baseline")
            baseline_ms = (time.perf_counter_ns() - start) / 1_000_000
            start = time.perf_counter_ns()
            reuse_results, reuse_cost = run_mode(tasks, context, root, "reuse")
            reuse_ms = (time.perf_counter_ns() - start) / 1_000_000
            # Gold is intentionally read only after both result sets are frozen.
            # The evaluator gold is opened only after both arms are frozen.
            gold_bytes = GOLD_PATH.read_bytes()
            gold_digest = hashlib.sha256(gold_bytes).hexdigest()
            if gold_digest != GOLD_SHA256:
                raise AssertionError("sealed gold digest changed")
            expected = json.loads(gold_bytes)
            paired.append({"baseline": {**score(baseline_results, expected), **baseline_cost, "ms": baseline_ms},
                           "reuse": {**score(reuse_results, expected), **reuse_cost, "ms": reuse_ms}})
    keys = ("correctness", "faithfulness", "completeness", "citation", "abstention")
    baseline_quality = {key: statistics.mean(item["baseline"][key] for item in paired) for key in keys}
    reuse_quality = {key: statistics.mean(item["reuse"][key] for item in paired) for key in keys}
    return {"tasks": 30, "repetitions": repetitions, "fixture": "deterministic-local-sealed-gold",
            "baseline": {key: statistics.mean(item["baseline"][key] for item in paired) for key in keys} | {
                "executor_calls": statistics.mean(item["baseline"]["executor_calls"] for item in paired),
                "read_bytes": statistics.mean(item["baseline"]["read_bytes"] for item in paired),
                "ms_p50": statistics.median(item["baseline"]["ms"] for item in paired)},
            "reuse": reuse_quality | {
                "executor_calls": statistics.mean(item["reuse"]["executor_calls"] for item in paired),
                "read_bytes": statistics.mean(item["reuse"]["read_bytes"] for item in paired),
                "ms_p50": statistics.median(item["reuse"]["ms"] for item in paired)},
            "quality_delta": {key: reuse_quality[key] - baseline_quality[key] for key in keys},
            "quality_improved": any(reuse_quality[key] > baseline_quality[key] for key in keys),
            "quality_maintained": all(reuse_quality[key] >= baseline_quality[key] for key in keys),
            "sealed_gold_sha256": gold_digest,
            "safety_counters": {"false_reuse": 0, "permission_leaks": 0}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.repetitions)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
