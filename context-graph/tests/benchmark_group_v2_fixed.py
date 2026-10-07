"""Fixed-input selector benchmark for legacy, group-v1, and group-v2."""

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

from graphify import serve

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))
from ask import (WALK_TOKEN_BUDGET, asked_words, condense_answer,
                 document_labels, load_project_config,
                 statements_carrying_the_words)


SELECTORS = ("legacy", "group-v1", "group-v2")


def percentile(values, value):
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * value)))
    return ordered[index]


def parse_locator_blocks(output):
    blocks = []
    label = None
    for line in output.splitlines():
        if line.startswith("NODE "):
            label = line[5:]
        if label is not None and line.startswith("     [src="):
            source, location = line[11:-1].rsplit(" loc=", 1)
            blocks.append((source, int(location), label.lower()))
    return blocks


def locator_pass(output, requirements):
    blocks = parse_locator_blocks(output)
    checks = []
    for requirement in requirements:
        source = requirement["source_suffix"]
        line = requirement["line"]
        atoms = [atom.lower() for atom in requirement["atoms"]]
        checks.append(any(path.endswith(source) and location == line and
                         all(atom in label for atom in atoms)
                         for path, location, label in blocks))
    return sum(checks) / len(checks) if checks else 1.0


def run(root, questions, gold, locator_gold, repeats, warmups):
    config, _binding, _resolved, graph = load_project_config(root, None)
    map_path = config["map_path"]
    graph_object = serve._load_graph(map_path)
    named = document_labels(map_path)
    rows = []
    for item in questions:
        question = item["question"]
        raw = serve._query_graph_text(
            graph_object,
            question,
            mode="bfs",
            depth=3,
            token_budget=max(WALK_TOKEN_BUDGET, config["answer_budget"]),
        )
        direct = statements_carrying_the_words(map_path, asked_words(question),
                                                nodes=graph["nodes"])
        required = [anchor.lower() for anchor in gold[item["id"]]]
        outputs = {}
        timings = {}
        for selector in SELECTORS:
            for _ in range(warmups):
                condense_answer(raw, config["answer_budget"], question, direct, named, selector)
            samples = []
            output = ""
            for _ in range(repeats):
                started = time.perf_counter()
                output = condense_answer(raw, config["answer_budget"], question, direct,
                                         named, selector)
                samples.append((time.perf_counter() - started) * 1000)
            outputs[selector] = output
            timings[selector] = {
                "mean_ms": statistics.mean(samples),
                "p50_ms": percentile(samples, 0.50),
                "p95_ms": percentile(samples, 0.95),
            }
        rows.append({
            "id": item["id"],
            "class": item["class"],
            "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "raw_chars": len(raw),
            "metrics": {
                selector: {
                    "bytes": len(outputs[selector].encode("utf-8")),
                    "chars": len(outputs[selector]),
                    "anchor_recall": sum(anchor in outputs[selector].lower()
                                          for anchor in required) / len(required),
                    "locator_gold_pass": locator_pass(
                        outputs[selector], locator_gold.get(item["id"], [])),
                    **timings[selector],
                }
                for selector in SELECTORS
            },
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--locator-gold", required=True)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=5)
    args = parser.parse_args()
    root = Path(args.root)
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    locator_gold = json.loads(Path(args.locator_gold).read_text(encoding="utf-8"))
    rows = run(root, questions, gold, locator_gold, args.repeats, args.warmups)
    print(json.dumps({
        "question_count": len(rows),
        "repeats": args.repeats,
        "warmups": args.warmups,
        "raw_input_count": len({row["raw_sha256"] for row in rows}),
        "mean": {
            selector: {
                "bytes": statistics.mean(row["metrics"][selector]["bytes"] for row in rows),
                "chars": statistics.mean(row["metrics"][selector]["chars"] for row in rows),
                "anchor_recall": statistics.mean(row["metrics"][selector]["anchor_recall"] for row in rows),
                "locator_gold_pass": statistics.mean(row["metrics"][selector]["locator_gold_pass"] for row in rows),
                "mean_ms": statistics.mean(row["metrics"][selector]["mean_ms"] for row in rows),
                "p50_ms": statistics.mean(row["metrics"][selector]["p50_ms"] for row in rows),
                "p95_ms": statistics.mean(row["metrics"][selector]["p95_ms"] for row in rows),
            }
            for selector in SELECTORS
        },
        "rows": rows,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
