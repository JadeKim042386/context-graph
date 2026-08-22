"""The conflicts sidecar: what counts as a conflict, and what a suppression does."""
import conflicts


def node(text, source_file, line=1):
    return {"id": source_file + str(line), "kind": "statement", "label": text,
            "source_file": source_file, "source_location": str(line)}


def test_the_same_value_in_two_units_is_not_a_conflict():
    nodes = [node("tray width: 3.5 m", "a.md"), node("tray width = 3500 mm", "b.md")]
    strong, _context, _suppressed, _counts = conflicts.find(nodes, {})
    assert strong == [], strong


def test_two_documents_stating_it_differently_is_a_conflict():
    nodes = [node("bend radius: 0.6 m", "a.md"), node("bend radius = 0.9 m", "b.md")]
    strong, _context, _suppressed, _counts = conflicts.find(nodes, {})
    assert [name for name, _values, _signature in strong] == ["bend radius"], strong


def test_one_document_disagreeing_with_itself_is_not_counted():
    nodes = [node("bend radius: 0.6 m", "a.md"), node("bend radius: 0.9 m", "a.md", line=7)]
    strong, _context, _suppressed, _counts = conflicts.find(nodes, {})
    assert strong == [], strong


def test_values_in_different_units_are_never_compared():
    """5 m and 67 % are not the same measurement, so they are not a disagreement."""
    nodes = [node("share of the run 5 m", "a.md"), node("share of the run 67 %", "b.md")]
    _strong, context, _suppressed, _counts = conflicts.find(nodes, {})
    assert context == [], context


def test_a_watched_name_skips_a_value_that_is_added_to_it():
    """`tray width + 0.30 m` adds to the width; it does not state the width."""
    nodes = [node("lane pitch is tray width + 0.30 m", "a.md"), node("tray width 0.66 m", "b.md")]
    found = conflicts.collect_watched(nodes, ["tray width"])
    assert set(found.get("tray width", {})) == {(0.66, "m")}, found


def test_a_suppression_releases_itself_when_a_value_changes():
    nodes = [node("bend radius: 0.6 m", "a.md"), node("bend radius: 0.9 m", "b.md")]
    strong, _context, _suppressed, _counts = conflicts.find(nodes, {})
    name, _values, signature = strong[0]

    quiet, _context, suppressed, _counts = conflicts.find(nodes, {name: signature})
    assert quiet == [] and suppressed == 1

    changed = [node("bend radius: 0.6 m", "a.md"), node("bend radius: 1.2 m", "b.md")]
    again, _context, suppressed_again, _counts = conflicts.find(changed, {name: signature})
    assert len(again) == 1 and suppressed_again == 0


def test_the_report_names_both_passes(tmp_path):
    nodes = [node("bend radius: 0.6 m", "a.md"), node("bend radius: 0.9 m", "b.md")]
    report = tmp_path / "map.conflicts.txt"
    conflicts.run(nodes, str(report), str(tmp_path / "map.suppressions.json"))
    written = report.read_text(encoding="utf-8")
    assert "[strong]" in written and "[context]" in written and "bend radius" in written


def test_a_unit_is_not_cut_in_half_by_the_window():
    """The window bounds where the number may start, not where its unit ends.

    An 18-character cut through "Tray width is fixed at 600 mm" lands between the two
    m's, and the value used to be read as 600 m - the same sentence then disagreed
    with itself.
    """
    nodes = [node("Tray width is fixed at 600 mm for every main run.", "a.md")]
    found = conflicts.collect_watched(nodes, ["tray width"])
    assert set(found.get("tray width", {})) == {(0.6, "m")}, found
