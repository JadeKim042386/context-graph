import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from setup_flow import apply_answers, autocompact_options, check_dependencies
from config import DEFAULT_CONFIG


def test_있는지_없는지와_까는_방법을_함께_돌려준다():
    result = check_dependencies()
    assert set(result) == {"graphify", "obsidian_second_brain"}
    for name in result:
        assert "installed" in result[name] and "install_hint" in result[name]
        assert result[name]["install_hint"]


def test_압축_기준을_퍼센트로_보여준다():
    options = autocompact_options()
    labels = [option["label"] for option in options]
    assert "auto" in [option["value"] for option in options]
    assert any("50%" in label for label in labels)
    for option in options:
        assert option["value"] == "auto" or 100000 <= int(option["value"]) <= 1000000


def test_답을_설정에_담는다():
    config = apply_answers(dict(DEFAULT_CONFIG), {
        "source_dirs": ["C:/문서/지식", "C:/문서/기억"],
        "map_path": "C:/지도/graph.json",
        "autocompact": "500000",
        "image_text_enabled": True,
    })
    assert config["source_dirs"] == ["C:/문서/지식", "C:/문서/기억"]
    assert config["autocompact"] == "500000"
    assert config["image_text_enabled"] is True
    assert config["answer_budget"] == 20000


def test_모르는_항목은_설정에_들어가지_않는다():
    config = apply_answers(dict(DEFAULT_CONFIG), {"엉뚱한항목": "값"})
    assert "엉뚱한항목" not in config
