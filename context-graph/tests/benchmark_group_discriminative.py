import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time


def run_case(root, selector, question):
    command = [sys.executable, "-B", "context-graph/scripts/ask.py",
               "--project-root", root, "--selector", selector, question]
    started = time.perf_counter()
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    elapsed = (time.perf_counter() - started) * 1000
    output = result.stdout
    return {
        "returncode": result.returncode,
        "bytes": len(output.encode("utf-8")),
        "nodes": output.count("NODE "),
        "locators": len(re.findall(r"\[src=.*? loc=.*?\]", output)),
        "elapsed_ms": elapsed,
        "output": output,
    }


def locator_pass(output, requirements):
    blocks = []
    current = None
    for line in output.splitlines():
        if line.startswith("NODE "):
            current = line[5:]
        match = re.match(r"\s+\[src=(.*?) loc=(\d+)", line)
        if match and current is not None:
            blocks.append((match.group(1), int(match.group(2)), current.lower()))
    checks = []
    for requirement in requirements:
        source = requirement["source_suffix"]
        line = requirement["line"]
        atoms = [atom.lower() for atom in requirement["atoms"]]
        checks.append(any(path.endswith(source) and locator == line and
                         all(atom in label for atom in atoms)
                         for path, locator, label in blocks))
    return sum(checks) / len(checks) if checks else 1.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--locator-gold", required=False)
    args = parser.parse_args()
    with open(args.questions, encoding="utf-8") as handle:
        questions = json.load(handle)
    with open(args.gold, encoding="utf-8") as handle:
        gold = json.load(handle)
    locator_gold = {}
    if args.locator_gold:
        with open(args.locator_gold, encoding="utf-8") as handle:
            locator_gold = json.load(handle)
    rows = []
    for item in questions:
        legacy = run_case(args.root, "legacy", item["question"])
        grouped = run_case(args.root, "group-v1", item["question"])
        cost_aware = run_case(args.root, "group-v2", item["question"])
        required = [anchor.lower() for anchor in gold[item["id"]]]
        rows.append({
            "id": item["id"],
            "class": item["class"],
            "question": item["question"],
            "legacy": {key: value for key, value in legacy.items() if key != "output"},
            "group_v1": {key: value for key, value in grouped.items() if key != "output"},
            "group_v2": {key: value for key, value in cost_aware.items() if key != "output"},
            "gold_anchor_recall": {
                "legacy": sum(anchor in legacy["output"].lower() for anchor in required) / len(required),
                "group_v1": sum(anchor in grouped["output"].lower() for anchor in required) / len(required),
                "group_v2": sum(anchor in cost_aware["output"].lower() for anchor in required) / len(required),
            },
            "locator_gold_pass": {
                "legacy": locator_pass(legacy["output"], locator_gold.get(item["id"], [])),
                "group_v1": locator_pass(grouped["output"], locator_gold.get(item["id"], [])),
                "group_v2": locator_pass(cost_aware["output"], locator_gold.get(item["id"], [])),
            },
        })
    print(json.dumps({
        "question_count": len(rows),
        "external_requests": 0,
        "mean_bytes": {
            "legacy": statistics.mean(row["legacy"]["bytes"] for row in rows),
            "group_v1": statistics.mean(row["group_v1"]["bytes"] for row in rows),
            "group_v2": statistics.mean(row["group_v2"]["bytes"] for row in rows),
        },
        "mean_elapsed_ms": {
            "legacy": statistics.mean(row["legacy"]["elapsed_ms"] for row in rows),
            "group_v1": statistics.mean(row["group_v1"]["elapsed_ms"] for row in rows),
            "group_v2": statistics.mean(row["group_v2"]["elapsed_ms"] for row in rows),
        },
        "rows": rows,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
