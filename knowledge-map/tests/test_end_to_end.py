import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from build_map import build_map
from score import score_map, verify_samples

실제_문서 = os.path.join(os.path.expanduser("~"), "Desktop", "ai_cable_integration", "knowledge")
pytestmark = pytest.mark.skipif(not os.path.isdir(실제_문서), reason="이 컴퓨터에만 있는 문서입니다")


def test_실제_문서로_만들면_위치정보가_높다(tmp_path):
    summary = build_map([실제_문서], str(tmp_path / "graph.json"))
    assert summary["nodes"] > 1000
    assert summary["elapsed"] < 5.0
    score = score_map(str(tmp_path / "graph.json"))
    assert score["located_ratio"] > 0.9


def test_표본_값이_원본_줄과_맞는다(tmp_path):
    build_map([실제_문서], str(tmp_path / "graph.json"))
    result = verify_samples(score_map(str(tmp_path / "graph.json")))
    assert result["checked"] > 0
    assert result["failed"] == []


def test_두_번_만들면_바이트까지_같다(tmp_path):
    첫번째 = str(tmp_path / "한번.json")
    두번째 = str(tmp_path / "두번.json")
    build_map([실제_문서], 첫번째)
    build_map([실제_문서], 두번째)
    assert open(첫번째, "rb").read() == open(두번째, "rb").read()
