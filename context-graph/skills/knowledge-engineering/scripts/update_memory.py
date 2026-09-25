#!/usr/bin/env python3
"""Update pointer-only project memory without copying source content."""

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote


class IntegrityError(ValueError):
    def __init__(self, state, reason):
        self.state = state
        self.reason = reason
        super().__init__(f"{state}: {reason}")


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "id" or (tag == "a" and key == "name"):
                self.ids.add(value)


def local_path(root, pointer):
    if not isinstance(pointer, str) or not pointer or ":" in pointer or "\\" in pointer:
        raise IntegrityError("unlocatable", "expected a project-relative file pointer")
    name, _, anchor = pointer.partition("#")
    path = Path(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise IntegrityError("unlocatable", "pointer must stay inside project root")
    path = (root / path).resolve()
    if not path.is_relative_to(root):
        raise IntegrityError("unlocatable", "pointer resolves outside project root")
    return path, unquote(anchor)


def checked_bytes(root, pointer, expected_hash, forbidden, reader=None):
    path, anchor = local_path(root, pointer)
    if path in forbidden:
        raise IntegrityError("unverified", "memory cannot be its own update evidence")
    try:
        content = (reader or Path.read_bytes)(path)
    except OSError as exc:
        raise IntegrityError("unlocatable", "target is missing or unreadable") from exc
    if "#" in pointer:
        if not anchor or path.suffix.lower() not in {".html", ".htm"}:
            raise IntegrityError("unlocatable", "fragment requires an HTML anchor")
        parser = Anchors()
        try:
            parser.feed(content.decode("utf-8"))
            parser.close()
        except (UnicodeError, ValueError) as exc:
            raise IntegrityError("unlocatable", "HTML target cannot be parsed") from exc
        if anchor not in parser.ids:
            raise IntegrityError("unlocatable", "HTML anchor is missing")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise IntegrityError("unverified", "SHA-256 must be 64 lowercase hexadecimal characters")
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise IntegrityError("stale", "content SHA-256 does not match target revision")
    return content


def checked_review(root, pointer, digest, status, review, forbidden, review_hash=None, reader=None):
    if not review:
        raise IntegrityError("unverified", "review/decision evidence is required")
    try:
        path, anchor = local_path(root, review)
        if anchor or "#" in review or path in forbidden:
            raise ValueError("review must be a separate JSON file")
        raw = (reader or Path.read_bytes)(path)
    except (OSError, ValueError) as exc:
        raise IntegrityError("unverified", "review/decision file is missing or invalid") from exc
    digest_review = hashlib.sha256(raw).hexdigest()
    if review_hash is not None and review_hash != digest_review:
        raise IntegrityError("stale", "review/decision revision has changed")
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise IntegrityError("unverified", "review/decision JSON is invalid") from exc
    if not isinstance(record, dict):
        raise IntegrityError("unverified", "review/decision must be a record object")
    required_strings = ("id", "created_at", "updated_at")
    provenance = record.get("provenance")
    allowed = {("Decision", "accepted")}
    if status != "accepted":
        allowed.add(("Review", "verified"))
    valid = (
        all(isinstance(record.get(key), str) and record[key].strip() for key in required_strings)
        and type(record.get("schema_version")) is int and record["schema_version"] > 0
        and type(record.get("revision")) is int and record["revision"] > 0
        and isinstance(provenance, dict)
        and all(isinstance(provenance.get(key), str) and provenance[key].strip()
                for key in ("agent", "activity_id"))
        and isinstance(record.get("record_type"), str)
        and isinstance(record.get("status"), str)
        and (record["record_type"], record["status"]) in allowed
        and record.get("target_pointer") == pointer
        and record.get("target_sha256") == digest
    )
    if not valid:
        raise IntegrityError("unverified", "review/decision must approve this exact pointer and revision")
    return digest_review


def classify(root, entry, forbidden, reader=None):
    try:
        if not isinstance(entry, dict):
            raise IntegrityError("unverified", "legacy pointer is not an object")
        if "value" in entry and entry.get("algorithm") != "sha256":
            raise IntegrityError("unverified", "snapshot algorithm must be sha256")
        pointer = entry.get("pointer", entry.get("source"))
        digest = entry.get("revision_sha256", entry.get("value"))
        reader_args = {"reader": reader} if reader is not None else {}
        checked_bytes(root, pointer, digest, forbidden, **reader_args)
        if not isinstance(entry.get("status"), str) or entry["status"] not in {"accepted", "verified"}:
            raise IntegrityError("unverified", "pointer has not been promoted")
        if not entry.get("review_sha256"):
            raise IntegrityError("unverified", "review/decision revision binding is missing")
        checked_review(root, pointer, digest, entry["status"], entry.get("review_pointer"),
                       forbidden, entry["review_sha256"], **reader_args)
        return "valid", "target, locator, hash and recorded review binding match"
    except IntegrityError as exc:
        return exc.state, exc.reason


def classify_memory(data, root, forbidden, annotate=False):
    entries = [(key, data[key]) for key in ("current_goal", "snapshot_hash") if key in data]
    for key in ("approved_decision_pointers", "unresolved_pointers"):
        group = data.get(key, [])
        if not isinstance(group, list):
            raise IntegrityError("unverified", "legacy pointer collection must be an array")
        entries.extend((f"{key}[{i}]", entry) for i, entry in enumerate(group))
    results = []
    for location, entry in entries:
        state, reason = classify(root, entry, forbidden)
        results.append({"location": location, "integrity_status": state, "integrity_reason": reason})
        if annotate and isinstance(entry, dict):
            entry.update(integrity_status=state, integrity_reason=reason)
    return results


def atomic_write(path, data):
    """Serialize before touching disk; replace only a fully flushed sibling file."""
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".memory-", delete=False) as temp:
            temp_path = Path(temp.name)
            if path.exists():
                os.fchmod(temp.fileno(), path.stat().st_mode & 0o777)
            temp.write(payload)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="classify legacy pointers without writing")
    parser.add_argument("--goal")
    parser.add_argument("--status", choices=["proposed", "verified", "accepted", "open", "blocked", "complete"])
    parser.add_argument("--snapshot-hash")
    parser.add_argument("--snapshot-source")
    parser.add_argument("--snapshot-id")
    parser.add_argument("--goal-hash")
    parser.add_argument("--review", help="project-relative Review/Decision JSON for the goal")
    parser.add_argument("--snapshot-review", help="project-relative Review/Decision JSON for the snapshot")
    args = parser.parse_args()
    if args.goal and not args.status:
        parser.error("--status is required when --goal is provided")
    update = args.goal is not None or args.snapshot_hash is not None
    if args.check and update:
        parser.error("--check cannot be combined with updates")
    if not args.goal and any(value is not None for value in (args.status, args.goal_hash, args.review)):
        parser.error("goal options require --goal")
    if args.snapshot_hash is None and any(value is not None for value in
                                         (args.snapshot_source, args.snapshot_review, args.snapshot_id)):
        parser.error("snapshot options require --snapshot-hash")
    try:
        root = args.root.resolve()
        memory = args.memory.resolve()
        if not memory.is_relative_to(root) or args.memory.is_symlink():
            raise IntegrityError("unlocatable", "memory must be a non-symlink file inside project root")
        forbidden = {memory}
        data = json.loads(memory.read_bytes()) if memory.exists() else {"schema_version": 1}
        if not isinstance(data, dict):
            raise IntegrityError("unverified", "memory must be a JSON object")
        now = datetime.now(timezone.utc).isoformat()
        if args.goal is not None:
            local_path(root, args.goal)
            goal = {"pointer": args.goal, "status": args.status, "updated_at": now}
            if args.status in {"accepted", "verified"}:
                checked_bytes(root, args.goal, args.goal_hash, forbidden)
                proof_hash = checked_review(root, args.goal, args.goal_hash, args.status, args.review, forbidden)
                goal.update(revision_sha256=args.goal_hash, review_pointer=args.review, review_sha256=proof_hash)
            elif args.goal_hash is not None or args.review is not None:
                raise IntegrityError("unverified", "review/hash options require accepted or verified status")
            data["current_goal"] = goal
        if args.snapshot_hash is not None:
            if not args.snapshot_source:
                raise IntegrityError("unverified", "snapshot source and review evidence are required")
            checked_bytes(root, args.snapshot_source, args.snapshot_hash, forbidden)
            proof_hash = checked_review(root, args.snapshot_source, args.snapshot_hash, "verified",
                                        args.snapshot_review, forbidden)
            data["snapshot_hash"] = {
                "algorithm": "sha256", "value": args.snapshot_hash, "status": "verified", "updated_at": now,
                "source": args.snapshot_source, "review_pointer": args.snapshot_review, "review_sha256": proof_hash,
            }
            if args.snapshot_id:
                data["snapshot_hash"]["snapshot_id"] = args.snapshot_id
        results = classify_memory(data, root, forbidden, annotate=update)
        promoted = set()
        if args.goal is not None and args.status in {"accepted", "verified"}:
            promoted.add("current_goal")
        if args.snapshot_hash is not None:
            promoted.add("snapshot_hash")
        for result in results:
            if result["location"] in promoted and result["integrity_status"] != "valid":
                raise IntegrityError(result["integrity_status"], result["integrity_reason"])
        if update:
            data.setdefault("approved_decision_pointers", [])
            data.setdefault("unresolved_pointers", [])
            atomic_write(memory, data)
        print(json.dumps({"ok": True, "changed": update, "memory": str(memory),
                          "classifications": results}, ensure_ascii=False))
    except (OSError, ValueError, UnicodeError) as exc:
        parser.error(str(exc) if isinstance(exc, IntegrityError) else "unverified: memory read/write or JSON failure")


if __name__ == "__main__":
    main()
