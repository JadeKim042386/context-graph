"""The flow that runs once, the first time. It asks, checks, and writes the config."""
import importlib.util
import os
import shutil

OBSIDIAN_SKILL_DIR = os.path.join(os.path.expanduser("~"), ".claude", "skills",
                                  "obsidian-second-brain")

# The keys the config accepts. Any answer not listed here is dropped.
ANSWER_KEYS = ("source_dirs", "map_path", "autocompact", "image_text_enabled")


def check_dependencies():
    """Report whether the two tools are present, and how to install the missing ones."""
    return {
        "graphify": {
            "installed": shutil.which("graphify") is not None
                         or importlib.util.find_spec("graphify") is not None,
            "install_hint": "pip install graphifyy",
            "why": "Used to query the map. Without it the map still builds, but asking does not work.",
        },
        "obsidian_second_brain": {
            "installed": os.path.isdir(OBSIDIAN_SKILL_DIR),
            "install_hint": ("git clone https://github.com/eugeniughelbur/obsidian-second-brain "
                             f'"{OBSIDIAN_SKILL_DIR}"'),
            "why": "Used to write the session into the knowledge documents when the conversation is compacted.",
        },
    }


def autocompact_options():
    """Offer the compaction threshold as percentages, easier to pick (1M token window)."""
    return [
        {"label": "10% — compact very often", "value": "100000"},
        {"label": "30% — often", "value": "300000"},
        {"label": "50% — in between", "value": "500000"},
        {"label": "80% — rarely", "value": "800000"},
        {"label": "auto — Claude Code decides", "value": "auto"},
    ]


def apply_answers(config, answers):
    """Put the answers into the config. Keys that were not asked about keep their defaults."""
    for key in ANSWER_KEYS:
        if key in answers:
            config[key] = answers[key]
    return config
