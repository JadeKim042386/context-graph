import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from ask import USAGE, build_graphify_command, stale_documents, truncation_notice


def test_지도보다_새_문서를_찾아낸다(tmp_path):
    source = tmp_path / "docs"; source.mkdir()
    (source / "가.md").write_text("내용", encoding="utf-8")
    map_path = tmp_path / "graph.json"
    map_path.write_text("{}", encoding="utf-8")
    assert stale_documents([str(source)], str(map_path)) == []
    time.sleep(0.01)
    (source / "나.md").write_text("새 내용", encoding="utf-8")
    assert stale_documents([str(source)], str(map_path)) == ["나"]


def test_지도가_없으면_전부_뒤처진_것으로_본다(tmp_path):
    source = tmp_path / "docs"; source.mkdir()
    (source / "가.md").write_text("내용", encoding="utf-8")
    assert stale_documents([str(source)], str(tmp_path / "없음.json")) == ["(지도 없음)"]


def test_묻는_명령에_한도가_박혀_있다(tmp_path):
    command = build_graphify_command("query", ["청크 기준"], "C:/지도/graph.json", 20000)
    assert command[:2] == ["graphify", "query"]
    assert "--budget" in command and "20000" in command
    assert "--graph" in command and "C:/지도/graph.json" in command


def test_길찾기는_한도를_붙이지_않는다():
    command = build_graphify_command("path", ["가", "나"], "C:/지도/graph.json", 20000)
    assert command[:2] == ["graphify", "path"]
    assert "--budget" not in command


def test_답이_한도까지_차면_알려준다():
    잘린_답 = "... budget 20000 tokens, 12 results cut by budget ..."
    assert "좁혀" in truncation_notice(잘린_답)


def test_짧은_답에는_알림이_붙지_않는다():
    assert truncation_notice("중앙값은 1.19 m 입니다 (가.md:8)") == ""


def test_안내에_좁게_물으라는_말이_있다():
    assert "좁게" in USAGE
