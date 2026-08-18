"""처음 쓸 때 한 번 도는 흐름입니다. 묻고, 확인하고, 설정에 적습니다."""
import importlib.util
import os
import shutil

OBSIDIAN_SKILL_DIR = os.path.join(os.path.expanduser("~"), ".claude", "skills",
                                  "obsidian-second-brain")

# 설정에 담을 수 있는 항목. 여기 없는 답은 버립니다.
ANSWER_KEYS = ("source_dirs", "map_path", "autocompact", "image_text_enabled")


def check_dependencies():
    """두 도구가 있는지 보고, 없으면 어떻게 까는지 함께 돌려줍니다."""
    return {
        "graphify": {
            "installed": shutil.which("graphify") is not None
                         or importlib.util.find_spec("graphify") is not None,
            "install_hint": "pip install graphifyy",
            "why": "지도에 묻는 데 씁니다. 없으면 지도는 만들어지지만 묻기가 안 됩니다.",
        },
        "obsidian_second_brain": {
            "installed": os.path.isdir(OBSIDIAN_SKILL_DIR),
            "install_hint": ("git clone https://github.com/eugeniughelbur/obsidian-second-brain "
                             f'"{OBSIDIAN_SKILL_DIR}"'),
            "why": "대화가 압축될 때 세션 내용을 지식 문서에 적는 데 씁니다.",
        },
    }


def autocompact_options():
    """압축 기준을 사람이 고르기 쉽게 퍼센트로 보여줍니다(창 100만 토큰 기준)."""
    return [
        {"label": "10% — 아주 자주 압축", "value": "100000"},
        {"label": "30% — 자주", "value": "300000"},
        {"label": "50% — 중간", "value": "500000"},
        {"label": "80% — 드물게", "value": "800000"},
        {"label": "알아서 — Claude Code가 정함", "value": "auto"},
    ]


def apply_answers(config, answers):
    """물어서 받은 답을 설정에 담습니다. 안 물은 항목은 기본값 그대로 둡니다."""
    for key in ANSWER_KEYS:
        if key in answers:
            config[key] = answers[key]
    return config
