"""Walking decision causality: a cycle stops it, and the depth limit holds."""
import ask


def link(source, target, relation):
    return {"source": source, "target": target, "relation": relation}


def test_a_miswritten_cycle_stops_the_walk():
    """A caused B and B caused A cannot both be true; the walk must still end."""
    links = [link("a", "b", "caused_by"), link("b", "a", "caused_by")]
    reached = ask.walk_chain("a", links, True, ask.CAUSE_RELATIONS)
    assert [node_id for node_id, _relation, _level in reached] == ["b"], reached


def test_the_depth_limit_holds():
    links = [link("a", "b", "caused_by"), link("b", "c", "caused_by"),
             link("c", "d", "caused_by"), link("d", "e", "caused_by")]
    reached = ask.walk_chain("a", links, True, ask.CAUSE_RELATIONS, depth=2)
    assert [node_id for node_id, _relation, _level in reached] == ["b", "c"], reached


def test_the_walk_runs_both_ways():
    """Forward finds what a decision came from; backward finds what it led to."""
    links = [link("later", "earlier", "caused_by")]
    assert ask.walk_chain("later", links, True, ask.CAUSE_RELATIONS)[0][0] == "earlier"
    assert ask.walk_chain("earlier", links, False, ask.CAUSE_RELATIONS)[0][0] == "later"


def test_nearby_relations_are_not_treated_as_cause():
    links = [link("a", "b", "supersedes")]
    assert ask.walk_chain("a", links, True, ask.CAUSE_RELATIONS) == []
    assert ask.walk_chain("a", links, True, ask.NEARBY_RELATIONS)[0][0] == "b"


def test_a_node_is_matched_by_part_of_its_name():
    nodes = [{"id": "n1", "label": "ADR 0013 Stage-3 Drops Coverage Metric"},
             {"id": "n2", "label": "ADR 0011 Inference-Valid Criteria"}]
    assert ask.find_node(nodes, "ADR 0013")["id"] == "n1"
    assert ask.find_node(nodes, "nothing like it") is None
