import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from image_text import apply_cache, image_hash, load_cache, pending_images, save_cache


def test_same_contents_give_the_same_key_under_different_names(tmp_path):
    first = tmp_path / "a.png"; first.write_bytes(b"same-bytes")
    second = tmp_path / "b.png"; second.write_bytes(b"same-bytes")
    assert image_hash(str(first)) == image_hash(str(second))


def test_a_cached_image_is_not_read_again(tmp_path):
    image = tmp_path / "a.png"; image.write_bytes(b"payload")
    cache = {image_hash(str(image)): {"text": "3,683 rows in the table"}}
    assert pending_images([str(image)], cache) == []
    image.write_bytes(b"changed-payload")
    assert pending_images([str(image)], cache) == [str(image)]


def test_statements_built_from_the_cache_carry_their_source(tmp_path):
    image = tmp_path / "a.png"; image.write_bytes(b"payload")
    cache = {image_hash(str(image)): {"text": "3,683 rows in the table"}}
    statements = apply_cache(cache, [str(image)])
    assert statements[0]["text"] == "3,683 rows in the table"
    assert statements[0]["source_file"].endswith("a.png")
    assert statements[0]["machine_read"] is True


def test_reading_a_missing_cache_file_gives_an_empty_cache(tmp_path):
    assert load_cache(str(tmp_path / "missing.json")) == {}


def test_non_ascii_text_survives_a_cache_round_trip(tmp_path):
    # Korean on purpose: the cache must round-trip documents that are not in English.
    cache_path = str(tmp_path / "cache" / "image_text.json")
    save_cache(cache_path, {"열쇠": {"text": "표에 3,683개"}})
    assert load_cache(cache_path)["열쇠"]["text"] == "표에 3,683개"
