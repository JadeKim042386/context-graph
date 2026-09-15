"""Paired synthetic comparison of four knowledge retrieval strategies.

The evaluator sidecar is read only after retrieval and answer simulation. Token
counts, answer quality, and cost are deterministic proxies; wall-clock latency
is a local measurement and is not an operational service-level result.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from knowledge_base_performance import load_fixture


STRATEGY_ORDER = (
    "A_full_context",
    "B_fixed_lexical_top_k",
    "C_current_index_graph_pack",
    "D_compile_first_interlinked_wiki",
)
WORD_RE = re.compile(r"[0-9A-Za-z가-힣_]+")


def _tokens(value):
    return max(1, len(WORD_RE.findall(value)))


def _claim_text(claim):
    return json.dumps(
        {key: claim[key] for key in ("id", "statement", "evidence", "locator", "status")},
        ensure_ascii=False,
        sort_keys=True,
    )


def _score(question, claim, include_topic):
    query = question["query"].lower()
    overlap = sum(1 for keyword in claim.get("keywords", []) if keyword.lower() in query)
    topic_match = int(include_topic and claim.get("topic") == question.get("canonical_key"))
    base = overlap * 10 + topic_match * 3
    if base == 0:
        return 0.0
    specific = sum(keyword.lower() not in {"general", "knowledge"} for keyword in claim.get("keywords", []))
    return base + specific / 100


def _rank(question, claims, include_topic):
    rows = [(_score(question, claim, include_topic), claim["id"], claim) for claim in claims]
    rows.sort(key=lambda row: (-row[0], row[1]))
    return rows


def _pack(question, claims, extra=None):
    payload = {
        "question": question["query"],
        "claims": [
            {
                "id": claim["id"],
                "statement": claim["statement"],
                "evidence": claim["evidence"],
                "locator": claim["locator"],
            }
            for claim in claims
        ],
    }
    if extra:
        payload["navigation"] = extra
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _compile_indexes(claims):
    topic_index = defaultdict(list)
    for claim in claims:
        topic_index[claim["topic"]].append(claim)
    for values in topic_index.values():
        values.sort(key=lambda claim: claim["id"])

    topics = sorted(topic_index)
    wiki = {}
    for index, topic in enumerate(topics):
        values = topic_index[topic]
        tags = sorted({keyword for claim in values for keyword in claim.get("keywords", [])})
        links = []
        if len(topics) > 1:
            links = [topics[(index - 1) % len(topics)], topics[(index + 1) % len(topics)]]
            links = list(dict.fromkeys(link for link in links if link != topic))
        wiki[topic] = {
            "title": topic,
            "summary": values[0]["statement"],
            "tags": tags,
            "links": links,
            "claims": values,
        }
    return dict(topic_index), wiki


def _strategy_a(question, env):
    claims = env["claims"]
    return {"candidates": claims, "calls": 0, "context": _pack(question, claims)}


def _strategy_b(question, env):
    ranked = _rank(question, env["claims"], include_topic=False)
    selected = [row[2] for row in ranked[:5]]
    return {"candidates": selected, "calls": 1, "context": _pack(question, selected)}


def _strategy_c(question, env):
    direct = env["topic_index"].get(question.get("canonical_key"), [])
    ranked = _rank(question, direct or env["claims"], include_topic=True)
    selected = []
    if ranked and ranked[0][0] > 0:
        best = ranked[0][0]
        selected = [row[2] for row in ranked if row[0] == best]
    return {
        "candidates": selected,
        "calls": 2,
        "context": _pack(question, selected, {"path": "index lookup → one-hop relation check"}),
    }


def _strategy_d(question, env):
    page_rows = []
    query = question["query"].lower()
    for topic, page in env["wiki"].items():
        lexical = sum(1 for tag in page["tags"] if tag.lower() in query)
        score = lexical * 10 + int(topic == question.get("canonical_key")) * 3
        page_rows.append((score, topic, page))
    page_rows.sort(key=lambda row: (-row[0], row[1]))
    calls = 1  # search
    selected = []
    navigation = {"operation": "search-read-follow-links-sufficiency", "page": None, "followed": []}
    if page_rows and page_rows[0][0] > 0:
        page = page_rows[0][2]
        navigation["page"] = page["title"]
        calls += 1  # read
        ranked = _rank(question, page["claims"], include_topic=True)
        if ranked and ranked[0][0] > 0:
            best = ranked[0][0]
            selected = [row[2] for row in ranked if row[0] == best]
        navigation["followed"] = page["links"]
        calls += 1  # inspect links
    else:
        calls += 1  # read empty search result
    calls += 1  # sufficiency check
    return {"candidates": selected, "calls": calls, "context": _pack(question, selected, navigation)}


def _answer_proxy(question, candidates):
    ranked = _rank(question, candidates, include_topic=True)
    if not ranked or ranked[0][0] <= 0:
        return {"abstained": True, "citations": [], "answer_claim_id": None}
    best = ranked[0][0]
    tied = [row[2] for row in ranked if row[0] == best]
    if len(tied) > 1:
        return {"abstained": True, "citations": [claim["id"] for claim in tied], "answer_claim_id": None}
    return {"abstained": False, "citations": [tied[0]["id"]], "answer_claim_id": tied[0]["id"]}


def _percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index]


def _evaluate_strategy(name, function, fixture, env, repetitions):
    recalls = []
    reciprocal_ranks = []
    evidence_recalls = []
    locator_recalls = []
    correctness = []
    false_answers = []
    abstention_checks = []
    faithfulness = []
    input_tokens = []
    calls = []
    latency = []
    question_results = []

    for question in fixture["questions"]:
        first = None
        answer = None
        samples = []
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            current = function(question, env)
            current_answer = _answer_proxy(question, current["candidates"])
            samples.append(max((time.perf_counter_ns() - started) / 1_000_000, 0.000001))
            if first is None:
                first, answer = current, current_answer
        latency.extend(samples)
        sidecar = fixture["evaluator_sidecar"][question["id"]]
        label = sidecar["label"]
        gold = set(sidecar["gold_claims"])
        ids = [claim["id"] for claim in first["candidates"]]
        selected = set(ids)
        if gold:
            recalls.append(len(gold & selected) / len(gold))
            positions = [ids.index(item) + 1 for item in gold if item in selected]
            reciprocal_ranks.append(0.0 if not positions else 1 / min(positions))
            evidence_recalls.append(sum(1 for claim in first["candidates"] if claim["id"] in gold and claim.get("evidence")) / len(gold))
            locator_recalls.append(sum(1 for claim in first["candidates"] if claim["id"] in gold and claim.get("locator")) / len(gold))

        if label == "answerable":
            correct = not answer["abstained"] and answer["answer_claim_id"] in gold
        elif label == "conflict":
            correct = answer["abstained"] and gold.issubset(set(answer["citations"]))
        else:
            correct = answer["abstained"]
        correctness.append(correct)
        false_answers.append(not answer["abstained"] and not correct)
        if label in {"conflict", "unanswerable"}:
            abstention_checks.append(correct)
        if answer["citations"]:
            cited = set(answer["citations"])
            locators_ok = all(claim.get("locator") for claim in first["candidates"] if claim["id"] in cited)
            supported = cited <= selected and (cited <= gold if label == "answerable" else gold <= cited)
            faithfulness.append(locators_ok and supported)

        tokens = _tokens(first["context"])
        input_tokens.append(tokens)
        calls.append(first["calls"])
        question_results.append({
            "question_id": question["id"],
            "label": label,
            "candidate_ids": ids,
            "retrieval_calls": first["calls"],
            "input_tokens": tokens,
            "abstained": answer["abstained"],
            "citation_ids": answer["citations"],
            "correct": correct,
        })

    metrics = {
        "input_tokens_p50": statistics.median(input_tokens),
        "compression_ratio": 0.0,
        "retrieval_recall_at_k": statistics.mean(recalls),
        "mrr": statistics.mean(reciprocal_ranks),
        "evidence_recall": statistics.mean(evidence_recalls),
        "locator_recall": statistics.mean(locator_recalls),
        "answer_accuracy": statistics.mean(correctness),
        "citation_faithfulness": statistics.mean(faithfulness),
        "false_answer_rate": statistics.mean(false_answers),
        "abstention_correctness": statistics.mean(abstention_checks),
        "latency_p50_ms": statistics.median(latency),
        "latency_p95_ms": _percentile(latency, 0.95),
        "retrieval_calls_mean": statistics.mean(calls),
        "cost_proxy": statistics.mean(input_tokens) + 32 * statistics.mean(calls),
    }
    return {
        "snapshot_id": fixture["snapshot_id"],
        "path": {
            "A_full_context": "full-context/no-retrieval",
            "B_fixed_lexical_top_k": "lexical-search/fixed-top-5",
            "C_current_index_graph_pack": "topic-index/one-hop-relation/context-pack",
            "D_compile_first_interlinked_wiki": "compile-wiki/search/read/follow-links/sufficiency-check",
        }[name],
        "metrics": metrics,
        "question_results": question_results,
    }


def _rounded(value):
    return round(value, 6) if isinstance(value, float) else value


def run_comparison(fixture_path, repetitions=7):
    fixture = load_fixture(fixture_path)
    topic_index, wiki = _compile_indexes(fixture["claims"])
    env = {"claims": fixture["claims"], "topic_index": topic_index, "wiki": wiki}
    functions = {
        "A_full_context": _strategy_a,
        "B_fixed_lexical_top_k": _strategy_b,
        "C_current_index_graph_pack": _strategy_c,
        "D_compile_first_interlinked_wiki": _strategy_d,
    }
    strategies = {
        name: _evaluate_strategy(name, function, fixture, env, repetitions)
        for name, function in functions.items()
    }
    baseline_mean = statistics.mean(item["input_tokens"] for item in strategies["A_full_context"]["question_results"])
    for row in strategies.values():
        mean_tokens = statistics.mean(item["input_tokens"] for item in row["question_results"])
        row["metrics"]["compression_ratio"] = mean_tokens / baseline_mean
        row["metrics"] = {key: _rounded(value) for key, value in row["metrics"].items()}

    c = strategies["C_current_index_graph_pack"]["metrics"]
    d = strategies["D_compile_first_interlinked_wiki"]["metrics"]
    if d["answer_accuracy"] > c["answer_accuracy"]:
        supported = "Strategy D has higher answer accuracy than C, supporting a trial of linked-wiki navigation on operational samples."
    else:
        supported = "Strategy D does not show an accuracy advantage over C, so there is no basis to replace the current default path immediately."
    result = {
        "experiment_id": "kb-four-strategy-paired-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixture_version": fixture["version"],
        "snapshot_id": fixture["snapshot_id"],
        "question_count": len(fixture["questions"]),
        "repetitions": repetitions,
        "next_role": "main-dispatcher",
        "evaluation_scope": "synthetic deterministic retrieval and answer proxy; not production LLM quality",
        "tokenizer": "Unicode word-count proxy",
        "latency": "local wall-clock retrieval plus deterministic answer proxy",
        "cost_proxy_definition": "mean input word tokens + 32 × mean retrieval calls",
        "strategies": strategies,
        "leakage_check": {
            "sidecar_in_strategy_inputs": False,
            "gold_ids_in_context_packs": False,
        },
        "literature": [
            {
                "title": "Andrej Karpathy, LLM Wiki idea file",
                "url": "https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f",
                "evidence": "Proposes immutable source material, a continuously updated interconnected wiki, rule documents, index-first queries, and linting.",
                "local_result_status": "design inspiration only; no benchmark claim imported",
            },
            {
                "title": "Retrieval as Reasoning: Self-Evolving Agent-Native Retrieval via LLM-Wiki",
                "url": "https://arxiv.org/abs/2605.25480",
                "evidence": "Reports compiling documents into a linked wiki and performing search, read, link-following, and sufficiency judgments.",
                "local_result_status": "paper results are not reproduced by this fixture",
            },
        ],
        "recommendations": {
            "supported_by_local_result": [
                supported,
                "Compression ratio and call count must be considered against the full-context input volume.",
            ],
            "unsupported_hypotheses": [
                "This synthetic fixture is not real multi-document reasoning, so Strategy D's multi-hop advantage is not established.",
                "Actual LLM accuracy, citation faithfulness, cost, and service latency cannot be established by this deterministic proxy measure.",
            ],
            "next_production_validation": [
                "Stratify answerable, conflict, and unanswerable operational questions using reviewer gold kept separate from retrieval input.",
                "Run C and D in cross-order A/B trials with the same real-document benchmark set and prompt.",
                "Record the real tokenizer, LLM usage, cold/warm p50/p95, and evidence-location reproduction together.",
            ],
        },
    }
    return result


def write_artifacts(result, json_path, html_path):
    json_path = Path(json_path)
    html_path = Path(html_path)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = []
    for name, row in result["strategies"].items():
        metric = row["metrics"]
        rows.append(
            f'<tr data-strategy="{html.escape(name, quote=True)}"><th>{html.escape(name)}</th>'
            f'<td><code>{html.escape(row["path"])}</code></td>'
            + "".join(f"<td>{metric[key]:.6f}</td>" for key in (
                "input_tokens_p50", "compression_ratio", "retrieval_recall_at_k", "mrr",
                "evidence_recall", "locator_recall", "answer_accuracy", "citation_faithfulness",
                "false_answer_rate", "abstention_correctness", "latency_p50_ms", "latency_p95_ms",
                "retrieval_calls_mean", "cost_proxy",
            ))
            + "</tr>"
        )
    literature = "".join(
        f'<li><a href="{html.escape(item["url"], quote=True)}">{html.escape(item["title"])}</a>: '
        f'{html.escape(item["evidence"])} <strong>Local status:</strong> {html.escape(item["local_result_status"])}</li>'
        for item in result["literature"]
    )
    recommendations = result["recommendations"]
    embedded = json.dumps(result, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Knowledge Base Four-Strategy Comparison</title><style>body{{max-width:1500px;margin:auto;padding:2rem;font:15px/1.6 system-ui,sans-serif;color:#172033}}table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid #ccd6e0;padding:.45rem;text-align:right;vertical-align:top}}th:first-child,td:nth-child(2){{text-align:left}}thead th{{background:#eef5f7}}code{{white-space:nowrap}}.warn{{border-left:4px solid #b45309;background:#fff7ed;padding:1rem}}</style></head><body>
<h1>Knowledge Base Four-Strategy Reproduction Comparison</h1>
<p>The same benchmark <code>{html.escape(result["snapshot_id"])}</code>, {result["question_count"]} questions, evidence, and evaluation gold were paired across four strategies.</p>
<p class="warn"><strong>Interpretation limit:</strong> These results use a synthetic fixture, a word-count token proxy, and deterministic answer-proxy logic. They do not validate a real tokenizer, LLM, operational documents, or service latency, so they must not be interpreted as production performance.</p>
<h2>Comparison results</h2>
<table><thead><tr><th>Strategy</th><th>Execution path</th><th>Input tokens p50</th><th>Compression ratio</th><th>Retrieval recall</th><th>Mean reciprocal rank</th><th>Evidence recall</th><th>Locator recall</th><th>Answer accuracy</th><th>Citation faithfulness</th><th>False-answer rate</th><th>Abstention correctness</th><th>Latency p50 ms</th><th>Latency p95 ms</th><th>Retrieval calls</th><th>Cost proxy</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p>The cost proxy adds 32 per retrieval call to the mean input word count per question. Latency repeats only local retrieval and answer-proxy logic on this computer.</p>
<h2>Literature evidence versus local synthetic results</h2><ul>{literature}</ul>
<h2>Improvements supported by the results</h2><ul>{''.join(f'<li>{html.escape(value)}</li>' for value in recommendations["supported_by_local_result"])}</ul>
<h2>Hypotheses not yet supported</h2><ul>{''.join(f'<li>{html.escape(value)}</li>' for value in recommendations["unsupported_hypotheses"])}</ul>
<h2>Next production validation plan</h2><ol>{''.join(f'<li>{html.escape(value)}</li>' for value in recommendations["next_production_validation"])}</ol>
<p><strong>Next role: {html.escape(result["next_role"])}</strong></p>
<h2>Reproduction</h2><pre>python design/knowledge_base_comparative_experiment.py --repetitions {result["repetitions"]}
pytest -q design/test_knowledge_base_comparative_experiment.py</pre>
<script id="comparison-result" type="application/json">{embedded}</script>
</body></html>'''
    html_path.write_text(document, encoding="utf-8")


def main():
    base = Path(__file__).parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=base / "performance-fixture.json")
    parser.add_argument("--json", type=Path, default=base / "knowledge-base-comparative-results.json")
    parser.add_argument("--html", type=Path, default=base / "knowledge-base-comparative-report.html")
    parser.add_argument("--repetitions", type=int, default=11)
    args = parser.parse_args()
    result = run_comparison(args.fixture, repetitions=args.repetitions)
    write_artifacts(result, args.json, args.html)
    print(json.dumps({name: row["metrics"] for name, row in result["strategies"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
