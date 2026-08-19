"""Turns one markdown document into pieces (headings, statements, links). It knows nothing about the map."""
import re

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
# Relation line: only the shape "- <word> [[target]]" counts as a relation. Section names are not relied on.
# The word may be written in any script, so a Korean note keeps its relations instead of losing them
# to an unnamed mention. Digits and underscores cannot open the word, which keeps list items such as
# "- 3 [[target]]" out.
RELATION_PATTERN = re.compile(r"^\s*[-*]\s+([^\W\d_]\w*)\s+\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*$",
                              re.UNICODE)

# Korean relation words, mapped onto the English names the rest of the map already uses, so that
# "- 대체함 [[X]]" and "- supersedes [[X]]" end up as the same relation and a path can run through
# both. This is a fixed table, not a translation service - nothing here calls a model. A word that
# is not in the table is kept exactly as it was written.
KOREAN_RELATION_NAMES = {
    "대체함": "supersedes",
    "대체": "supersedes",
    "부분대체함": "supersedes_partially",
    "부분대체": "supersedes_partially",
    "관련": "relates_to",
    "관련됨": "relates_to",
    "참고": "relates_to",
    "후속": "follows",
    "따름": "follows",
    "선행": "precedes",
    "정정함": "corrects",
    "정정": "corrects",
    "포함": "part_of",
    "속함": "part_of",
    "확장": "extends",
    "구현": "implements",
    "반박": "contradicts",
    "출처": "sources",
    "근거": "sources",
}


def relation_name(written_word):
    """The relation name to store. A Korean word becomes its English name; anything else is kept as written."""
    return KOREAN_RELATION_NAMES.get(written_word, written_word)
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
                          "relation": relation_name(relation.group(1)),
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
