"""Entry point for asking the knowledge map.

This does not rebuild the map. Refreshes only run at session start, when a
delegated task ends, and right before and after compaction. It does, however,
report how many documents the map is behind.
"""
import json
import os
import re
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
    python ask.py --chain "<decision>"     what a decision came from and led to
    python ask.py --conflicts              values two documents state differently
    python ask.py --settle "1:2 2:3"       settle them (add --dry-run to only show)

**Ask in the language the knowledge documents are written in.** A question in
another language matches nothing.

**Ask narrowly.** A question after a single value ("tray piece length median")
comes back in a few hundred characters, far cheaper than opening the file. A
question that sweeps a whole topic ("clustering objective function overall")
fills the 20,000 budget with a truncated list, more expensive than reading one
note whole. To sweep a topic, hand it to a subagent and take only the conclusion.
"""


# ---------- decision causality ----------
# `caused_by` is a line a person writes in a decision document: `- caused_by [[ADR 0071]]`.
# The parser takes any relation name, so writing it needs no code change. The rest are
# relations already in use between decisions; they are shown apart because they are not cause.
CAUSE_RELATIONS = {"caused_by", "caused", "causes", "led_to"}
NEARBY_RELATIONS = {"supersedes", "supersedes_partially", "corrects", "refines", "extends",
                    "follows", "continues", "operationalizes"}
CHAIN_DEPTH = 3


def load_map(map_path):
    with open(map_path, encoding="utf-8") as handle:
        graph = json.load(handle)
    return graph["nodes"], graph["links"]


def find_node(nodes, wanted):
    """Match a node by name: exact first, then the shortest label that contains it."""
    lowered = wanted.strip().lower()
    exact = [node for node in nodes if (node.get("label") or "").strip().lower() == lowered]
    if exact:
        return exact[0]
    partial = sorted((node for node in nodes if lowered in (node.get("label") or "").lower()),
                     key=lambda node: len(node.get("label") or ""))
    return partial[0] if partial else None


def walk_chain(start_id, links, forward, relations, depth=CHAIN_DEPTH):
    """Follow one direction. A node is stepped on once, so a miswritten cycle still stops."""
    reached, frontier, seen = [], [(start_id, 0)], {start_id}
    while frontier:
        node_id, level = frontier.pop(0)
        if level >= depth:
            continue
        for link in links:
            if link["relation"] not in relations:
                continue
            here, there = ((link["source"], link["target"]) if forward
                           else (link["target"], link["source"]))
            if here != node_id or there in seen:
                continue
            seen.add(there)
            reached.append((there, link["relation"], level + 1))
            frontier.append((there, level + 1))
    return reached


def show_chain(wanted, map_path):
    """What a decision came from and what it led to, with the file and line for each."""
    nodes, links = load_map(map_path)
    start = find_node(nodes, wanted)
    if start is None:
        print("No node by that name: %s" % wanted)
        return 1
    label_of = {node["id"]: (node.get("label") or node["id"]) for node in nodes}
    source_of = {node["id"]: "%s:%s" % (node.get("source_file") or "?",
                                        node.get("source_location") or "?") for node in nodes}
    print("%s  [%s]" % (label_of[start["id"]], source_of[start["id"]]))
    for title, forward, relations in (("came from", True, CAUSE_RELATIONS),
                                      ("led to", False, CAUSE_RELATIONS),
                                      ("nearby decisions (not cause)", True, NEARBY_RELATIONS)):
        reached = walk_chain(start["id"], links, forward, relations)
        print("")
        print("%s - %d" % (title, len(reached)))
        if not reached:
            print("   none.")
            continue
        for node_id, relation, level in reached[:20]:
            print("   %s%s · %s  [%s]" % ("  " * (level - 1), relation,
                                          label_of.get(node_id, node_id),
                                          source_of.get(node_id, "?")))
        if len(reached) > 20:
            print("   ... and %d more" % (len(reached) - 20))
    print("")
    print("[Write `- caused_by [[ADR 0071]]` in a decision document and it shows up here. "
          "The walk goes %d steps]" % CHAIN_DEPTH)
    return 0


# ---------- settling conflicts ----------
CONFLICT_PAGE = 10          # how many are shown at once


def conflict_paths(map_path):
    folder = os.path.dirname(map_path) or "."
    stem = os.path.splitext(os.path.basename(map_path))[0]
    return (os.path.join(folder, stem + ".conflicts.txt"),
            os.path.join(folder, stem + ".suppressions.json"),
            os.path.join(folder, stem + ".resolutions.log"))


def current_conflicts(map_path, watched_names=None):
    """Conflicts in a stable order: the strong pass first, then the context pass."""
    import conflicts as conflict_check

    with open(map_path, encoding="utf-8") as handle:
        nodes = json.load(handle)["nodes"]
    _report, suppressions_path, _log = conflict_paths(map_path)
    strong, weak, _suppressed, _counts = conflict_check.find(
        nodes, conflict_check.load_suppressions(suppressions_path), watched_names)
    return strong + weak


def value_spellings(number, unit):
    """How the value may be written in the document. The first one is what gets written back."""
    def both(value, suffix):
        plain = ("%g" % value)
        return [plain + " " + suffix, plain + suffix]

    if unit == "m":
        texts = both(number, "m")
        if abs(number * 1000 - round(number * 1000)) < 1e-6:
            texts += both(round(number * 1000), "mm")
        if abs(number * 100 - round(number * 100)) < 1e-6:
            texts += both(round(number * 100), "cm")
        return texts
    if unit == "s":
        return both(number, "s")
    return both(number, unit)


def line_has_value(path, line_number, spellings):
    lines = open(path, encoding="utf-8").read().splitlines()
    if line_number < 1 or line_number > len(lines):
        return False
    return any(text in lines[line_number - 1] for text in spellings)


def find_value_lines(path, spellings, name):
    """Where the value is actually written.

    The map records the line a section starts on, so the value is often on a later line.
    Lines that also carry the words of the value name come first.
    """
    lines = open(path, encoding="utf-8").read().splitlines()
    words = [word for word in re.split(r"[\s/]+", name) if len(word) > 1]
    with_name, without_name = [], []
    for number, line in enumerate(lines, start=1):
        if not any(text in line for text in spellings):
            continue
        lowered = line.lower()
        if words and all(word.lower() in lowered for word in words):
            with_name.append((number, line.strip()))
        else:
            without_name.append((number, line.strip()))
    return with_name or without_name


def rewrite_value(path, line_number, spellings, new_text):
    """Replace the value on that line only. A changed line is left alone."""
    lines = open(path, encoding="utf-8").read().splitlines(keepends=True)
    if line_number < 1 or line_number > len(lines):
        return False, "the line number is past the end of the file", None
    line = lines[line_number - 1]
    for old_text in spellings:
        if old_text in line:
            lines[line_number - 1] = line.replace(old_text, new_text, 1)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("".join(lines))
            return True, None, old_text
    return False, "the old value is no longer on that line (the document changed)", None


def show_conflicts(map_path, watched_names=None):
    """List the conflicts with a number, ten at a time."""
    conflicts = current_conflicts(map_path, watched_names)
    if not conflicts:
        print("No conflicts.")
        return 0
    print("%d conflict(s) - showing the first %d."
          % (len(conflicts), min(CONFLICT_PAGE, len(conflicts))))
    print("")
    for index, (name, by_value, _signature) in enumerate(conflicts[:CONFLICT_PAGE], start=1):
        values = sorted(by_value)
        print("%d. %s" % (index, name))
        for choice, (number, unit) in enumerate(values, start=1):
            sources = by_value[(number, unit)]
            shown = ", ".join(sources[:2])
            if len(sources) > 2:
                shown += " and %d more" % (len(sources) - 2)
            print("     %d) %g %s  <-  %s" % (choice, number, unit, shown))
        print("     %d) not a conflict     %d) leave it" % (len(values) + 1, len(values) + 2))
        print("")
    if len(conflicts) > CONFLICT_PAGE:
        print("The remaining %d come back once these ten are settled."
              % (len(conflicts) - CONFLICT_PAGE))
    print("[Then pass the picks: python ask.py --settle \"1:2 2:3\" - conflict number : choice]")
    return 0


def save_suppression(path, name, signature_value):
    suppressions = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                suppressions = json.load(handle)
        except ValueError:
            suppressions = {}
    suppressions[name] = signature_value
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(suppressions, handle, ensure_ascii=False, indent=2, sort_keys=True)


def settle_conflicts(answer, map_path, watched_names=None, dry_run=False):
    """Apply the picks: fix the document, mark it not a conflict, or leave it."""
    import datetime

    conflicts = current_conflicts(map_path, watched_names)[:CONFLICT_PAGE]
    if not conflicts:
        print("No conflicts. Nothing to settle.")
        return 0
    _report, suppressions_path, log_path = conflict_paths(map_path)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    fixed = suppressed = left = skipped = 0
    for pair in answer.replace(",", " ").split():
        if ":" not in pair:
            print("Not a pick: %s (write conflict:choice)" % pair)
            continue
        left_side, right_side = pair.split(":", 1)
        if not left_side.strip().isdigit() or not right_side.strip().isdigit():
            print("Not numbers: %s" % pair)
            continue
        index, choice = int(left_side), int(right_side)
        if not 1 <= index <= len(conflicts):
            print("No conflict with that number: %d" % index)
            continue
        name, by_value, signature_value = conflicts[index - 1]
        values = sorted(by_value)
        if choice == len(values) + 2:
            left += 1
            continue
        if choice == len(values) + 1:
            if not dry_run:
                save_suppression(suppressions_path, name, signature_value)
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write("%s | not a conflict | %s | values %s\n"
                                 % (stamp, name, signature_value))
            suppressed += 1
            continue
        if not 1 <= choice <= len(values):
            print("Conflict %d has no choice %d" % (index, choice))
            continue
        keep = values[choice - 1]
        new_text = value_spellings(*keep)[0]
        for value, sources in by_value.items():
            if value == keep:
                continue
            for source in sources:
                source_file, _, line_text = source.rpartition(":")
                if not os.path.exists(source_file) or not line_text.isdigit():
                    print("   skipped - no such file: %s" % source)
                    skipped += 1
                    continue
                spellings = value_spellings(*value)
                targets = [(int(line_text), None)]
                if not line_has_value(source_file, int(line_text), spellings):
                    targets = find_value_lines(source_file, spellings, name)
                    if not targets:
                        print("   skipped - the value is not in that file: %s" % source)
                        skipped += 1
                        continue
                for number, shown in targets:
                    if dry_run:
                        print("   (dry run) %s:%d  %g %s -> %s"
                              % (source_file, number, value[0], value[1], new_text))
                        if shown:
                            print("        %s" % shown[:150])
                        fixed += 1
                        continue
                    done, reason, old_text = rewrite_value(source_file, number, spellings, new_text)
                    if done:
                        with open(log_path, "a", encoding="utf-8") as handle:
                            handle.write("%s | fixed | %s | %s:%d | %s -> %s\n"
                                         % (stamp, name, source_file, number, old_text, new_text))
                        fixed += 1
                    else:
                        print("   skipped - %s: %s:%d" % (reason, source_file, number))
                        skipped += 1
    print("fixed %d · marked not a conflict %d · left %d · skipped %d"
          % (fixed, suppressed, left, skipped))
    if (fixed or suppressed) and not dry_run:
        print("[They drop off the list at the next refresh. The log is beside the map]")
    return 0


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


ANSWER_NODE_PATTERN = re.compile(
    r"^NODE (?P<label>.*?) \[src=(?P<source>.*?) loc=(?P<line>\S+)(?: community=\S*)?\]\s*$")
TRAVERSAL_START_PATTERN = re.compile(r"Start: \[(?P<seeds>.*?)\] \|")
QUOTED_SEED_PATTERN = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")


def matched_labels(raw_answer):
    """The labels the query tool actually matched, in the order it listed them.

    The tool walks outwards from those, so everything else in the answer is a neighbour
    that came along for the ride. Keeping the order lets the statement that answers the
    question stay at the top instead of landing somewhere in the middle.
    """
    header = TRAVERSAL_START_PATTERN.search(raw_answer)
    if not header:
        return []
    return [(single or double).replace("\\'", "'").replace('\\"', '"')
            for single, double in QUOTED_SEED_PATTERN.findall(header.group("seeds"))]


def condense_answer(raw_answer):
    """Keep the statements out of a query answer and drop the traversal noise.

    The query tool prints its traversal header, every node it walked through and every
    edge between them. The statements carrying the values are in there, buried. Keep
    those with their file and line, name the documents they came from once at the end,
    and drop the rest. A node with no location is a name someone linked to and never
    wrote, so it has no value to return.
    """
    seeds = matched_labels(raw_answer)
    statements, documents = [], []
    for line in raw_answer.splitlines():
        found = ANSWER_NODE_PATTERN.match(line)
        if not found:
            continue
        label, source, line_number = (found.group("label").strip(),
                                      found.group("source").strip(),
                                      found.group("line"))
        if not source or line_number == "None":
            continue
        if line_number == "1":                       # the node standing for the whole document
            if label not in documents:
                documents.append(label)
            continue
        rank = seeds.index(label) if label in seeds else len(seeds)
        statements.append((rank, f"NODE {label}\n     [src={source} loc={line_number}]"))

    if not statements:
        return raw_answer                            # nothing recognised - show what the tool said
    ordered = [text for _, text in sorted(statements, key=lambda pair: pair[0])]
    condensed = "\n".join(ordered)
    if documents:
        # Naming every document turns the tail into a wall of text of its own, so name a few.
        shown = ", ".join(documents[:4])
        rest = f" and {len(documents) - 4} more" if len(documents) > 4 else ""
        condensed += f"\n\n[also touched: {shown}{rest}]"
    return condensed


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
    sys.stdout.write(condense_answer(answer) + "\n" if mode == "query" else answer)
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

    if argv[0] == "--chain":
        if len(argv) != 2:
            print("--chain needs one decision name.")
            return 1
        return show_chain(argv[1], config["map_path"])
    if argv[0] == "--conflicts":
        return show_conflicts(config["map_path"], config.get("watched_names"))
    if argv[0] == "--settle":
        picks = [item for item in argv[1:] if item != "--dry-run"]
        if not picks:
            print("--settle needs the picks, such as \"1:2 2:3\".")
            return 1
        return settle_conflicts(" ".join(picks), config["map_path"],
                                config.get("watched_names"), dry_run="--dry-run" in argv)
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
