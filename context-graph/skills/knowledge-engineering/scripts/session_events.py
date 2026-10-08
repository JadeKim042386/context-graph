"""Explicit, project-bound provisional events; no hooks or automatic promotion."""
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from build_task_continuity import (ACTIONS, CONSTRAINTS, HASH, BoundedReader, ReadLimit,
                                   integrity, safe_pointer, strict_json)

CONFIG = "knowledge-base/_ops/session-capture.json"
STORE = "knowledge-base/_ops/session-events-v3"
MAX_INPUT = 16384
MAX_EVENTS = 128
MAX_ITEMS = 16
MAX_PACK = 32768
EVENTS = {"pre_compact", "post_compact", "session_end"}
RUNTIMES = {"codex", "claude-code"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
PAYLOAD_KEYS_V1 = {"schema_version", "session_id", "invocation_id", "occurred_at",
                   "artifact_pointers", "required_constraints", "next_actions"}
PAYLOAD_KEYS_V2 = PAYLOAD_KEYS_V1 | {"attribution"}
RECORD_KEYS_V3 = {"schema_version", "record_type", "event_id", "project_id", "session_id",
               "invocation_id", "event_type", "occurred_at", "runtime", "status", "review_state",
               "artifact_pointers", "required_constraints", "next_actions", "provenance", "record_sha256"}
RECORD_KEYS_V4 = RECORD_KEYS_V3 | {"attribution"}


class CaptureError(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode()


def local(root, relative):
    """Reject even in-root symlinks for journal/config identity and publication."""
    path, _ = safe_pointer(root, relative)
    cursor = root
    for part in Path(relative.partition("#")[0]).parts:
        cursor /= part
        if cursor.is_symlink():
            raise CaptureError("unsafe_path")
    return path


def read_bytes(path, bound):
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > bound:
        raise CaptureError("read_limit")
    with path.open("rb") as stream:
        raw = stream.read(bound + 1)
    if len(raw) > bound:
        raise CaptureError("read_limit")
    return raw


def binding(root):
    root = Path(root).resolve()
    if not root.is_dir() or not Path.cwd().resolve().is_relative_to(root):
        raise CaptureError("cwd_mismatch")
    path = local(root, CONFIG)
    try:
        raw = read_bytes(path, MAX_INPUT)
        config = strict_json(raw)
        if not isinstance(config, dict) or type(config.get("schema_version")) is not int or config["schema_version"] != 1:
            raise ValueError()
    except FileNotFoundError as exc:
        raise CaptureError("missing_config") from exc
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise CaptureError("invalid_config") from exc
    if config.get("enabled") is not True:
        raise CaptureError("capture_disabled")
    project_id = "PRJ-" + sha(str(root).encode())[:16]
    if config.get("project_id") != project_id:
        raise CaptureError("project_binding_mismatch")
    if any(config.get(k) is not False for k in ("capture_content", "capture_commands", "capture_untracked")):
        raise CaptureError("unsafe_config")
    includes = config.get("include_globs")
    if (config.get("tracked_paths_only") is not True or not isinstance(includes, list)
            or not 1 <= len(includes) <= 32 or not all(isinstance(v, str) and 0 < len(v) <= 200 for v in includes)):
        raise CaptureError("unsafe_config")
    return root, config, project_id, sha(raw)


def codes(value, allowed):
    if not isinstance(value, list) or len(value) > len(allowed) or not all(isinstance(v, str) and v in allowed for v in value):
        raise CaptureError("invalid_payload")
    if len(set(value)) != len(value):
        raise CaptureError("invalid_payload")
    return sorted(value)


def content_fields(root, config, data):
    time = data.get("occurred_at")
    if not isinstance(time, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", time):
        raise CaptureError("invalid_payload")
    try:
        datetime.strptime(time, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise CaptureError("invalid_payload") from exc
    pointers = data.get("artifact_pointers")
    if not isinstance(pointers, list) or not 1 <= len(pointers) <= 8:
        raise CaptureError("invalid_payload")
    seen = set()
    for item in pointers:
        if not isinstance(item, dict) or set(item) != {"pointer", "revision_sha256"}:
            raise CaptureError("invalid_payload")
        pointer, digest = item["pointer"], item["revision_sha256"]
        local(root, pointer)
        if pointer in seen or not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise CaptureError("invalid_payload")
        seen.add(pointer)
        name = pointer.partition("#")[0]
        if name.startswith("knowledge-base/_ops/") or not any(fnmatch(name, glob) for glob in config["include_globs"]):
            raise CaptureError("pointer_outside_capture_scope")
    return {"occurred_at": time, "artifact_pointers": sorted(pointers, key=lambda i: i["pointer"]),
            "required_constraints": codes(data.get("required_constraints"), CONSTRAINTS),
            "next_actions": codes(data.get("next_actions"), ACTIONS)}


def event_id(record):
    return "SEV-" + sha(encode([record[k] for k in ("project_id", "session_id", "invocation_id", "runtime", "event_type")]))


def attribution_fields(project_id, data):
    attribution = data.get("attribution")
    if (not isinstance(attribution, dict)
            or set(attribution) != {"agent_instance_id", "task_id", "assignment_id", "reassigned_from_event_id"}
            or any(not isinstance(attribution[key], str) or not UUID.fullmatch(attribution[key])
                   for key in ("agent_instance_id", "task_id", "assignment_id"))):
        raise CaptureError("invalid_attribution")
    predecessor = attribution["reassigned_from_event_id"]
    if predecessor is not None and (not isinstance(predecessor, str)
                                    or not re.fullmatch(r"SEV-[0-9a-f]{64}", predecessor)):
        raise CaptureError("invalid_attribution")
    task_key = sha(encode(["task-v1", project_id, attribution["task_id"]]))
    return {"agent_instance_id": sha(encode(["agent-instance-v1", project_id, attribution["agent_instance_id"]])),
            "task_id": task_key,
            "assignment_id": sha(encode(["assignment-v1", project_id, task_key, attribution["assignment_id"]])),
            "reassigned_from_event_id": predecessor, "basis": "caller_supplied"}


def make_record(root, config, project_id, config_sha, event, runtime, raw):
    if len(raw) > MAX_INPUT or event not in EVENTS or runtime not in RUNTIMES:
        raise CaptureError("invalid_payload")
    data = strict_json(raw)
    version = data.get("schema_version") if isinstance(data, dict) else None
    payload_keys = PAYLOAD_KEYS_V2 if version == 2 else PAYLOAD_KEYS_V1
    if (not isinstance(data, dict) or set(data) != payload_keys or type(data["schema_version"]) is not int
            or version not in (1, 2) or not all(isinstance(data[k], str) and UUID.fullmatch(data[k]) for k in ("session_id", "invocation_id"))):
        raise CaptureError("invalid_payload")
    if version not in (1, 2):
        raise CaptureError("invalid_payload")
    attribution = attribution_fields(project_id, data) if version == 2 else None
    record = {"schema_version": 3, "record_type": "SessionLifecycleEvent", "project_id": project_id,
              "session_id": sha(encode([project_id, data["session_id"]])),
              "invocation_id": sha(data["invocation_id"].encode()), "runtime": runtime, "event_type": event,
              "status": "provisional", "review_state": "not_reviewed",
              "provenance": {"method": "explicit_capture_v3", "config_sha256": config_sha},
              **content_fields(root, config, data)}
    if attribution is not None:
        record["schema_version"] = 4
        record["provenance"]["method"] = "explicit_capture_v4"
        record["attribution"] = attribution
    record["event_id"] = event_id(record)
    record["record_sha256"] = sha(encode(record))
    return record


def validate_record(root, config, project_id, raw, name):
    try:
        record = strict_json(raw)
        version = record.get("schema_version") if isinstance(record, dict) else None
        expected_keys = RECORD_KEYS_V4 if version == 4 else RECORD_KEYS_V3
        if (not isinstance(record, dict) or set(record) != expected_keys or type(record["schema_version"]) is not int
                or version not in (3, 4) or record["project_id"] != project_id
                or record["record_type"] != "SessionLifecycleEvent" or record["status"] != "provisional"
                or record["review_state"] != "not_reviewed" or record["runtime"] not in RUNTIMES
                or record["event_type"] not in EVENTS):
            raise ValueError()
        for key in ("session_id", "invocation_id", "record_sha256"):
            if not isinstance(record[key], str) or not HASH.fullmatch(record[key]):
                raise ValueError()
        provenance = record["provenance"]
        if (not isinstance(provenance, dict) or set(provenance) != {"method", "config_sha256"}
                or provenance["method"] != ("explicit_capture_v4" if version == 4 else "explicit_capture_v3")
                or not isinstance(provenance["config_sha256"], str)
                or not HASH.fullmatch(provenance["config_sha256"])):
            raise ValueError()
        if version == 4:
            attribution = record["attribution"]
            if (set(attribution) != {"agent_instance_id", "task_id", "assignment_id", "reassigned_from_event_id", "basis"}
                    or attribution["basis"] != "caller_supplied"
                    or any(not isinstance(attribution[key], str) or not HASH.fullmatch(attribution[key])
                           for key in ("agent_instance_id", "task_id", "assignment_id"))
                    or (attribution["reassigned_from_event_id"] is not None
                        and not re.fullmatch(r"SEV-[0-9a-f]{64}", attribution["reassigned_from_event_id"]))):
                raise ValueError()
        fields = content_fields(root, config, record)
        if any(record[key] != value for key, value in fields.items()):
            raise ValueError()
        unsigned = {k: v for k, v in record.items() if k != "record_sha256"}
        if (record["event_id"] != event_id(record) or name != record["event_id"] + ".json"
                or record["record_sha256"] != sha(encode(unsigned))):
            raise ValueError()
        return record
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, integrity.IntegrityError) as exc:
        raise CaptureError("invalid_event") from exc


def records(root, config, project_id):
    store = local(root, STORE)
    if not store.exists():
        return []
    found = []
    with os.scandir(store) as entries:
        for entry in entries:
            if entry.name.startswith(".pending-"):
                continue  # unpublished crash residue is not an event
            if len(found) >= MAX_EVENTS:
                raise CaptureError("journal_limit")
            if not re.fullmatch(r"SEV-[0-9a-f]{64}\.json", entry.name):
                raise CaptureError("invalid_journal")
            path = local(root, f"{STORE}/{entry.name}")
            raw = read_bytes(path, MAX_INPUT)
            found.append((validate_record(root, config, project_id, raw, entry.name), raw))
    return sorted(found, key=lambda pair: (pair[0]["occurred_at"], pair[0]["event_id"]))


def pointer_state(root, record, reader):
    # Respect the existing tracked-only opt-in; explicit selection is not an override.
    # Ignore foreign Git environment bindings and disable optional index writes.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    command = ["git", "--literal-pathspecs", "-C", str(root), "-c", "core.fsmonitor=false"]
    try:
        top = subprocess.run(command + ["rev-parse", "--show-toplevel"], env=env,
                             capture_output=True, text=True, timeout=5)
        if top.returncode or Path(top.stdout.strip()).resolve() != root:
            return "unverified"
        selected = [item["pointer"].partition("#")[0] for item in record["artifact_pointers"]]
        tracked = subprocess.run(command + ["ls-files", "--error-unmatch", "--", *selected],
                                 env=env, capture_output=True, text=True, timeout=5)
        if tracked.returncode:
            return "unverified"
    except (OSError, subprocess.SubprocessError):
        return "unverified"
    states = []
    for item in record["artifact_pointers"]:
        try:
            safe_pointer(root, item["pointer"])
            integrity.checked_bytes(root, item["pointer"], item["revision_sha256"], set(), reader=reader.read)
            states.append("valid")
        except integrity.IntegrityError as exc:
            states.append(exc.state)
        except ReadLimit:
            states.append("unknown")
    return next((s for s in ("unlocatable", "stale", "unknown", "unverified") if s in states), "valid")


def capture(root, event, runtime, raw):
    """Publish a complete new file with no replacement; identical replay is a no-op."""
    try:
        root, config, project_id, config_sha = binding(root)
        record = make_record(root, config, project_id, config_sha, event, runtime, raw)
        existing = records(root, config, project_id)
        serialized = encode(record)
        target = local(root, f"{STORE}/{record['event_id']}.json")
        for old, old_raw in existing:
            if old["event_id"] == record["event_id"]:
                if old_raw != serialized:
                    raise CaptureError("event_id_conflict")
                return {"status": "duplicate", "event_id": record["event_id"], "pointer": target.relative_to(root).as_posix()}
        attribution = record.get("attribution")
        if attribution:
            for old, _ in existing:
                old_attr = old.get("attribution")
                if (old_attr and old_attr["assignment_id"] == attribution["assignment_id"]
                        and (old_attr["agent_instance_id"], old_attr["task_id"], old_attr["reassigned_from_event_id"])
                        != (attribution["agent_instance_id"], attribution["task_id"], attribution["reassigned_from_event_id"])):
                    raise CaptureError("assignment_conflict")
        predecessor = record.get("attribution", {}).get("reassigned_from_event_id")
        if predecessor:
            prior = next((old for old, _ in existing if old["event_id"] == predecessor), None)
            if (prior is None or prior.get("schema_version") != 4
                    or prior["attribution"]["task_id"] != record["attribution"]["task_id"]
                    or prior["attribution"]["assignment_id"] == record["attribution"]["assignment_id"]):
                raise CaptureError("invalid_attribution")
        if len(existing) >= MAX_EVENTS:
            raise CaptureError("journal_limit")
        if pointer_state(root, record, BoundedReader(root, 262144, 2097152)) != "valid":
            raise CaptureError("pointer_not_verified")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".pending-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if read_bytes(target, MAX_INPUT) != serialized:
                    raise CaptureError("event_id_conflict")
                try:
                    from session_knowledge import merge_session
                    merge_session(root, session_key=record["session_id"], rebuild_projection=(event == "session_end"))
                except Exception:
                    pass
                return {"status": "duplicate", "event_id": record["event_id"], "pointer": target.relative_to(root).as_posix()}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        try:
            from session_knowledge import merge_session
            merge_session(root, session_key=record["session_id"], rebuild_projection=(event == "session_end"))
        except Exception:
            pass
        return {"status": "captured", "event_id": record["event_id"], "pointer": target.relative_to(root).as_posix()}
    except CaptureError as exc:
        return {"status": "unverified", "reason": str(exc)}
    except integrity.IntegrityError:
        return {"status": "unverified", "reason": "unsafe_pointer"}
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return {"status": "unverified", "reason": "invalid_or_unreadable"}


def _selection_keys(project_id, *, session_id=None, runtime=None, invocation_ids=None,
                    agent_instance_id=None, task_id=None, assignment_id=None):
    """Validate caller-supplied scope without inventing task or agent identity."""
    scoped = any(value is not None for value in (session_id, runtime, invocation_ids,
                                                agent_instance_id, task_id, assignment_id))
    if not scoped:
        return None
    if not (isinstance(session_id, str) and UUID.fullmatch(session_id)
            and runtime in RUNTIMES):
        raise CaptureError("invalid_selection")
    if invocation_ids is not None:
        if (not isinstance(invocation_ids, (list, tuple)) or not invocation_ids
                or len(invocation_ids) > MAX_EVENTS
                or any(not isinstance(value, str) or not UUID.fullmatch(value) for value in invocation_ids)
                or len(set(invocation_ids)) != len(invocation_ids)):
            raise CaptureError("invalid_selection")
    for value in (agent_instance_id, task_id, assignment_id):
        if value is not None and (not isinstance(value, str) or not UUID.fullmatch(value)):
            raise CaptureError("invalid_selection")
    if assignment_id is not None and task_id is None:
        raise CaptureError("invalid_selection")
    invocation_keys = sorted({sha(value.encode()) for value in invocation_ids or []})
    return {"version": 1, "mode": "session_and_invocations" if invocation_keys else "session",
            "session_key": sha(encode([project_id, session_id])), "runtime": runtime,
            "invocation_keys": invocation_keys, "membership_basis": "caller_supplied",
            "agent_key": sha(encode(["agent-instance-v1", project_id, agent_instance_id])) if agent_instance_id else None,
            "task_key": sha(encode(["task-v1", project_id, task_id])) if task_id else None,
            "assignment_key": sha(encode(["assignment-v1", project_id,
                                           sha(encode(["task-v1", project_id, task_id])), assignment_id]))
            if assignment_id else None}


def _matches_selection(record, selection):
    if selection is None:
        return True
    attribution = record.get("attribution")
    return (record["session_id"] == selection["session_key"]
            and record["runtime"] == selection["runtime"]
            and (not selection["invocation_keys"] or record["invocation_id"] in selection["invocation_keys"])
            and (selection["agent_key"] is None or (attribution and attribution["agent_instance_id"] == selection["agent_key"]))
            and (selection["task_key"] is None or (attribution and attribution["task_id"] == selection["task_key"]))
            and (selection["assignment_key"] is None or (attribution and attribution["assignment_id"] == selection["assignment_key"])))


def _assignment_relations(found):
    """Classify bounded attribution links without inferring ownership."""
    by_event = {record["event_id"]: record for record, _ in found}
    by_assignment = {}
    successors = {}
    states = {}
    for record, _ in found:
        attribution = record.get("attribution")
        if not attribution:
            continue
        event_id = record["event_id"]
        assignment = attribution["assignment_id"]
        signature = (attribution["agent_instance_id"], attribution["task_id"],
                     attribution["reassigned_from_event_id"])
        previous = by_assignment.get(assignment)
        if previous and previous[1] != signature:
            states[event_id] = "conflict"
            states[previous[0]] = "conflict"
        else:
            by_assignment[assignment] = (event_id, signature)
        predecessor = attribution["reassigned_from_event_id"]
        if predecessor:
            prior = by_event.get(predecessor)
            if (prior is None or prior.get("schema_version") != 4
                    or prior["attribution"]["task_id"] != attribution["task_id"]
                    or prior["attribution"]["assignment_id"] == assignment):
                states[event_id] = "unverified"
            successors.setdefault(predecessor, []).append((event_id, assignment))
    for children in successors.values():
        assignments = {assignment for _, assignment in children}
        if len(assignments) > 1:
            for event_id, _ in children:
                states[event_id] = "conflict"
    return states


def handoff(root, *, session_id=None, runtime=None, invocation_ids=None,
            agent_instance_id=None, task_id=None, assignment_id=None,
            include_attribution=False, harness_context=None):
    """Session evidence remains provisional even when its bytes/locators replay."""
    pack = {"schema_version": 1, "kind": "session_continuity", "read_only": True,
            "promotion_performed": False, "pack_status": "unverified", "reason": "unknown",
            "items": [], "total_count": 0, "included_count": 0, "omitted_count": 0,
            "max_pack_bytes": MAX_PACK, "source_bytes_read": 0}
    try:
        root, config, project_id, config_sha = binding(root)
        selection = _selection_keys(project_id, session_id=session_id, runtime=runtime,
                                    invocation_ids=invocation_ids, agent_instance_id=agent_instance_id,
                                    task_id=task_id, assignment_id=assignment_id)
        if selection is not None:
            pack["selection"] = {**selection, "scope_matched": False,
                                  "missing_invocation_count": 0}
            for key in ("agent_key", "task_key", "assignment_key"):
                pack["selection"].pop(key, None)
        attribution_view = include_attribution or any(value is not None for value in
                                                      (agent_instance_id, task_id, assignment_id))
        if attribution_view:
            pack["schema_version"] = 2
        pack["binding"] = {"project_id": project_id, "config_sha256": config_sha,
                           "status": "verified", "config_map_state": "not_used"}
        found = records(root, config, project_id)
        relation_states = _assignment_relations(found)
        if selection is not None:
            selected = [(record, raw) for record, raw in found if _matches_selection(record, selection)]
            pack["selection"]["scope_matched"] = bool(selected)
            if selection["invocation_keys"]:
                present = {record["invocation_id"] for record, _ in selected}
                pack["selection"]["missing_invocation_count"] = len(
                    set(selection["invocation_keys"]) - present)
        else:
            selected = found
        if harness_context is not None:
            from role_access import AccessDenied, authorize, authorize_pointer
            try:
                decision = authorize(harness_context, action="handoff")
                authorized = []
                for record, raw in selected:
                    pointers = [item["pointer"] for item in record.get("artifact_pointers", [])]
                    if pointers and all(authorize_pointer(harness_context, pointer) for pointer in pointers):
                        authorized.append((record, raw))
                pack["harness"] = {"effect": decision["effect"], "scope_ids": decision["scope_ids"],
                                    "denied_count": len(selected) - len(authorized),
                                    "filtered_before_limits": True}
                selected = authorized
            except AccessDenied as exc:
                pack.update(reason=str(exc), items=[])
                return pack
        pack["total_count"] = len(selected)
        reader = BoundedReader(root, 262144, 2097152)
        for record, raw in selected[-MAX_ITEMS:]:
            state = pointer_state(root, record, reader)
            if record["provenance"]["config_sha256"] != config_sha:
                state = "unverified"
            item = {"pointer": f"{STORE}/{record['event_id']}.json", "revision_sha256": sha(raw),
                "event_id": record["event_id"], "session_id": record["session_id"], "event_type": record["event_type"],
                "occurred_at": record["occurred_at"], "runtime": record["runtime"], "integrity_status": state,
                "status": "provisional", "review_state": "not_reviewed", "applicable": False,
                "artifact_pointers": record["artifact_pointers"], "required_constraints": record["required_constraints"],
                "next_actions": record["next_actions"]}
            if attribution_view:
                item["actor_state"] = "declared" if record.get("schema_version") == 4 else "actor_unknown"
                item["attribution"] = record.get("attribution")
                item["attribution_status"] = relation_states.get(
                    record["event_id"], "declared" if record.get("schema_version") == 4 else "unknown")
            pack["items"].append(item)
        pack["source_bytes_read"] = reader.bytes_read
        while True:
            pack["included_count"] = len(pack["items"])
            pack["omitted_count"] = len(selected) - len(pack["items"])
            missing = pack.get("selection", {}).get("missing_invocation_count", 0)
            relation_ok = not attribution_view or all(
                i["attribution_status"] in {"declared", "unknown"} for i in pack["items"])
            ready = (not pack["omitted_count"] and not missing and relation_ok
                     and all(i["integrity_status"] == "valid" for i in pack["items"]))
            pack["pack_status"] = "empty" if not selected else ("ready" if ready else "partial")
            pack["reason"] = "provisional_only"
            if len(encode(pack)) <= MAX_PACK:
                return pack
            pack["items"].pop(0)
    except CaptureError as exc:
        pack.update(reason=str(exc), items=[])
    except integrity.IntegrityError:
        pack.update(reason="unsafe_pointer", items=[])
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        pack.update(reason="invalid_or_unreadable", items=[])
    return pack
