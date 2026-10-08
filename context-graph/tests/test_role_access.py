import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "knowledge-engineering" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import role_access


def _write_fixture(root, *, session_role="analyst", agent_role="analyst", task_scopes=None,
                   assignment_scopes=None, revoked=False):
    policy = {"schema_version": 1, "project_id": "PRJ-test", "revision": "r1", "default_effect": "deny",
              "roles": {"analyst": {"scope_ids": ["scope-a", "scope-shared"]},
                        "editor": {"scope_ids": ["scope-b", "scope-shared"]}}}
    catalog = {"schema_version": 1, "artifacts": {
        "knowledge/a.md": {"scope_ids": ["scope-a"]},
        "knowledge/b.md": {"scope_ids": ["scope-b"]},
        "knowledge/shared.md": {"scope_ids": ["scope-shared"]},
    }}
    binding = {"schema_version": 1, "binding_id": "bind-1", "project_id": "PRJ-test",
               "session_id": "s1", "agent_instance_id": "a1", "task_id": "t1", "assignment_id": "x1",
               "session_role": session_role, "agent_role": agent_role,
               "task_scope_ids": task_scopes or ["scope-a", "scope-shared"],
               "assignment_scope_ids": assignment_scopes or ["scope-a", "scope-shared"],
               "policy_revision": "r1", "issuer": "launcher", "trusted": True, "revoked": revoked}
    policy_path, binding_path, catalog_path = (root / name for name in ("policy.json", "binding.json", "catalog.json"))
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    binding["policy_sha256"] = role_access._digest(policy)
    binding["catalog_sha256"] = role_access._digest(catalog)
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    subject = {"trusted": True, "issuer": "launcher", "project_id": "PRJ-test", "session_id": "s1",
               "agent_instance_id": "a1", "task_id": "t1", "assignment_id": "x1"}
    return role_access.load_access_context(root, "policy.json", "binding.json", "catalog.json", subject)


def test_effective_scope_is_the_full_intersection(tmp_path):
    context = _write_fixture(tmp_path, task_scopes=["scope-a", "scope-shared"],
                             assignment_scopes=["scope-shared"])
    assert role_access.authorize(context)["scope_ids"] == ["scope-shared"]
    assert role_access.authorize_pointer(context, "knowledge/shared.md")
    assert not role_access.authorize_pointer(context, "knowledge/a.md")


def test_unknown_role_and_revoked_binding_fail_closed(tmp_path):
    with pytest.raises(role_access.AccessDenied, match="unknown_role"):
        _write_fixture(tmp_path, session_role="unknown")
    with pytest.raises(role_access.AccessDenied, match="invalid_binding"):
        _write_fixture(tmp_path, revoked=True)


def test_pack_filters_whole_items_before_limits(tmp_path):
    context = _write_fixture(tmp_path)
    pack = {"items": [
        {"id": "allowed", "artifact_pointers": ["knowledge/a.md"]},
        {"id": "foreign", "artifact_pointers": ["knowledge/b.md"]},
        {"id": "mixed", "artifact_pointers": ["knowledge/a.md", "knowledge/b.md"]},
    ], "omitted_count": 0}
    filtered = role_access.filter_pack(context, pack)
    assert [item["id"] for item in filtered["items"]] == ["allowed"]
    assert filtered["harness"] == {"effect": "allow", "scope_ids": ["scope-a", "scope-shared"],
                                    "denied_count": 2, "filtered_before_limits": True}


def test_untrusted_subject_and_uncatalogued_path_are_denied(tmp_path):
    _write_fixture(tmp_path)
    with pytest.raises(role_access.AccessDenied, match="untrusted_subject"):
        role_access.load_access_context(tmp_path, "policy.json", "binding.json", "catalog.json", {})
    context = _write_fixture(tmp_path)
    with pytest.raises(role_access.AccessDenied, match="uncatalogued_artifact"):
        role_access.authorize_pointer(context, "knowledge/unknown.md")
    with pytest.raises(role_access.AccessDenied, match="unsafe_pointer"):
        role_access.authorize_pointer(context, "../secret.txt")


def test_symlinked_policy_path_is_denied(tmp_path):
    context_root = tmp_path / "project"
    context_root.mkdir()
    source = tmp_path / "outside.json"
    source.write_text("{}", encoding="utf-8")
    (context_root / "policy.json").symlink_to(source)
    with pytest.raises(role_access.AccessDenied, match="unsafe_policy_path"):
        role_access.load_access_context(context_root, "policy.json", "binding.json", "catalog.json",
                                        {"trusted": True})
