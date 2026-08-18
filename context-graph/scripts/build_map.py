"""Joins the pieces into a single map file. The parsers know the formats; this only joins.

The four refresh points (session start, delegated task end, before and after
compaction) call this file from the command line.
"""
import argparse
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


def build_map(source_dirs, map_path):
    """Scan the knowledge documents, build the map, return a summary. Sources are read only."""
    started_at = time.time()
    nodes, links = [], []
    by_key = {}

    parsed_documents = []
    for path in _document_files(source_dirs):
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read()
        parsed = parse_html(text) if path.endswith(HTML_SUFFIXES) else parse_markdown(text)
        document_name = os.path.splitext(os.path.basename(path))[0]
        document_id = "doc_" + _title_key(document_name).replace(" ", "_")
        parsed_documents.append((path, document_id, document_name, parsed))
        nodes.append({"id": document_id, "label": document_name, "kind": "document",
                      "source_file": path, "source_location": 1})
        by_key[_title_key(document_name)] = document_id

    for path, document_id, _document_name, parsed in parsed_documents:
        for index, section in enumerate(parsed["sections"]):
            section_id = f"{document_id}_s{index}"
            nodes.append({"id": section_id, "label": section["title"], "kind": "section",
                          "source_file": path, "source_location": section["line"]})
            links.append({"source": section_id, "target": document_id, "relation": "part_of"})
        for index, statement in enumerate(parsed["statements"]):
            statement_id = f"{document_id}_t{index}"
            nodes.append({"id": statement_id, "label": statement["text"], "kind": "statement",
                          "source_file": path, "source_location": statement["line"]})
            links.append({"source": statement_id, "target": document_id, "relation": "part_of"})
        for link in parsed["links"]:
            key = _title_key(link["target"])
            if key not in by_key:
                name_only_id = "name_" + key.replace(" ", "_")
                by_key[key] = name_only_id
                nodes.append({"id": name_only_id, "label": link["target"], "kind": "name_only",
                              "source_file": "", "source_location": None})
            links.append({"source": document_id, "target": by_key[key],
                          "relation": link["relation"] or "mentions"})

    nodes.sort(key=lambda node: node["id"])
    links.sort(key=lambda link: (link["source"], link["target"], link["relation"]))

    os.makedirs(os.path.dirname(map_path) or ".", exist_ok=True)
    temporary_path = map_path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as handle:
        json.dump({"nodes": nodes, "links": links}, handle,
                  ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(temporary_path, map_path)   # swap the whole file, so nobody reads a half-written map

    return {"nodes": len(nodes), "links": len(links),
            "located": sum(1 for node in nodes if node["source_location"] is not None),
            "relation_kinds": len({link["relation"] for link in links}),
            "elapsed": time.time() - started_at}


def main(argv):
    """Entry point for the four refresh points. Paths come from the config; the direct
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

    summary = build_map(source_dirs, map_path)
    if not options.quiet:
        from score import format_score, score_map
        print(format_score(score_map(map_path)) + f" · {summary['elapsed']:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
