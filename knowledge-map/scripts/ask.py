"""지식 지도에 묻는 입구입니다.

여기서 지도를 다시 만들지 않습니다. 갱신은 세션 시작·맡긴 작업 종료·압축 전후에만 돕니다.
다만 지도가 몇 개 문서보다 뒤처졌는지는 알려 줍니다.
"""
import os
import subprocess
import sys

from config import load_config, default_config_path

# 답에 줄표(—) 같은 글자가 하나만 있어도 한글 윈도우 기본 출력 방식으로는 찍다가 죽습니다.
# 묻는 일이 다 끝난 뒤 찍는 자리에서 죽으므로 답을 받고도 못 봅니다. 여기서 못 박습니다.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

DOCUMENT_SUFFIXES = (".md", ".markdown", ".html", ".htm")

USAGE = """지식 지도에 묻습니다.

    python ask.py "<물음>"                 값·결정 찾기
    python ask.py --path "<가>" "<나>"      두 노드를 잇는 길
    python ask.py --explain "<노드>"        그 노드 풀이

**지식 문서에 적힌 언어로** 물으십시오. 다른 언어로 물으면 한 건도 안 걸립니다.

**좁게 물으십시오.** 값 하나를 찾는 물음("트레이 조각 길이 중앙값")은 답이 수백 자로 와서
파일을 여는 것보다 훨씬 쌉니다. 반면 주제를 통째로 훑는 물음("클러스터링 목적함수 전반")은
한도 2만 토큰을 꽉 채운 잘린 목록이 와서 노트 하나를 통째로 읽는 것보다 비쌉니다.
주제를 훑어야 하면 서브에이전트에 맡겨 결론만 받으십시오.
"""


def stale_documents(source_dirs, map_path):
    """지도보다 새로 고쳐진 문서 이름을 돌려줍니다. 248개를 훑는 데 2밀리초쯤 걸립니다."""
    if not os.path.exists(map_path):
        return ["(지도 없음)"]
    map_written_at = os.path.getmtime(map_path)
    changed = []
    for source_dir in sorted(source_dirs):
        for folder, sub_folders, file_names in os.walk(source_dir):
            sub_folders.sort()
            for file_name in sorted(file_names):
                if file_name.endswith(DOCUMENT_SUFFIXES):
                    path = os.path.join(folder, file_name)
                    if os.path.getmtime(path) > map_written_at:
                        changed.append(os.path.splitext(file_name)[0])
    return changed


def build_graphify_command(mode, arguments, map_path, budget):
    """묻는 도구를 부를 명령을 만듭니다. 한도는 실측으로 정한 값이라 여기에 박습니다."""
    command = ["graphify", mode, *arguments, "--graph", map_path]
    if mode == "query":
        command += ["--budget", str(budget)]
    return command


def truncation_notice(answer):
    """답이 한도까지 차서 잘렸으면 알릴 말을 돌려줍니다. 안 잘렸으면 빈 글입니다."""
    if "budget" in answer and "cut by" in answer:
        return ("\n[물음이 넓어 답이 한도까지 차서 잘렸습니다. 이만큼이면 문서 하나를 통째로 "
                "읽는 것보다 비쌉니다. 낱말을 좁혀 다시 묻거나, 주제를 훑어야 하면 "
                "서브에이전트에 맡겨 결론만 받으십시오]")
    return ""


def run(mode, arguments, source_dirs, map_path, budget):
    """묻고, 답이 잘렸거나 지도가 뒤처졌으면 알립니다."""
    changed = stale_documents(source_dirs, map_path)
    completed = subprocess.run(build_graphify_command(mode, arguments, map_path, budget),
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                               capture_output=True)
    answer = completed.stdout.decode("utf-8", "replace")
    sys.stdout.write(answer)
    notice = truncation_notice(answer)
    if notice:
        print(notice)
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr.decode("utf-8", "replace"))
    if changed:
        preview = ", ".join(changed[:3]) + (" 외" if len(changed) > 3 else "")
        print(f"\n[지도가 문서 {len(changed)}개보다 뒤처져 있습니다 — {preview}. 다음 압축 때 갱신됩니다]")
    return completed.returncode


def main(argv):
    """설정에서 경로와 한도를 읽어 묻습니다. 경로는 어디에도 박지 않습니다."""
    if not argv:
        print(USAGE)
        return 1
    config = load_config(default_config_path())
    if not config["map_path"]:
        print("설정에 지도 자리가 없습니다. 먼저 처음 설치 흐름을 도십시오.")
        return 1

    if argv[0] == "--path":
        if len(argv) != 3:
            print("--path 는 노드 이름 두 개가 필요합니다.")
            return 1
        mode, arguments = "path", argv[1:3]
    elif argv[0] == "--explain":
        if len(argv) != 2:
            print("--explain 은 노드 이름 하나가 필요합니다.")
            return 1
        mode, arguments = "explain", argv[1:2]
    else:
        mode, arguments = "query", [" ".join(argv)]

    return run(mode, arguments, config["source_dirs"], config["map_path"],
               config["answer_budget"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
