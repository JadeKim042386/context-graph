import importlib.util
import json
from html.parser import HTMLParser
from pathlib import Path


REBUILD = Path(__file__).parent


class ProjectionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.source_ids = []
        self.evidence_ids = []
        self.in_summary = False
        self.summary_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section" and attrs.get("data-source-id"):
            self.source_ids.append(attrs["data-source-id"])
        if tag == "article" and attrs.get("data-evidence-id"):
            self.evidence_ids.append(attrs["data-evidence-id"])
        if tag == "script" and attrs.get("id") == "local-projection-summary":
            self.in_summary = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_summary = False

    def handle_data(self, data):
        if self.in_summary:
            self.summary_parts.append(data)


class CycleReportParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.cycle_ids = []
        self.in_result = False
        self.result_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("data-cycle-id"):
            self.cycle_ids.append(attrs["data-cycle-id"])
        if tag == "script" and attrs.get("id") == "knowledge-cycle-result":
            self.in_result = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_result = False

    def handle_data(self, data):
        if self.in_result:
            self.result_parts.append(data)


def load(name):
    return json.loads((REBUILD / name).read_text(encoding="utf-8"))


def load_builder():
    spec = importlib.util.spec_from_file_location("local_rebuild", REBUILD / "local_rebuild.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_frozen_source_has_local_evidence_and_graph_links():
    manifest = load("source-manifest.json")
    evidence = load("local-evidence.json")
    graph = load("typed-knowledge-graph.local-v2.json")
    source_ids = {record["stable_id"] for record in manifest["records"]}
    evidence_ids = {record["stable_id"] for record in evidence["records"]}
    graph_ids = {node["id"] for node in graph["nodes"]}

    assert set(evidence["source_coverage"]) == source_ids
    assert all(evidence["source_coverage"][source_id] >= 1 for source_id in source_ids)
    assert all(record["source_id"] in source_ids for record in evidence["records"])
    assert all(record["locator"] and record["provenance"] for record in evidence["records"])
    assert source_ids | evidence_ids <= graph_ids
    assert {edge["source"] for edge in graph["edges"] if edge["type"] == "has_evidence"} == source_ids
    assert {edge["target"] for edge in graph["edges"] if edge["type"] == "has_evidence"} == evidence_ids


def test_local_conclusions_and_html_projection_cover_every_source_and_evidence():
    manifest = load("source-manifest.json")
    evidence = load("local-evidence.json")
    conclusions = load("conclusions.local-v2.json")
    source_ids = {record["stable_id"] for record in manifest["records"]}
    evidence_ids = {record["stable_id"] for record in evidence["records"]}

    covered_sources = {item["subject_id"] for item in conclusions["conclusions"] if item["conclusion_method"] == "source-content-coverage"}
    assert covered_sources == source_ids
    assert all(item["evidence_ids"] for item in conclusions["conclusions"])

    parser = ProjectionParser()
    parser.feed((REBUILD / "knowledge-projection.local-v2.html").read_text(encoding="utf-8"))
    assert set(parser.source_ids) == source_ids
    assert set(parser.evidence_ids) == evidence_ids


def test_audit_has_evidence_for_every_design_requirement():
    audit = load("local-rebuild-audit.json")
    required = {
        "raw-preservation", "source-catalog", "format-locators",
        "typed-graph", "typed-conclusions", "html-projection",
        "append-only-provenance", "gold-isolation", "conflict-abstain",
    }
    by_id = {item["requirement_id"]: item for item in audit["requirements"]}
    assert required <= by_id.keys()
    assert all(by_id[item]["evidence"] for item in required)
    assert all(by_id[item]["status"] == "passed" for item in required)


def test_followup_rebuild_appends_unique_provenance_events(tmp_path):
    builder = load_builder()
    log_path = tmp_path / "build-log.jsonl"
    original = {"event_id": "ACT-EXISTING", "status": "preserved"}
    log_path.write_text(json.dumps(original) + "\n", encoding="utf-8")

    builder.build_followup(build_log_path=log_path)
    builder.build_followup(build_log_path=log_path)

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert events[0] == original
    assert len(events) == 3
    assert len({event["event_id"] for event in events}) == 3
    assert all(event["status"] == "local-v2-generated" for event in events[1:])
    assert all(event["inventory_snapshot_sha256"] for event in events[1:])


def test_semantic_conflict_audit_is_traceable_and_abstains_without_inference():
    evidence = load("local-evidence.json")
    audit = load("semantic-conflict-audit.json")
    evidence_by_id = {record["stable_id"]: record for record in evidence["records"]}

    assert audit["status"] == "passed"
    assert audit["records"]
    for record in audit["records"]:
        assert record["conflict_source_id"]
        assert record["evidence_ids"]
        assert record["evidence_locators"]
        assert record["semantic_claims"] == []
        assert record["semantic_parse_status"] == "not_inferred"
        assert record["resolution"] == "abstain"
        assert record["abstain_reason"]
        assert all(evidence_id in evidence_by_id for evidence_id in record["evidence_ids"])
        assert record["evidence_locators"] == [
            evidence_by_id[evidence_id]["locator"] for evidence_id in record["evidence_ids"]
        ]


def test_html_evidence_uses_explicit_global_ordinal_and_text_quote_selector():
    evidence = load("local-evidence.json")
    records = [
        record for record in evidence["records"]
        if record["kind"] in {"html-block", "media-description"}
    ]

    assert records
    for record in records:
        locator = record["locator"]
        assert locator["selector_model"] == "document-global-tag-ordinal"
        assert locator["selector"].startswith("global-tag-ordinal(")
        assert "nth-of-type" not in locator["selector"]
        assert locator["element"]["global_ordinal"] >= 1
        assert locator["web_annotation_selector"] == {
            "type": "TextQuoteSelector",
            "exact": record["content"],
        }


def test_local_projection_summary_is_valid_embedded_json():
    parser = ProjectionParser()
    parser.feed((REBUILD / "knowledge-projection.local-v2.html").read_text(encoding="utf-8"))
    summary = json.loads("".join(parser.summary_parts))

    assert summary["sources"] == 22
    assert summary["evidence"] == 3389
    assert summary["graph_nodes"] == 3411
    assert summary["graph_edges"] == 3389


def test_public_projection_seals_evaluator_only_locators():
    evidence = load("local-evidence.json")
    evaluator_ids = [
        record["stable_id"] for record in evidence["records"]
        if record["visibility"] == "evaluator-only"
    ]
    projection = (REBUILD / "knowledge-projection.local-v2.html").read_text(encoding="utf-8")

    assert len(evaluator_ids) == 10
    assert "/evaluator_sidecar" not in projection
    assert all(f'data-evidence-id="{evidence_id}"' in projection for evidence_id in evaluator_ids)


def test_cycle_report_embeds_three_measured_cycles_and_stopping_evidence():
    parser = CycleReportParser()
    parser.feed((REBUILD / "knowledge-cycle-report.html").read_text(encoding="utf-8"))
    result = json.loads("".join(parser.result_parts))

    assert parser.cycle_ids == ["cycle-1", "cycle-2", "cycle-3"]
    assert [cycle["cycle_id"] for cycle in result["cycles"]] == parser.cycle_ids
    assert result["stopping"]["minimum_cycles_met"] is True
    assert result["stopping"]["hard_gates_passed"] is True
    assert result["stopping"]["last_cycle_core_metric_improvement"] == 0
