import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from build_map import build_map
from score import score_map, verify_samples

REAL_DOCUMENTS = os.path.join(os.path.expanduser("~"), "Desktop", "ai_cable_integration",
                              "knowledge")
pytestmark = pytest.mark.skipif(not os.path.isdir(REAL_DOCUMENTS),
                                reason="these documents only exist on this machine")


def test_real_documents_give_a_high_located_ratio(tmp_path):
    summary = build_map([REAL_DOCUMENTS], str(tmp_path / "graph.json"))
    assert summary["nodes"] > 1000
    assert summary["elapsed"] < 5.0
    score = score_map(str(tmp_path / "graph.json"))
    assert score["located_ratio"] > 0.9


def test_sampled_values_match_the_source_line(tmp_path):
    build_map([REAL_DOCUMENTS], str(tmp_path / "graph.json"))
    result = verify_samples(score_map(str(tmp_path / "graph.json")))
    assert result["checked"] > 0
    assert result["failed"] == []


def test_building_twice_gives_byte_identical_output(tmp_path):
    first_map = str(tmp_path / "first.json")
    second_map = str(tmp_path / "second.json")
    build_map([REAL_DOCUMENTS], first_map)
    build_map([REAL_DOCUMENTS], second_map)
    assert open(first_map, "rb").read() == open(second_map, "rb").read()
