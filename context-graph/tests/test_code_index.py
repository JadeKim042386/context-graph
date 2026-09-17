import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from code_index import build_index, collect_records, normalized_digest, replay_evidence


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


@pytest.fixture()
def code_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "lib.py").write_text("import os\n\ndef answer():\n    return 42\n", encoding="utf-8")
    (repo / "helpers.py").write_text("def answer():\n    return 7\n", encoding="utf-8")
    (repo / "test_lib.py").write_text("from lib import answer\n\ndef test_answer():\n    assert answer() == 42\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "fixture")
    return repo


def test_collect_records_is_commit_and_blob_bound(code_repo: Path):
    commit = git(code_repo, "rev-parse", "HEAD")
    records = collect_records(code_repo, commit)
    assert records["source"]["commit_sha"] == commit
    assert {item["path_at_commit"] for item in records["evidence"]} == {"helpers.py", "lib.py", "test_lib.py"}
    assert all(item["blob_sha"] and item["content_sha256"] for item in records["evidence"])
    assert all(item["locator"].startswith("git -C <repo> show ") for item in records["evidence"])
    assert all(replay_evidence(code_repo, item) for item in records["evidence"])


def test_build_index_finds_symbols_and_imports(code_repo: Path):
    commit = git(code_repo, "rev-parse", "HEAD")
    index = build_index(code_repo, commit)
    names = {(node["kind"], node["name"]) for node in index["nodes"]}
    assert ("import", "os") in names
    assert ("function", "answer") in names
    assert ("function", "test_answer") in names
    assert index["input_commit"] == commit
    assert index["limitations"]
    assert all(node["commit_sha"] == commit and node["blob_sha"] and node["locator"] for node in index["nodes"])
    assert any(edge["relation"] == "contains" for edge in index["edges"])
    assert any(edge["relation"] == "imports" for edge in index["edges"])
    assert len([node for node in index["nodes"] if node["name"] == "answer"]) == 2


def test_index_rejects_unknown_commit(code_repo: Path):
    with pytest.raises(subprocess.CalledProcessError):
        build_index(code_repo, "0" * 40)


def test_old_locator_survives_a_later_rename(code_repo: Path):
    first_commit = git(code_repo, "rev-parse", "HEAD")
    evidence = collect_records(code_repo, first_commit)["evidence"]
    (code_repo / "lib.py").rename(code_repo / "core.py")
    git(code_repo, "add", ".")
    git(code_repo, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "rename")
    assert all(replay_evidence(code_repo, item) for item in evidence)
    second = build_index(code_repo, "HEAD")
    assert any(node["path"] == "core.py" for node in second["nodes"])


def test_same_commit_has_a_deterministic_normalized_digest(code_repo: Path):
    commit = git(code_repo, "rev-parse", "HEAD")
    assert normalized_digest(build_index(code_repo, commit)) == normalized_digest(build_index(code_repo, commit))
