#!/usr/bin/env python3
"""Validate artifacts required by the project knowledge-engineering skill."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile", choices=["portable", "project"], default="portable")
    args = parser.parse_args()
    root = args.root.resolve()
    required = []
    if args.profile == "project":
        required = [
            "knowledge-base/_ops/memory/index.json",
            "knowledge/knowledge-base-architecture-design.html",
            "design/knowledge-base-comparative-report.html",
            "design/knowledge-base-comparative-results.json",
        ]
    missing = [path for path in required if not (root / path).exists()]
    if missing:
        print(json.dumps({"ok": False, "missing": missing}, ensure_ascii=False))
        return 1
    for relative in ("knowledge-base/_ops/memory/index.json", "design/knowledge-base-comparative-results.json"):
        candidate = root / relative
        if candidate.exists():
            json.loads(candidate.read_text(encoding="utf-8"))
    print(json.dumps({"ok": True, "root": str(root), "checked": required}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
