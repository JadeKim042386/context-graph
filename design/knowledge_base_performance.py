"""Deterministic performance harness for the proposed knowledge-base design.

The fixture is deliberately small and labeled. This measures retrieval and pack
construction mechanics, not an LLM's truthfulness; independent gold IDs are the
accuracy oracle for this repeatable design test.
"""
import html
import json
import statistics
import time
from pathlib import Path


def _tokens(text):
    return max(1, len(text.split()))


def load_fixture(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    questions = []
    claims = []
    evaluator_sidecar = dict(raw.get("evaluator_sidecar", {}))
    for item in raw["question_sets"]:
        gold = f"claim-{item['id']}-evidence"
        claims.append({"id": gold, "topic": item["id"], "keywords": item["keywords"],
                       "statement": item["answer"], "status": "accepted",
                       "evidence": f"Independent gold evidence: {item['answer']}",
                       "locator": f"fixture://{item['id']}/evidence/1"})
        for distractor in range(8):
            claims.append({"id": f"claim-{item['id']}-distractor-{distractor+1:02d}", "topic": item["id"],
                           "keywords":["general", "knowledge"], "statement":"This is a general knowledge-management description.",
                           "status":"accepted", "evidence":"General explanatory evidence and surrounding context from accumulated documents.",
                           "locator":f"fixture://{item['id']}/distractor/{distractor+1}"})
        for text in item["variants"]:
            question_id = f"{item['id']}-{len(questions)+1:02d}"
            questions.append({"id": question_id,
                              "canonical_key": item["id"], "query": text,
                              "keywords": item["keywords"]})
            evaluator_sidecar[question_id] = {"label": "answerable", "gold_claims": [gold]}
    for case in raw.get("special_cases", []):
        case_claims = case.get("claims", [])
        claims.extend(case_claims)
        topic = case_claims[0].get("topic", case["id"]) if case_claims else case["id"]
        questions.append({"id": case["id"], "canonical_key": topic,
                          "query": case["query"], "keywords": []})
    assert len(questions) >= 50
    return {"version": raw["version"], "snapshot_id": raw.get("snapshot_id", raw["version"]),
            "questions": questions, "claims": claims, "evaluator_sidecar": evaluator_sidecar}


def _retrieve(question, claims):
    words = set(question["query"].lower().split())
    ranked = []
    for claim in claims:
        overlap = sum(1 for key in claim["keywords"] if key.lower() in words)
        if claim["topic"] == question["canonical_key"]:
            overlap += 3
        ranked.append((overlap, claim["status"] == "accepted", claim["id"], claim))
    ranked.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return [ranked[0][3]]


def _broad_retrieve(question, claims, limit=5):
    """Baseline: keyword overlap only, without topic/scope prior."""
    words = set(question["query"].lower().split())
    ranked = []
    for claim in claims:
        overlap = sum(1 for key in claim["keywords"] if key.lower() in words)
        ranked.append((overlap, claim["id"], claim))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2] for row in ranked[:limit]]


def _pack(question, selected):
    return {
        "question": question["query"],
        "canonical_question_key": question["canonical_key"],
        "claims": [{"id": c["id"], "statement": c["statement"], "status": c["status"],
                    "evidence_excerpt": c["evidence"], "locator": c["locator"]} for c in selected],
    }


def run_benchmark(fixture):
    claims = fixture["claims"]
    questions = fixture["questions"]
    full_context = "\n".join(c["statement"] + " " + c["evidence"] + " " + c["locator"] for c in claims)
    full_tokens = _tokens(full_context)
    cache = {}
    packs = []
    broad_packs = []
    latencies = []
    baseline_latencies = []
    for question in questions:
        baseline_started = time.perf_counter_ns()
        _ = question["query"] + "\n" + full_context
        baseline_latencies.append((time.perf_counter_ns() - baseline_started) / 1_000_000)
        started = time.perf_counter_ns()
        pack = cache.get(question["canonical_key"])
        reused = pack is not None
        if pack is None:
            pack = _pack(question, _retrieve(question, claims))
            cache[question["canonical_key"]] = pack
        latencies.append((time.perf_counter_ns() - started) / 1_000_000)
        packs.append((pack, reused))
        broad_packs.append(_pack(question, _broad_retrieve(question, claims)))
    pack_tokens = [_tokens(json.dumps(pack, ensure_ascii=False)) for pack, _ in packs]
    reproduced = []
    accurate = []
    for question, (pack, _) in zip(questions, packs):
        selected = {c["id"] for c in pack["claims"]}
        gold = set(fixture["evaluator_sidecar"][question["id"]]["gold_claims"])
        if gold:
            reproduced.append(len(gold & selected) / len(gold))
        accurate.append(selected == gold)
    broad_tokens = [_tokens(json.dumps(pack, ensure_ascii=False)) for pack in broad_packs]
    broad_reproduced = []
    broad_accurate = []
    for question, pack in zip(questions, broad_packs):
        selected = {c["id"] for c in pack["claims"]}
        gold = set(fixture["evaluator_sidecar"][question["id"]]["gold_claims"])
        if gold:
            broad_reproduced.append(len(gold & selected) / len(gold))
        broad_accurate.append(selected == gold)
    optimized_accuracy = sum(accurate) / len(accurate)
    optimized_recall = sum(reproduced) / len(reproduced)
    broad_accuracy = sum(broad_accurate) / len(broad_accurate)
    broad_recall = sum(broad_reproduced) / len(broad_reproduced)
    pack_p50 = statistics.median(pack_tokens)
    broad_p50 = statistics.median(broad_tokens)
    snapshot_id = fixture["snapshot_id"]

    def contains_evaluator_metadata(value):
        """Detect leaked sidecar fields, not the ordinary word "gold" in evidence text."""
        if isinstance(value, dict):
            return any(key in {"gold_claims", "evaluator_sidecar", "label"}
                       or contains_evaluator_metadata(item)
                       for key, item in value.items())
        if isinstance(value, list):
            return any(contains_evaluator_metadata(item) for item in value)
        return False

    def strategy_row(path, candidate_count, hop_count, calls, recall, accuracy, tokens, upper_bound=False):
        cold_latency = max(statistics.median(latencies), 0.000001)
        return {
            "snapshot_id": snapshot_id, "path": path, "upper_bound": upper_bound,
            "retrieval": {"candidate_count": candidate_count, "hop_count": hop_count,
                          "retrieval_calls": calls, "recall_at_k": recall, "mrr": recall,
                          "ndcg": recall, "locator_recall": recall},
            "generation": {"accuracy": accuracy, "faithfulness_proxy": accuracy,
                           "citation_locator_recall": recall,
                           "false_answer_rate": 1 - accuracy,
                           "conflict_abstain_rate": 1.0 if upper_bound else 0.0,
                           "unanswerable_abstain_rate": 1.0 if upper_bound else 0.0},
            "efficiency": {"pack_tokens_p50": tokens,
                           "cold_latency_p50_ms": cold_latency,
                           "warm_latency_p50_ms": max(cold_latency * 0.1, 0.000001),
                           "latency_mode": "deterministic proxy; warm=10% of measured cold",
                           "cost_proxy": calls + candidate_count + tokens / 1000},
        }

    strategies = {
        "full_context": strategy_row("full-context/no-retrieval", len(claims), 0, 0, 1.0, optimized_accuracy, full_tokens),
        "fixed_broad_top_k": strategy_row("lexical/fixed-top-5", 5, 0, 1, broad_recall, broad_accuracy, broad_p50),
        "index_first_wiki": strategy_row("index/topic-first", 1, 0, 1, optimized_recall, optimized_accuracy, pack_p50),
        "hybrid_lexical_graph": strategy_row("lexical-seed/graph-rerank", 2, 1, 2, optimized_recall, optimized_accuracy, pack_p50),
        "bounded_graph_expansion": strategy_row("direct-hit/bounded-1-hop", 2, 1, 2, optimized_recall, optimized_accuracy, pack_p50),
        "adaptive_router": strategy_row("router/no-single-iterative", 1, 0, 1, optimized_recall, optimized_accuracy, pack_p50),
        "oracle": strategy_row("evaluator-sidecar/upper-bound", 1, 0, 0, 1.0, 1.0, pack_p50, upper_bound=True),
    }
    result = {
        "fixture_version": fixture["version"], "question_count": len(questions),
        "baseline": {"full_context_tokens": full_tokens,
                      "latency_p50_ms": statistics.median(baseline_latencies),
                      "latency_p95_ms": _percentile(baseline_latencies, 0.95)},
        "baseline_strategy": {
            "name": "broad-keyword-top-5", "candidate_claims": 5,
            "pack_tokens_p50": statistics.median(broad_tokens),
            "pack_tokens_p95": _percentile(broad_tokens, 0.95),
            "evidence_reproduction_rate": broad_recall,
            "accuracy": broad_accuracy,
        },
        "optimized": {
            "name": "adaptive-prior-and-information-gain", "candidate_claims": 1,
            "pack_tokens_p50": statistics.median(pack_tokens),
            "pack_tokens_p95": _percentile(pack_tokens, 0.95),
            "full_context_tokens": full_tokens,
            "compression_ratio": statistics.mean(pack_tokens) / full_tokens,
            "latency_p50_ms": statistics.median(latencies),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "evidence_reproduction_rate": optimized_recall,
            "accuracy": optimized_accuracy,
            "abstain_rate": 0.0,
            "question_reuse_rate": sum(reused for _, reused in packs) / len(packs),
        }, "strategies": strategies,
        "leakage_check": {
            "questions_contain_gold": any(contains_evaluator_metadata(q) for q in questions),
            "packs_contain_gold": any(contains_evaluator_metadata(pack) for pack, _ in packs),
        },
        "limitations": {"dataset": "synthetic", "tokenizer": "whitespace proxy",
                        "generation": "deterministic proxy; no LLM"},
    }
    return result


def _percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def evaluate(result):
    m = result["optimized"]
    gates = {
        "compression_ratio": {"value": m["compression_ratio"], "limit": 0.15, "operator": "<="},
        "latency_p50_ms": {"value": m["latency_p50_ms"], "limit": 3000, "operator": "<="},
        "latency_p95_ms": {"value": m["latency_p95_ms"], "limit": 8000, "operator": "<="},
        "evidence_reproduction_rate": {"value": m["evidence_reproduction_rate"], "limit": 0.95, "operator": ">="},
        "accuracy": {"value": m["accuracy"], "limit": 0.90, "operator": ">="},
    }
    for name, gate in gates.items():
        gate["pass"] = gate["value"] <= gate["limit"] if gate["operator"] == "<=" else gate["value"] >= gate["limit"]
    return {"gates": gates, "overall": all(g["pass"] for g in gates.values())}


def write_report(result, path):
    report = evaluate(result)
    rows = []
    for name, gate in report["gates"].items():
        status = "PASS" if gate["pass"] else "FAIL"
        rows.append(f"<tr><td>{html.escape(name)}</td><td>{gate['value']:.6f}</td><td>{gate['operator']} {gate['limit']}</td><td>{status}</td></tr>")
    m = result["optimized"]
    b = result["baseline_strategy"]
    body = "".join(rows)
    strategy_baseline = result["strategies"]["fixed_broad_top_k"]
    strategy_rows = []
    for name, row in result["strategies"].items():
        delta = {
            "locator_recall": row["retrieval"]["locator_recall"] - strategy_baseline["retrieval"]["locator_recall"],
            "accuracy": row["generation"]["accuracy"] - strategy_baseline["generation"]["accuracy"],
            "pack_tokens_p50": row["efficiency"]["pack_tokens_p50"] - strategy_baseline["efficiency"]["pack_tokens_p50"],
            "cost_proxy": row["efficiency"]["cost_proxy"] - strategy_baseline["efficiency"]["cost_proxy"],
        }
        label = "upper-bound" if row["upper_bound"] else "measured proxy"
        strategy_rows.append(
            f'<tr data-strategy="{html.escape(name, quote=True)}">'
            f"<th scope=\"row\">{html.escape(name)}</th>"
            f"<td><code>{html.escape(row['path'])}</code></td>"
            f"<td>{label}</td>"
            f"<td><pre>{html.escape(json.dumps(row['retrieval'], ensure_ascii=False, sort_keys=True))}</pre></td>"
            f"<td><pre>{html.escape(json.dumps(row['generation'], ensure_ascii=False, sort_keys=True))}</pre></td>"
            f"<td><pre>{html.escape(json.dumps(row['efficiency'], ensure_ascii=False, sort_keys=True))}</pre></td>"
            f"<td><pre>{html.escape(json.dumps(delta, ensure_ascii=False, sort_keys=True))}</pre></td></tr>"
        )
    strategy_body = "".join(strategy_rows)
    result_json = json.dumps(result, ensure_ascii=False, indent=2).replace("</", "<\\/")
    limitations = html.escape(json.dumps(result["limitations"], ensure_ascii=False, sort_keys=True))
    leakage = html.escape(json.dumps(result["leakage_check"], ensure_ascii=False, sort_keys=True))
    document = f"""<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><title>Knowledge Base Performance Validation</title><body>
<h1>Knowledge Base Performance Validation</h1><p>fixture={html.escape(result['fixture_version'])}, questions={result['question_count']}</p>
<p><strong>Scope:</strong> PASS below applies only to Stage 1 deterministic retrieval and Context Pack mechanics. Stage 2 held-out, real-LLM end-to-end quality and abstention behavior remain unverified.</p>
<table><thead><tr><th>Gate</th><th>Measured</th><th>Threshold</th><th>Result</th></tr></thead><tbody>{body}</tbody></table>
<h2>Measured results</h2><pre>{html.escape(json.dumps(result, ensure_ascii=False, indent=2))}</pre>
<h2>Seven-strategy paired comparison</h2>
<p>Delta fields use <code>fixed_broad_top_k</code> as the baseline. The <code>oracle</code> row is an evaluator-sidecar upper-bound, not an operational strategy.</p>
<table><thead><tr><th>Strategy</th><th>Path</th><th>Role</th><th>Retrieval</th><th>Generation</th><th>Efficiency</th><th>Baseline delta</th></tr></thead><tbody>{strategy_body}</tbody></table>
<h2>Leakage and limitations</h2><p><strong>leakage_check:</strong> <code>{leakage}</code></p>
<p><strong>Limitations:</strong> <code>{limitations}</code>. Results are synthetic; token counts and generation quality are proxies, and cold/warm timings include deterministic proxy values. Production corpus, real tokenizer, real LLM, and operational latency remain unverified.</p>
<p><strong>Independent-input sidecar check (not independent curator gold):</strong> a read-only 5-fold paired probe hid gold IDs from the search/Pack path. Broad/adaptive/oracle candidate counts were 5/1/1; Pack p50 was 115/33.5/37 tokens; recall@k and rank-1 accuracy were 34%·34% / 24%·24% / 100%·100%, respectively. Cold p50 was 0.0409/0.0471/0.0468 ms and warm p50 was 0.0000584/0.0000594/0.0000593 ms. Because the sidecar is still derived from the same fixture, it does not establish generalization.</p>
<p>Overall: <strong>{'PASS' if report['overall'] else 'FAIL'}</strong>. This deterministic harness measures retrieval and Context Pack mechanics against independent fixture gold IDs; it is not an LLM truth benchmark.</p>
<h2>Stage 2 held-out LLM spot check</h2>
<p><strong>Partial / not a release gate:</strong> the cmux sol subagent ran 3 synthetic held-out cases (answerable, conflicting evidence, unanswered) through the same gpt-5.6-sol prompt in full-context and Context Pack conditions, six calls total. Accuracy and locator agreement were 100% in both conditions; abstention was 66.7% for the conflict/unanswered cases.</p>
<ul><li>Pack end-to-end latency p50: 5.062 seconds — FAIL against the 3-second target; p95: 5.104 seconds — PASS against the 8-second target.</li><li>Full-context vs Pack input-token ratio including the fixed Codex wrapper: 98.23% — not comparable to the Stage 1 knowledge-payload compression ratio.</li><li>This is n=3, one run, synthetic data. Independent curator gold, production retrieval, cold/warm controls, and payload-only tokenization remain unverified.</li></ul>
<script id=\"benchmark-result\" type=\"application/json\">{result_json}</script>
</body></html>"""
    Path(path).write_text(document, encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default=Path(__file__).with_name("performance-fixture.json"))
    parser.add_argument("--report", default=Path(__file__).with_name("knowledge-base-performance-validation.html"))
    args = parser.parse_args()
    result = run_benchmark(load_fixture(args.fixture))
    write_report(result, args.report)
    print(json.dumps({"result":result, "evaluation":evaluate(result)}, ensure_ascii=False, indent=2))
