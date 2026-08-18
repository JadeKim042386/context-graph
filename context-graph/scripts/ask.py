"""Entry point for asking the knowledge map.

This does not rebuild the map. Refreshes only run at session start, when a
delegated task ends, and right before and after compaction. It does, however,
report how many documents the map is behind.
"""
import os
import subprocess
import sys

from config import load_config, default_config_path

# A single character such as an em dash (—) in the answer is enough to kill the
# default console encoding on a Korean Windows box. It dies at the print, after
# the question already ran, so the answer is lost. Pin the encoding here.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

DOCUMENT_SUFFIXES = (".md", ".markdown", ".html", ".htm")

USAGE = """Ask the knowledge map.

    python ask.py "<question>"              find a value or a decision
    python ask.py --path "<a>" "<b>"        the path linking two nodes
    python ask.py --explain "<node>"        explain that node

**Ask in the language the knowledge documents are written in.** A question in
another language matches nothing.

**Ask narrowly.** A question after a single value ("tray piece length median")
comes back in a few hundred characters, far cheaper than opening the file. A
question that sweeps a whole topic ("clustering objective function overall")
fills the 20,000 budget with a truncated list, more expensive than reading one
note whole. To sweep a topic, hand it to a subagent and take only the conclusion.
"""


def stale_documents(source_dirs, map_path):
    """Return the names of documents newer than the map. 248 files take about 2 ms."""
    if not os.path.exists(map_path):
        return ["(no map)"]
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
    """Build the command that calls the query tool. The budget is a measured value, pinned here."""
    command = ["graphify", mode, *arguments, "--graph", map_path]
    if mode == "query":
        command += ["--budget", str(budget)]
    return command


def truncation_notice(answer):
    """Return the notice to print when the answer filled the budget. Empty if it did not."""
    if "budget" in answer and "cut by" in answer:
        return ("\n[The question was broad, so the answer filled the budget and was cut off. "
                "That costs more than reading one document whole. Narrow the words and ask "
                "again, or hand the topic to a subagent and take only the conclusion]")
    return ""


def run(mode, arguments, source_dirs, map_path, budget):
    """Ask, then report a truncated answer or a map that lags the documents."""
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
        preview = ", ".join(changed[:3]) + (" and more" if len(changed) > 3 else "")
        print(f"\n[The map is behind {len(changed)} document(s) — {preview}. "
              f"It is refreshed at the next compaction]")
    return completed.returncode


def main(argv):
    """Read the paths and the budget from the config, then ask. No path is hard-coded."""
    if not argv:
        print(USAGE)
        return 1
    config = load_config(default_config_path())
    if not config["map_path"]:
        print("The config has no place for the map. Run the first-time setup flow first.")
        return 1

    if argv[0] == "--path":
        if len(argv) != 3:
            print("--path needs two node names.")
            return 1
        mode, arguments = "path", argv[1:3]
    elif argv[0] == "--explain":
        if len(argv) != 2:
            print("--explain needs one node name.")
            return 1
        mode, arguments = "explain", argv[1:2]
    else:
        mode, arguments = "query", [" ".join(argv)]

    return run(mode, arguments, config["source_dirs"], config["map_path"],
               config["answer_budget"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
