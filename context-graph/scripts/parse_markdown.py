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
# A fence opens and closes a code block. What is inside is not prose: a comment in there is not a
# heading and a line of code is not a statement, so the whole block is stepped over.
FENCE_PATTERN = re.compile(r"^\s*(`{3,}|~{3,})")
# The rule under a table header carries no value, only the shape of the table.
TABLE_RULE_PATTERN = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def parse_markdown(text):
    """Scan one document and return its pieces. Line numbers start at 1.

    A fence that is opened and never closed would step over everything after it, so the scan
    is run again with that one line dropped. Dropping the line it actually opened on matters:
    taking out the first marker in the file instead turns the real closing marker into an
    opening one, which swallows the prose that follows and lets the code through in its place.
    """
    skip_lines = set()
    while True:
        parsed, unclosed_at = _scan(text.split("\n"), skip_lines)
        if unclosed_at is None:
            return parsed
        skip_lines.add(unclosed_at)


def _scan(lines, skip_lines):
    """One pass over the lines. Returns the pieces, and the line an unclosed fence opened on."""
    sections, statements, links = [], [], []
    current_section = ""
    inside_front_matter = False
    open_fence = None                # (marker character, its length, the line it opened on)

    for line_number, line in enumerate(lines, start=1):
        if line_number in skip_lines:
            continue
        if line_number == 1 and line.strip() == "---":
            inside_front_matter = True
            continue
        if inside_front_matter:
            if line.strip() == "---":
                inside_front_matter = False
            continue

        fence = FENCE_PATTERN.match(line)
        if fence:
            marker, length = fence.group(1)[0], len(fence.group(1))
            if open_fence is None:
                open_fence = (marker, length, line_number)
                continue
            # Only the same character closes it, and only a run at least as long as the one that
            # opened it - which is how a four-backtick block can hold a three-backtick example.
            if marker == open_fence[0] and length >= open_fence[1]:
                open_fence = None
                continue
        if open_fence is not None:
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
            # The pattern is anchored, so a line that matches is nothing but the relation - it
            # carries no value of its own and is already stored as a link. Storing it again as a
            # statement puts the same fact in the map twice and fills answers with "NODE
            # relates_to [[...]]" lines. Scanning does not stop here: prose after the relation
            # section still becomes statements on the lines that follow.
            continue
        else:
            for target in WIKILINK_PATTERN.findall(line):
                links.append({"target": target.strip(), "relation": None, "line": line_number})

        if TABLE_RULE_PATTERN.match(line):
            continue

        list_item = LIST_ITEM_PATTERN.match(line)
        content = list_item.group(1) if list_item else line.strip()
        if content:
            statements.append({"text": content, "line": line_number,
                               "section": current_section,
                               # Which heading this sits under, by position. The map hangs the
                               # statement on it, and a position cannot be confused the way a
                               # repeated title or an out-of-order line number can.
                               "section_index": len(sections) - 1 if sections else None})
            if sections:
                sections[-1]["body"] += content + "\n"

    pieces = {"sections": sections, "statements": statements, "links": links}
    return pieces, (open_fence[2] if open_fence is not None else None)
