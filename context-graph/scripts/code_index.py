#!/usr/bin/env python3
"""Collect Git-pinned code evidence and build a small Python structure index."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

GENERATOR_VERSION = "code-index-v1"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_digest(value: dict[str, Any]) -> str:
    stable = {key: item for key, item in value.items() if key != "generated_at"}
    rendered = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256(rendered)


def _commit_info(repo: Path, commit: str) -> dict[str, str]:
    full_commit = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}")
    return {
        "commit_sha": full_commit,
        "tree_sha": _git(repo, "rev-parse", f"{full_commit}^{{tree}}"),
        "branch_observed": _git(repo, "branch", "--show-current"),
    }


def _paths(repo: Path, commit_sha: str, paths: Iterable[str] | None) -> list[str]:
    all_paths = _git(repo, "ls-tree", "-r", "--name-only", commit_sha).splitlines()
    requested = [p for p in (paths or []) if p]
    if not requested:
        return [p for p in all_paths if p.endswith(".py")]
    return [p for p in all_paths if any(p == wanted or p.startswith(wanted.rstrip("/") + "/") for wanted in requested)]


def _blob_shas(repo: Path, commit_sha: str) -> dict[str, str]:
    lines = _git(repo, "ls-tree", "-r", commit_sha).splitlines()
    result: dict[str, str] = {}
    for line in lines:
        metadata, path = line.split("\t", 1)
        fields = metadata.split()
        if len(fields) >= 3:
            result[path] = fields[2]
    return result


def _source_record(repo: Path, info: dict[str, str]) -> dict[str, Any]:
    remote = ""
    try:
        remote = _git(repo, "config", "--get", "remote.origin.url")
    except subprocess.CalledProcessError:
        remote = str(repo.resolve())
    return {
        "schema_version": 1,
        "id": f"SRC-{info['commit_sha'][:12]}",
        "record_type": "Source",
        "revision": 1,
        "status": "proposed",
        "source_kind": "repository",
        "repository_id": _sha256(remote.encode())[:16],
        "repository": remote,
        **info,
        "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "rights_state": "unverified",
    }


def collect_records(repo: Path, commit: str = "HEAD", paths: Iterable[str] | None = None) -> dict[str, Any]:
    info = _commit_info(repo, commit)
    source = _source_record(repo, info)
    evidence: list[dict[str, Any]] = []
    for path in _paths(repo, info["commit_sha"], paths):
        blob_sha = _git(repo, "rev-parse", f"{info['commit_sha']}:{path}")
        content = subprocess.run(
            ["git", "-C", str(repo), "show", f"{info['commit_sha']}:{path}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        text = content.decode("utf-8", errors="replace")
        evidence.append(
            {
                "schema_version": 1,
                "id": f"EVD-{info['commit_sha'][:12]}-{_sha256(path.encode())[:10]}",
                "record_type": "Evidence",
                "revision": 1,
                "status": "proposed",
                "source_id": source["id"],
                "commit_sha": info["commit_sha"],
                "blob_sha": blob_sha,
                "path_at_commit": path,
                "line_start": 1,
                "line_end": max(1, len(text.splitlines())),
                "content_sha256": _sha256(content),
                "selector_type": "git-line-range",
                "locator": f"git -C <repo> show {info['commit_sha']}:{path}",
                "extraction_method": GENERATOR_VERSION,
            }
        )
    return {"source": source, "evidence": evidence}


def replay_evidence(repo: Path, evidence: dict[str, Any]) -> bool:
    """Replay a Git-pinned evidence selector without trusting the current branch."""
    commit = evidence["commit_sha"]
    path = evidence["path_at_commit"]
    blob_sha = _git(repo, "rev-parse", f"{commit}:{path}")
    content = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    return blob_sha == evidence["blob_sha"] and _sha256(content) == evidence["content_sha256"]


class _PythonIndex(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, str]] = []

    def _add_symbol(self, node: ast.AST, kind: str, name: str) -> None:
        self.nodes.append(
            {
                "id": f"{self.path}:{getattr(node, 'lineno', 1)}:{name}",
                "kind": kind,
                "name": name,
                "path": self.path,
                "line": getattr(node, "lineno", 1),
                "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 1)),
            }
        )

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            self._add_symbol(node, "import", alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        module = node.module or ""
        self._add_symbol(node, "import", module)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._add_symbol(node, "function", node.name)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._add_symbol(node, "class", node.name)
        self.generic_visit(node)


def build_index(repo: Path, commit: str = "HEAD", paths: Iterable[str] | None = None) -> dict[str, Any]:
    info = _commit_info(repo, commit)
    selected = _paths(repo, info["commit_sha"], paths)
    blob_shas = _blob_shas(repo, info["commit_sha"])
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    for path in selected:
        if not path.endswith(".py"):
            continue
        content = subprocess.run(
            ["git", "-C", str(repo), "show", f"{info['commit_sha']}:{path}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.decode("utf-8", errors="replace")
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError:
            continue
        parser = _PythonIndex(path)
        parser.visit(tree)
        blob_sha = blob_shas[path]
        file_id = f"file:{path}"
        nodes.append({"id": file_id, "kind": "file", "name": path, "path": path, "commit_sha": info["commit_sha"], "blob_sha": blob_sha, "locator": f"git -C <repo> show {info['commit_sha']}:{path}"})
        for node in parser.nodes:
            node.update(
                {
                    "commit_sha": info["commit_sha"],
                    "blob_sha": blob_sha,
                    "module": path,
                    "qualified_name": f"{path}:{node['name']}",
                    "locator": f"git -C <repo> show {info['commit_sha']}:{path}",
                }
            )
            edges.append({"source": file_id, "relation": "contains", "target": node["id"]})
            if node["kind"] == "import":
                edges.append({"source": file_id, "relation": "imports", "target": node["name"]})
        nodes.extend(parser.nodes)
    nodes.sort(key=lambda item: item["id"])
    return {
        "schema_version": 1,
        "generator": GENERATOR_VERSION,
        "input_commit": info["commit_sha"],
        "input_tree": info["tree_sha"],
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "language": "python",
        "nodes": nodes,
        "edges": sorted(edges, key=lambda edge: (edge["source"], edge["relation"], edge["target"])),
        "limitations": ["python-ast-only", "no-runtime-binding", "no-rename-inference"],
    }


def _write(value: dict[str, Any], output: str | None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("collect", "index"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--repo", type=Path, default=Path.cwd())
        sub.add_argument("--commit", default="HEAD")
        sub.add_argument("--path", action="append", dest="paths")
        sub.add_argument("--output")
    args = parser.parse_args(argv)
    value = collect_records(args.repo, args.commit, args.paths) if args.command == "collect" else build_index(args.repo, args.commit, args.paths)
    _write(value, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
