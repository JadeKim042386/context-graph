import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "tests"
sys.path.insert(0, str(SCRIPTS))
from task_reuse_quality_executor import build_fixture, run_mode, score  # noqa: E402
from benchmark_task_reuse_quality import GOLD_PATH, GOLD_SHA256  # noqa: E402


def test_paired_quality_is_measured_on_independent_tasks(tmp_path):
    tasks, context = build_fixture(tmp_path / "inputs")
    baseline, baseline_cost = run_mode(tasks, context, tmp_path / "inputs", "baseline")
    reuse, reuse_cost = run_mode(tasks, context, tmp_path / "inputs", "reuse")
    gold = __import__("json").loads(GOLD_PATH.read_text())
    baseline_score = score(baseline, gold)
    reuse_score = score(reuse, gold)
    assert len(tasks) == 30
    assert baseline_score["correctness"] < reuse_score["correctness"]
    assert baseline_score["completeness"] < reuse_score["completeness"]
    assert baseline_score["citation"] < reuse_score["citation"]
    assert reuse_score == {"correctness": 1.0, "faithfulness": 1.0,
                           "completeness": 1.0, "citation": 1.0, "abstention": 1.0}
    assert baseline_cost["executor_calls"] == 30
    assert reuse_cost["executor_calls"] == 25
    assert len(GOLD_SHA256) == 64
