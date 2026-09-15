#!/usr/bin/env python3
"""Update pointer-only project memory without copying source content."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", required=True, type=Path)
    parser.add_argument("--goal")
    parser.add_argument("--status", choices=["proposed", "verified", "accepted", "open", "blocked", "complete"])
    parser.add_argument("--snapshot-hash")
    parser.add_argument("--snapshot-source")
    parser.add_argument("--snapshot-id")
    args = parser.parse_args()
    data = json.loads(args.memory.read_text(encoding="utf-8")) if args.memory.exists() else {"schema_version": 1}
    now = datetime.now(timezone.utc).isoformat()
    if args.goal:
        data["current_goal"] = {"pointer": args.goal, "status": args.status or "verified", "updated_at": now}
    if args.snapshot_hash:
        data["snapshot_hash"] = {"algorithm": "sha256", "value": args.snapshot_hash, "status": "verified", "updated_at": now}
        if args.snapshot_source:
            data["snapshot_hash"]["source"] = args.snapshot_source
        if args.snapshot_id:
            data["snapshot_hash"]["snapshot_id"] = args.snapshot_id
    data.setdefault("approved_decision_pointers", [])
    data.setdefault("unresolved_pointers", [])
    args.memory.parent.mkdir(parents=True, exist_ok=True)
    args.memory.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "memory": str(args.memory), "updated_at": now}, ensure_ascii=False))


if __name__ == "__main__":
    main()
