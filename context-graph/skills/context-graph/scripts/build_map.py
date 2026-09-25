"""Joins the pieces into a single map file. The parsers know the formats; this only joins.

The three refresh points (session start, delegated task end, after compaction) call this
file from the command line. Before compaction the hook only prints a reminder - there is
nothing to rebuild from until the session has been written into the documents.
"""
import argparse
import collections
import json
import os
import re
import sys
import time
import hashlib
from pathlib import Path

from parse_html import parse_html
from parse_markdown import parse_markdown
from config import (BindingError, binding_failure, load_project_config,
                    validate_bound_map, validate_source_path)
from freshness import (FreshnessError, document_files, file_record, make_snapshot,
                       scan_snapshot, projection_digest)

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
    return document_files(source_dirs)


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


def _fingerprint(source_dirs, snapshot=None):
    """Versioned path/content identity; source timestamps never authorize a cache hit."""
    snapshot = scan_snapshot(source_dirs) if snapshot is None else snapshot
    here = Path(__file__).resolve().parent
    code = hashlib.sha256()
    for name in ("build_map.py", "parse_markdown.py", "parse_html.py", "conflicts.py", "config.py", "freshness.py"):
        code.update(name.encode())
        code.update((here / name).read_bytes())
    return {"schema_version": 2, "documents": len(snapshot["files"]), "source_snapshot": snapshot,
            "builder": _builder_stamp(), "builder_sha256": code.hexdigest()}


def _builder_stamp():
    """When the files that decide the map's shape were last changed.

    `conflicts.py` is in here because the report it writes beside the map is written by this
    build too: without it, changing what counts as a conflict left the old report standing
    until somebody happened to edit a document.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    stamps = []
    for name in ("build_map.py", "parse_markdown.py", "parse_html.py", "conflicts.py"):
        try:
            stamps.append(round(os.path.getmtime(os.path.join(here, name)), 3))
        except OSError:
            pass
    return max(stamps, default=0.0)


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
        with open(map_path, encoding="utf-8") as handle:
            graph = json.load(handle)
        current = _fingerprint(source_dirs)
        return (previous == current and graph.get("source_snapshot") == current["source_snapshot"]
                and graph.get("projection_sha256") == projection_digest(graph))
    except (OSError, ValueError, AttributeError):
        return False


def _document_ids(paths_and_names):
    """A node id for every document, none of them shared, none of them tied to scan order.

    The name alone is not enough: two vaults both hold `_CLAUDE.md`, `index.md` and
    `overview.md`, and one node id shared by two files merges their contents into a single
    node, so an answer about one vault's rules carries the other vault's rules with it.

    Whoever is scanned first must not get to keep the plain name either. If it did, adding a
    second `index.md` would rename the first one, and every id that was ever written down
    beside the map would point at nothing. So a name that appears more than once gives *all*
    of its documents the folder they sit in.

    One folder is often not enough. This vault holds `_CLAUDE.md`, `index.md` and
    `overview.md` twice over, and both copies of each sit in a folder called `knowledge` -
    so the folder settles nothing and a counted suffix took over, which put the ids back at
    the mercy of the scan order. Enough of the path is taken to tell them apart, and then
    what any one document is called no longer depends on what else was scanned.
    """
    seen = collections.Counter(_title_key(name) for _path, name in paths_and_names)
    ids = {}
    for path, name in paths_and_names:
        key = _title_key(name)
        chosen = "doc_" + key.replace(" ", "_")
        if seen[key] > 1:
            twins = [other for other, other_name in paths_and_names
                     if _title_key(other_name) == key]
            chosen += "__" + _distinguishing_path(path, twins)
        ids[path] = chosen
    # Nothing above may hand two documents the same id: one id shared is two files merged into
    # one node, which is the whole reason these are built the way they are. The check is cheap
    # and it does not depend on the rules above being right.
    taken = set()
    for path in sorted(ids):
        chosen = ids[path]
        if chosen in taken:
            chosen += "__" + _whole_path(path)
            while chosen in taken:
                chosen += "_"
        taken.add(chosen)
        ids[path] = chosen
    return ids


def _whole_path(path):
    """Every folder above a document, as one piece of an id."""
    return "_".join(_title_key(part).replace(" ", "_")
                    for part in _path_parts(path)[:-1] if part)


def _path_parts(path):
    """Split either POSIX or Windows paths, regardless of the host OS."""
    return [part for part in re.split(r"[\\/]", path) if part]


def _distinguishing_path(path, twins):
    """As much of the folders above a document as it takes to tell it from its namesakes.

    One folder name is taken first, then two, and so on. Counting instead - the first one
    scanned keeps the plain name, the next gets a 2 - reads the same but is not the same
    thing: the number depends on what else the scan found, so adding a document renames one
    that was already there.

    Two folders count as telling a document apart only if they still differ once they are
    written the way an id is written. Comparing the raw folders instead let `Knowledge` and
    `knowledge`, or `a b` and `a_b`, look different here and come out identical.
    """
    def suffix_at(other, depth):
        parts = _path_parts(other)[:-1][-depth:]
        return "_".join(_title_key(part).replace(" ", "_") for part in parts if part)

    folders = _path_parts(path)[:-1]
    for depth in range(1, len(folders) + 1):
        mine = suffix_at(path, depth)
        if not any(other != path and suffix_at(other, depth) == mine for other in twins):
            return mine
    # Same name, and folders that read the same all the way up. The whole path is the honest
    # answer, and the caller has a final check for what even that cannot separate.
    return _whole_path(path)


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


def build_map(source_dirs, map_path, project_binding=None):
    """Scan the knowledge documents, build the map, return a summary. Sources are read only."""
    started_at = time.time()
    nodes, links = [], []
    by_key = {}                      # title -> [(folder, id), ...], in scan order

    files = [(path, os.path.splitext(os.path.basename(path))[0])
             for path in _document_files(source_dirs)]
    if project_binding is not None:
        for path, _name in files:
            validate_source_path(path, project_binding)
    document_ids = _document_ids(files)

    parsed_documents, captured_files = [], []
    for path, document_name in files:      # the same list the ids came from, not a second scan
        raw = Path(path).read_bytes()
        captured_files.append(file_record(path, raw))
        text = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
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

    snapshot = make_snapshot(captured_files)
    validate = (lambda path: validate_source_path(path, project_binding)) if project_binding is not None else None
    if scan_snapshot(source_dirs, validate) != snapshot:
        raise FreshnessError("source_changed_during_build")
    fingerprint = _fingerprint(source_dirs, snapshot)
    graph = {"nodes": nodes, "links": links, "source_snapshot": snapshot}
    graph["projection_sha256"] = projection_digest(graph)
    if project_binding is not None:
        graph["project_binding"] = project_binding
    os.makedirs(os.path.dirname(map_path) or ".", exist_ok=True)
    temporary_path = map_path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as handle:
        json.dump(graph, handle,
                  ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(temporary_path, map_path)   # swap the whole file, so nobody reads a half-written map
    # Remember what the documents looked like, so the next run can skip an unchanged scan.
    record = _fingerprint_path(map_path)
    with open(record + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(fingerprint, handle, ensure_ascii=False)
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
    parser.add_argument("--project-root")
    parser.add_argument("--config")
    options = parser.parse_args(argv)

    source_dirs, map_path = options.source, options.out
    binding, watched = None, None
    if options.project_root is not None or not source_dirs or not map_path or options.config:
        try:
            config, binding, _resolved, _graph = load_project_config(options.project_root, options.config, require_map=False)
            if source_dirs or map_path:
                raise BindingError("bound_build_disallows_path_overrides")
            source_dirs, map_path = config["source_dirs"], config["map_path"]
            watched = config.get("watched_names")
        except BindingError as exc:
            print(json.dumps(binding_failure(exc.reason), sort_keys=True))
            return 2

    binding_matches = binding is None
    if binding is not None and os.path.exists(map_path):
        try:
            with open(map_path, encoding="utf-8") as handle:
                validate_bound_map(json.load(handle), binding)
            binding_matches = True
        except (OSError, ValueError):
            binding_matches = False

    if binding_matches and unchanged_since_last_build(source_dirs, map_path):
        if not options.quiet:
            print("No document changed, so the map was left as it is.")
        return 0   # the refresh points fire often; an unchanged scan is pure cost

    try:
        summary = build_map(source_dirs, map_path, project_binding=binding)
    except (BindingError, FreshnessError, OSError) as exc:
        reason = exc.reason if isinstance(exc, BindingError) else (str(exc) if isinstance(exc, FreshnessError) else "source_unreadable")
        print(json.dumps(binding_failure(reason), sort_keys=True))
        return 2
    conflict_line = write_conflict_report(map_path, watched)
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
