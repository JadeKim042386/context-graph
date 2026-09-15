"""Project external fetch observations without modifying canonical local sources."""

import hashlib
import html
import json
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
SNAPSHOT = "66dee5187dca93f9069f3388f8374ed88fece66f4a3094f1ca47f005b8ad90af"


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def sid(prefix, *parts):
    value = "\x1f".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:20].upper()}"


def latest_results(results):
    latest = {}
    for batch_key in ("batches", "media_batches", "retry_batches", "recovery_batches"):
        for batch in results.get(batch_key, []):
            for record in batch["records"]:
                latest[record["stable_id"]] = (batch["batch_id"], record)
    return latest


def build_graph(manifest, results):
    latest = latest_results(results)
    nodes, edges = [], []
    for record in manifest["records"]:
        nodes.append({
            "id": record["stable_id"], "stable_id": record["stable_id"], "type": "ExternalSource",
            "url": record["url"], "fetch_status": record["fetch_status"],
            "first_reference": record["first_reference"], "rights_status": record["rights_status"],
            "provenance": record["provenance"],
        })
    for record in manifest["media_records"]:
        nodes.append({
            "id": record["stable_id"], "stable_id": record["stable_id"], "type": "MediaReference",
            "url": record["url"], "media_kind": record["media_kind"], "fetch_status": record["fetch_status"],
            "first_reference": record["first_reference"], "rights_status": record["rights_status"],
            "provenance": record["provenance"],
        })
        edge_id = sid("EDG", record["stable_id"], "references_external_source", record["source_stable_id"])
        edges.append({"id": edge_id, "type": "references_external_source", "source": record["stable_id"], "target": record["source_stable_id"], "provenance": record["provenance"]})
    observation_ids = {}
    for stable_id, (batch_id, result) in latest.items():
        observation_id = sid("OBS", batch_id, stable_id)
        observation_ids[stable_id] = observation_id
        nodes.append({
            "id": observation_id, "stable_id": observation_id, "type": "FetchObservation",
            "subject_id": stable_id, "http_status": result["http_status"], "fetch_status": result["fetch_status"],
            "final_url": result["final_url"], "redirects": result["redirects"],
            "content_sha256": result["content_sha256"], "extraction_format": result["extraction_format"],
            "rights_status": result["rights_status"], "robots_outcome": result["robots_outcome"],
            "method": result.get("method"), "fallback_used": result.get("fallback_used"),
            "attempt_count": result.get("attempt_count", 1),
            "network_error_class": result.get("network_error_class"),
            "result_locator": {"type": "json-record", "path": "knowledge-base/_ops/rebuild/external-fetch-results.json", "batch_id": batch_id, "stable_id": stable_id},
            "provenance": result["provenance"],
        })
        edge_id = sid("EDG", stable_id, "has_fetch_observation", observation_id)
        edges.append({"id": edge_id, "type": "has_fetch_observation", "source": stable_id, "target": observation_id, "provenance": result["provenance"]})
    graph = {
        "schema_version": 1, "graph_id": "KG-KE-EXTERNAL-20260914-001",
        "inventory_snapshot_sha256": SNAPSHOT,
        "nodes": nodes, "edges": edges,
        "counts": {"external_sources": len(manifest["records"]), "media_references": len(manifest["media_records"]), "fetch_observations": len(latest)},
    }
    (HERE / "typed-external-knowledge-graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return graph, observation_ids


def build_conclusions(manifest, graph, observation_ids):
    conclusions = []
    for kind, records in (("external-url", manifest["records"]), ("external-media", manifest["media_records"])):
        for record in records:
            observed = record["fetch_status"] == "metadata_fetched"
            conclusions.append({
                "id": sid("CON", record["stable_id"], "external-metadata-availability"),
                "subject_id": record["stable_id"],
                "statement": (
                    f"Response metadata was observed with HTTP {record['http_status']}; body content remains unverified."
                    if observed else
                    f"No verified response metadata is available; status={record['fetch_status']}."
                ),
                "status": "observed" if observed else "abstain",
                "evidence_ids": [observation_ids.get(record["stable_id"], record["stable_id"])],
                "conclusion_method": f"{kind}-metadata-observation" if observed else f"{kind}-availability-abstention",
                "rights_status": record["rights_status"],
                "content_status": "unverified-no-body-hash",
                "provenance": record.get("fetch_provenance", record["provenance"]),
            })
    document = {
        "schema_version": 1, "conclusions_id": "CONSET-KE-EXTERNAL-20260914-001",
        "graph_id": graph["graph_id"], "inventory_snapshot_sha256": SNAPSHOT,
        "policy": "HEAD or robots-approved GET Range metadata supports availability only; missing body, rights, or failed fetch requires abstention.",
        "conclusions": conclusions, "conflict_sets": [],
        "status_counts": dict(sorted(Counter(item["status"] for item in conclusions).items())),
    }
    (HERE / "external-conclusions.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def build_projection(manifest, graph, conclusions):
    all_records = [("URL", item) for item in manifest["records"]] + [("media", item) for item in manifest["media_records"]]
    rows = []
    for kind, record in all_records:
        locator = record.get("external_fetch_result_locator")
        rows.append(
            f'<tr data-external-id="{html.escape(record["stable_id"], quote=True)}"><td>{kind}</td>'
            f'<td><code>{html.escape(record["stable_id"])}</code></td><td>{html.escape(record["url"])}</td>'
            f'<td>{html.escape(record["fetch_status"])}</td><td>{html.escape(str(record["http_status"]))}</td>'
            f'<td>{html.escape(record["rights_status"])}</td><td><code>{html.escape(json.dumps(locator, ensure_ascii=False, sort_keys=True)) if locator else "not_started"}</code></td></tr>'
        )
    summary = {
        "inventory_snapshot_sha256": SNAPSHOT,
        "url_records": len(manifest["records"]), "media_records": len(manifest["media_records"]),
        "url_statuses": manifest["fetch_status_counts"], "media_statuses": manifest["media_fetch_status_counts"],
        "url_observations": sum(record["fetch_status"] != "not_started" for record in manifest["records"]),
        "media_observations": sum(record["fetch_status"] != "not_started" for record in manifest["media_records"]),
        "graph_nodes": len(graph["nodes"]), "graph_edges": len(graph["edges"]),
        "conclusions": len(conclusions["conclusions"]),
        "content_hashes": sum(bool(record.get("content_sha256")) for record in manifest["records"] + manifest["media_records"]),
        "rights_verified": sum(record["rights_status"] != "unverified" for record in manifest["records"] + manifest["media_records"]),
        "network_used": True,
    }
    payload = json.dumps(summary, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    document = "\n".join([
        "<!doctype html>", '<html lang="ko"><head><meta charset="utf-8"><title>External Knowledge Verification</title></head><body>',
        "<h1>External Knowledge Verification</h1>",
        f'<p>Snapshot: <code>{SNAPSHOT}</code>. Verification is bounded to HEAD or robots-approved GET Range metadata; no body or license inference.</p>',
        '<table><thead><tr><th>Kind</th><th>ID</th><th>URL</th><th>Status</th><th>HTTP</th><th>Rights</th><th>Result locator</th></tr></thead><tbody>',
        "".join(rows), "</tbody></table>",
        f'<script id="external-verification-summary" type="application/json">{payload}</script>', "</body></html>\n",
    ])
    (HERE / "external-knowledge-projection.html").write_text(document, encoding="utf-8")
    return summary


def upsert_layer(index, layer):
    for position, current in enumerate(index["layers"]):
        if current["path"] == layer["path"]:
            index["layers"][position] = layer
            return
    index["layers"].append(layer)


def update_discovery(summary):
    index = load("rebuild-index.json")
    results = load("external-fetch-results.json")
    url_batches = len(results["batches"]) + len(results.get("retry_batches", [])) + len(results.get("recovery_batches", []))
    media_batches = len(results.get("media_batches", []))
    retry_records = [record for batch in results.get("retry_batches", []) for record in batch["records"]]
    retry_counts = dict(sorted(Counter(record["fetch_status"] for record in retry_records).items()))
    recovery_records = [record for batch in results.get("recovery_batches", []) for record in batch["records"]]
    recovery_counts = dict(sorted(Counter(record["fetch_status"] for record in recovery_records).items()))
    url_request_attempts = sum(
        record.get("attempt_count", 1)
        for key in ("batches", "retry_batches", "recovery_batches")
        for batch in results.get(key, []) for record in batch["records"]
    )
    fetched_urls = summary["url_statuses"].get("metadata_fetched", 0)
    failed_urls = summary["url_statuses"].get("failed", 0)
    http_error_urls = summary["url_statuses"].get("http_error", 0)
    not_started_urls = summary["url_statuses"].get("not_started", 0)
    fetched_media = summary["media_statuses"].get("metadata_fetched", 0)
    for layer, stable_id, path, status, counts in (
        ("L2", "ART-EXTERNAL-FETCH-RESULTS-001", "knowledge-base/_ops/rebuild/external-fetch-results.json", "bounded-metadata-observations", {"url_batches": url_batches, "url_observations": summary["url_observations"], "url_request_attempts": url_request_attempts, "media_batches": media_batches, "media_attempts": summary["media_observations"]}),
        ("L3", "ART-EXTERNAL-GRAPH-001", "knowledge-base/_ops/rebuild/typed-external-knowledge-graph.json", "typed-external-observation-graph", {"nodes": summary["graph_nodes"], "edges": summary["graph_edges"]}),
        ("L4", "ART-EXTERNAL-CONCLUSIONS-001", "knowledge-base/_ops/rebuild/external-conclusions.json", "external-availability-conclusions", {"conclusions": summary["conclusions"]}),
        ("L5", "ART-EXTERNAL-PROJECTION-001", "knowledge-base/_ops/rebuild/external-knowledge-projection.html", "external-verification-projection", {"url_records": summary["url_records"], "media_records": summary["media_records"]}),
    ):
        upsert_layer(index, {"layer": layer, "stable_id": stable_id, "path": path, "status": status, "counts": counts, "inventory_snapshot_sha256": SNAPSHOT})
    index["counts"].update({
        "external_metadata_fetched_urls": fetched_urls, "external_failed_urls": failed_urls,
        "external_http_error_urls": http_error_urls, "external_not_started_urls": not_started_urls,
        "external_metadata_fetched_media": fetched_media,
        "external_content_hashes": summary["content_hashes"], "external_rights_verified": summary["rights_verified"],
    })
    for layer in index["layers"]:
        if layer["path"] == "knowledge-base/_ops/rebuild/rebuild-index.json":
            layer["counts"]["indexed_layers"] = len(index["layers"])
    (HERE / "rebuild-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    projection_path = HERE / "knowledge-projection.html"
    projection = projection_path.read_text(encoding="utf-8")
    start, end = "<!-- external-cycle:start -->", "<!-- external-cycle:end -->"
    block = (
        f'{start}<h2>Bounded external verification</h2><p><a href="external-fetch-results.json">Fetch results</a>: URL metadata {fetched_urls} success / {http_error_urls} HTTP error / {failed_urls} network failure / {not_started_urls} not started; media metadata {fetched_media} success. '
        '<a href="typed-external-knowledge-graph.json">External graph</a>, <a href="external-conclusions.json">conclusions</a>, and '
        f'<a href="external-knowledge-projection.html">L5 projection</a> preserve result locators. Body hashes {summary["content_hashes"]}; verified rights {summary["rights_verified"]}.</p>{end}'
    )
    if start in projection:
        projection = projection[:projection.index(start)] + block + projection[projection.index(end) + len(end):]
    else:
        projection = projection.replace("<h2>Typed graph</h2>", block + "\n<h2>Typed graph</h2>")
    projection_path.write_text(projection, encoding="utf-8")

    cycle_path = HERE / "knowledge-cycle-report.html"
    cycle = cycle_path.read_text(encoding="utf-8")
    cstart, cend = "<!-- external-cycle-report:start -->", "<!-- external-cycle-report:end -->"
    external = {
        "cycle_id": "external-cycle-1", "url_batches": url_batches, "url_attempts": summary["url_observations"],
        "url_request_attempts": url_request_attempts,
        "url_metadata_fetched": fetched_urls, "url_http_errors": http_error_urls,
        "url_network_failures": failed_urls, "url_not_started": not_started_urls,
        "media_batches": media_batches, "media_attempts": summary["media_observations"], "media_metadata_fetched": fetched_media,
        "body_hashes": summary["content_hashes"], "rights_verified": summary["rights_verified"],
        "improvement_units": fetched_urls + fetched_media,
        "final_retry": {"attempts": len(retry_records), "counts": retry_counts},
        "recovery": {"attempts": len(recovery_records), "counts": recovery_counts},
        "stopping_reason": "one bounded recovery sample completed; 2 network failures recovered while persistent access-control, robots, timeout, and connection-refused outcomes remain explicit",
    }
    script = json.dumps(external, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    cblock = (
        f'{cstart}<section data-external-cycle-id="external-cycle-1"><h2>External Cycle 1</h2>'
        '<p>Input: 1,203 URL and 17 media references with fetched content 0.</p>'
        f'<p>Result: URL metadata {fetched_urls} success, {http_error_urls} HTTP error, {failed_urls} network failure, {not_started_urls} not started; media HEAD metadata {fetched_media} success. Body hashes {summary["content_hashes"]}; verified rights {summary["rights_verified"]}.</p>'
        f'<p>Final retry: {len(retry_records)} attempts, <code>{html.escape(json.dumps(retry_counts, sort_keys=True))}</code>.</p>'
        f'<p>Recovery sample: {len(recovery_records)} records, <code>{html.escape(json.dumps(recovery_counts, sort_keys=True))}</code>; {url_request_attempts} total URL request attempts including bounded retries.</p>'
        f'<p>Decision: {html.escape(external["stopping_reason"])}</p></section>'
        f'<script id="external-cycle-result" type="application/json">{script}</script>{cend}'
    )
    if cstart in cycle:
        cycle = cycle[:cycle.index(cstart)] + cblock + cycle[cycle.index(cend) + len(cend):]
    else:
        cycle = cycle.replace("<h2>Stopping reason</h2>", cblock + "\n<h2>Stopping reason</h2>")
    cycle_path.write_text(cycle, encoding="utf-8")


def main():
    manifest, results = load("external-source-manifest.json"), load("external-fetch-results.json")
    graph, observation_ids = build_graph(manifest, results)
    conclusions = build_conclusions(manifest, graph, observation_ids)
    summary = build_projection(manifest, graph, conclusions)
    update_discovery(summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
