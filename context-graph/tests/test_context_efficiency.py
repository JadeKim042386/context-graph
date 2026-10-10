import sys
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "knowledge-engineering" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import context_efficiency as ce


def test_pointer_first_pack_deduplicates_and_stays_bounded():
    key = ce.query_key(project_id="P", question_key="q", scope="s", as_of="2026-10-10", dependency_digest="a" * 64)
    items = [
        {"canonical_id": "K1", "record_type": "CanonicalKnowledgeRecord", "value": "long body", "pointer": "knowledge/a.html", "locator": "line:4", "provenance": {"session_id": "S1"}},
        {"canonical_id": "K1", "record_type": "CanonicalKnowledgeRecord", "value": "duplicate", "pointer": "knowledge/a.html"},
        {"canonical_id": "K2", "value": "another", "pointer": "knowledge/b.html"},
    ]
    context = {"project_id": "P", "question_key": "q", "scope": "s", "as_of": "2026-10-10"}
    pack = ce.build_pack(items, query="q", query_key_value=key, query_context=context, dependency_digest="a" * 64, max_bytes=4096)
    assert pack["content_mode"] == "pointer_first"
    assert pack["included_count"] == 3
    assert "value" not in pack["items"][0]
    assert pack["version_conflicts"] == 1


def test_reuse_requires_exact_query_and_dependency_digest():
    key = ce.query_key(project_id="P", question_key="q", scope="s", as_of="today", dependency_digest="a" * 64)
    context = {"project_id": "P", "question_key": "q", "scope": "s", "as_of": "today"}
    pack = ce.build_pack([{ "id": "K1", "pointer": "knowledge/a.html" }], query="q", query_key_value=key, query_context=context, dependency_digest="a" * 64)
    assert ce.reuse(pack, query_key_value=key, current_dependency_digest="a" * 64)["decision"] == "reuse_pointer_pack"
    assert ce.reuse(pack, query_key_value=key, current_dependency_digest="b" * 64)["decision"] == "bounded_reload"
    tampered = dict(pack, query="changed")
    assert ce.reuse(tampered, query_key_value=key, current_dependency_digest="a" * 64)["reason"] == "pack_tampered"


def test_governance_fields_and_conflict_content_are_preserved_safely():
    key = ce.query_key(project_id="P", question_key="q", scope="s", as_of="today", dependency_digest="a" * 64)
    context = {"project_id": "P", "question_key": "q", "scope": "s", "as_of": "today"}
    pack = ce.build_pack([
        {"id": "K1", "pointer": "knowledge/a.html", "status": "conflict", "rights": "unverified",
         "review_pointer": "knowledge/review.json", "value": "do not expose"},
    ], query="q", query_key_value=key, query_context=context, dependency_digest="a" * 64, include_content=True)
    item = pack["items"][0]
    assert item["rights"] == "unverified"
    assert item["status"] == "conflict"
    assert item["content_withheld"] is True
    assert "value" not in item


def test_final_pack_budget_is_enforced():
    key = ce.query_key(project_id="P", question_key="q", scope="s", as_of="today", dependency_digest="a" * 64)
    try:
        ce.build_pack([{ "id": "K1", "pointer": "knowledge/a.html" }], query="x" * 1000, query_key_value=key,
                      query_context={"project_id": "P", "question_key": "q", "scope": "s", "as_of": "today"},
                      dependency_digest="a" * 64, max_bytes=512)
    except ce.ContextPackError as exc:
        assert str(exc) == "pack_budget"
    else:
        raise AssertionError("expected final serialized budget rejection")


def test_pack_is_order_independent_and_rederives_query_key():
    context = {"project_id": "P", "question_key": "q", "scope": "s", "as_of": "today"}
    key = ce.query_key(**context, dependency_digest="a" * 64)
    items = [{"id": "b", "pointer": "knowledge/b.html"}, {"id": "a", "pointer": "knowledge/a.html"}]
    one = ce.build_pack(items, query="q", query_key_value=key, query_context=context, dependency_digest="a" * 64)
    two = ce.build_pack(list(reversed(items)), query="q", query_key_value=key, query_context=context, dependency_digest="a" * 64)
    assert one["pack_sha256"] == two["pack_sha256"]
    assert ce.reuse(dict(one, query_context={**context, "scope": "other"}), query_key_value=key, current_dependency_digest="a" * 64)["reason"] == "pack_tampered"


def test_raw_provenance_is_replaced_by_digest_and_unsafe_values_are_omitted():
    context = {"project_id": "P", "question_key": "q", "scope": "s", "as_of": "today"}
    key = ce.query_key(**context, dependency_digest="a" * 64)
    pack = ce.build_pack([
        {"id": "raw", "pointer": "knowledge/raw.html", "provenance": {"session_id": "raw-id", "transcript": "SECRET"}},
        {"id": "bad", "pointer": "../../etc/passwd"},
    ], query="q", query_key_value=key, query_context=context, dependency_digest="a" * 64)
    serialized = json.dumps(pack, ensure_ascii=False)
    assert "raw-id" not in serialized and "SECRET" not in serialized
    assert pack["omitted_reasons"]["unsafe_pointer"] == 1


def test_same_identity_with_different_governance_is_preserved_and_withheld():
    context = {"project_id": "P", "question_key": "q", "scope": "s", "as_of": "today"}
    key = ce.query_key(**context, dependency_digest="a" * 64)
    pack = ce.build_pack([
        {"id": "K1", "pointer": "knowledge/a.html", "sha256": "a" * 64, "status": "accepted", "value": "safe"},
        {"id": "K1", "pointer": "knowledge/a.html", "sha256": "a" * 64, "status": "retracted", "value": "unsafe"},
    ], query="q", query_key_value=key, query_context=context, dependency_digest="a" * 64, include_content=True)
    assert pack["included_count"] == 2
    assert any(item.get("content_withheld") for item in pack["items"])


def test_budget_overflow_drops_optional_items_before_failing():
    context = {"project_id": "P", "question_key": "q", "scope": "s", "as_of": "today"}
    key = ce.query_key(**context, dependency_digest="a" * 64)
    pack = ce.build_pack([{ "id": str(i), "pointer": f"knowledge/{i}.html" } for i in range(20)],
                         query="q", query_key_value=key, query_context=context, dependency_digest="a" * 64,
                         max_bytes=800)
    assert pack["included_count"] < 20
    assert pack["omitted_reasons"]["budget"] > 0
