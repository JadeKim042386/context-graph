"""마크다운 한 편을 조각(소제목·문장·연결)으로 바꿉니다. 지도가 무엇인지는 모릅니다."""
import re

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
# 관계 줄: "- <낱말> [[대상]]" 꼴만 관계로 봅니다. 절 이름에 기대지 않습니다.
RELATION_PATTERN = re.compile(r"^\s*[-*]\s+([A-Za-z_][A-Za-z0-9_]*)\s+\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*$")
LIST_ITEM_PATTERN = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")


def parse_markdown(text):
    """한 편을 훑어 조각들을 돌려줍니다. 줄 번호는 1부터입니다."""
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
            continue

        for target in WIKILINK_PATTERN.findall(line):
            links.append({"target": target.strip(), "relation": None, "line": line_number})

        list_item = LIST_ITEM_PATTERN.match(line)
        content = list_item.group(1) if list_item else line.strip()
        if content:
            statements.append({"text": content, "line": line_number, "section": current_section})
            if sections:
                sections[-1]["body"] += content + "\n"

    return {"sections": sections, "statements": statements, "links": links}
