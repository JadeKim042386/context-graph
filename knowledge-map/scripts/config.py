"""Reads and writes the config. No path is hard-coded anywhere else; everything goes through here."""
import json
import os

DEFAULT_CONFIG = {
    "source_dirs": [],            # where the knowledge documents live
    "map_path": "",               # where the map goes (outside the knowledge documents)
    "answer_budget": 20000,       # answer size limit. Lower it and statements carrying values get cut
    "image_text_enabled": False,  # pull text out of images. Off by default
    "autocompact": "auto",        # compaction threshold (auto, or 100000-1000000)
}


def load_config(config_path):
    """Read the config. A missing file or a missing key falls back to the default."""
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8-sig", errors="replace") as handle:
            config.update(json.load(handle))
    return config


def default_config_path():
    """Where the config lives. An environment variable overrides it, so each machine can differ."""
    return os.environ.get("KNOWLEDGE_MAP_CONFIG") or os.path.join(
        os.path.expanduser("~"), ".claude", "knowledge-map", "config.json")


def save_config(config_path, config):
    """Write the config, creating the folder if it does not exist."""
    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2, sort_keys=True)
