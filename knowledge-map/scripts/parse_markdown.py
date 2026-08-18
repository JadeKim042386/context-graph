"""Turns one markdown document into pieces (headings, statements, links). It knows nothing about the map."""
import re

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
# Relation line: only the shape "- <word> [[target]]" counts as a relation. Section names are not relied on.
RELATION_PATTERN = re.compile(r"^\s*[-*]\s+([A-Za-z_][A-Za-z0-9_]*)\s+\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*$")
LIST_ITEM_PATTERN = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")


def parse_markdown(text):
    """Scan one document and return its pieces. Line numbers start at 1."""
    lines = text.split("\n")
    sections, statements, links = [], [], []
    current_section = ""
    inside_front_matter = False

    for line_number, line in enumerate(lines, start=1):
        if line_number == 1 and line.strip() == "---":
            inside_front_matter = True
            continue
        if inside_front_matter:
            if line.strip() == "---":
                inside_front_matter = False
            continue

        heading = HEADING_PATTERN.match(line)
        if heading:
            current_section = heading.group(2)
            sections.append({"title": current_section, "line": line_number, "body": ""})
            continue

        relation = RELATION_PATTERN.match(line)
        if relation:
            links.append({"target": relation.group(2).strip(),
                          "relation": relation.group(1),
                          "line": line_number})
            # Do not stop here. The relation line has to be kept as a statement below
            # as well, or documents that continue with prose after the relation section
            # lose the statements that carry the values.
        else:
            for target in WIKILINK_PATTERN.findall(line):
                links.append({"target": target.strip(), "relation": None, "line": line_number})

        list_item = LIST_ITEM_PATTERN.match(line)
        content = list_item.group(1) if list_item else line.strip()
        if content:
            statements.append({"text": content, "line": line_number, "section": current_section})
            if sections:
                sections[-1]["body"] += content + "\n"

    return {"sections": sections, "statements": statements, "links": links}
