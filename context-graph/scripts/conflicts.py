"""Finds values that two documents state differently, and writes them beside the map.

The report is a sidecar, never part of an answer. A rule-based check misses and misfires,
and a warning that is sometimes wrong drags down the trust in every answer next to it.

Three passes collect values, from the most trustworthy down:

  1. watched names - names a person put in the config, read with the first number that
     follows them. A person chose the name, so this pass is the one to read first.
  2. `name: value` lines - the name is written next to the value, so it needs no guessing.
  3. context - the words in front of a number are taken as its name. This one misfires,
     so it only compares values in the same unit and drops names that end in a preposition
     or a common verb. It is reported separately.

Units are normalised before comparing, so 3.5 m and 3500 mm are the same value. A name
marked "not a conflict" is kept in a suppressions file together with the set of values it
had at the time, so the mark releases itself the moment any of those values changes.
"""
import json
import os
import re

DEFAULT_WATCHED_NAMES = ["bend radius", "tray width", "tray thickness", "tier gap",
                         "lane gap", "clearance", "edge clearance"]
WATCH_WINDOW = 18        # how far after a watched name the number may start
# Read a little past the window so a unit is never cut in half. An 18-character cut through
# "tray width is fixed at 600 mm" lands between the two m's and reads the value as 600 m.
UNIT_TAIL = 4
# A number this far after the name is not its value: "tray width + 0.30 m" adds to the width.
WATCH_BREAKERS = ("+", "-", "±", "x ", "×", "plus", "over", "than", "gap")

NAMED_VALUE = re.compile(
    r"(?P<key>[A-Za-z가-힣][A-Za-z0-9 _\-/()가-힣]{1,38}?)\s*[:=]\s*"
    r"(?P<number>-?\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|km|m|s|ms|%|MB|KB|GB)(?![A-Za-z0-9])")
NUMBER_IN_TEXT = re.compile(
    r"(?<![\d.\-–])(?P<number>-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>mm|cm|km|m|s|ms|%|MB|KB|GB)(?![A-Za-z0-9])")

UNIT_SCALE = {"mm": ("m", 0.001), "cm": ("m", 0.01), "m": ("m", 1.0), "km": ("m", 1000.0),
              "ms": ("s", 0.001), "s": ("s", 1.0)}

# Words too common to be a value name, and tails that mean the phrase is not a name.
GENERIC_NAMES = {"observations", "relations", "context", "decision", "consequences", "note",
                 "notes", "summary", "status"}
STOP_TAILS = {"to", "is", "are", "was", "were", "up", "at", "of", "in", "on", "by", "for",
              "from", "than", "about", "roughly", "under", "over", "with", "and", "or",
              "the", "a", "an", "reach", "captures", "design", "measured", "found", "gives"}


def normalise_name(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def normalise_value(number, unit):
    """The value in its base unit, rounded to three decimals. Thousands commas are dropped."""
    base_unit, scale = UNIT_SCALE.get(unit, (unit, 1.0))
    return round(float(str(number).replace(",", "")) * scale, 3), base_unit


def node_text(node):
    """The node's text. This map keeps it in `label`; other maps may use `text`."""
    return node.get("text") or node.get("label") or ""


def source_of(node):
    return "%s:%s" % (node.get("source_file") or "?", node.get("source_location") or "?")


def add(found, name, value, source):
    found.setdefault(name, {}).setdefault(value, [])
    if source not in found[name][value]:
        found[name][value].append(source)


def collect_watched(nodes, watched_names):
    """Values written right after a name the config watches."""
    found = {}
    for node in nodes:
        text = node_text(node)
        lowered = text.lower()
        for name in watched_names:
            start = 0
            while True:
                at = lowered.find(name.lower(), start)
                if at < 0:
                    break
                start = at + len(name)
                window = text[start:start + WATCH_WINDOW + UNIT_TAIL]
                match = NUMBER_IN_TEXT.search(window)
                if not match or match.start() >= WATCH_WINDOW:
                    continue
                if any(breaker in window[:match.start()] for breaker in WATCH_BREAKERS):
                    continue
                add(found, normalise_name(name),
                    normalise_value(match.group("number"), match.group("unit")), source_of(node))
    return found


def collect_named(nodes):
    """Values written as `name: value` or `name = value`."""
    found = {}
    for node in nodes:
        for match in NAMED_VALUE.finditer(node_text(node)):
            name = normalise_name(match.group("key"))
            if name in GENERIC_NAMES or len(name) < 2:
                continue
            add(found, name, normalise_value(match.group("number"), match.group("unit")),
                source_of(node))
    return found


def name_from_context(prefix):
    """The words in front of a number, taken as its name. Empty when they read as a phrase."""
    words = [word for word in re.findall(r"[A-Za-z가-힣][A-Za-z0-9_\-가-힣]*",
                                         prefix)[-4:] if len(word) > 1]
    if not words or words[-1].lower() in STOP_TAILS:
        return ""
    name = " ".join(words[-3:]).lower()
    return name if len(name) >= 4 else ""


def collect_context(nodes):
    """Values written inside a sentence, named by the words in front of them."""
    found = {}
    for node in nodes:
        text = node_text(node)
        for match in NUMBER_IN_TEXT.finditer(text):
            name = name_from_context(text[max(0, match.start() - 60):match.start()])
            if not name or name in GENERIC_NAMES:
                continue
            add(found, name, normalise_value(match.group("number"), match.group("unit")),
                source_of(node))
    return found


def signature(values):
    """The set of values as one string. A suppression carries it, so it releases on any change."""
    return "|".join("%s%s" % (number, unit) for number, unit in sorted(values))


def load_suppressions(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def split(values, suppressions, same_unit_only=False):
    """Names whose value splits in two, across two documents, and is not suppressed."""
    conflicts, suppressed = [], 0
    for name, by_value in sorted(values.items()):
        if len(by_value) < 2:
            continue
        if same_unit_only and len({unit for _number, unit in by_value}) > 1:
            continue                     # different units are not the same value at all
        files = {source.rsplit(":", 1)[0] for sources in by_value.values() for source in sources}
        if len(files) < 2:               # one document disagreeing with itself is not counted
            continue
        current = signature(by_value.keys())
        if suppressions.get(name) == current:
            suppressed += 1
            continue
        conflicts.append((name, by_value, current))
    return conflicts, suppressed


def find(nodes, suppressions, watched_names=None):
    """(strong conflicts, context conflicts, suppressed count, counts)."""
    watched_names = DEFAULT_WATCHED_NAMES if watched_names is None else watched_names
    named = collect_named(nodes)
    spellings = {name.lower() for name in watched_names}
    named = {name: values for name, values in named.items() if name not in spellings}
    named.update(collect_watched(nodes, watched_names))
    # A name the first two passes already carry is not counted again from context.
    context = {name: values for name, values in collect_context(nodes).items()
               if name not in named}

    strong, suppressed_strong = split(named, suppressions, same_unit_only=True)
    weak, suppressed_weak = split(context, suppressions, same_unit_only=True)
    counts = {"names": len(named), "context_names": len(context),
              "split": sum(1 for values in named.values() if len(values) > 1)}
    return strong, weak, suppressed_strong + suppressed_weak, counts


def render(strong, weak, suppressed, counts):
    """The sidecar report, as text."""
    def block(title, items, note):
        lines = ["%s - %d" % (title, len(items)), note, ""]
        for index, (name, by_value, current) in enumerate(items, start=1):
            lines.append("%d. %s   (values %s)" % (index, name, current))
            for (number, unit), sources in sorted(by_value.items()):
                shown = ", ".join(sources[:3])
                if len(sources) > 3:
                    shown += " and %d more" % (len(sources) - 3)
                lines.append("     %g %s  <-  %s" % (number, unit, shown))
            lines.append("")
        if not items:
            lines += ["   none.", ""]
        return lines

    lines = ["# Values two documents state differently",
             "#",
             "# This file is a notice. It is never mixed into an answer.",
             "# To settle one, pick the value to keep and fix the document that has the other.",
             "# If it is not a conflict, record the name and its value set in the suppressions",
             "# file; the mark releases itself as soon as any of those values changes.",
             "",
             "names %d (split %d) - context names %d - suppressed %d"
             % (counts["names"], counts["split"], counts["context_names"], suppressed),
             ""]
    lines += block("[strong] the name is written next to the value", strong,
                   "The name and the value share a line, so this pass rarely misfires.")
    lines += block("[context] the name is taken from the words in front of the value", weak,
                   "This pass misfires. Only same-unit values are compared and phrase-like "
                   "names are dropped, but a person still has to read them.")
    return "\n".join(lines)


def run(nodes, report_path, suppressions_path, watched_names=None):
    """Find conflicts and write the sidecar report. Returns (strong, context, suppressed, counts)."""
    strong, weak, suppressed, counts = find(nodes, load_suppressions(suppressions_path),
                                            watched_names)
    if report_path:
        folder = os.path.dirname(report_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write(render(strong, weak, suppressed, counts))
    return strong, weak, suppressed, counts
