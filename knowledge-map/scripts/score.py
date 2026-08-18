"""지도에 스스로 점수를 매깁니다. 지도는 멀쩡히 만들어지면서 반쪽짜리일 수 있습니다."""
import json
import re

NUMBER_PATTERN = re.compile(r"\d")
SAMPLE_COUNT = 5


def score_map(map_path):
    """다섯 가지를 재고, 낮은 항목의 원인을 짚어 돌려줍니다."""
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

    # 표본: 숫자가 든 문장 노드를 정해진 방식(정렬)으로 골라 늘 같은 것이 뽑히게 합니다.
    candidates = sorted(
        (node for node in nodes
         if node.get("kind") == "statement" and NUMBER_PATTERN.search(node["label"] or "")),
        key=lambda node: node["id"])
    samples = [{"label": node["label"], "source_file": node["source_file"],
                "source_location": node["source_location"], "matched": False}
               for node in candidates[:SAMPLE_COUNT]]

    hints = []
    if located_ratio < 0.8:
        hints.append(f"위치 정보 {located_ratio:.0%} — 소제목만 있고 그 아래 본문이 안 담긴 문서가 많습니다")
    if document_node_ratio > 0.5:
        hints.append(f"문서 통짜 노드 {document_node_ratio:.0%} — 지도가 문서 목록에 가깝습니다")
    if len({link["relation"] for link in links}) <= 2:
        hints.append("관계 종류가 적습니다 — `- <낱말> [[대상]]` 꼴이 거의 없습니다")
    if components > max(1, len(nodes) // 50):
        hints.append(f"덩어리 {components}개 — 문서끼리 링크가 드뭅니다. 길 찾기는 기대하기 어렵습니다")

    return {"nodes": len(nodes), "links": len(links),
            "located_ratio": located_ratio, "document_node_ratio": document_node_ratio,
            "relation_kinds": len({link["relation"] for link in links}),
            "components": components, "isolated": isolated,
            "samples": samples, "hints": hints}


def format_score(score):
    """평소 갱신 때 보여줄 한 줄로 바꿉니다."""
    return (f"노드 {score['nodes']} · 연결 {score['links']} · "
            f"위치 {score['located_ratio']:.1%} · 관계 {score['relation_kinds']}종 · "
            f"덩어리 {score['components']}개")
