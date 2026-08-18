"""Caches and reuses text pulled out of images.

The key is a hash of the image contents, not the file timestamp. Renaming or
re-saving an image does not force a re-read. Building the map only reads this
cache, so build time is unchanged.
"""
import hashlib
import json
import os


def image_hash(image_path):
    """Hash of the image contents. The same image gives the same key under any file name."""
    with open(image_path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def load_cache(cache_path):
    """Read the cache. Return an empty one if there is no file."""
    if not os.path.exists(cache_path):
        return {}
    with open(cache_path, encoding="utf-8-sig", errors="replace") as handle:
        return json.load(handle)


def save_cache(cache_path, cache):
    """Write the cache, creating the folder if it does not exist."""
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=1, sort_keys=True)


def pending_images(image_paths, cache):
    """Return only the images that have not been read yet."""
    return [path for path in sorted(image_paths) if image_hash(path) not in cache]


def apply_cache(cache, image_paths):
    """Turn cached text into statement pieces, marked as machine-read."""
    statements = []
    for path in sorted(image_paths):
        entry = cache.get(image_hash(path))
        if entry and entry.get("text", "").strip():
            statements.append({"text": entry["text"].strip(), "source_file": path,
                               "source_location": None, "machine_read": True})
    return statements
