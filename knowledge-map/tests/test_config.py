# tests/test_config.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from config import DEFAULT_CONFIG, default_config_path, load_config, save_config


def test_없는_파일을_읽으면_기본값이_온다(tmp_path):
    config = load_config(os.path.join(str(tmp_path), "없는파일.json"))
    assert config == DEFAULT_CONFIG
    assert config["answer_budget"] == 20000
    assert config["image_text_enabled"] is False
    assert config["source_dirs"] == []


def test_저장한_뒤_읽으면_그대로_온다(tmp_path):
    config_path = os.path.join(str(tmp_path), "config.json")
    config = dict(DEFAULT_CONFIG, source_dirs=["C:/문서/지식"], answer_budget=1234)
    save_config(config_path, config)
    assert load_config(config_path)["source_dirs"] == ["C:/문서/지식"]
    assert load_config(config_path)["answer_budget"] == 1234


def test_모르는_항목이_있어도_기본값이_채워진다(tmp_path):
    config_path = os.path.join(str(tmp_path), "config.json")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write('{"source_dirs": ["C:/가"]}')
    config = load_config(config_path)
    assert config["source_dirs"] == ["C:/가"]
    assert config["answer_budget"] == 20000


def test_설정_자리는_환경_변수로_바꿀_수_있다(monkeypatch, tmp_path):
    바꾼_자리 = os.path.join(str(tmp_path), "여기.json")
    monkeypatch.setenv("KNOWLEDGE_MAP_CONFIG", 바꾼_자리)
    assert default_config_path() == 바꾼_자리
    monkeypatch.delenv("KNOWLEDGE_MAP_CONFIG")
    assert default_config_path().endswith(os.path.join("knowledge-map", "config.json"))
