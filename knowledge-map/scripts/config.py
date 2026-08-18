"""설정을 읽고 씁니다. 경로는 어디에도 박지 않고 전부 여기를 거칩니다."""
import json
import os

DEFAULT_CONFIG = {
    "source_dirs": [],            # 지식 문서가 있는 곳들
    "map_path": "",               # 지도를 둘 자리(지식 문서 바깥)
    "answer_budget": 20000,       # 답 분량 한도. 낮추면 값이 든 문장이 잘립니다
    "image_text_enabled": False,  # 그림에서 글자 뽑기. 기본은 꺼짐
    "autocompact": "auto",        # 압축 기준(auto 또는 100000~1000000)
}


def load_config(config_path):
    """설정을 읽습니다. 파일이 없거나 항목이 빠져 있으면 기본값으로 채웁니다."""
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8-sig", errors="replace") as handle:
            config.update(json.load(handle))
    return config


def default_config_path():
    """설정 파일 자리. 환경 변수로 바꿀 수 있어 컴퓨터마다 다른 자리를 쓸 수 있습니다."""
    return os.environ.get("KNOWLEDGE_MAP_CONFIG") or os.path.join(
        os.path.expanduser("~"), ".claude", "knowledge-map", "config.json")


def save_config(config_path, config):
    """설정을 씁니다. 폴더가 없으면 만듭니다."""
    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2, sort_keys=True)
