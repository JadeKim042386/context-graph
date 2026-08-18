import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
BUILD_MAP_SCRIPT = os.path.join(ROOT, "knowledge-map", "scripts", "build_map.py")


def _읽기(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as handle:
        return json.load(handle)


def _글로_읽기(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8-sig") as handle:
        return handle.read()


def test_창고_명세가_플러그인을_가리킨다():
    marketplace = _읽기(".claude-plugin", "marketplace.json")
    assert marketplace["name"] == "knowledge-map"
    assert marketplace["plugins"][0]["source"] == "./knowledge-map"


def test_플러그인_명세에_이름과_판이_있다():
    plugin = _읽기("knowledge-map", ".claude-plugin", "plugin.json")
    assert plugin["name"] == "knowledge-map"
    assert plugin["version"]


def test_갱신_자리_넷이_걸려_있다():
    hooks = _읽기("knowledge-map", "hooks", "hooks.json")["hooks"]
    assert set(hooks) == {"SessionStart", "SubagentStop", "PreCompact", "PostCompact"}


def test_훅_경로에_이_컴퓨터의_자리가_박혀_있지_않다():
    """어느 컴퓨터에서나 돌아야 하므로 경로는 ${CLAUDE_PLUGIN_ROOT} 로만 잡습니다."""
    hooks_text = _글로_읽기("knowledge-map", "hooks", "hooks.json")
    assert "C:" not in hooks_text and "/home/" not in hooks_text
    for event in json.loads(hooks_text)["hooks"].values():
        for group in event:
            for hook in group["hooks"]:
                if "scripts" in hook["command"]:
                    assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"]


def test_훅이_부르는_지도_만들기가_실제로_돈다(tmp_path):
    """훅은 스크립트를 명령줄로 부릅니다. 부를 입구가 없으면 갱신이 통째로 안 됩니다."""
    source = tmp_path / "docs"
    source.mkdir()
    (source / "가.md").write_text("## 절\n\n중앙값은 1.19 m 입니다\n", encoding="utf-8")
    map_path = tmp_path / "map" / "graph.json"
    completed = subprocess.run(
        [sys.executable, BUILD_MAP_SCRIPT, "--source", str(source), "--out", str(map_path)],
        capture_output=True)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    assert map_path.exists()


def test_안내에_한계_셋이_적혀_있다():
    readme = _글로_읽기("knowledge-map", "README.md")
    assert "적힌 언어" in readme                       # 하나: 문서 언어로 물어야 한다
    assert "20,000" in readme or "20000" in readme     # 둘: 답 분량 한도
    assert "좁게" in readme                            # 셋: 넓게 물으면 잘린 목록이 온다


def test_스킬에도_같은_규칙이_적혀_있다():
    skill = _글로_읽기("knowledge-map", "skills", "knowledge-map", "SKILL.md")
    assert "적힌 언어" in skill
    assert "20,000" in skill or "20000" in skill
    assert "좁게" in skill
