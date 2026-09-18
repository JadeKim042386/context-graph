#!/usr/bin/env python3
"""Compare exact-name lexical lookup with the commit-bound multi-language index."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from code_index import build_index, is_code_path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


def evaluate(repo: Path, queries: list[str], commit: str = "HEAD") -> dict:
    pinned = _git(repo, "rev-parse", f"{commit}^{{commit}}")
    index_started = time.perf_counter()
    index = build_index(repo, pinned)
    index_ms = (time.perf_counter() - index_started) * 1000
    index_names: dict[str, list[dict]] = {}
    for node in index["nodes"]:
        index_names.setdefault(node["name"], []).append(node)
    lexical_hits: dict[str, list[str]] = {}
    lexical_ms = 0.0
    for query in queries:
        started = time.perf_counter()
        hits = []
        for path in _git(repo, "ls-tree", "-r", "--name-only", pinned).splitlines():
            if not is_code_path(path):
                continue
            text = subprocess.run(["git", "-C", str(repo), "show", f"{pinned}:{path}"], check=True, text=True, stdout=subprocess.PIPE).stdout
            if query in text:
                hits.append(path)
        lexical_hits[query] = hits
        lexical_ms += (time.perf_counter() - started) * 1000
    found = sum(bool(index_names.get(query)) for query in queries)
    lexical_found = sum(bool(lexical_hits[query]) for query in queries)
    return {
        "commit": pinned,
        "queries": queries,
        "query_count": len(queries),
        "lexical_recall": lexical_found / len(queries) if queries else 0.0,
        "index_recall": found / len(queries) if queries else 0.0,
        "lexical_candidate_count": sum(len(value) for value in lexical_hits.values()),
        "index_candidate_count": found,
        "lexical_ms": round(lexical_ms, 3),
        "index_build_ms": round(index_ms, 3),
        "index_generator": index["generator"],
        "limitations": index["limitations"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--query", action="append", dest="queries")
    args = parser.parse_args(argv)
    queries = args.queries or ["build_index", "collect_records", "build_map"]
    print(json.dumps(evaluate(args.repo, queries, args.commit), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
