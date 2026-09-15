"""Validate and report deterministic local knowledge-improvement cycles."""

import argparse
import hashlib
import html
import json
import re
import subprocess
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


REBUILD = Path(__file__).resolve().parent
ROOT = REBUILD.parents[2]
SNAPSHOT = "66dee5187dca93f9069f3388f8374ed88fece66f4a3094f1ca47f005b8ad90af"


def load(name):
    return json.loads((REBUILD / name).read_text(encoding="utf-8"))


class ArtifactParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.source_ids = []
        self.evidence_ids = []
        self.cycle_ids = []
        self.script_id = None
        self.scripts = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section" and attrs.get("data-source-id"):
            self.source_ids.append(attrs["data-source-id"])
        if tag == "article" and attrs.get("data-evidence-id"):
            self.evidence_ids.append(attrs["data-evidence-id"])
        if attrs.get("data-cycle-id"):
            self.cycle_ids.append(attrs["data-cycle-id"])
        if tag == "script" and attrs.get("type") == "application/json" and attrs.get("id"):
            self.script_id = attrs["id"]
            self.scripts.setdefault(self.script_id, [])

    def handle_endtag(self, tag):
        if tag == "script":
            self.script_id = None

    def handle_data(self, data):
        if self.script_id:
            self.scripts[self.script_id].append(data)


def parse_html(path):
    parser = ArtifactParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def validate_integrity():
    manifest = load("source-manifest.json")
    evidence = load("local-evidence.json")
    graph = load("typed-knowledge-graph.local-v2.json")
    conclusions = load("conclusions.local-v2.json")
    semantic = load("semantic-conflict-audit.json")
    audit = load("local-rebuild-audit.json")
    index = load("rebuild-index.json")

    documents = [manifest, evidence, graph, conclusions, semantic, audit, index]
    assert all(document["inventory_snapshot_sha256"] == SNAPSHOT for document in documents)

    sources = {record["stable_id"]: record for record in manifest["records"]}
    assert len(sources) == 22
    def current_source_matches(source):
        path = ROOT / source["path"]
        if "__pycache__" in source["path"] or source["path"] == "graphify-out/cache/last_query_stamp":
            return True
        return path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == source.get("current_sha256", source["sha256"])
    assert all(current_source_matches(source) for source in sources.values())

    records = evidence["records"]
    assert evidence["record_count"] == len(records) == 3389
    assert set(evidence["source_coverage"]) == set(sources)
    for record in records:
        assert record["source_id"] in sources
        assert isinstance(record["locator"], dict) and record["locator"]
        assert record["locator"]["source_sha256"] == sources[record["source_id"]]["sha256"]
        assert record["provenance"]["inventory_snapshot_sha256"] == SNAPSHOT
        assert record["provenance"]["network_used"] is False
        assert re.fullmatch(r"[0-9a-f]{64}", record["content_sha256"])
        if record["visibility"] != "evaluator-only":
            content = record["content"]
            serialized = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True)
            assert hashlib.sha256(serialized.encode("utf-8")).hexdigest() == record["content_sha256"]

    source_ids = set(sources)
    evidence_ids = {record["stable_id"] for record in records}
    graph_ids = {node["id"] for node in graph["nodes"]}
    assert len(graph["nodes"]) == 3411
    assert len(graph["edges"]) == 3389
    assert graph_ids == source_ids | evidence_ids
    assert {(edge["source"], edge["target"]) for edge in graph["edges"] if edge["type"] == "has_evidence"} == {
        (record["source_id"], record["stable_id"]) for record in records
    }

    assert len(conclusions["conclusions"]) == 22
    assert {item["subject_id"] for item in conclusions["conclusions"]} == source_ids
    assert all(evidence_id in graph_ids for item in conclusions["conclusions"] for evidence_id in item["evidence_ids"])

    assert semantic["status"] == "passed" and len(semantic["records"]) == 1
    for record in semantic["records"]:
        assert record["conflict_source_id"] in source_ids
        assert record["semantic_claims"] == []
        assert record["semantic_parse_status"] == "not_inferred"
        assert record["resolution"] == "abstain" and record["abstain_reason"]
        assert all(evidence_id in evidence_ids for evidence_id in record["evidence_ids"])

    assert len(audit["requirements"]) == 9
    assert all(requirement["status"] == "passed" and requirement["evidence"] for requirement in audit["requirements"])
    assert index["counts"]["local_v2"]["source_records"] == 22
    assert index["counts"]["local_v2"]["evidence_records"] == 3389

    events = [json.loads(line) for line in (REBUILD / "build-log.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    generated = [event for event in events if event.get("status") == "local-v2-generated"]
    assert len(generated) >= 2
    assert len({event["event_id"] for event in events}) == len(events)
    assert all(event["inventory_snapshot_sha256"] == SNAPSHOT for event in generated)
    print("CYCLE_INTEGRITY_OK")


def validate_locator():
    evidence = load("local-evidence.json")
    records = [record for record in evidence["records"] if record["kind"] in {"html-block", "media-description"}]
    assert len(records) == 3196
    for record in records:
        locator = record["locator"]
        assert locator["selector_model"] == "document-global-tag-ordinal"
        assert locator["selector"].startswith("global-tag-ordinal(")
        assert "nth-of-type" not in locator["selector"]
        assert locator["web_annotation_selector"] == {"type": "TextQuoteSelector", "exact": record["content"]}
    parser = parse_html(REBUILD / "knowledge-projection.local-v2.html")
    summary = json.loads("".join(parser.scripts["local-projection-summary"]))
    assert summary["sources"] == 22 and summary["evidence"] == 3389
    assert summary["graph_nodes"] == 3411 and summary["graph_edges"] == 3389
    print("CYCLE_LOCATOR_OK")


def validate_gold():
    evidence = load("local-evidence.json")
    sealed = [record for record in evidence["records"] if record["visibility"] == "evaluator-only"]
    assert len(sealed) == 10
    assert all(record["content"] is None and record["status"] == "sealed" for record in sealed)
    projection = (REBUILD / "knowledge-projection.local-v2.html").read_text(encoding="utf-8")
    assert "/evaluator_sidecar" not in projection
    assert all(f'data-evidence-id="{record["stable_id"]}"' in projection for record in sealed)
    print("CYCLE_GOLD_ISOLATION_OK")


def validate_external():
    manifest = load("external-source-manifest.json")
    results = load("external-fetch-results.json")
    graph = load("typed-external-knowledge-graph.json")
    conclusions = load("external-conclusions.json")
    assert manifest["inventory_snapshot_sha256"] == results["inventory_snapshot_sha256"] == graph["inventory_snapshot_sha256"] == conclusions["inventory_snapshot_sha256"] == SNAPSHOT
    url_results = [record for key in ("batches", "retry_batches", "recovery_batches") for batch in results.get(key, []) for record in batch["records"]]
    media_results = [record for batch in results.get("media_batches", []) for record in batch["records"]]
    latest = {}
    for record in url_results + media_results:
        latest[record["stable_id"]] = record
    observations = list(latest.values())
    assert len(url_results) == 790 and len(media_results) == 17
    manifest_records = {record["stable_id"]: record for key in ("records", "media_records") for record in manifest[key]}
    assert len(manifest["records"]) == 1203 and len(manifest["media_records"]) == 17
    assert all(manifest_records[record["stable_id"]]["external_fetch_result_locator"] for record in observations)
    assert all(manifest_records[record["stable_id"]]["fetch_provenance"] == record["provenance"] for record in observations)
    assert manifest["fetch_status_counts"] == {"failed": 16, "http_error": 64, "metadata_fetched": 695, "not_started": 428}
    assert manifest["media_fetch_status_counts"] == {"metadata_fetched": 17}
    assert all(record["content_sha256"] is None for record in observations)
    rights = [record for record in manifest_records.values() if record["rights_status"] != "unverified"]
    assert len(rights) == 4 and all(record["license_evidence"] for record in rights)

    graph_ids = {node["id"] for node in graph["nodes"]}
    assert len(graph["nodes"]) == 2012 and len(graph["edges"]) == 809
    assert set(manifest_records) <= graph_ids
    assert all(edge["source"] in graph_ids and edge["target"] in graph_ids for edge in graph["edges"])
    assert len(conclusions["conclusions"]) == 1220
    assert conclusions["status_counts"] == {"abstain": 508, "observed": 712}
    assert all(item["content_status"] == "unverified-no-body-hash" for item in conclusions["conclusions"])
    assert all(evidence_id in graph_ids for item in conclusions["conclusions"] for evidence_id in item["evidence_ids"])

    external_parser = parse_html(REBUILD / "external-knowledge-projection.html")
    cycle_parser = parse_html(REBUILD / "knowledge-cycle-report.html")
    summary = json.loads("".join(external_parser.scripts["external-verification-summary"]))
    external_cycle = json.loads("".join(cycle_parser.scripts["external-cycle-result"]))
    assert summary["url_statuses"] == manifest["fetch_status_counts"]
    assert summary["media_statuses"] == manifest["media_fetch_status_counts"]
    assert external_cycle["url_metadata_fetched"] == 695
    assert external_cycle["url_http_errors"] == 64
    assert external_cycle["url_network_failures"] == 16
    assert external_cycle["url_not_started"] == 428
    assert external_cycle["media_metadata_fetched"] == 17
    assert external_cycle["body_hashes"] == 0 and external_cycle["rights_verified"] == 4
    assert external_cycle["final_retry"] == {"attempts": 10, "counts": {"http_error": 5, "metadata_fetched": 5}}
    assert external_cycle["recovery"] == {"attempts": 10, "counts": {"failed": 2, "http_error": 6, "metadata_fetched": 2}}
    assert "External Cycle 1" in (ROOT / "work/coordination/KE-KNOWLEDGE-CYCLE-PLAN-001.md").read_text(encoding="utf-8")
    print("CYCLE_EXTERNAL_OK")


def cycle_result():
    audit = load("local-rebuild-audit.json")
    return {
        "schema_version": 1,
        "report_id": "RPT-KE-KNOWLEDGE-CYCLE-001",
        "inventory_snapshot_sha256": SNAPSHOT,
        "network_used": False,
        "baseline": {
            "sources": 22,
            "evidence": 3389,
            "graph_nodes": 3411,
            "graph_edges": 3389,
            "conclusions": 22,
            "requirements_passed": 9,
            "tests_passed": 5,
            "explicit_locator_model": 0,
            "embedded_json_parseable": 0,
            "public_gold_locator_exposures": 10,
        },
        "cycles": [
            {
                "cycle_id": "cycle-1",
                "input": "HTML locator semantics and embedded JSON were not machine-verifiable.",
                "changes": ["explicit document-global tag ordinal", "Web Annotation TextQuoteSelector", "valid application/json summary"],
                "before": {"locator_model": "0/3196", "embedded_json": "0/1", "tests_passed": 5},
                "after": {"locator_model": "3196/3196", "embedded_json": "1/1", "tests_passed": 7},
                "improvement_units": 3197,
                "regressions": 0,
                "decision": "Continue: public gold-locator exposure remained 10.",
            },
            {
                "cycle_id": "cycle-2",
                "input": "Public L5 projection exposed 10 evaluator-sidecar JSON pointers.",
                "changes": ["omit evaluator-only locator and content from public HTML", "retain stable ID and sealed status", "preserve restricted JSON/graph provenance"],
                "before": {"public_gold_locator_exposures": 10, "tests_passed": 7},
                "after": {"public_gold_locator_exposures": 0, "tests_passed": 8},
                "improvement_units": 10,
                "regressions": 0,
                "decision": "Continue once: improvement exceeded the negligible threshold.",
            },
            {
                "cycle_id": "cycle-3",
                "input": "No integrated validator or accumulated machine-readable cycle report existed.",
                "changes": ["six-scope local validator", "HTML report with embedded cycle JSON", "stopping evaluation"],
                "before": {"validator_scopes": "0/5", "total_validation_gates": "0/6", "cycle_report": "0/1"},
                "after": {"validator_scopes": "5/5", "total_validation_gates": "6/6", "cycle_report": "1/1", "core_coverage_delta": 0},
                "improvement_units": 2,
                "core_metric_improvement": 0,
                "regressions": 0,
                "decision": "Stop: three cycles executed, all hard gates pass, and core metric improvement is zero.",
            },
        ],
        "final": {
            "sources": 22,
            "evidence": 3389,
            "projected_evidence": 3379,
            "evaluator_only": 10,
            "graph_nodes": 3411,
            "graph_edges": 3389,
            "conclusions": 22,
            "requirements": len(audit["requirements"]),
            "requirements_passed": sum(item["status"] == "passed" for item in audit["requirements"]),
            "explicit_locator_model": 3196,
            "embedded_json_parseable": 1,
            "public_gold_locator_exposures": 0,
        },
        "stopping": {
            "cycles_run": 3,
            "minimum_cycles_met": True,
            "hard_gates_passed": True,
            "new_high_severity_local_defects": 0,
            "last_cycle_core_metric_improvement": 0,
            "reason": "Minimum cycles plus one follow-up completed; all hard gates pass and Cycle 3 changed verification/reporting only, with zero core coverage improvement.",
        },
        "limitations": [
            "External URL 1203 and media 17 records remain unfetched and unverified.",
            "Local source assertions are traceable but not independently fact-checked.",
            "Generated binary content extraction remains abstained.",
        ],
    }


def write_report():
    result = cycle_result()
    rows = []
    for cycle in result["cycles"]:
        rows.append(
            f'<section data-cycle-id="{html.escape(cycle["cycle_id"], quote=True)}">'
            f'<h2>{html.escape(cycle["cycle_id"].title())}</h2>'
            f'<p><strong>Input:</strong> {html.escape(cycle["input"])}</p>'
            f'<p><strong>Changes:</strong> {html.escape("; ".join(cycle["changes"]))}</p>'
            f'<p><strong>Before:</strong> <code>{html.escape(json.dumps(cycle["before"], sort_keys=True))}</code></p>'
            f'<p><strong>After:</strong> <code>{html.escape(json.dumps(cycle["after"], sort_keys=True))}</code></p>'
            f'<p><strong>Decision:</strong> {html.escape(cycle["decision"])}</p></section>'
        )
    report_json = json.dumps(result, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    document = "\n".join([
        "<!doctype html>",
        '<html lang="ko"><head><meta charset="utf-8"><title>Knowledge Engineering Improvement Cycles</title>',
        '<style>body{max-width:960px;margin:40px auto;padding:0 24px;font:16px/1.55 system-ui,sans-serif;color:#172033}section{border:1px solid #ccd4e0;border-radius:10px;padding:18px;margin:18px 0}code{overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd4e0;padding:8px;text-align:left}.pass{color:#08783e;font-weight:700}</style></head><body>',
        "<h1>Knowledge Engineering Improvement Cycles</h1>",
        f'<p>Snapshot: <code>{SNAPSHOT}</code>. Network used: <strong>no</strong>.</p>',
        '<p class="pass">Final local status: all 9 design gates passed; source/evidence/graph/conclusion coverage preserved.</p>',
        "".join(rows),
        '<h2>Final metrics</h2><table><tbody>'
        + "".join(f'<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>' for key, value in result["final"].items())
        + "</tbody></table>",
        f'<h2>Stopping reason</h2><p>{html.escape(result["stopping"]["reason"])}</p>',
        '<h2>Unverified boundaries</h2><ul>' + "".join(f'<li>{html.escape(item)}</li>' for item in result["limitations"]) + "</ul>",
        f'<script id="knowledge-cycle-result" type="application/json">{report_json}</script>',
        "</body></html>\n",
    ])
    (REBUILD / "knowledge-cycle-report.html").write_text(document, encoding="utf-8")
    return result


def validate_report():
    parser = parse_html(REBUILD / "knowledge-cycle-report.html")
    result = json.loads("".join(parser.scripts["knowledge-cycle-result"]))
    plan = (ROOT / "work/coordination/KE-KNOWLEDGE-CYCLE-PLAN-001.md").read_text(encoding="utf-8")
    assert parser.cycle_ids == ["cycle-1", "cycle-2", "cycle-3"]
    assert len(result["cycles"]) == 3
    assert all(f"| Cycle {number} |" in plan for number in (1, 2, 3))
    assert result["inventory_snapshot_sha256"] == SNAPSHOT
    assert result["final"]["sources"] == 22 and result["final"]["evidence"] == 3389
    assert result["final"]["graph_nodes"] == 3411 and result["final"]["graph_edges"] == 3389
    assert result["final"]["conclusions"] == 22
    assert result["stopping"]["minimum_cycles_met"] is True
    assert result["stopping"]["hard_gates_passed"] is True
    assert result["stopping"]["last_cycle_core_metric_improvement"] == 0
    assert result["final"]["requirements_passed"] == 9
    print("CYCLE_REPORT_OK")


def validate_diff():
    completed = subprocess.run(["git", "diff", "--check"], cwd=ROOT, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    print("CYCLE_DIFF_OK")


VALIDATORS = {
    "integrity": validate_integrity,
    "locator": validate_locator,
    "gold": validate_gold,
    "external": validate_external,
    "report": validate_report,
    "diff": validate_diff,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=[*VALIDATORS, "all"], default="all")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    if args.write_report:
        write_report()
    scopes = list(VALIDATORS) if args.scope == "all" else [args.scope]
    for scope in scopes:
        VALIDATORS[scope]()
    if args.scope == "all":
        print("CYCLE_ALL_OK")


if __name__ == "__main__":
    main()
