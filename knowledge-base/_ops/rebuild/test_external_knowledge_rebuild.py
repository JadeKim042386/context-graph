import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError

import fetch_external_sources as fetcher


HERE = Path(__file__).parent


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


class ScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = None
        self.scripts = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/json":
            self.active = attrs.get("id")
            self.scripts.setdefault(self.active, [])

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = None

    def handle_data(self, data):
        if self.active:
            self.scripts[self.active].append(data)


def test_external_manifest_links_every_completed_observation():
    manifest, results = load("external-source-manifest.json"), load("external-fetch-results.json")
    latest = {}
    for key in ("batches", "media_batches", "retry_batches", "recovery_batches"):
        for batch in results.get(key, []):
            for item in batch["records"]:
                latest[item["stable_id"]] = item
    observations = list(latest.values())
    manifest_records = {item["stable_id"]: item for key in ("records", "media_records") for item in manifest[key]}

    assert len(manifest["records"]) == 1203
    assert len(manifest["media_records"]) == 17
    assert all(manifest_records[item["stable_id"]]["external_fetch_result_locator"] for item in observations)
    assert all(manifest_records[item["stable_id"]]["fetch_provenance"] == item["provenance"] for item in observations)
    assert all(item["content_sha256"] is None for item in observations)


def test_external_graph_and_conclusions_preserve_errors_as_abstain():
    manifest = load("external-source-manifest.json")
    graph, conclusions = load("typed-external-knowledge-graph.json"), load("external-conclusions.json")
    source_ids = {item["stable_id"] for key in ("records", "media_records") for item in manifest[key]}
    graph_ids = {node["id"] for node in graph["nodes"]}

    assert source_ids <= graph_ids
    assert all(edge["source"] in graph_ids and edge["target"] in graph_ids for edge in graph["edges"])
    assert len(conclusions["conclusions"]) == 1220
    assert {item["subject_id"] for item in conclusions["conclusions"]} == source_ids
    assert all(evidence_id in graph_ids for item in conclusions["conclusions"] for evidence_id in item["evidence_ids"])
    by_subject = {item["subject_id"]: item for item in conclusions["conclusions"]}
    for record in manifest["records"]:
        expected = "observed" if record["fetch_status"] == "metadata_fetched" else "abstain"
        assert by_subject[record["stable_id"]]["status"] == expected


def test_external_l5_and_cycle_report_embed_current_counts():
    manifest = load("external-source-manifest.json")
    external_parser, cycle_parser = ScriptParser(), ScriptParser()
    external_parser.feed((HERE / "external-knowledge-projection.html").read_text(encoding="utf-8"))
    cycle_parser.feed((HERE / "knowledge-cycle-report.html").read_text(encoding="utf-8"))
    summary = json.loads("".join(external_parser.scripts["external-verification-summary"]))
    cycle = json.loads("".join(cycle_parser.scripts["external-cycle-result"]))

    assert summary["url_statuses"] == manifest["fetch_status_counts"]
    assert summary["media_statuses"] == manifest["media_fetch_status_counts"]
    assert cycle["url_metadata_fetched"] == manifest["fetch_status_counts"]["metadata_fetched"]
    assert cycle["url_not_started"] == manifest["fetch_status_counts"]["not_started"]
    assert cycle["media_metadata_fetched"] == 17
    rights_verified = [
        item for key in ("records", "media_records") for item in manifest[key]
        if item["rights_status"] != "unverified"
    ]
    assert cycle["body_hashes"] == 0
    assert cycle["rights_verified"] == len(rights_verified) == 4
    assert all(item["license_evidence"] for item in rights_verified)


def test_recovery_uses_safe_get_metadata_fallback_without_body(monkeypatch):
    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key, super().get(key.lower(), default))

    class Response:
        status = 200
        headers = Headers({"Content-Type": "text/html", "Content-Length": "42"})

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://example.org/resource"

        def read(self, *_args):
            raise AssertionError("metadata recovery must not read or hash response bodies")

    calls = []

    def fake_open(request, _timeout):
        calls.append(request.get_method())
        if request.get_method() == "HEAD":
            raise HTTPError(request.full_url, 405, "Method Not Allowed", Headers({}), None)
        return Response()

    monkeypatch.setattr(fetcher, "public_host", lambda _url: (True, None))
    monkeypatch.setattr(fetcher, "robots_check", lambda _url, _timeout: ("allowed", None))
    monkeypatch.setattr(fetcher, "safe_open", fake_open)
    monkeypatch.setattr(fetcher.time, "sleep", lambda _delay: None)

    result = fetcher.fetch_recovery(
        {
            "stable_id": "EXT-TEST-001",
            "url": "https://example.org/resource",
            "first_reference": {"source_path": "knowledge/example.html", "locator": "a[href]"},
            "provenance": {"inventory_snapshot_sha256": "sha256:test"},
        },
        timeout=1,
        batch_id="ACT-TEST",
    )

    assert calls == ["HEAD", "GET"]
    assert result["fetch_status"] == "metadata_fetched"
    assert result["fallback_used"] == "GET-range-metadata"
    assert result["robots_outcome"] == "allowed"
    assert result["content_sha256"] is None
    assert result["attempt_count"] == 2


def test_recovery_selection_is_bounded_and_failure_stratified():
    def record(stable_id, status, http_status=None, error=None):
        return {
            "stable_id": stable_id,
            "fetch_status": status,
            "http_status": http_status,
            "fetch_error": error,
        }

    records = [
        *[record(f"403-{index}", "http_error", 403) for index in range(6)],
        *[record(f"405-{index}", "http_error", 405) for index in range(3)],
        *[record(f"dns-{index}", "failed", error="dns_error:gaierror") for index in range(3)],
        record("timeout-0", "failed", error="TimeoutError:timed out"),
        record("refused-0", "failed", error="URLError:connection refused"),
    ]

    selected = fetcher.select_recovery_records(records, limit=10)

    assert len(selected) == 10
    assert {item["http_status"] for item in selected if item["http_status"]} == {403, 405}
    errors = " ".join(item["fetch_error"] or "" for item in selected).lower()
    assert "dns" in errors and "timeout" in errors and "refused" in errors


def test_recorded_recovery_is_bounded_robots_safe_and_metadata_only():
    results = load("external-fetch-results.json")
    batches = results.get("recovery_batches", [])

    assert len(batches) == 1
    batch = batches[0]
    assert 0 < len(batch["records"]) <= 10
    assert batch["config"]["response_body_retained"] is False
    assert all(item["content_sha256"] is None for item in batch["records"])
    assert all(0 < item["attempt_count"] <= 6 for item in batch["records"])
    assert all(
        item["robots_outcome"] in {"allowed", "not_found_allow"}
        for item in batch["records"] if item["fallback_used"] == "GET-range-metadata"
    )
    assert all(
        item["network_error_class"]
        for item in batch["records"] if item["fetch_status"] == "failed"
    )
