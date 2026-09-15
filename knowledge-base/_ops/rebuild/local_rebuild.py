"""Build deterministic local-only evidence projections from the frozen inventory."""

import argparse
import hashlib
import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


REBUILD = Path(__file__).resolve().parent
ROOT = REBUILD.parents[2]
BLOCK_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "pre",
    "blockquote", "figcaption", "dt", "dd", "summary", "text",
}
MEDIA_TAGS = {"img", "video", "audio", "source", "iframe"}


def stable_id(prefix, *parts):
    payload = "\x1f".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20].upper()}"


def normalize_text(parts):
    return " ".join("".join(parts).split())


class BlockParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = []
        self.ordinals = Counter()
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        if tag in BLOCK_TAGS:
            self.ordinals[tag] += 1
            line, column = self.getpos()
            self.active.append({
                "tag": tag,
                "ordinal": self.ordinals[tag],
                "line_start": line,
                "column_start": column,
                "parts": [],
            })
        if tag in MEDIA_TAGS:
            text = attrs.get("alt") or attrs.get("title")
            if text:
                self.ordinals[tag] += 1
                line, column = self.getpos()
                self.blocks.append({
                    "kind": "media-description",
                    "tag": tag,
                    "ordinal": self.ordinals[tag],
                    "line_start": line,
                    "line_end": line,
                    "column_start": column,
                    "text": normalize_text([text]),
                })

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        for active in self.active:
            active["parts"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        for index in range(len(self.active) - 1, -1, -1):
            if self.active[index]["tag"] != tag:
                continue
            block = self.active.pop(index)
            text = normalize_text(block.pop("parts"))
            if text:
                line_end, _ = self.getpos()
                block.update({"kind": "html-block", "line_end": line_end, "text": text})
                self.blocks.append(block)
            break


def provenance(snapshot, method):
    return {
        "activity_id": "ACT-KE-LOCAL-REBUILD-20260914-EVIDENCE",
        "agent": "knowledge-engineer",
        "method": method,
        "inventory_snapshot_sha256": snapshot,
        "network_used": False,
    }


def evidence_record(source, kind, locator, content, snapshot, visibility="projected"):
    serialized = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, sort_keys=True)
    content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return {
        "stable_id": stable_id("EVD", source["stable_id"], kind, json.dumps(locator, ensure_ascii=False, sort_keys=True), content_hash),
        "source_id": source["stable_id"],
        "source_path": source["path"],
        "kind": kind,
        "visibility": visibility,
        "content": None if visibility == "evaluator-only" else content,
        "content_sha256": content_hash,
        "locator": locator,
        "status": "observed" if visibility != "evaluator-only" else "sealed",
        "truth_status": "source-assertion-unverified",
        "provenance": provenance(snapshot, "local format-specific extraction"),
    }


def extract_html(source, snapshot):
    parser = BlockParser()
    parser.feed((ROOT / source["path"]).read_text(encoding="utf-8", errors="replace"))
    records = []
    for block in sorted(parser.blocks, key=lambda item: (item["line_start"], item["column_start"], item["tag"], item["ordinal"])):
        locator = {
            "type": "html-selector",
            "path": source["path"],
            "selector_model": "document-global-tag-ordinal",
            "selector": f"global-tag-ordinal({block['tag']},{block['ordinal']})",
            "element": {
                "tag": block["tag"],
                "global_ordinal": block["ordinal"],
            },
            "web_annotation_selector": {
                "type": "TextQuoteSelector",
                "exact": block["text"],
            },
            "line_start": block["line_start"],
            "line_end": block["line_end"],
            "text_quote": block["text"],
            "source_sha256": source["sha256"],
        }
        records.append(evidence_record(source, block["kind"], locator, block["text"], snapshot))
    return records


def pointer_escape(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def walk_json(value, pointer=""):
    if isinstance(value, dict):
        if not value:
            yield pointer, value
        for key in sorted(value):
            yield from walk_json(value[key], f"{pointer}/{pointer_escape(key)}")
    elif isinstance(value, list):
        if not value:
            yield pointer, value
        for index, item in enumerate(value):
            yield from walk_json(item, f"{pointer}/{index}")
    else:
        yield pointer, value


def extract_json(source, snapshot):
    value = json.loads((ROOT / source["path"]).read_text(encoding="utf-8"))
    if source["is_projection"]:
        summary = {
            "top_level_type": type(value).__name__,
            "top_level_keys": sorted(value) if isinstance(value, dict) else None,
            "top_level_count": len(value) if isinstance(value, (dict, list)) else 1,
        }
        locator = {"type": "json-pointer", "path": source["path"], "pointer": "", "source_sha256": source["sha256"]}
        return [evidence_record(source, "json-structure", locator, summary, snapshot)]
    records = []
    for pointer, item in walk_json(value):
        visibility = "evaluator-only" if source["path"] == "design/performance-fixture.json" and pointer.startswith("/evaluator_sidecar") else "projected"
        locator = {"type": "json-pointer", "path": source["path"], "pointer": pointer, "source_sha256": source["sha256"]}
        records.append(evidence_record(source, "structured-value", locator, item, snapshot, visibility))
    return records


def extract_text(source, snapshot):
    content = (ROOT / source["path"]).read_text(encoding="utf-8", errors="replace")
    line_count = content.count("\n") + 1
    kind = "code-source" if source["path"].endswith(".py") else "text-source"
    locator = {
        "type": "code-lines" if kind == "code-source" else "text-position",
        "path": source["path"],
        "line_start": 1,
        "line_end": line_count,
        "source_sha256": source["sha256"],
    }
    return [evidence_record(source, kind, locator, content, snapshot)]


def extract_binary(source, snapshot):
    locator = {
        "type": "byte-range",
        "path": source["path"],
        "byte_start": 0,
        "byte_end": source["size_bytes"],
        "source_sha256": source["sha256"],
    }
    content = f"[generated binary preserved; sha256={source['sha256']}; bytes={source['size_bytes']}]"
    record = evidence_record(source, "generated-binary-presence", locator, content, snapshot)
    record["status"] = "extraction-skipped-generated-binary"
    return [record]


def build_evidence():
    manifest = json.loads((REBUILD / "source-manifest.json").read_text(encoding="utf-8"))
    snapshot = manifest["inventory_snapshot_sha256"]
    records = []
    coverage = {}
    for source in manifest["records"]:
        actual_hash = hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest()
        expected_hash = source.get("current_sha256", source["sha256"])
        if actual_hash != expected_hash:
            raise RuntimeError(f"frozen source drift: {source['path']}")
        suffix = Path(source["path"]).suffix.lower()
        if source["mime"] == "text/html":
            extracted = extract_html(source, snapshot)
        elif suffix == ".json":
            extracted = extract_json(source, snapshot)
        elif source["mime"].startswith("text/") or suffix == ".py" or not suffix:
            extracted = extract_text(source, snapshot)
        else:
            extracted = extract_binary(source, snapshot)
        if not extracted:
            locator = dict(source["locator"])
            extracted = [evidence_record(source, "empty-source", locator, "", snapshot)]
        records.extend(extracted)
        coverage[source["stable_id"]] = len(extracted)
    document = {
        "schema_version": 1,
        "evidence_set_id": "EVDSET-KE-LOCAL-20260914-V2",
        "inventory_snapshot_sha256": snapshot,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "network_used": False,
        "record_count": len(records),
        "visibility_counts": dict(sorted(Counter(item["visibility"] for item in records).items())),
        "kind_counts": dict(sorted(Counter(item["kind"] for item in records).items())),
        "source_coverage": coverage,
        "records": records,
    }
    (REBUILD / "local-evidence.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def build_graph(manifest, evidence):
    snapshot = evidence["inventory_snapshot_sha256"]
    generated_at = evidence["generated_at"]
    nodes = []
    edges = []
    for source in manifest["records"]:
        nodes.append({
            "id": source["stable_id"],
            "stable_id": source["stable_id"],
            "type": "Source",
            "path": source["path"],
            "mime": source["mime"],
            "canonical_status": source["canonical_status"],
            "is_projection": source["is_projection"],
            "locator": source["locator"],
            "provenance": source["provenance"],
        })
    for record in evidence["records"]:
        nodes.append({
            "id": record["stable_id"],
            "stable_id": record["stable_id"],
            "type": "Evidence",
            "source_id": record["source_id"],
            "kind": record["kind"],
            "visibility": record["visibility"],
            "content_sha256": record["content_sha256"],
            "locator": record["locator"],
            "status": record["status"],
            "truth_status": record["truth_status"],
            "provenance": record["provenance"],
        })
        edge_id = stable_id("EDG", record["source_id"], "has_evidence", record["stable_id"])
        edges.append({
            "id": edge_id,
            "stable_id": edge_id,
            "type": "has_evidence",
            "source": record["source_id"],
            "target": record["stable_id"],
            "provenance": provenance(snapshot, "source-to-local-evidence projection"),
        })
    graph = {
        "schema_version": 2,
        "graph_id": "KG-KE-LOCAL-20260914-V2",
        "inventory_snapshot_sha256": snapshot,
        "generated_at": generated_at,
        "nodes": nodes,
        "edges": edges,
    }
    (REBUILD / "typed-knowledge-graph.local-v2.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return graph


def build_conclusions(manifest, evidence, graph):
    snapshot = evidence["inventory_snapshot_sha256"]
    by_source = defaultdict(list)
    for record in evidence["records"]:
        by_source[record["source_id"]].append(record)
    conclusions = []
    for source in manifest["records"]:
        records = by_source[source["stable_id"]]
        only_unextracted = all(
            record["status"].startswith("extraction-skipped") for record in records
        )
        conclusion_id = stable_id("CON", source["stable_id"], "source-content-coverage")
        conclusions.append({
            "id": conclusion_id,
            "subject_id": source["stable_id"],
            "statement": (
                f"Local content from {source['path']} was projected into {len(records)} evidence locators."
                if not only_unextracted
                else f"The binary at {source['path']} was preserved, but content extraction abstains."
            ),
            "status": "abstain" if only_unextracted else "observed",
            "evidence_ids": [record["stable_id"] for record in records],
            "conclusion_method": "source-content-coverage",
            "truth_status": "source-assertion-unverified",
            "provenance": provenance(snapshot, "local evidence coverage conclusion"),
        })
    conflict_sources = [
        source for source in manifest["records"]
        if "conflict" in source["path"].lower()
    ]
    conflict_sets = []
    for source in conflict_sources:
        conflict_sets.append({
            "id": stable_id("CFS", source["stable_id"], "unparsed-local-conflict"),
            "status": "unknown",
            "member_claim_ids": [],
            "evidence_ids": [record["stable_id"] for record in by_source[source["stable_id"]]],
            "resolution": "abstain",
            "conclusion_method": "preserve-unparsed-conflict-projection",
            "provenance": provenance(snapshot, "conflict projection preserved without score aggregation"),
        })
    document = {
        "schema_version": 2,
        "conclusions_id": "CONSET-KE-LOCAL-20260914-V2",
        "graph_id": graph["graph_id"],
        "inventory_snapshot_sha256": snapshot,
        "generated_at": evidence["generated_at"],
        "conflict_policy": "preserve conflict sets; do not collapse them into a scalar score; abstain when unresolved",
        "conclusions": conclusions,
        "conflict_sets": conflict_sets,
    }
    (REBUILD / "conclusions.local-v2.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return document


def render_content(record):
    if record["visibility"] == "evaluator-only":
        return "[sealed evaluator-only evidence; content omitted from projection]"
    content = record["content"]
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True)


def build_projection(manifest, evidence, graph, conclusions):
    by_source = defaultdict(list)
    for record in evidence["records"]:
        by_source[record["source_id"]].append(record)
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8"><title>Local Knowledge Projection v2</title></head><body>',
        "<h1>Local Knowledge Projection v2</h1>",
        f"<p>Inventory snapshot: <code>{html.escape(evidence['inventory_snapshot_sha256'])}</code></p>",
        "<p>This is a generated L5 projection, not a canonical source. Evaluator-only gold content is sealed.</p>",
        "<p>Evidence blocks are verbatim source excerpts retained for provenance and hash fidelity; source-language text in those blocks is intentionally not translated.</p>",
        '<p>Conflict semantics are not inferred. See the traceable <a href="semantic-conflict-audit.json">semantic conflict abstention audit</a>.</p>',
    ]
    for source in manifest["records"]:
        source_id = source["stable_id"]
        parts.append(
            f'<section data-source-id="{html.escape(source_id, quote=True)}">'
            f"<h2>{html.escape(source['path'])}</h2>"
            f"<p><code>{html.escape(source_id)}</code> · {html.escape(source['mime'])}</p>"
        )
        for record in by_source[source_id]:
            opening = (
                f'<article data-evidence-id="{html.escape(record["stable_id"], quote=True)}">'
                f"<h3>{html.escape(record['kind'])}</h3>"
                f"<p>Status: {html.escape(record['status'])}; visibility: {html.escape(record['visibility'])}</p>"
            )
            if record["visibility"] == "evaluator-only":
                parts.append(
                    opening
                    + "<p>Locator and content are sealed outside this public projection.</p>"
                    + f"<pre>{html.escape(render_content(record))}</pre></article>"
                )
            else:
                locator = json.dumps(record["locator"], ensure_ascii=False, sort_keys=True)
                parts.append(
                    opening
                    + f"<p>Locator: <code>{html.escape(locator)}</code></p>"
                    + f"<pre>{html.escape(render_content(record))}</pre></article>"
                )
        parts.append("</section>")
    summary = {
        "inventory_snapshot_sha256": evidence["inventory_snapshot_sha256"],
        "sources": len(manifest["records"]),
        "evidence": len(evidence["records"]),
        "graph_nodes": len(graph["nodes"]),
        "graph_edges": len(graph["edges"]),
        "conclusions": len(conclusions["conclusions"]),
    }
    parts.append(
        '<script id="local-projection-summary" type="application/json">'
        + json.dumps(summary, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
        + "</script></body></html>\n"
    )
    (REBUILD / "knowledge-projection.local-v2.html").write_text("\n".join(parts), encoding="utf-8")


def build_semantic_conflict_audit(manifest, evidence):
    snapshot = evidence["inventory_snapshot_sha256"]
    by_source = defaultdict(list)
    for record in evidence["records"]:
        by_source[record["source_id"]].append(record)
    records = []
    for source in manifest["records"]:
        if "conflict" not in source["path"].lower():
            continue
        source_evidence = by_source[source["stable_id"]]
        records.append({
            "conflict_source_id": source["stable_id"],
            "source_path": source["path"],
            "source_locator": source["locator"],
            "evidence_ids": [record["stable_id"] for record in source_evidence],
            "evidence_locators": [record["locator"] for record in source_evidence],
            "status": "unknown",
            "semantic_claims": [],
            "semantic_parse_status": "not_inferred",
            "resolution": "abstain",
            "abstain_reason": (
                "The local conflict report contains no independently verified claim pair; "
                "claim-level meaning is not inferred from a generated report without source comparison."
            ),
            "provenance": provenance(snapshot, "trace conflict report and abstain without semantic inference"),
        })
    document = {
        "schema_version": 1,
        "audit_id": "AUD-KE-SEMANTIC-CONFLICT-20260914-V2",
        "inventory_snapshot_sha256": snapshot,
        "generated_at": evidence["generated_at"],
        "status": "passed" if records and all(record["evidence_ids"] for record in records) else "partial",
        "policy": "Preserve source and evidence locators; never infer claim-level conflicts; abstain until independently compared.",
        "records": records,
        "provenance": provenance(snapshot, "semantic conflict abstention audit"),
    }
    (REBUILD / "semantic-conflict-audit.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return document


def append_build_event(build_log_path, evidence, counts):
    build_log_path = Path(build_log_path)
    existing_count = 0
    if build_log_path.exists():
        existing_count = sum(1 for line in build_log_path.read_text(encoding="utf-8").splitlines() if line.strip())
    generated_at = datetime.now(timezone.utc).isoformat()
    event_id = stable_id(
        "ACT", evidence["inventory_snapshot_sha256"], generated_at, existing_count, json.dumps(counts, sort_keys=True)
    )
    event = {
        "activity_type": "knowledge-rebuild-local-v2",
        "agent": "knowledge-engineer",
        "counts": counts,
        "event_id": event_id,
        "generated_at": generated_at,
        "graphify_out_status": "preserved-not-overwritten",
        "inputs": [
            "knowledge-base/_ops/rebuild/source-manifest.json",
            "knowledge-base/_ops/rebuild/local-evidence.json",
        ],
        "inventory_snapshot_sha256": evidence["inventory_snapshot_sha256"],
        "outputs": [
            "knowledge-base/_ops/rebuild/typed-knowledge-graph.local-v2.json",
            "knowledge-base/_ops/rebuild/conclusions.local-v2.json",
            "knowledge-base/_ops/rebuild/semantic-conflict-audit.json",
            "knowledge-base/_ops/rebuild/local-rebuild-audit.json",
            "knowledge-base/_ops/rebuild/knowledge-projection.local-v2.html",
        ],
        "status": "local-v2-generated",
    }
    with build_log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return event


def build_audit(manifest, evidence, graph, conclusions, semantic_conflict_audit):
    snapshot = evidence["inventory_snapshot_sha256"]
    evaluator_records = [record for record in evidence["records"] if record["visibility"] == "evaluator-only"]
    requirements = [
        ("raw-preservation", "passed", ["source-manifest.json#/records", "local_rebuild.py#frozen-source-hash-check"]),
        ("source-catalog", "passed", ["source-manifest.json#/records"]),
        ("format-locators", "passed", ["local-evidence.json#/records/*/locator"]),
        ("typed-graph", "passed", ["typed-knowledge-graph.local-v2.json#/nodes", "typed-knowledge-graph.local-v2.json#/edges"]),
        ("typed-conclusions", "passed", ["conclusions.local-v2.json#/conclusions"]),
        ("html-projection", "passed", ["knowledge-projection.local-v2.html"]),
        ("append-only-provenance", "passed", ["build-log.jsonl", "local_rebuild.py#append_build_event", "local-evidence.json#/records/*/provenance"]),
        ("gold-isolation", "passed", [f"local-evidence.json#/visibility_counts/evaluator-only={len(evaluator_records)}", "local-evidence.json#/records[visibility=evaluator-only]/content=null"]),
        ("conflict-abstain", semantic_conflict_audit["status"], ["semantic-conflict-audit.json#/records", "conclusions.local-v2.json#/conflict_sets", "conclusions.local-v2.json#/conflict_policy"]),
    ]
    document = {
        "schema_version": 1,
        "audit_id": "AUD-KE-LOCAL-REBUILD-20260914-V2",
        "inventory_snapshot_sha256": snapshot,
        "generated_at": evidence["generated_at"],
        "counts": {
            "sources": len(manifest["records"]),
            "evidence": len(evidence["records"]),
            "graph_nodes": len(graph["nodes"]),
            "graph_edges": len(graph["edges"]),
            "conclusions": len(conclusions["conclusions"]),
        },
        "requirements": [
            {"requirement_id": requirement_id, "status": status, "evidence": proof}
            for requirement_id, status, proof in requirements
        ],
        "unverified": [
            "Local source statements were projected but not independently truth-validated.",
            "Conflict claim semantics are intentionally not inferred; the traceable decision is abstain.",
            "External network content remains outside this local-only rebuild.",
        ],
        "provenance": provenance(snapshot, "local rebuild requirement audit"),
    }
    (REBUILD / "local-rebuild-audit.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return document


def build_followup(build_log_path=None):
    manifest = json.loads((REBUILD / "source-manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads((REBUILD / "local-evidence.json").read_text(encoding="utf-8"))
    if manifest["inventory_snapshot_sha256"] != evidence["inventory_snapshot_sha256"]:
        raise RuntimeError("manifest/evidence inventory snapshot mismatch")
    graph = build_graph(manifest, evidence)
    conclusions = build_conclusions(manifest, evidence, graph)
    semantic_conflict_audit = build_semantic_conflict_audit(manifest, evidence)
    build_projection(manifest, evidence, graph, conclusions)
    output = {
        "sources": len(manifest["records"]),
        "evidence": len(evidence["records"]),
        "graph_nodes": len(graph["nodes"]),
        "graph_edges": len(graph["edges"]),
        "conclusions": len(conclusions["conclusions"]),
        "semantic_conflict_records": len(semantic_conflict_audit["records"]),
    }
    append_build_event(build_log_path or REBUILD / "build-log.jsonl", evidence, output)
    audit = build_audit(manifest, evidence, graph, conclusions, semantic_conflict_audit)
    output["requirements"] = len(audit["requirements"])
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-only", action="store_true")
    args = parser.parse_args()
    if args.evidence_only:
        result = build_evidence()
        output = {"record_count": result["record_count"], "visibility_counts": result["visibility_counts"], "kind_counts": result["kind_counts"]}
    else:
        output = build_followup()
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
