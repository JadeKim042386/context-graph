"""Fail-closed, project-bound role authorization for knowledge harnesses."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class AccessDenied(ValueError):
    pass


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise AccessDenied("unsafe_policy_path")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise AccessDenied("invalid_policy_json") from exc
    if not isinstance(data, dict):
        raise AccessDenied("invalid_policy_shape")
    return data


def _inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or os.path.isabs(relative):
        raise AccessDenied("unsafe_policy_path")
    cursor = root
    for part in Path(relative).parts:
        if part in ("", "."):
            continue
        cursor /= part
        if cursor.is_symlink():
            raise AccessDenied("unsafe_policy_path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise AccessDenied("unsafe_policy_path")
    return path


def load_access_context(root: str | Path, policy: str, binding: str,
                        catalog: str, subject: dict) -> dict:
    """Load and validate launcher-provided policy, binding and catalog."""
    root = Path(root).resolve()
    if not root.is_dir() or not isinstance(subject, dict) or subject.get("trusted") is not True:
        raise AccessDenied("untrusted_subject")
    paths = [_inside(root, item) for item in (policy, binding, catalog)]
    policy_data, binding_data, catalog_data = (_read_json(item) for item in paths)
    if policy_data.get("schema_version") != 1 or policy_data.get("default_effect") != "deny":
        raise AccessDenied("invalid_policy")
    if binding_data.get("schema_version") != 1 or binding_data.get("revoked") is True:
        raise AccessDenied("invalid_binding")
    if catalog_data.get("schema_version") != 1:
        raise AccessDenied("invalid_catalog")
    if binding_data.get("project_id") != policy_data.get("project_id"):
        raise AccessDenied("project_mismatch")
    if subject.get("project_id") != policy_data.get("project_id"):
        raise AccessDenied("subject_project_mismatch")
    if subject.get("issuer") != binding_data.get("issuer") or binding_data.get("trusted") is not True:
        raise AccessDenied("untrusted_issuer")
    if binding_data.get("policy_revision") != policy_data.get("revision"):
        raise AccessDenied("stale_policy")
    if binding_data.get("policy_sha256") != _digest(policy_data):
        raise AccessDenied("policy_digest_mismatch")
    if binding_data.get("catalog_sha256") != _digest(catalog_data):
        raise AccessDenied("catalog_digest_mismatch")
    for key in ("session_id", "agent_instance_id", "task_id", "assignment_id"):
        if subject.get(key) != binding_data.get(key):
            raise AccessDenied("subject_binding_mismatch")
    session_role, agent_role = binding_data.get("session_role"), binding_data.get("agent_role")
    roles = policy_data.get("roles")
    if not isinstance(roles, dict) or session_role not in roles or agent_role not in roles:
        raise AccessDenied("unknown_role")
    if not isinstance(catalog_data.get("artifacts"), dict):
        raise AccessDenied("invalid_catalog")
    return {"root": root, "policy": policy_data, "binding": binding_data, "catalog": catalog_data,
            "session_role": session_role, "agent_role": agent_role}


def _scope_set(context: dict) -> set[str]:
    policy, binding = context["policy"], context["binding"]
    roles = policy["roles"]
    allowed = set(roles[context["session_role"]].get("scope_ids", []))
    allowed &= set(roles[context["agent_role"]].get("scope_ids", []))
    for cap in (binding.get("task_scope_ids"), binding.get("assignment_scope_ids")):
        if not isinstance(cap, list):
            raise AccessDenied("missing_scope_cap")
        allowed &= set(cap)
    return allowed


def authorize(context: dict, *, action: str = "read") -> dict:
    if action not in {"read", "handoff", "continuity", "audit"}:
        raise AccessDenied("unsupported_action")
    scopes = _scope_set(context)
    if not scopes:
        raise AccessDenied("empty_scope_intersection")
    return {"effect": "allow", "action": action, "scope_ids": sorted(scopes),
            "policy_revision": context["policy"]["revision"],
            "binding_id": context["binding"].get("binding_id")}


def authorize_pointer(context: dict, pointer: str) -> bool:
    """Return true only when a cataloged pointer has all required scopes allowed."""
    if not isinstance(pointer, str) or pointer.startswith("/") or ".." in Path(pointer).parts:
        raise AccessDenied("unsafe_pointer")
    item = context["catalog"]["artifacts"].get(pointer)
    if not isinstance(item, dict) or not isinstance(item.get("scope_ids"), list):
        raise AccessDenied("uncatalogued_artifact")
    return set(item["scope_ids"]).issubset(_scope_set(context))


def filter_pack(context: dict, pack: dict) -> dict:
    """Filter a pack before ranking/truncation; mixed or unknown items are withheld."""
    decision = authorize(context, action="continuity")
    result = dict(pack)
    visible, denied = [], 0
    for item in pack.get("items", []):
        pointers = item.get("artifact_pointers") or [item.get("source_file")]
        try:
            allowed = bool(pointers) and all(authorize_pointer(context, pointer) for pointer in pointers)
        except AccessDenied:
            allowed = False
        if allowed:
            visible.append(item)
        else:
            denied += 1
    result["items"] = visible
    result["total_count"] = len(visible)
    result["included_count"] = len(visible)
    result["omitted_count"] = int(pack.get("omitted_count", 0)) + denied
    result["harness"] = {"effect": decision["effect"], "scope_ids": decision["scope_ids"],
                          "denied_count": denied, "filtered_before_limits": True}
    return result
