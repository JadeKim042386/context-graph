# tests/test_config.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from config import DEFAULT_CONFIG, default_config_path, load_config, save_config


def test_reading_a_missing_file_gives_the_defaults(tmp_path):
    config = load_config(os.path.join(str(tmp_path), "missing.json"))
    assert config == DEFAULT_CONFIG
    assert config["answer_budget"] == 20000
    assert config["source_dirs"] == []


def test_what_was_saved_comes_back_unchanged(tmp_path):
    config_path = os.path.join(str(tmp_path), "config.json")
    config = dict(DEFAULT_CONFIG, source_dirs=["C:/docs/knowledge"], answer_budget=1234)
    save_config(config_path, config)
    assert load_config(config_path)["source_dirs"] == ["C:/docs/knowledge"]
    assert load_config(config_path)["answer_budget"] == 1234


def test_missing_keys_are_filled_with_the_defaults(tmp_path):
    config_path = os.path.join(str(tmp_path), "config.json")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write('{"source_dirs": ["C:/a"]}')
    config = load_config(config_path)
    assert config["source_dirs"] == ["C:/a"]
    assert config["answer_budget"] == 20000


def test_an_environment_variable_moves_the_config(monkeypatch, tmp_path):
    moved_path = os.path.join(str(tmp_path), "here.json")
    monkeypatch.setenv("KNOWLEDGE_MAP_CONFIG", moved_path)
    assert default_config_path() == moved_path
    monkeypatch.delenv("KNOWLEDGE_MAP_CONFIG")
    assert default_config_path().endswith(os.path.join("context-graph", "config.json"))
