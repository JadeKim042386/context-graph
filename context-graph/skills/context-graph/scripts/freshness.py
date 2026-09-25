"""Content-based source snapshots shared by bound build and retrieval."""
import hashlib
import json
import os
import re
from pathlib import Path

SUFFIXES = (".md", ".markdown", ".html", ".htm")


class FreshnessError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def document_files(source_dirs):
    found = set()
    def on_error(_error):
        raise FreshnessError("source_unreadable")
    for source_dir in sorted(source_dirs):
        for folder, directories, names in os.walk(source_dir, onerror=on_error):
            directories.sort()
            for name in sorted(names):
                if name.endswith(SUFFIXES):
                    found.add(os.path.abspath(os.path.join(folder, name)))
    return sorted(found)


def file_record(path, raw):
    return {"path": os.path.abspath(path), "sha256": hashlib.sha256(raw).hexdigest()}


def make_snapshot(files):
    files = sorted(files, key=lambda entry: entry["path"])
    return {"schema_version": 1, "algorithm": "sha256", "files": files, "sha256": digest(files)}


def scan_snapshot(source_dirs, validate_path=None):
    records = []
    try:
        for path in document_files(source_dirs):
            if validate_path is not None:
                validate_path(path)
            records.append(file_record(path, Path(path).read_bytes()))
    except OSError as exc:
        raise FreshnessError("source_unreadable") from exc
    return make_snapshot(records)


def snapshot_files(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1 or snapshot.get("algorithm") != "sha256":
        raise FreshnessError("invalid_source_snapshot")
    files = snapshot.get("files")
    if not isinstance(files, list):
        raise FreshnessError("invalid_source_snapshot")
    by_path = {}
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise FreshnessError("invalid_source_snapshot")
        path, sha = entry["path"], entry["sha256"]
        if not isinstance(path, str) or not Path(path).is_absolute() or path in by_path:
            raise FreshnessError("invalid_source_snapshot")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise FreshnessError("invalid_source_snapshot")
        by_path[path] = sha
    if snapshot.get("sha256") != digest(files) or list(by_path) != sorted(by_path):
        raise FreshnessError("invalid_source_snapshot")
    return by_path


def projection_digest(graph):
    return digest({"nodes": graph.get("nodes"), "links": graph.get("links")})


def source_delta(old, current):
    before, after = snapshot_files(old), snapshot_files(current)
    return {"deleted": sorted(before.keys() - after.keys()),
            "added": sorted(after.keys() - before.keys()),
            "changed": sorted(path for path in before.keys() & after.keys() if before[path] != after[path])}


def verify_freshness(graph, source_dirs, validate_path=None):
    old = graph.get("source_snapshot")
    if old is None:
        raise FreshnessError("freshness_unverified")
    files = snapshot_files(old)
    if graph.get("projection_sha256") != projection_digest(graph):
        raise FreshnessError("map_records_changed")
    if {node.get("source_file") for node in graph["nodes"] if node.get("source_file")} != set(files):
        raise FreshnessError("map_source_snapshot_mismatch")
    delta = source_delta(old, scan_snapshot(source_dirs, validate_path))
    if delta["deleted"] and delta["added"]:
        raise FreshnessError("source_set_changed")
    if delta["deleted"]:
        raise FreshnessError("source_deleted")
    if delta["added"]:
        raise FreshnessError("source_added")
    if delta["changed"]:
        raise FreshnessError("source_content_changed")
    return old["sha256"]
