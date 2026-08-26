"""Entry point for asking the knowledge map.

This does not rebuild the map. Refreshes only run at session start, when a
delegated task ends, and right after compaction. It does, however,
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

**Ask in the language the document you want is written in.** Matching is on the
words as they are written, so a question in another language reaches only the
notes written in that language. It says nothing about it - it returns whatever it
can find, and most of that is a near-miss.

**Ask narrowly.** A question after a single value ("tray piece length median")
comes back with what the documents say about that value and nothing else, which
costs less than opening the files it drew from. A question that sweeps a whole
topic ("clustering objective function overall") fills the `answer_budget` and
says how much it had to leave out - which tells you less than reading one note
whole. To sweep a topic, hand it to a subagent and take only the conclusion.
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


def build_graphify_command(mode, arguments, map_path, budget=0):
    """Build the command that calls the query tool.

    The query tool's own budget is counted in tokens and it cuts by how many neighbours a node
    has, not by what was asked. Tying it to `answer_budget` meant that lowering the answer also
    narrowed what the tool was allowed to return, so statements were cut upstream before the
    ranking here ever saw them - and the count of what was left out came out short. It is
    pinned wide instead, and `answer_budget` does its own job further down, in characters.
    """
    command = ["graphify", mode, *arguments, "--graph", map_path]
    if mode == "query":
        # Wide by default, but never narrower than what the caller means to print: raising
        # answer_budget above this used to buy nothing, because the walk stopped first.
        command += ["--budget", str(max(WALK_TOKEN_BUDGET, budget or 0))]
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


# How much the query tool may walk before it cuts, counted in tokens (it allows about three
# characters per token). Wide enough that the ranking below decides what survives, rather than
# a cut made upstream by how many neighbours a node happened to have.
WALK_TOKEN_BUDGET = 20000

# Words too common to tell one statement from another, so they are not counted as a match.
COMMON_WORDS = frozenset("""a an and are as at be by do does for from has have how in into is it
its many much not of on or that the their there they this to was were what when where which who
why will with""".split())
WORD_PATTERN = re.compile(r"[\w가-힣]+", re.UNICODE)
# Korean particles ride on the end of a word. Matching is done on the written form, so a question
# that says "케이블은" has to be trimmed back to "케이블" to reach the note that says it.
# Only these four may be taken off a two-syllable word to leave one syllable behind. The other
# particle letters also end ordinary nouns - 결과, 추가, 경로, 정도 - and taking one off those
# leaves a syllable that matches half the vocabulary.
BARE_SYLLABLE_PARTICLES = frozenset("은는을를")
# Words that end in one of those letters without the letter being a particle at all. Measured
# against the vault, taking 작은 down to 작 matched 130 statements about 작업 and 시작 that have
# nothing to do with anything being small; 있는 matched 52 the same way.
# Only two-syllable words ending in one of those four letters ever reach this, so a word that
# ends any other way would sit here doing nothing.
MODIFIER_FORMS = frozenset({
    # Modifiers: the last letter is part of the verb, not a particle.
    "같은", "있는", "없는", "작은", "많은", "적은", "높은", "낮은", "좋은", "쓰는", "하는",
    "되는", "가는", "오는", "보는", "넣는", "여는", "닫는", "맞는", "받는", "주는", "아는",
    # Nouns whose last letter only looks like one: 마을 is not 마 + 을.
    "마을", "노을", "가을", "겨울", "서울", "이름", "다음", "처음", "사람",
})

KOREAN_PARTICLES = ("에서의", "으로는", "에서는", "에게는", "이라는", "라는", "으로", "에서",
                    "에게", "께서", "부터", "까지", "보다", "처럼", "만큼", "이나", "나마",
                    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "로", "만")


def _is_korean(word):
    """Is this written in Hangul?"""
    return any("가" <= letter <= "힣" for letter in word)


def strip_korean_particle(word):
    """Take a Korean particle off the end of a word. Anything else is returned as it came."""
    if not _is_korean(word):
        return word
    for particle in KOREAN_PARTICLES:
        # Two syllables have to be left. The letters a particle is written with are also the
        # last letter of plenty of ordinary words - 결과, 경로, 추가 - and taking one off those
        # leaves a single syllable that matches half the vocabulary. Measured against this
        # vault: trimming down to one syllable mangles 1,512 of its 4,085 Korean words.
        if word.endswith(particle) and len(word) - len(particle) >= 2:
            return word[:-len(particle)]
    return word
LABEL_CAP = 2000
# Below this many statements an answer is too thin to judge, so the walk's own neighbours are
# kept even when they carry none of the asked words. Above it, a statement that carries none of
# them is a neighbour of a neighbour and only costs room.
MIN_STATEMENTS = 8
# How many statements the direct lookup may add. It is a second opinion on the walk, not a
# replacement for it, so it stays small enough that the walk still shapes the answer.
DIRECT_LOOKUP_LIMIT = 12
# How far from a statement that matched a neighbour may sit and still be kept. A value
# often carries none of the asked words itself - the heading says "Bending radius" and
# the line under it says "12 x D" - so the lines around a match are worth keeping. The
# rest of the document is not: it is in the answer only because the walk passed through it.
NEARBY_LINES = 20


def fold_long_label(label, source, line_number):
    """Fold a label longer than a note is worth reading into its opening plus a pointer.

    One physical line of markdown becomes one statement, so a paragraph written without
    line breaks arrives here as a single label of many thousand characters. Printing it
    whole costs more than the document it came from. The opening carries the subject and
    the pointer says where the rest is.
    """
    if len(label) <= LABEL_CAP:
        return label
    return (label[:LABEL_CAP].rstrip()
            + f" [+{len(label) - LABEL_CAP} more characters - open {source}:{line_number}]")


def asked_words(question):
    """The words worth matching on, each as the set of forms it may be written in.

    A single letter is dropped unless it was written as a capital: `a` in "a value" carries
    nothing, but the S, T, V and E of "role letters S T V E" are the whole question. A Korean
    word arrives with its particle attached, so the trimmed form is kept beside the written
    one - otherwise "케이블은" never reaches the note that says "케이블".

    Both forms of one word live in the same set, and a set counts once however many of its
    forms a statement happens to carry. Keeping them as separate words scored one statement
    twice, which put a statement holding no value above one that did.
    """
    by_stem = {}
    for word in WORD_PATTERN.findall(question):
        if len(word) == 1:
            # A single Latin letter is only worth matching when it was written as a capital:
            # `a` in "a value" says nothing, the S of "role S" is the question. A single Korean
            # syllable is a whole word - 폭, 값, 층 - and Korean has no capitals to go by.
            if word.isupper() or _is_korean(word):
                by_stem.setdefault(word.lower(), set()).add(word.lower())
            continue
        lowered = word.lower()
        if lowered in COMMON_WORDS:
            continue
        # The stem is what makes two forms the same word, so it is the key. Asking
        # "트레이는 ... 트레이의" used to build two sets and count 트레이 twice, which put a
        # statement holding no value above one that did - the very thing the sets were for.
        stem = strip_korean_particle(lowered)
        forms = by_stem.setdefault(stem, {stem})
        forms.add(lowered)
        # 폭은 has no two-syllable stem to fall back on, so the bare syllable is added here
        # instead. It cannot inflate the score: a set counts once however many forms match.
        if (_is_korean(lowered) and len(lowered) == 2
                and lowered[1] in BARE_SYLLABLE_PARTICLES
                and lowered not in MODIFIER_FORMS):
            # The bare syllable becomes the key as well. Keyed on the written form instead,
            # 폭은 and 폭을 made two sets that both carried 폭, and the word counted twice.
            forms = by_stem.setdefault(lowered[0], set()) | forms
            by_stem.pop(stem, None)
            by_stem[lowered[0]] = forms
            forms.add(lowered[0])
    return {frozenset(forms) for forms in by_stem.values()}


def matching_word_count(label, words):
    """How many of the asked words this statement carries. Ties are broken by walk order.

    A word of two letters or more counts anywhere in the text, so "cable" reaches "cables".
    A single letter has to stand as a word of its own: `s` inside "statements" says nothing,
    and counting it would make every English sentence a match.
    """
    if not words:
        return 0
    lowered = label.lower()
    tokens = None
    carried = 0
    for forms in words:
        for form in forms:
            # A single Latin letter has to stand as a word of its own: `s` inside "statements"
            # says nothing, and counting it would make every English sentence a match. A single
            # Korean syllable compounds into longer words (폭 inside 트레이폭), so it is matched
            # the way any other word is.
            if len(form) == 1 and not _is_korean(form):
                if tokens is None:
                    tokens = set(WORD_PATTERN.findall(lowered))
                hit = form in tokens
            else:
                hit = form in lowered
            if hit:
                carried += 1                         # one word, counted once, however written
                break
    return carried


def document_labels(map_path):
    """The labels of the nodes that stand for a whole document, read from the map.

    The query tool prints a label, a file and a line, but not what kind of node it was, so
    whether a line is a document used to be guessed from its line number being 1. A document
    written on one line - which is how a generated HTML report usually arrives - has every one
    of its statements at line 1, and the guess threw all of them away. The map knows.
    """
    if not os.path.exists(map_path):
        return None                      # nothing to read: the caller falls back to line numbers
    try:
        with open(map_path, encoding="utf-8") as handle:
            nodes = json.load(handle)["nodes"]
    except (OSError, ValueError, KeyError):
        return None
    labels = {node.get("label") for node in nodes if node.get("kind") == "document"}
    return labels or None                # a map with no document nodes says nothing either


def statements_carrying_the_words(map_path, words, limit=DIRECT_LOOKUP_LIMIT):
    """Statements whose own text carries the asked words, read straight out of the map.

    The walk starts from whatever the query tool picked as a seed and spreads outward, so a
    statement can hold the answer and never be visited. Reading the map for the words costs
    one pass over a file that is already on this machine, and it does not care where the walk
    happened to start. Statements that carry more of the words come first; between two that
    carry the same number, the shorter one is the denser answer.
    """
    if not words or not os.path.exists(map_path):
        return []
    try:
        with open(map_path, encoding="utf-8") as handle:
            nodes = json.load(handle)["nodes"]
    except (OSError, ValueError, KeyError):
        return []                                    # a half-written map must not break the answer
    found = []
    for node in nodes:
        if node.get("kind") != "statement" or not node.get("source_location"):
            continue
        label = node.get("label") or ""
        carried = matching_word_count(label, words)
        if carried:
            found.append((-carried, len(label), label,
                          node.get("source_file") or "", node["source_location"]))
    found.sort()
    return found[:limit]


def _as_line(value):
    """A line number as an int. Anything that cannot be placed sits at 0, far from everything."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def near_a_match(rows):
    """Build the test for whether a statement sits close to one that carried the asked words."""
    anchors = {}
    for row in rows:
        if row[1] < 0:
            anchors.setdefault(row[3], []).append(row[4])

    def is_near(row):
        return any(abs(row[4] - anchor) <= NEARBY_LINES for anchor in anchors.get(row[3], ()))

    return is_near


def dropped_notice(count, budget):
    """The closing line that says the answer was narrowed. Built once so its length can be measured."""
    return (f"\n[{count} further statement(s) left out to stay inside the {budget}-character "
            f"answer. The question reached more of the documents than one answer can carry - "
            f"narrow the words, or hand the topic to a subagent and take only the conclusion]")


def condense_answer(raw_answer, budget=None, question="", direct=(), documents_named=None):
    """Keep the statements out of a query answer and drop the traversal noise.

    The query tool prints its traversal header, every node it walked through and every
    edge between them. The statements carrying the values are in there, buried. Keep
    those with their file and line, name the documents they came from once at the end,
    and drop the rest. A node with no location is a name someone linked to and never
    wrote, so it has no value to return.

    `budget` caps what this returns, in **characters**. Two short notices can follow it on the
    way out - that the question was broad, that the map lags the documents - and those are how
    the caller learns the answer was narrowed, so they are printed outside the cap. Asking here is only worth it when it
    costs less than opening the document, and a document is measured in characters, so the
    answer has to be too. The query tool's own budget is counted in tokens and cuts at about
    three times this number, which is why the cap is applied again here. Statements are
    dropped whole from the back, never cut in the middle, because a value usually sits at the
    end of its line. What was dropped is counted in a closing line, so a narrowed answer is
    never mistaken for a complete one.

    `question` puts the statements carrying the asked words first. The walk order alone puts
    headings before the line under them, so the value a question is after can sit far down a
    long answer - and once there is a cap, far down means dropped.

    `direct` carries statements found by reading the map for the asked words. They are merged
    with what the walk returned and ranked the same way, so a statement the walk never reached
    can still answer the question. A statement found by both routes is kept once.
    """
    seeds = matched_labels(raw_answer)
    words = asked_words(question)
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
        # A node standing for a whole document. The map says which labels those are; without
        # it, fall back to the line number, which is where a document node sits.
        is_document = (label in documents_named if documents_named is not None
                       else line_number == "1")
        if is_document:
            if label not in documents:
                documents.append(label)
            continue
        rank = seeds.index(label) if label in seeds else len(seeds)
        carried = matching_word_count(label, words)
        label = fold_long_label(label, source, line_number)
        statements.append((rank, -carried, len(statements), source,
                           _as_line(line_number),
                           f"NODE {label}\n     [src={source} loc={line_number}]"))

    seen = {text.rsplit("[src=", 1)[-1] for *_head, text in statements}
    for _negative, _length, label, direct_source, direct_line in direct:
        marker = f"{direct_source} loc={direct_line}]"
        if marker in seen:
            continue
        seen.add(marker)
        carried = matching_word_count(label, words)
        label = fold_long_label(label, direct_source, direct_line)
        statements.append((len(seeds), -carried, len(statements), direct_source,
                           _as_line(direct_line),
                           f"NODE {label}\n     [src={direct_source} loc={direct_line}]"))

    if not statements:
        # Nothing was recognised, so show what the tool said - but still inside the cap. The
        # shape of that output is not ours to rely on; if it ever changes, this is the path
        # every answer takes, and an uncapped answer here would undo the cap everywhere.
        if budget and len(raw_answer) > budget:
            notice = (f"\n[cut at the {budget}-character answer. The answer was not in the "
                      f"expected shape, so it is shown as it came]")
            room = budget - len(notice)
            # A budget too small to hold even the notice still has to hold the answer.
            return raw_answer[:room].rstrip() + notice if room > 0 else raw_answer[:budget]
        return raw_answer
    tail = ""
    if documents:
        # Naming every document turns the tail into a wall of text of its own, so name a few.
        shown = ", ".join(documents[:4])
        rest = f" and {len(documents) - 4} more" if len(documents) > 4 else ""
        tail = f"\n\n[also touched: {shown}{rest}]"

    ranked = sorted(statements, key=lambda row: row[:3])
    if words:
        # The walk returns a neighbourhood, not an answer. A statement that carries none of the
        # asked words is only there because it sits next to one that does - it fills the cap and
        # makes every answer the same size whatever was asked.
        #
        # Not all of them, though. A value often carries none of the words itself: the heading
        # says "Bending radius" and the line under it says "12 x D". Those sit in the same
        # document as something that did match, so same-document neighbours are kept and only
        # the ones from elsewhere are trimmed back.
        is_near = near_a_match(ranked)
        near = [row for row in ranked if row[1] < 0 or is_near(row)]
        if len(near) < MIN_STATEMENTS:
            # Top it up from what the walk returned rather than taking the first few outright:
            # the walk's own order puts seed labels ahead of everything, so taking the head can
            # hand back an answer with none of the statements that carried the asked words.
            chosen = list(near)
            for row in ranked:
                if len(chosen) >= MIN_STATEMENTS:
                    break
                if row not in near:
                    chosen.append(row)
            near = sorted(chosen, key=lambda row: row[:3])
        ranked = near
    ordered = [row[-1] for row in ranked]
    kept, dropped = ordered, 0
    if budget:
        # Measure the closing lines instead of guessing at them. The document tail has no length
        # limit of its own, so a guess can be out by the length of four document names.
        notice = dropped_notice(len(ordered), budget)
        room = max(0, budget - len(tail) - len(notice))
        kept, used = [], 0
        for position, text in enumerate(ordered):
            if kept and used + len(text) + 1 > room:
                dropped = len(ordered) - position
                break
            kept.append(text)
            used += len(text) + 1
    # Held as pieces to the last moment. Joining first and then slicing characters off the
    # end took the closing notice away instead of the tail, and left a half-written
    # "[also touched:" behind - the document list surviving at the cost of the statements,
    # which is what dropping the tail was for.
    body = "\n".join(kept)
    notice = dropped_notice(dropped, budget) if dropped else ""
    if not budget or len(body) + len(tail) + len(notice) <= budget:
        return body + tail + notice

    # The tail goes first. It names documents, and a name costs more room than it earns
    # once the statements themselves are at risk - but say that it went, because a document
    # with no surviving statement is named nowhere else.
    dropped_tail = "\n[the list of documents touched was left out for room]" if tail else ""
    if len(body) + len(notice) + len(dropped_tail) <= budget:
        return body + dropped_tail + notice

    # Last resort: cut into the text itself, and say so. A value usually sits at the end of
    # a line, so this is the one shape of answer that can lose one without a word.
    warning = "\n[cut mid-statement at the character budget - raise answer_budget]"
    # The count of what was left out still goes in if there is room for it: the
    # reader has to know the answer was narrowed, whichever way it had to narrow.
    closing = warning + notice if len(warning) + len(notice) < budget else warning
    room = budget - len(closing)
    return body[:room].rstrip() + closing if room > 0 else body[:budget]


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
    question = " ".join(arguments)
    direct = (statements_carrying_the_words(map_path, asked_words(question))
              if mode == "query" else [])
    named = document_labels(map_path) if mode == "query" else None
    sys.stdout.write(condense_answer(answer, budget, question, direct, named) + "\n"
                     if mode == "query" else answer)
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
