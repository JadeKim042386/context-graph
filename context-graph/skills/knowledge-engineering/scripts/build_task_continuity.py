#!/usr/bin/env python3
"""Emit a bounded, read-only task continuity pack; never promote or execute."""

import argparse
import hashlib
import json
import re
import stat
import sys
from datetime import date
from pathlib import Path

# Importing this sibling must not create a projection or __pycache__ on resume.
sys.dont_write_bytecode = True
import update_memory as integrity


CONSTRAINTS = frozenset({
    "no_network", "no_commit", "no_push", "no_deploy", "no_source_edits",
    "no_memory_edits", "no_generated_edits", "preserve_user_changes",
    "review_before_promotion", "no_secrets",
})
ACTIONS = frozenset({"review_evidence", "replay_locator", "run_focused_tests", "check_snapshot",
                     "request_approval", "resolve_conflict", "review_unresolved"})
STATUSES = frozenset({"proposed", "verified", "accepted", "open", "blocked", "complete",
                      "superseded", "deprecated", "retracted", "conflict", "unknown"})
RETIRED = frozenset({"superseded", "deprecated", "retracted"})
UNSAFE = re.compile(r"secret|token|credential|password|cookie|private|prompt|transcript|evaluator|gold|id_rsa", re.I)
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,79}\Z")
POINTER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,479}(?:#[A-Za-z0-9_.-]{1,80})?\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")


class ReadLimit(Exception):
    pass


def strict_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique)


def safe_id(value):
    return value if isinstance(value, str) and IDENTIFIER.fullmatch(value) and not UNSAFE.search(value) else None


def safe_pointer(root, value):
    if not isinstance(value, str) or not POINTER.fullmatch(value) or UNSAFE.search(value):
        raise integrity.IntegrityError("unlocatable", "unsafe_pointer")
    path, anchor = integrity.local_path(root, value)
    relative = path.relative_to(root).as_posix()
    if any(part.startswith(".") for part in Path(relative).parts) or UNSAFE.search(relative):
        raise integrity.IntegrityError("unlocatable", "unsafe_pointer")
    return path, anchor


class BoundedReader:
    def __init__(self, root, file_limit, total_limit):
        self.root, self.file_limit, self.total_limit = root, file_limit, total_limit
        self.bytes_read = 0
        self.cache = {}

    def read(self, path, limit=None):
        path, _ = safe_pointer(self.root, path.relative_to(self.root).as_posix())
        if path in self.cache:
            return self.cache[path]
        remaining = self.total_limit - self.bytes_read
        # Reserve the size-change probe byte inside, not beyond, the total budget.
        bound = min(self.file_limit if limit is None else limit, remaining - 1)
        if bound <= 0:
            raise ReadLimit("read_budget")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise integrity.IntegrityError("unlocatable", "not_regular_file")
        if info.st_size > bound:
            raise ReadLimit("file_limit")
        with path.open("rb") as stream:
            raw = stream.read(bound + 1)
        self.bytes_read += len(raw)
        if len(raw) > bound:
            raise ReadLimit("file_changed_or_limit")
        self.cache[path] = raw
        return raw


def empty_item(group, slot):
    return {"group": group, "slot": slot, "pointer": None, "recorded_status": "unknown",
            "integrity_status": "unknown", "reason": "invalid_entry", "lifecycle_status": "unknown",
            "continuity_state": "unknown", "applicable": False, "record_id": None, "record_revision": None,
            "revision_sha256": None, "review_pointer": None, "review_sha256": None,
            "supersedes": [], "superseded_by": [], "required_constraints": [], "next_actions": [],
            "proof_type": None, "proof_status": None, "decision_context": None, "context_status": "unknown",
            "conflicts_with": [], "conflict_criteria": [], "duplicate_of": None}


def valid_context(value):
    if not isinstance(value, dict) or set(value) != {"question_key", "scope", "as_of", "outcome_id"}:
        return False
    if not all(safe_id(value[k]) for k in ("question_key", "scope", "outcome_id")):
        return False
    try:
        return isinstance(value["as_of"], str) and date.fromisoformat(value["as_of"]).isoformat() == value["as_of"]
    except ValueError:
        return False


def context_key(item):
    context = item["decision_context"]
    return tuple(context[k] for k in ("question_key", "scope", "as_of")) if context else None


def read_item(root, memory_path, reader, group, slot, entry):
    item = empty_item(group, slot)
    if not isinstance(entry, dict):
        return item
    status = entry.get("status")
    if isinstance(status, str) and status in STATUSES:
        item["recorded_status"] = status
        if status in RETIRED or status == "conflict":
            item["lifecycle_status"] = status
        if status == "conflict":
            item["conflict_criteria"] = ["recorded_conflict_unverified"]
    try:
        pointer = entry.get("pointer", entry.get("source"))
        path, _ = safe_pointer(root, pointer)
        item["pointer"] = pointer
        review = entry.get("review_pointer")
        if review is not None:
            safe_pointer(root, review)
        state, _ = integrity.classify(root, entry, {memory_path}, reader=reader.read)
        item.update(integrity_status=state, reason=state)
        for output, value in (("revision_sha256", entry.get("revision_sha256", entry.get("value"))),
                              ("review_sha256", entry.get("review_sha256"))):
            if isinstance(value, str) and HASH.fullmatch(value):
                item[output] = value
        item["review_pointer"] = review
        if state != "valid":
            return item
        review_path, _ = safe_pointer(root, review)
        proof = strict_json(reader.read(review_path))
        record_id = safe_id(proof.get("id"))
        metadata = proof.get("continuity")
        if record_id is None or not isinstance(metadata, dict):
            return item
        item.update(record_id=record_id, record_revision=proof["revision"],
                    proof_type=proof["record_type"], proof_status=proof["status"])
        lifecycle = metadata.get("lifecycle_status")
        relations = metadata.get("supersedes")
        constraints, actions = metadata.get("required_constraints"), metadata.get("next_actions")
        if not isinstance(lifecycle, str) or lifecycle not in {"active", "superseded", "retracted", "deprecated"}:
            return item
        if not isinstance(relations, list) or len(relations) > 32 or not all(safe_id(v) for v in relations):
            return item
        if not isinstance(constraints, list) or len(constraints) > 32 or not all(isinstance(v, str) and v in CONSTRAINTS for v in constraints):
            return item
        if not isinstance(actions, list) or len(actions) > 32 or not all(isinstance(v, str) and v in ACTIONS for v in actions):
            return item
        # A bound canonical JSON target's retirement cannot be overridden by the envelope.
        if path.suffix.lower() == ".json":
            target = strict_json(reader.read(path))
            if isinstance(target, dict) and isinstance(target.get("status"), str) and target["status"] in RETIRED | {"conflict"}:
                lifecycle = target["status"]
                if lifecycle == "conflict":
                    item["conflict_criteria"] = ["target_conflict"]
        item.update(lifecycle_status=lifecycle, continuity_state="known", reason="bound_continuity",
                    supersedes=sorted(set(relations)), required_constraints=sorted(set(constraints)),
                    next_actions=sorted(set(actions)))
        context, conflicts = metadata.get("decision_context"), metadata.get("conflicts_with", [])
        if not valid_context(context) or not isinstance(conflicts, list) or len(conflicts) > 32 or not all(safe_id(v) for v in conflicts):
            item["reason"] = "unknown_decision_context"
            return item
        item.update(decision_context=context, context_status="inventory", conflicts_with=sorted(set(conflicts)))
    except ReadLimit:
        item.update(integrity_status="unknown", reason="read_limit")
    except integrity.IntegrityError as exc:
        item.update(integrity_status=exc.state, reason="unsafe_or_unlocatable")
    except (OSError, ValueError, UnicodeError, RecursionError):
        item.update(integrity_status="unknown", reason="invalid_or_unreadable")
    return item


def resolve_relations(items):
    """Resolve verified declarations before ranking; never infer acceptance from recency."""
    by_id = {}
    complete = True
    identical = {}
    for item in items:
        if item["continuity_state"] != "known" or item["integrity_status"] != "valid" or not item["decision_context"]:
            complete = False
            continue
        key = tuple(item[k] for k in ("record_id", "record_revision", "pointer", "revision_sha256",
                                      "review_pointer", "review_sha256", "recorded_status", "lifecycle_status"))
        if key in identical:
            item.update(duplicate_of=identical[key]["record_id"], lifecycle_status="duplicate", reason="identical_revision")
            continue
        identical[key] = item
        by_id.setdefault(item["record_id"], []).append(item)

    def conflict(item, criterion, other):
        item.update(lifecycle_status="conflict", reason=criterion)
        item["conflict_criteria"] = sorted(set(item["conflict_criteria"] + [criterion]))
        item["conflicts_with"] = sorted(set(item["conflicts_with"] + [other]))

    for identity, matches in by_id.items():
        if len(matches) > 1:
            complete = False
            for item in matches:
                conflict(item, "duplicate_record_id", identity)

    links = {}
    for item in identical.values():
        if not item["supersedes"]:
            continue
        if item["lifecycle_status"] != "active":
            complete = False
            continue
        if (item["proof_type"], item["proof_status"]) != ("Decision", "accepted"):
            complete = False
            item["reason"] = "nonaccepted_superseder"
            continue
        targets = []
        for old in item["supersedes"]:
            if len(by_id.get(old, [])) != 1 or old == item["record_id"]:
                complete = False
                item["reason"] = "unresolved_supersedes"
                continue
            if context_key(item) != context_key(by_id[old][0]):
                complete = False
                item["reason"] = "supersedes_context_mismatch"
                continue
            targets.append(old)
        links[item["record_id"]] = targets
    # Check cycles before mutating any target lifecycle.
    for identity in links:
        pending, seen = list(links[identity]), set()
        while pending:
            current = pending.pop()
            if current == identity:
                complete = False
                conflict(by_id[identity][0], "supersedes_cycle", identity)
                break
            if current not in seen:
                seen.add(current)
                pending.extend(links.get(current, []))
    for identity, targets in links.items():
        if by_id[identity][0]["lifecycle_status"] == "conflict":
            continue
        for old in targets:
            target = by_id[old][0]
            if target["lifecycle_status"] == "active":
                target["lifecycle_status"] = "superseded"
            target["superseded_by"] = sorted(set(target["superseded_by"] + [identity]))

    active = [i for i in identical.values() if i["lifecycle_status"] == "active"]
    for item in active:
        if item["record_id"] in item["conflicts_with"]:
            conflict(item, "declared_conflict", item["record_id"])
            complete = False
    for index, a in enumerate(active):
        for b in active[index + 1:]:
            if context_key(a) == context_key(b):
                criterion = None
                if a["decision_context"]["outcome_id"] != b["decision_context"]["outcome_id"]:
                    criterion = "same_context_different_outcome"
                elif b["record_id"] in a["conflicts_with"] or a["record_id"] in b["conflicts_with"]:
                    criterion = "declared_conflict"
                if criterion:
                    conflict(a, criterion, b["record_id"])
                    conflict(b, criterion, a["record_id"])
                    complete = False
    for item in active:
        for other in item["conflicts_with"]:
            if len(by_id.get(other, [])) != 1 or context_key(by_id[other][0]) != context_key(item):
                item["reason"] = "unresolved_conflict"
                complete = False
    return complete and not any(i["lifecycle_status"] == "conflict" for i in items)


def encode(pack):
    return json.dumps(pack, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"


def build_pack(root, memory="knowledge-base/_ops/memory/index.json", *, max_entries=32,
               max_file_bytes=262144, max_total_bytes=1048576, max_pack_bytes=32768,
               question_key=None, scope=None, as_of=None, expected_dependency_sha256=None):
    limits = {"max_entries": max_entries, "max_file_bytes": max_file_bytes,
              "max_total_bytes": max_total_bytes, "max_pack_bytes": max_pack_bytes}
    for name, low, high in (("max_entries", 1, 128), ("max_file_bytes", 1, 1048576),
                            ("max_total_bytes", 1024, 8388608), ("max_pack_bytes", 1024, 131072)):
        if type(limits[name]) is not int or not low <= limits[name] <= high:
            raise ValueError("invalid limits")
    root = Path(root).resolve()
    query = None
    if any(v is not None for v in (question_key, scope, as_of)):
        context = {"question_key": question_key, "scope": scope, "as_of": as_of, "outcome_id": "query"}
        if not valid_context(context):
            raise ValueError("invalid query context")
        query = {k: context[k] for k in ("question_key", "scope", "as_of")}
    if expected_dependency_sha256 is not None and not HASH.fullmatch(expected_dependency_sha256):
        raise ValueError("invalid dependency digest")
    reader = BoundedReader(root, max_file_bytes, max_total_bytes)
    pack = {"schema_version": 1, "read_only": True, "promotion_performed": False,
            "pack_status": "invalid_memory", "memory_sha256": None, "items": [],
            "total_count": 0, "included_count": 0, "omitted_count": 0,
            "bytes_read": 0, "limits": limits, "query": query,
            "assessed_count": 0, "relation_scan_complete": False, "conflict_count": 0, "duplicate_count": 0,
            "dependency_sha256": None, "cache_state": "unverified" if expected_dependency_sha256 else "not_requested",
            "cache_reusable": False,
            "safety": {"memory_complete": False, "constraints": [
                "do_not_assume_complete_memory", "review_unresolved_before_dependent_action",
                "applicability_is_not_approval"]}}
    pack["binding"] = {"scope": "memory", "status": "unverified", "reason": "cwd_mismatch",
                       "root_id": hashlib.sha256(str(root).encode()).hexdigest(), "root": ".",
                       "memory_path": None, "allowed_source_roots": ["."], "config_map_state": "not_used"}
    if not root.is_dir() or not Path.cwd().resolve().is_relative_to(root):
        return pack
    try:
        memory_path, anchor = safe_pointer(root, memory)
        if anchor or memory_path.suffix.lower() != ".json":
            pack["binding"]["reason"] = "invalid_memory_path"
            return pack
        pack["binding"].update(status="verified", reason="bound_root", memory_path=memory)
        raw = reader.read(memory_path, limit=262144)
        pack["memory_sha256"] = hashlib.sha256(raw).hexdigest()
        data = strict_json(raw)
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            return pack
        if any(key in data and not isinstance(data[key], list) for key in ("approved_decision_pointers", "unresolved_pointers")):
            return pack
    except FileNotFoundError:
        pack["pack_status"] = "missing_memory"
        return pack
    except (OSError, ValueError, ReadLimit, RecursionError):
        if pack["binding"]["status"] != "verified":
            pack["binding"]["reason"] = "invalid_memory_path"
        return pack
    finally:
        pack["bytes_read"] = reader.bytes_read
    entries = [(key, 0, data[key]) for key in ("current_goal", "snapshot_hash") if key in data]
    for key in ("approved_decision_pointers", "unresolved_pointers"):
        entries.extend((key, slot, value) for slot, value in enumerate(data.get(key, [])))
    pack["total_count"] = len(entries)
    assessed = [read_item(root, memory_path, reader, *entry) for entry in entries[:128]]
    pack["bytes_read"] = reader.bytes_read
    pack["assessed_count"] = len(assessed)
    pack["relation_scan_complete"] = len(entries) <= 128 and not any(i["reason"] == "read_limit" for i in assessed)
    complete = resolve_relations(assessed) and pack["relation_scan_complete"]
    for item in assessed:
        if query is not None and item["decision_context"]:
            item["context_status"] = "match" if context_key(item) == tuple(query.values()) else "mismatch"
            if item["context_status"] == "mismatch":
                complete = False
    pack["conflict_count"] = sum(i["lifecycle_status"] == "conflict" for i in assessed)
    pack["duplicate_count"] = sum(i["duplicate_of"] is not None for i in assessed)
    dependency = {"policy": "continuity-item-applicability-v3", "root": pack["binding"]["root_id"],
                  "memory": pack["memory_sha256"], "query": query, "limits": limits,
                  "dependencies": sorted((p.relative_to(root).as_posix(), hashlib.sha256(raw).hexdigest())
                                         for p, raw in reader.cache.items()), "assessed": assessed}
    pack["dependency_sha256"] = hashlib.sha256(encode(dependency).encode()).hexdigest()
    if expected_dependency_sha256:
        pack["cache_state"] = "match" if expected_dependency_sha256 == pack["dependency_sha256"] else "mismatch"
        if pack["cache_state"] == "mismatch":
            complete = False
    # A failed relation blocks both its claimant and referenced endpoints, not
    # independent reviewed items. Unknown/open entries remain visible below.
    relation_blocked = set()
    for item in assessed:
        if item["reason"] in {"nonaccepted_superseder", "unresolved_supersedes",
                              "supersedes_context_mismatch", "unresolved_conflict"}:
            relation_blocked.update([item["record_id"], *item["supersedes"], *item["conflicts_with"]])
    # Ranking only after evidence/relations: accepted active decisions cannot be
    # hidden by an earlier superseded pointer. Ties preserve stored order.
    def priority(item):
        active = item["lifecycle_status"] == "active" and item["context_status"] != "mismatch"
        accepted = (item["proof_type"], item["proof_status"]) == ("Decision", "accepted")
        return 0 if active and accepted else (1 if active else (2 if item["lifecycle_status"] == "conflict" else 3))
    pack["items"] = sorted(assessed, key=priority)[:max_entries]
    while True:
        pack["included_count"] = len(pack["items"])
        pack["omitted_count"] = len(entries) - len(pack["items"])
        ready = complete and not pack["omitted_count"] and all(
            i["integrity_status"] == "valid" and i["continuity_state"] == "known" for i in pack["items"])
        pack["pack_status"] = "empty" if not entries else ("conflict" if pack["conflict_count"] else ("ready" if ready else "partial"))
        pack["safety"]["memory_complete"] = pack["pack_status"] in {"ready", "empty"}
        pack["cache_reusable"] = ready and query is not None and pack["cache_state"] == "match"
        for item in pack["items"]:
            item["applicable"] = bool(
                pack["relation_scan_complete"] and not pack["omitted_count"]
                and pack["cache_state"] != "mismatch"
                and item["integrity_status"] == "valid" and item["continuity_state"] == "known"
                and item["context_status"] in {"inventory", "match"}
                and item["lifecycle_status"] == "active" and item["reason"] == "bound_continuity"
                and not item["conflict_criteria"] and item["duplicate_of"] is None
                and item["record_id"] not in relation_blocked
                and (item["proof_type"], item["proof_status"]) in {
                    ("Review", "verified"), ("Decision", "accepted")})
        if len(encode(pack).encode("utf-8")) <= max_pack_bytes:
            return pack
        if not pack["items"]:
            raise ValueError("output budget too small for envelope")
        pack["items"].pop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--memory", default="knowledge-base/_ops/memory/index.json")
    parser.add_argument("--question-key")
    parser.add_argument("--scope")
    parser.add_argument("--as-of")
    parser.add_argument("--expected-dependency-sha256")
    parser.add_argument("--session-handoff", action="store_true",
                        help="read explicitly captured provisional session pointers instead of memory")
    for name, default in (("max-entries", 32), ("max-file-bytes", 262144),
                          ("max-total-bytes", 1048576), ("max-pack-bytes", 32768)):
        parser.add_argument("--" + name, type=int, default=default)
    args = vars(parser.parse_args())
    if args.pop("session_handoff"):
        from session_events import handoff
        pack = handoff(args["root"])
        sys.stdout.write(encode(pack))
        return 2 if pack["pack_status"] == "unverified" else 0
    try:
        pack = build_pack(**args)
    except ValueError:
        parser.error("limit arguments are outside the supported bounds")
    sys.stdout.write(encode(pack))
    return 2 if pack["pack_status"] in {"invalid_memory", "missing_memory"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
