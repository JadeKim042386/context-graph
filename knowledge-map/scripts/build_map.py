"""조각들을 이어 지도 파일 하나를 만듭니다. 파일 형식은 파서가 알고, 여기서는 잇기만 합니다."""
import json
import os
import time

from parse_html import parse_html
from parse_markdown import parse_markdown

MARKDOWN_SUFFIXES = (".md", ".markdown")
HTML_SUFFIXES = (".html", ".htm")


def _문서_파일들(source_dirs):
    """훑을 파일을 정렬해 돌려줍니다. 정렬이 같은 결과를 보장합니다."""
    found = []
    for source_dir in sorted(source_dirs):
        for folder, sub_folders, file_names in os.walk(source_dir):
            sub_folders.sort()
            for file_name in sorted(file_names):
                if file_name.endswith(MARKDOWN_SUFFIXES + HTML_SUFFIXES):
                    found.append(os.path.join(folder, file_name))
    return found


def _제목_열쇠(text):
    """이름 맞추기용 열쇠. 제목의 기호 차이(`/`·`:` ↔ `-`)를 흡수합니다."""
    lowered = text.strip().lower()
    for symbol in "/:\\":
        lowered = lowered.replace(symbol, "-")
    return " ".join(lowered.split())


def build_map(source_dirs, map_path):
    """지식 문서를 훑어 지도를 만들고 요약을 돌려줍니다. 원본은 읽기만 합니다."""
    started_at = time.time()
    nodes, links = [], []
    by_key = {}

    parsed_documents = []
    for path in _문서_파일들(source_dirs):
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read()
        parsed = parse_html(text) if path.endswith(HTML_SUFFIXES) else parse_markdown(text)
        document_name = os.path.splitext(os.path.basename(path))[0]
        document_id = "doc_" + _제목_열쇠(document_name).replace(" ", "_")
        parsed_documents.append((path, document_id, document_name, parsed))
        nodes.append({"id": document_id, "label": document_name, "kind": "document",
                      "source_file": path, "source_location": 1})
        by_key[_제목_열쇠(document_name)] = document_id

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
            key = _제목_열쇠(link["target"])
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
    os.replace(temporary_path, map_path)   # 반쯤 쓰인 지도를 읽는 일이 없게 통째로 바꿔칩니다

    return {"nodes": len(nodes), "links": len(links),
            "located": sum(1 for node in nodes if node["source_location"] is not None),
            "relation_kinds": len({link["relation"] for link in links}),
            "elapsed": time.time() - started_at}
