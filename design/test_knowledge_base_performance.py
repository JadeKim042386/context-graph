import json
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_base_performance import load_fixture, run_benchmark, evaluate, write_report  # noqa: E402


class _BenchmarkReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.strategy_rows = []
        self.result_json = []
        self._in_result_json = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "tr" and "data-strategy" in attributes:
            self.strategy_rows.append(attributes["data-strategy"])
        if tag == "script" and attributes.get("id") == "benchmark-result":
            self._in_result_json = True

    def handle_data(self, data):
        if self._in_result_json:
            self.result_json.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_result_json = False


@pytest.fixture(scope="module")
def result():
    return run_benchmark(load_fixture(Path(__file__).with_name("performance-fixture.json")))


def test_fixture_is_fixed_at_fifty_questions():
    fixture = load_fixture(Path(__file__).with_name("performance-fixture.json"))
    assert len(fixture["questions"]) >= 50
    assert fixture["evaluator_sidecar"]
    assert all("gold_claims" not in q and "label" not in q for q in fixture["questions"])


def test_optimized_retrieval_preserves_gold_evidence(result):
    assert result["optimized"]["evidence_reproduction_rate"] >= 0.95
    assert result["optimized"]["accuracy"] >= 0.90


def test_adaptive_strategy_beats_broad_strategy(result):
    baseline = result["baseline_strategy"]
    optimized = result["optimized"]
    assert optimized["pack_tokens_p50"] < baseline["pack_tokens_p50"]
    assert optimized["accuracy"] > baseline["accuracy"]
    assert optimized["evidence_reproduction_rate"] >= baseline["evidence_reproduction_rate"]


def test_context_pack_meets_compression_gate(result):
    assert result["optimized"]["compression_ratio"] <= 0.15


def test_benchmark_evaluates_all_documented_gates(result):
    report = evaluate(result)
    assert set(report["gates"]) == {
        "compression_ratio", "latency_p50_ms", "latency_p95_ms",
        "evidence_reproduction_rate", "accuracy",
    }
    assert report["overall"] is True


def test_gold_never_enters_retrieval_or_context_packs(result):
    assert result["leakage_check"]["questions_contain_gold"] is False
    assert result["leakage_check"]["packs_contain_gold"] is False


def test_five_or_more_strategies_are_paired_on_one_snapshot(result):
    assert len(result["strategies"]) >= 5
    assert len({row["snapshot_id"] for row in result["strategies"].values()}) == 1


def test_retrieval_generation_and_efficiency_metrics_are_separate(result):
    required_retrieval = {"candidate_count", "hop_count", "retrieval_calls", "recall_at_k", "mrr", "ndcg", "locator_recall"}
    required_generation = {"accuracy", "faithfulness_proxy", "citation_locator_recall", "false_answer_rate", "conflict_abstain_rate", "unanswerable_abstain_rate"}
    required_efficiency = {"pack_tokens_p50", "cold_latency_p50_ms", "warm_latency_p50_ms", "cost_proxy"}
    for row in result["strategies"].values():
        assert required_retrieval <= row["retrieval"].keys()
        assert required_generation <= row["generation"].keys()
        assert required_efficiency <= row["efficiency"].keys()


def test_oracle_is_labeled_as_upper_bound(result):
    assert result["strategies"]["oracle"]["upper_bound"] is True


def test_strategies_expose_distinct_paths_and_nonzero_timings(result):
    paths = {row["path"] for row in result["strategies"].values()}
    assert len(paths) == len(result["strategies"])
    for row in result["strategies"].values():
        assert row["efficiency"]["cold_latency_p50_ms"] > 0
        assert row["efficiency"]["warm_latency_p50_ms"] > 0


def test_report_is_regenerated_from_current_strategy_results(result, tmp_path):
    report_path = tmp_path / "performance.html"
    write_report(result, report_path)
    parser = _BenchmarkReportParser()
    parser.feed(report_path.read_text(encoding="utf-8"))

    embedded = json.loads("".join(parser.result_json))
    assert parser.strategy_rows == list(result["strategies"])
    assert embedded["strategies"] == result["strategies"]
    assert embedded["leakage_check"] == result["leakage_check"]
    assert embedded["limitations"] == result["limitations"]
