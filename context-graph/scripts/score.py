"""Scores the map against itself. A map can build cleanly and still be half useless."""
import json
import os
import re

NUMBER_PATTERN = re.compile(r"\d")
# The map makes these two by itself, so their presence says nothing about what a person wrote.
AUTOMATIC_RELATIONS = frozenset({"part_of", "mentions"})
SAMPLE_COUNT = 5


def score_map(map_path):
    """Measure five things and point at the cause behind whichever one is low."""
    with open(map_path, encoding="utf-8-sig", errors="replace") as handle:
        graph = json.load(handle)
    nodes, links = graph["nodes"], graph["links"]

    located = sum(1 for node in nodes if node.get("source_location") is not None)
    documents = sum(1 for node in nodes if node.get("kind") == "document")
    located_ratio = located / len(nodes) if nodes else 0.0
    document_node_ratio = documents / len(nodes) if nodes else 0.0

    neighbours = {node["id"]: set() for node in nodes}
    for link in links:
        if link["source"] in neighbours and link["target"] in neighbours:
            neighbours[link["source"]].add(link["target"])
            neighbours[link["target"]].add(link["source"])
    components, seen = 0, set()
    for node_id in sorted(neighbours):
        if node_id in seen:
            continue
        components += 1
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(neighbours[current] - seen)
    isolated = sum(1 for node_id in neighbours if not neighbours[node_id])

    # Samples: statement nodes carrying a number, picked in a fixed order so the same ones come
    # out every time - but one document at a time. Taking the first few by id took whatever the
    # alphabet put in front, which was four lines of the same file, and a check that only ever
    # looks at one document is not much of a check.
    candidates = sorted(
        (node for node in nodes
         if node.get("kind") == "statement" and NUMBER_PATTERN.search(node["label"] or "")),
        key=lambda node: node["id"])
    # Grouped by folder first, then by document. Going document by document alone let the five
    # come from whichever folder sorts first - the same "took what the alphabet put in front"
    # the per-document grouping was meant to fix, one level up.
    per_folder = {}
    for node in candidates:
        folder = os.path.dirname(node["source_file"])
        per_folder.setdefault(folder, {}).setdefault(node["source_file"], []).append(node)
    queues = {folder: [found for _name, found in sorted(in_folder.items())]
              for folder, in_folder in per_folder.items()}
    spread, exhausted = [], False
    while len(spread) < SAMPLE_COUNT and not exhausted:
        exhausted = True
        for folder in sorted(queues):
            waiting = queues[folder]
            while waiting and not waiting[0]:
                waiting.pop(0)                       # this document has none left to give
            if not waiting:
                continue
            spread.append(waiting[0].pop(0))
            waiting.append(waiting.pop(0))           # and the next turn goes to the next document
            exhausted = False
            if len(spread) >= SAMPLE_COUNT:
                break
    samples = [{"label": node["label"], "source_file": node["source_file"],
                "source_location": node["source_location"], "matched": False}
               for node in spread[:SAMPLE_COUNT]]

    hints = []
    if located_ratio < 0.8:
        hints.append(f"located {located_ratio:.0%} — many documents carry headings only,"
                     " with no body text under them")
    if document_node_ratio > 0.5:
        hints.append(f"whole-document nodes {document_node_ratio:.0%} — the map is closer"
                     " to a list of documents")
    # Counting kinds hides the real shape: the map makes `part_of` and `mentions` by itself, so
    # those two are always there however few relations a person actually wrote. What matters is
    # how many hand-written relations there are per document.
    written = [link for link in links if link["relation"] not in AUTOMATIC_RELATIONS]
    if documents and len(written) / documents < 1:
        hints.append(f"few written relations — {len(written)} across {documents} documents; "
                     "the `- <word> [[target]]` shape is almost absent")
    if components > max(1, len(nodes) // 50):
        hints.append(f"{components} components — documents rarely link to each other,"
                     " so path finding will not get far")

    return {"nodes": len(nodes), "links": len(links),
            "located_ratio": located_ratio, "document_node_ratio": document_node_ratio,
            "relation_kinds": len({link["relation"] for link in links}),
            "components": components, "isolated": isolated,
            "samples": samples, "hints": hints}


def format_score(score):
    """Format the one line shown on an ordinary refresh."""
    return (f"nodes {score['nodes']} · links {score['links']} · "
            f"located {score['located_ratio']:.1%} · relations {score['relation_kinds']} kinds · "
            f"components {score['components']}")


def verify_samples(score):
    """Check each sample statement against that line in the source file.

    One mismatch shows up right here.
    """
    checked, matched, failed = 0, 0, []
    for sample in score["samples"]:
        source_file, line_number = sample["source_file"], sample["source_location"]
        if not source_file or line_number is None:
            continue
        checked += 1
        try:
            with open(source_file, encoding="utf-8-sig", errors="replace") as handle:
                lines = handle.read().split("\n")
            original = lines[line_number - 1] if 0 < line_number <= len(lines) else ""
        except OSError:
            original = ""
        if sample["label"].strip() and sample["label"].strip() in original:
            sample["matched"] = True
            matched += 1
        else:
            failed.append(f"{os.path.basename(source_file)}:{line_number}")
    return {"checked": checked, "matched": matched, "failed": failed}
