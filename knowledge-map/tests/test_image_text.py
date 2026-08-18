import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from image_text import apply_cache, image_hash, load_cache, pending_images, save_cache


def test_내용이_같으면_이름이_달라도_같은_열쇠(tmp_path):
    첫째 = tmp_path / "가.png"; 첫째.write_bytes(b"same-bytes")
    둘째 = tmp_path / "나.png"; 둘째.write_bytes(b"same-bytes")
    assert image_hash(str(첫째)) == image_hash(str(둘째))


def test_캐시에_있으면_다시_읽지_않는다(tmp_path):
    그림 = tmp_path / "가.png"; 그림.write_bytes(b"payload")
    cache = {image_hash(str(그림)): {"text": "표에 3,683개"}}
    assert pending_images([str(그림)], cache) == []
    그림.write_bytes(b"changed-payload")
    assert pending_images([str(그림)], cache) == [str(그림)]


def test_캐시에서_문장을_만들_때_출처가_붙는다(tmp_path):
    그림 = tmp_path / "가.png"; 그림.write_bytes(b"payload")
    cache = {image_hash(str(그림)): {"text": "표에 3,683개"}}
    statements = apply_cache(cache, [str(그림)])
    assert statements[0]["text"] == "표에 3,683개"
    assert statements[0]["source_file"].endswith("가.png")
    assert statements[0]["machine_read"] is True


def test_없는_캐시_파일을_읽으면_빈_것이_온다(tmp_path):
    assert load_cache(str(tmp_path / "없음.json")) == {}


def test_저장한_캐시를_다시_읽으면_한글이_그대로다(tmp_path):
    cache_path = str(tmp_path / "cache" / "image_text.json")
    save_cache(cache_path, {"열쇠": {"text": "표에 3,683개"}})
    assert load_cache(cache_path)["열쇠"]["text"] == "표에 3,683개"
