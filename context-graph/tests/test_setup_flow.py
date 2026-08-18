import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from setup_flow import apply_answers, autocompact_options, check_dependencies
from config import DEFAULT_CONFIG


def test_it_reports_presence_together_with_how_to_install():
    result = check_dependencies()
    assert set(result) == {"graphify", "obsidian_second_brain"}
    for name in result:
        assert "installed" in result[name] and "install_hint" in result[name]
        assert result[name]["install_hint"]


def test_the_compaction_threshold_is_offered_as_percentages():
    options = autocompact_options()
    labels = [option["label"] for option in options]
    assert "auto" in [option["value"] for option in options]
    assert any("50%" in label for label in labels)
    for option in options:
        assert option["value"] == "auto" or 100000 <= int(option["value"]) <= 1000000


def test_the_answers_land_in_the_config():
    config = apply_answers(dict(DEFAULT_CONFIG), {
        "source_dirs": ["C:/docs/knowledge", "C:/docs/memory"],
        "map_path": "C:/maps/graph.json",
        "autocompact": "500000",
        "image_text_enabled": True,
    })
    assert config["source_dirs"] == ["C:/docs/knowledge", "C:/docs/memory"]
    assert config["autocompact"] == "500000"
    assert config["image_text_enabled"] is True
    assert config["answer_budget"] == 20000


def test_an_unknown_key_never_enters_the_config():
    config = apply_answers(dict(DEFAULT_CONFIG), {"unknown_key": "value"})
    assert "unknown_key" not in config
