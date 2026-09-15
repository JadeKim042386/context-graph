import json
import sys
from html.parser import HTMLParser
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))

from knowledge_base_comparative_experiment import run_comparison, write_artifacts  # noqa: E402


FIXTURE = Path(__file__).with_name("performance-fixture.json")


class _ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.strategy_rows = []
        self.embedded = []
        self._in_result = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "tr" and values.get("data-strategy"):
            self.strategy_rows.append(values["data-strategy"])
        if tag == "script" and values.get("id") == "comparison-result":
            self._in_result = True

    def handle_data(self, data):
        if self._in_result:
            self.embedded.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_result = False


def test_four_strategies_share_fixture_and_expose_requested_metrics():
    result = run_comparison(FIXTURE, repetitions=3)
    assert result["question_count"] == 54
    assert list(result["strategies"]) == [
        "A_full_context",
        "B_fixed_lexical_top_k",
        "C_current_index_graph_pack",
        "D_compile_first_interlinked_wiki",
    ]
    metric_keys = {
        "input_tokens_p50",
        "compression_ratio",
        "retrieval_recall_at_k",
        "mrr",
        "evidence_recall",
        "locator_recall",
        "answer_accuracy",
        "citation_faithfulness",
        "false_answer_rate",
        "abstention_correctness",
        "latency_p50_ms",
        "latency_p95_ms",
        "retrieval_calls_mean",
        "cost_proxy",
    }
    for row in result["strategies"].values():
        assert row["snapshot_id"] == "fixture://2026-09-12-fixed-v1"
        assert metric_keys == set(row["metrics"])
        assert row["metrics"]["input_tokens_p50"] > 0
        assert row["metrics"]["latency_p50_ms"] > 0
        assert row["metrics"]["latency_p95_ms"] >= row["metrics"]["latency_p50_ms"]
    assert result["strategies"]["A_full_context"]["metrics"]["retrieval_calls_mean"] == 0
    assert result["strategies"]["B_fixed_lexical_top_k"]["metrics"]["retrieval_calls_mean"] == 1
    assert result["strategies"]["D_compile_first_interlinked_wiki"]["metrics"]["retrieval_calls_mean"] >= 3
    assert result["leakage_check"] == {
        "sidecar_in_strategy_inputs": False,
        "gold_ids_in_context_packs": False,
    }


def test_report_and_json_are_generated_from_the_same_result(tmp_path):
    result = run_comparison(FIXTURE, repetitions=2)
    assert result["next_role"] == "main-dispatcher"
    json_path = tmp_path / "result.json"
    html_path = tmp_path / "report.html"
    write_artifacts(result, json_path, html_path)

    stored = json.loads(json_path.read_text(encoding="utf-8"))
    parser = _ReportParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    embedded = json.loads("".join(parser.embedded))

    assert stored == result
    assert embedded == result
    assert parser.strategy_rows == list(result["strategies"])
    report = html_path.read_text(encoding="utf-8")
    assert "Literature evidence versus local synthetic results" in report
    assert "must not be interpreted as production performance" in report
    assert "Next production validation plan" in report
    assert "Next role: main-dispatcher" in report
