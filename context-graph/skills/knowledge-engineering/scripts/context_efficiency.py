#!/usr/bin/env python3
"""Build bounded, pointer-first context packs and safely reuse exact results."""
from __future__ import annotations

import hashlib
import json
from typing import Any


class ContextPackError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def query_key(*, project_id: str, question_key: str, scope: str, as_of: str,
              dependency_digest: str) -> str:
    """The cache key excludes session/agent identity so equivalent work can reuse knowledge."""
    if not all(isinstance(value, str) and value for value in (project_id, question_key, scope, as_of, dependency_digest)) or len(dependency_digest) != 64:
        raise ContextPackError("query_key_required")
    return digest(["context-pack-v1", project_id, question_key, scope, as_of, dependency_digest])


def _identity(item: dict) -> str:
    base = next((item[key] for key in ("canonical_id", "claim_id", "evidence_id", "source_id", "id", "pointer")
                 if isinstance(item.get(key), str) and item[key]), None)
    if base is None:
        return "digest:" + digest(item)
    try:
        version = digest({"sha256": item.get("sha256"), "value": item.get("value"), "locator": item.get("locator"),
                          "source_refs": item.get("source_refs"), "status": item.get("status"),
                          "rights": item.get("rights"), "evidence_status": item.get("evidence_status")})
    except (TypeError, ValueError):
        version = "invalid"
    return f"identity:{base}:version:{version}"


def _withheld(item: dict) -> bool:
    status = item.get("status")
    rights = item.get("rights")
    evidence_status = item.get("evidence_status")
    bad_status = status in {"conflict", "stale", "retracted", "superseded"}
    bad_rights = rights is not None and (not isinstance(rights, str) or rights not in {"verified", "accepted", "approved"})
    bad_evidence = evidence_status is not None and (not isinstance(evidence_status, str) or evidence_status not in {"verified", "accepted", "approved"})
    return bad_status or bad_rights or bad_evidence


def _minimal(item: dict, *, include_content: bool) -> dict:
    """Keep locators and provenance, omit repeated body text by default."""
    allowed = ("canonical_id", "claim_id", "evidence_id", "source_id", "id", "record_type",
               "pointer", "sha256", "locator", "source_refs", "provenance", "claim_key", "conditions",
               "rights", "license", "status", "evidence_status", "superseded_by", "review_pointer", "review_sha256")
    result = {key: item[key] for key in allowed if key in item}
    if "provenance" in item:
        result.pop("provenance", None)
        result["provenance_digest"] = digest(item["provenance"])
    withheld = _withheld(item)
    if include_content and "value" in item and not withheld:
        result["value"] = item["value"]
    elif withheld:
        result["content_withheld"] = True
    return result


def build_pack(items: list[dict], *, query: str, query_key_value: str, query_context: dict,
               dependency_digest: str,
               max_items: int = 32, max_bytes: int = 32768, include_content: bool = False) -> dict:
    if not isinstance(items, list) or len(items) > 10000 or not isinstance(query, str) or not query_key_value or not isinstance(query_context, dict) or not isinstance(dependency_digest, str) or len(dependency_digest) != 64:
        raise ContextPackError("pack_input")
    required_context = ("project_id", "question_key", "scope", "as_of")
    if set(query_context) != set(required_context) or not all(isinstance(query_context[key], str) and query_context[key] for key in required_context):
        raise ContextPackError("query_context")
    if query_key(**query_context, dependency_digest=dependency_digest) != query_key_value:
        raise ContextPackError("query_key_mismatch")
    if type(max_items) is not int or max_items < 1 or max_items > 256 or type(max_bytes) is not int or max_bytes < 512 or max_bytes > 1 << 20:
        raise ContextPackError("pack_budget")
    selected, seen = [], set()
    version_conflicts = 0
    omitted = 0
    omitted_reasons = {}
    candidates = sorted((item for item in items if isinstance(item, dict)), key=_identity)
    omitted += len(items) - len(candidates)
    if len(items) != len(candidates):
        omitted_reasons["invalid_item"] = len(items) - len(candidates)
    for raw in candidates:
        if not isinstance(raw, dict):
            omitted += 1
            continue
        pointer = raw.get("pointer")
        if pointer is not None and (not isinstance(pointer, str) or pointer.startswith("/") or ".." in pointer.split("/") or "\\" in pointer):
            omitted += 1
            omitted_reasons["unsafe_pointer"] = omitted_reasons.get("unsafe_pointer", 0) + 1
            continue
        if "sha256" in raw and (not isinstance(raw["sha256"], str) or len(raw["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in raw["sha256"])):
            omitted += 1
            omitted_reasons["invalid_sha256"] = omitted_reasons.get("invalid_sha256", 0) + 1
            continue
        identity = _identity(raw)
        base_identity = identity.split(":version:", 1)[0]
        if identity in seen:
            omitted += 1
            continue
        if any(existing.startswith(base_identity + ":version:") for existing in seen):
            version_conflicts += 1
        if len(selected) >= max_items:
            omitted += 1
            continue
        try:
            candidate = _minimal(raw, include_content=include_content)
            _canonical(candidate)
        except (TypeError, ValueError):
            omitted += 1
            omitted_reasons["unserializable"] = omitted_reasons.get("unserializable", 0) + 1
            continue
        trial = {"schema_version": 1, "record_type": "ContextPack", "query": query,
                 "query_key": query_key_value, "dependency_digest": dependency_digest,
                 "query_context": query_context,
                 "budget_unit": "canonical_ascii_json_bytes", "items": selected + [candidate],
                 "included_count": len(selected) + 1, "omitted_count": omitted,
                 "version_conflicts": version_conflicts, "omitted_reasons": omitted_reasons,
                 "content_mode": "full" if include_content else "pointer_first",
                 "pack_sha256": "0" * 64, "utf8_bytes": 0,
                 "item_chars": sum(len(json.dumps(i, ensure_ascii=False, allow_nan=False)) for i in selected + [candidate])}
        if len(_canonical(trial)) > max_bytes:
            omitted += 1
            omitted_reasons["budget"] = omitted_reasons.get("budget", 0) + 1
            continue
        seen.add(identity)
        selected.append(candidate)
    pack = {"schema_version": 1, "record_type": "ContextPack", "query": query,
            "query_key": query_key_value, "dependency_digest": dependency_digest,
            "query_context": query_context,
            "budget_unit": "canonical_ascii_json_bytes", "items": selected, "included_count": len(selected),
            "omitted_count": omitted, "version_conflicts": version_conflicts,
            "omitted_reasons": omitted_reasons, "content_mode": "full" if include_content else "pointer_first", "pack_sha256": "0" * 64,
            "utf8_bytes": 0, "item_chars": sum(len(json.dumps(i, ensure_ascii=False, allow_nan=False)) for i in selected)}
    for _ in range(5):
        pack["pack_sha256"] = digest({key: value for key, value in pack.items() if key != "pack_sha256"})
        pack["utf8_bytes"] = len(json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    pack["pack_sha256"] = digest({key: value for key, value in pack.items() if key != "pack_sha256"})
    while len(_canonical(pack)) > max_bytes and selected:
        selected.pop()
        omitted += 1
        pack["items"] = selected
        pack["included_count"] = len(selected)
        pack["omitted_count"] = omitted
        pack["omitted_reasons"]["budget"] = pack["omitted_reasons"].get("budget", 0) + 1
        pack["item_chars"] = sum(len(json.dumps(i, ensure_ascii=False, allow_nan=False)) for i in selected)
        pack["pack_sha256"] = "0" * 64
        for _ in range(5):
            pack["pack_sha256"] = digest({key: value for key, value in pack.items() if key != "pack_sha256"})
            pack["utf8_bytes"] = len(json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        pack["pack_sha256"] = digest({key: value for key, value in pack.items() if key != "pack_sha256"})
    if len(_canonical(pack)) > max_bytes:
        raise ContextPackError("pack_budget")
    return pack


def reuse(pack: dict, *, query_key_value: str, current_dependency_digest: str) -> dict:
    """Return a small reuse decision; never returns cached body content itself."""
    if not isinstance(pack, dict) or pack.get("record_type") != "ContextPack" or not isinstance(pack.get("items"), list):
        return {"decision": "bounded_reload", "reason": "invalid_pack"}
    if not isinstance(pack.get("query_context"), dict) or pack.get("included_count") != len(pack["items"]):
        return {"decision": "bounded_reload", "reason": "pack_inconsistent"}
    if any(not isinstance(item, dict) for item in pack["items"]):
        return {"decision": "bounded_reload", "reason": "invalid_pack"}
    expected = pack.get("pack_sha256")
    actual = digest({key: value for key, value in pack.items() if key != "pack_sha256"}) if isinstance(expected, str) else None
    if expected != actual:
        return {"decision": "bounded_reload", "reason": "pack_tampered"}
    try:
        derived = query_key(**pack["query_context"], dependency_digest=pack.get("dependency_digest", ""))
    except ContextPackError:
        return {"decision": "bounded_reload", "reason": "query_key_mismatch"}
    if derived != pack.get("query_key") or derived != query_key_value:
        return {"decision": "bounded_reload", "reason": "query_key_mismatch"}
    if pack.get("dependency_digest") != current_dependency_digest:
        return {"decision": "bounded_reload", "reason": "dependencies_changed"}
    return {"decision": "reuse_pointer_pack", "reason": "exact_query_and_dependencies", "pack_sha256": pack.get("pack_sha256"),
            "item_count": len(pack.get("items", []))}
