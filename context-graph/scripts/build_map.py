"""Joins the pieces into a single map file. The parsers know the formats; this only joins.

The three refresh points (session start, delegated task end, after compaction) call this
file from the command line. Before compaction the hook only prints a reminder - there is
nothing to rebuild from until the session has been written into the documents.
"""
import argparse
import collections
import json
import os
import sys
import time

from parse_html import parse_html
from parse_markdown import parse_markdown

# The score line contains an em dash. The default console encoding on a Korean
# Windows box dies on that single character.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

MARKDOWN_SUFFIXES = (".md", ".markdown")
HTML_SUFFIXES = (".html", ".htm")


def _document_files(source_dirs):
    """Return the files to scan, sorted. Sorting is what makes the result repeatable."""
    found = []
    for source_dir in sorted(source_dirs):
        for folder, sub_folders, file_names in os.walk(source_dir):
            sub_folders.sort()
            for file_name in sorted(file_names):
                if file_name.endswith(MARKDOWN_SUFFIXES + HTML_SUFFIXES):
                    found.append(os.path.join(folder, file_name))
    return found


def _title_key(text):
    """Key used to match names. Absorbs punctuation differences (`/`, `:` vs `-`) in titles."""
    lowered = text.strip().lower()
    for symbol in "/:\\":
        lowered = lowered.replace(symbol, "-")
    return " ".join(lowered.split())


def folder_notes(source_dirs, document_count):
    """Say why the map came out empty, when it did.

    A folder named in the config that is not there and a folder with nothing in it both
    end at `nodes 0`, so a typo in the path looks exactly like an empty set of documents.
    Name the cause instead of leaving someone to guess.
    """
    notes = [f"[the document folder in the config is not there - {source_dir}]"
             for source_dir in sorted(source_dirs) if not os.path.isdir(source_dir)]
    if not notes and document_count == 0:
        where = ", ".join(sorted(source_dirs))
        notes.append(f"[no .md, .markdown, .html or .htm documents under {where}]")
    return notes


def _drop_mentions_that_repeat_a_named_relation(links):
    """Remove the plain mention between two documents that a named relation already covers.

    A decision usually names the decision it replaces twice: once in the relations line
    (`- supersedes [[...]]`) and again in the prose above it. Both become a link, and a path
    running between the two documents can then come back labelled `mentions`, hiding the
    lineage the relations line spelled out. The named one wins.
    """
    named_pairs = {(link["source"], link["target"])
                   for link in links if link["relation"] != "mentions"}
    return [link for link in links
            if link["relation"] != "mentions" or (link["source"], link["target"]) not in named_pairs]


def _fingerprint(source_dirs):
    """Summarise the documents: how many there are and the newest change time.

    The count is part of it because a deleted document leaves the newest time untouched.
    """
    count, newest = 0, 0.0
    for path in _document_files(source_dirs):
        count += 1
        newest = max(newest, os.path.getmtime(path))
    return {"documents": count, "newest": round(newest, 3)}


def _fingerprint_path(map_path):
    """Where the previous fingerprint is kept — beside the map, hidden."""
    folder = os.path.dirname(map_path) or "."
    return os.path.join(folder, "." + os.path.basename(map_path) + ".fingerprint")


def unchanged_since_last_build(source_dirs, map_path):
    """True when no document changed since the map was written, so the scan can be skipped."""
    record = _fingerprint_path(map_path)
    if not (os.path.exists(map_path) and os.path.exists(record)):
        return False
    try:
        with open(record, encoding="utf-8") as handle:
            previous = json.load(handle)
    except (OSError, ValueError):
        return False
    return previous == _fingerprint(source_dirs)


def _document_ids(paths_and_names):
    """A node id for every document, none of them shared, none of them tied to scan order.

    The name alone is not enough: two vaults both hold `_CLAUDE.md`, `index.md` and
    `overview.md`, and one node id shared by two files merges their contents into a single
    node, so an answer about one vault's rules carries the other vault's rules with it.

    Whoever is scanned first must not get to keep the plain name either. If it did, adding a
    second `index.md` would rename the first one, and every id that was ever written down
    beside the map would point at nothing. So a name that appears more than once gives *all*
    of its documents the folder they sit in, and the folder settles it for good.
    """
    seen = collections.Counter(_title_key(name) for _path, name in paths_and_names)
    ids, taken = {}, set()
    for path, name in paths_and_names:
        key = _title_key(name)
        chosen = "doc_" + key.replace(" ", "_")
        if seen[key] > 1:
            folder = _title_key(os.path.basename(os.path.dirname(path))).replace(" ", "_")
            chosen = f"{chosen}__{folder}" if folder else chosen
        candidate, suffix = chosen, 2
        while candidate in taken:                    # same name in two folders of the same name
            candidate = f"{chosen}_{suffix}"
            suffix += 1
        taken.add(candidate)
        ids[path] = candidate
    return ids


def _shared_path_length(one, other):
    """How much of a path two folders have in common. Nothing in common counts as zero.

    Two folders on different drives - which is exactly the shape this is here to sort out,
    since vaults get kept on separate drives - have no common path at all, and asking for one
    raises. So does a mix of absolute and relative. Neither is an error worth stopping a build
    for: they simply share nothing.
    """
    try:
        return len(os.path.commonpath([one, other]))
    except ValueError:
        return 0


def _nearest(candidates, from_path):
    """Which document a title points at, when more than one document carries that title.

    Two vaults both hold `index.md`, and whoever was scanned last used to win every link to
    `[[index]]` - including the links written in the other vault. A writer means the document
    beside them, so the one in the same folder is taken first, then the nearest folder above,
    and only then the first by scan order.
    """
    if len(candidates) == 1:
        return candidates[0][1]
    here = os.path.dirname(from_path)
    for folder, node_id in candidates:
        if folder == here:
            return node_id
    # Whoever shares the longest path with the writer is the nearest. Taking the first match
    # instead took the shallowest one, which is the farthest - the opposite of what was meant.
    overlapping = [(_shared_path_length(folder, here), node_id)
                   for folder, node_id in candidates if folder]
    if overlapping:
        depth, node_id = max(overlapping, key=lambda pair: pair[0])
        if depth > 0:
            return node_id
    return candidates[0][1]


def _section_index_for(statement, section_lines):
    """Which section a statement sits under, or None if it is above the first heading.

    The parsers carry the position of the heading they were under, which holds however the
    document is laid out. Falling back to line numbers keeps anything that builds a parsed
    document by hand working, but that fallback assumes the lines run in order - which a
    generated HTML report written on one line does not.
    """
    index = statement.get("section_index")
    if index is not None:
        return index if 0 <= index < len(section_lines) else None
    if "section_index" in statement:
        return None                                  # the parser said: above the first heading
    found = None
    for position, section_line in enumerate(section_lines):
        if section_line <= statement["line"]:
            found = position
        else:
            break
    return found


def build_map(source_dirs, map_path):
    """Scan the knowledge documents, build the map, return a summary. Sources are read only."""
    started_at = time.time()
    nodes, links = [], []
    by_key = {}                      # title -> [(folder, id), ...], in scan order

    files = [(path, os.path.splitext(os.path.basename(path))[0])
             for path in _document_files(source_dirs)]
    document_ids = _document_ids(files)

    parsed_documents = []
    for path, document_name in files:      # the same list the ids came from, not a second scan
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read()
        parsed = parse_html(text) if path.endswith(HTML_SUFFIXES) else parse_markdown(text)
        document_id = document_ids[path]
        parsed_documents.append((path, document_id, document_name, parsed))
        nodes.append({"id": document_id, "label": document_name, "kind": "document",
                      "source_file": path, "source_location": 1})
        by_key.setdefault(_title_key(document_name), []).append(
            (os.path.dirname(path), document_id))

    for path, document_id, _document_name, parsed in parsed_documents:
        section_ids, section_lines = [], []
        for index, section in enumerate(parsed["sections"]):
            section_id = f"{document_id}_s{index}"
            section_ids.append(section_id)
            section_lines.append(section["line"])
            nodes.append({"id": section_id, "label": section["title"], "kind": "section",
                          "source_file": path, "source_location": section["line"]})
            links.append({"source": section_id, "target": document_id, "relation": "part_of"})
        for index, statement in enumerate(parsed["statements"]):
            statement_id = f"{document_id}_t{index}"
            nodes.append({"id": statement_id, "label": statement["text"], "kind": "statement",
                          "source_file": path, "source_location": statement["line"]})
            # Hang the statement on its own heading, not on the document. Hanging everything on
            # the document makes one hub whose neighbours are every statement in the file, so a
            # walk of two steps from any statement reaches the whole document - which is why a
            # broad question came back with a file dumped into it. Under its heading, the same
            # walk reaches the section it belongs to. Text above the first heading has no
            # section to sit under, so it stays on the document.
            section_index = _section_index_for(statement, section_lines)
            parent = section_ids[section_index] if section_index is not None else document_id
            links.append({"source": statement_id, "target": parent, "relation": "part_of"})
        for link in parsed["links"]:
            key = _title_key(link["target"])
            if key not in by_key:
                name_only_id = "name_" + key.replace(" ", "_")
                by_key[key] = [("", name_only_id)]
                nodes.append({"id": name_only_id, "label": link["target"], "kind": "name_only",
                              "source_file": "", "source_location": None})
            links.append({"source": document_id, "target": _nearest(by_key[key], path),
                          "relation": link["relation"] or "mentions"})

    links = _drop_mentions_that_repeat_a_named_relation(links)
    nodes.sort(key=lambda node: node["id"])
    links.sort(key=lambda link: (link["source"], link["target"], link["relation"]))

    os.makedirs(os.path.dirname(map_path) or ".", exist_ok=True)
    temporary_path = map_path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as handle:
        json.dump({"nodes": nodes, "links": links}, handle,
                  ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(temporary_path, map_path)   # swap the whole file, so nobody reads a half-written map
    # Remember what the documents looked like, so the next run can skip an unchanged scan.
    record = _fingerprint_path(map_path)
    with open(record + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(_fingerprint(source_dirs), handle, ensure_ascii=False)
    os.replace(record + ".tmp", record)

    return {"documents": len(parsed_documents), "nodes": len(nodes), "links": len(links),
            "located": sum(1 for node in nodes if node["source_location"] is not None),
            "relation_kinds": len({link["relation"] for link in links}),
            "elapsed": time.time() - started_at}


def conflict_paths(map_path):
    """The sidecar files live beside the map, named after it."""
    folder = os.path.dirname(map_path) or "."
    stem = os.path.splitext(os.path.basename(map_path))[0]
    return (os.path.join(folder, stem + ".conflicts.txt"),
            os.path.join(folder, stem + ".suppressions.json"))


def config_watched_names():
    """Value names the config asks to watch. Missing key means the built-in list."""
    from config import default_config_path, load_config
    return load_config(default_config_path()).get("watched_names")


def write_conflict_report(map_path, watched_names=None):
    """Write the conflicts sidecar. Never fails the build - the map is already written."""
    try:
        import conflicts

        with open(map_path, encoding="utf-8") as handle:
            nodes = json.load(handle)["nodes"]
        report_path, suppressions_path = conflict_paths(map_path)
        strong, weak, suppressed, _counts = conflicts.run(nodes, report_path, suppressions_path,
                                                          watched_names)
        return ("conflicts %d strong · %d context · %d suppressed"
                % (len(strong), len(weak), suppressed))
    except Exception as error:                     # noqa: BLE001 - a sidecar must never break the build
        return "conflicts (not checked: %s)" % error


def main(argv):
    """Entry point for the three refresh points. Paths come from the config; the direct
    arguments exist for the tests."""
    parser = argparse.ArgumentParser(
        description="Scan the knowledge documents and build the map.")
    parser.add_argument("--source", action="append", default=[],
                        help="knowledge document folder (repeatable). Read from the config if absent")
    parser.add_argument("--out", default="",
                        help="where to put the map. Read from the config if absent")
    parser.add_argument("--quiet", action="store_true", help="do not print the score")
    options = parser.parse_args(argv)

    source_dirs, map_path = options.source, options.out
    if not source_dirs or not map_path:
        from config import default_config_path, load_config
        config = load_config(default_config_path())
        source_dirs = source_dirs or config["source_dirs"]
        map_path = map_path or config["map_path"]
    if not source_dirs or not map_path:
        if not options.quiet:
            print("The config has no document folder or no place for the map. "
                  "Run the first-time setup flow first.")
        return 0   # this runs from a hook, so stay quiet until the setup flow has run

    if unchanged_since_last_build(source_dirs, map_path):
        if not options.quiet:
            print("No document changed, so the map was left as it is.")
        return 0   # the refresh points fire often; an unchanged scan is pure cost

    summary = build_map(source_dirs, map_path)
    conflict_line = write_conflict_report(map_path, config_watched_names())
    for note in folder_notes(source_dirs, summary["documents"]):
        print(note)          # printed even when quiet: a wrong path is the thing worth saying
    if not options.quiet:
        from score import format_score, score_map, verify_samples
        score = score_map(map_path)
        # The sampled check is the only measure that catches a map that scores well and still
        # answers with nothing, so it runs on every build, not only in the tests.
        sampled = verify_samples(score)
        sample_line = (f" · samples {sampled['matched']}/{sampled['checked']} verbatim"
                       if sampled["checked"] else "")
        print(format_score(score) + sample_line + f" · {summary['elapsed']:.2f}s")
        print(conflict_line)
        for failure in sampled["failed"]:
            print(f"[a sampled statement is no longer on that line - {failure}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
