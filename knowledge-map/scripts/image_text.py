"""그림에서 뽑은 글자를 캐시에 두고 씁니다.

열쇠는 파일 시각이 아니라 그림 내용의 해시입니다. 이름을 바꾸거나 다시 저장만 해도
다시 읽지 않습니다. 지도를 만들 때는 이 캐시를 읽기만 하므로 재생성 시간이 그대로입니다.
"""
import hashlib
import json
import os


def image_hash(image_path):
    """그림 내용의 해시. 같은 그림이면 이름이 달라도 같은 열쇠입니다."""
    with open(image_path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def load_cache(cache_path):
    """캐시를 읽습니다. 없으면 빈 것을 돌려줍니다."""
    if not os.path.exists(cache_path):
        return {}
    with open(cache_path, encoding="utf-8-sig", errors="replace") as handle:
        return json.load(handle)


def save_cache(cache_path, cache):
    """캐시를 씁니다. 폴더가 없으면 만듭니다."""
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=1, sort_keys=True)


def pending_images(image_paths, cache):
    """아직 읽지 않은 그림만 골라 돌려줍니다."""
    return [path for path in sorted(image_paths) if image_hash(path) not in cache]


def apply_cache(cache, image_paths):
    """캐시에 있는 글자를 문장 조각으로 바꿉니다. 기계가 읽은 것이라고 표시합니다."""
    statements = []
    for path in sorted(image_paths):
        entry = cache.get(image_hash(path))
        if entry and entry.get("text", "").strip():
            statements.append({"text": entry["text"].strip(), "source_file": path,
                               "source_location": None, "machine_read": True})
    return statements
