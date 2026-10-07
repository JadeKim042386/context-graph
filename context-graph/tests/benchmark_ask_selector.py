import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from ask import select_answer_items


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def load_cases(path):
    with open(path, encoding="utf-8") as handle:
        definitions = json.load(handle)
    cases = []
    for definition in definitions:
        for variant in range(6):
            cases.append([
                {
                    "label": (definition["label_prefix"] + str(variant) + ":" + str(index) + " " +
                              ("detail " * definition["repeat"])),
                    "source_file": f"knowledge/{definition['kind']}-{variant}-{index}.html",
                    "source_location": 40 + index,
                    "evidence_status": "unverified",
                }
                for index in range(6)
            ])
    return cases


def run(cases, budgets, warmup, repeats):
    rows = []
    for budget in budgets:
        for selector in ("legacy", "pointer-v1"):
            sizes, latencies, omitted, pointers = [], [], [], []
            for candidates in cases:
                for _ in range(warmup):
                    select_answer_items(candidates, budget, selector)
                timings = []
                result = None
                for _ in range(repeats):
                    started = time.perf_counter_ns()
                    result = select_answer_items(candidates, budget, selector)
                    timings.append((time.perf_counter_ns() - started) / 1_000_000)
                encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                sizes.append(len(encoded.encode("utf-8")))
                latencies.extend(timings)
                omitted.append(result["omitted_count"])
                pointers.append(sum(item["action"] == "pointer-only" for item in result["items"]))
            rows.append({
                "budget": budget,
                "selector": selector,
                "cases": len(cases),
                "mean_bytes": statistics.mean(sizes),
                "p50_ms": percentile(latencies, 0.50),
                "p95_ms": percentile(latencies, 0.95),
                "mean_omitted": statistics.mean(omitted),
                "pointer_items": sum(pointers),
                "external_requests": 0,
            })
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--budgets", default="256,1024,4096,8000")
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=200)
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    with open(args.gold, encoding="utf-8") as handle:
        gold = json.load(handle)
    assert len(cases) == gold["case_count"] * gold["variants_per_case"]
    rows = run(cases, [int(value) for value in args.budgets.split(",")], args.warmup, args.repeats)
    by_budget = {}
    for row in rows:
        by_budget.setdefault(row["budget"], {})[row["selector"]] = row
    for budget, pair in by_budget.items():
        baseline = pair["legacy"]["mean_bytes"]
        pair["pointer-v1"]["reduction_ratio"] = ((baseline - pair["pointer-v1"]["mean_bytes"]) / baseline
                                                    if baseline else 0.0)
    print(json.dumps({"cases": len(cases), "rows": rows, "external_requests": 0,
                      "gold": "sealed-sidecar-read-only"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
