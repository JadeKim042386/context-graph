"""Counterbalanced end-to-end benchmark for held-out legacy versus group-v2."""

import argparse
import hashlib
import itertools
import json
import statistics
import subprocess
import time
from pathlib import Path


def locator_pass(output, requirements):
    blocks = {}
    label = None
    for line in output.splitlines():
        if line.startswith("NODE "):
            label = line[5:]
        if label is not None and line.startswith("     [src="):
            source, location = line[11:-1].rsplit(" loc=", 1)
            key = (source, int(location))
            blocks[key] = f"{blocks.get(key, '')}\n{label.lower()}"
    checks = []
    for requirement in requirements:
        checks.append(any(
            path.endswith(requirement["source_suffix"]) and location == requirement["line"] and
            all(atom.lower() in text for atom in requirement["atoms"])
            for (path, location), text in blocks.items()
        ))
    return sum(checks) / len(checks) if checks else 1.0


def run_case(root, selector, question):
    started = time.perf_counter_ns()
    result = subprocess.run(
        ["/Users/joo/miniconda3/bin/python", "-B", "context-graph/scripts/ask.py",
         "--project-root", str(root), "--selector", selector, question],
        cwd=root, capture_output=True, text=True,
    )
    elapsed = (time.perf_counter_ns() - started) / 1_000_000
    output = result.stdout
    return {
        "returncode": result.returncode,
        "elapsed_ms": elapsed,
        "bytes": len(output.encode("utf-8")),
        "chars": len(output),
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "output": output,
        "locator_gold_pass": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--locator-gold", required=True)
    parser.add_argument("--unavailable", default="")
    parser.add_argument("--rounds", type=int, default=30)
    args = parser.parse_args()
    root = Path(args.root)
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    locator_gold = json.loads(Path(args.locator_gold).read_text(encoding="utf-8"))
    unavailable = {item for item in args.unavailable.split(",") if item}
    selectors = ("legacy", "group-v2")
    fixed_index_by_id = {item["id"]: index for index, item in enumerate(questions)}
    trials = []
    # One excluded balanced warmup pair per question.
    for index, item in enumerate(questions):
        order = selectors if index % 2 == 0 else tuple(reversed(selectors))
        for selector in order:
            run_case(root, selector, item["question"])
    for round_number in range(args.rounds):
        ordered_questions = questions if round_number % 2 == 0 else list(reversed(questions))
        for _display_index, item in enumerate(ordered_questions):
            fixed_index = fixed_index_by_id[item["id"]]
            order = selectors if (round_number + fixed_index) % 2 == 0 else tuple(reversed(selectors))
            for position, selector in enumerate(order):
                result = run_case(root, selector, item["question"])
                result.update({
                    "round": round_number,
                    "question_id": item["id"],
                    "question_index": fixed_index,
                    "selector": selector,
                    "position": position,
                    "upstream_available": item["id"] not in unavailable,
                    "question_sha256": hashlib.sha256(item["question"].encode("utf-8")).hexdigest(),
                })
                result["locator_gold_pass"] = locator_pass(
                    result.pop("output"), locator_gold.get(item["id"], []))
                trials.append(result)
    by_selector = {}
    for selector in selectors:
        selected = [row for row in trials if row["selector"] == selector]
        by_selector[selector] = {
            "runs": len(selected),
            "mean_bytes": statistics.mean(row["bytes"] for row in selected),
            "median_bytes": statistics.median(row["bytes"] for row in selected),
            "mean_elapsed_ms": statistics.mean(row["elapsed_ms"] for row in selected),
            "median_elapsed_ms": statistics.median(row["elapsed_ms"] for row in selected),
            "locator_gold_pass": statistics.mean(row["locator_gold_pass"] for row in selected),
            "nonzero": sum(row["returncode"] != 0 for row in selected),
        }
    first_position_counts = {
        item["id"]: {
            selector: sum(
                row["position"] == 0
                for row in trials
                if row["question_id"] == item["id"] and row["selector"] == selector
            )
            for selector in selectors
        }
        for item in questions
    }
    print(json.dumps({
        "question_count": len(questions),
        "rounds": args.rounds,
        "runs_per_selector": len(trials) // len(selectors),
        "unavailable_upstream": sorted(unavailable),
        "summary": by_selector,
        "first_position_counts": first_position_counts,
        "trials": trials,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
