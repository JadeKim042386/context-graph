#!/usr/bin/env python3
"""Build privacy-preserving provisional knowledge from session event metadata."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def _events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("record_type") == "SessionLifecycleEvent":
            result.append(item)
    return result


def build_proposals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("session_id", "unknown")), []).append(event)
    proposals: list[dict[str, Any]] = []
    for session_id, session_events in sorted(grouped.items()):
        ordered = sorted(session_events, key=lambda item: (item.get("sequence", 0), item.get("occurred_at", "")))
        proposals.append(
            {
                "schema_version": 1,
                "record_type": "SessionKnowledgeProposal",
                "id": f"SKP-{session_id}",
                "session_id": session_id,
                "knowledge_state": "provisional",
                "promotion_state": "review_required",
                "candidate_claim_ids": [],
                "event_ids": [item.get("event_id") for item in ordered],
                "checkpoints": [
                    {
                        "event_type": item.get("event_type"),
                        "occurred_at": item.get("occurred_at"),
                        "artifact_pointers": item.get("artifact_pointers", []),
                        "working_tree_digest": item.get("working_tree_digest"),
                    }
                    for item in ordered
                ],
                "warnings": ["session metadata is not reviewed evidence", "session end is not completion proof"]
                if not any(item.get("event_type") == "session_end" for item in ordered)
                else ["session metadata is not reviewed evidence"],
                "generator": "build_session_proposal-v1",
            }
        )
    return proposals


def write_outputs(root: Path) -> list[Path]:
    ops = root / "knowledge-base" / "_ops"
    proposals_dir = ops / "session-proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    proposals = build_proposals(_events(ops / "session-events.jsonl"))
    outputs: list[Path] = []
    for proposal in proposals:
        path = proposals_dir / f"{proposal['session_id']}.json"
        path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outputs.append(path)
    rows = ["<h1>Session knowledge proposals</h1>", "<p>Provisional metadata only; review is required.</p>", "<ul>"]
    for proposal in proposals:
        rows.append(f"<li><code>{html.escape(proposal['id'])}</code>: {len(proposal['event_ids'])} lifecycle events</li>")
    rows.append("</ul>")
    index = proposals_dir / "index.html"
    index.write_text("<!doctype html><html><body>" + "".join(rows) + "</body></html>\n", encoding="utf-8")
    outputs.append(index)
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    write_outputs(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
