import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from ask import (render_pointer_stub, select_answer_items, select_statement_groups,
                 select_cost_aware_rows, condense_answer, prioritize_identifier_rows)


def item(label, source="knowledge/example.html", location=42, status="unverified"):
    return {
        "label": label,
        "source_file": source,
        "source_location": location,
        "evidence_status": status,
    }


def test_pointer_selector_keeps_full_item_then_uses_complete_pointer():
    candidates = [item("A very long evidence label that cannot fit " * 10), item("short")]

    result = select_answer_items(candidates, budget=400, selector="pointer-v1")

    assert result["items"][0]["action"] == "pointer-only"
    assert result["items"][0]["requires_retrieval"] is True
    assert result["items"][0]["source_file"] == "knowledge/example.html"
    assert result["items"][1]["action"] == "keep"


def test_pointer_stub_is_metadata_only_and_deterministic():
    candidate = item("Sensitive or unverified text", status="unverified")

    first = render_pointer_stub(candidate)
    second = render_pointer_stub(candidate)

    assert first == second
    payload = json.loads(first)
    assert payload["action"] == "pointer-only"
    assert payload["requires_retrieval"] is True
    assert "Sensitive or unverified text" not in first
    assert payload["label_sha256"]


def test_selector_does_not_emit_partial_pointer_when_metadata_does_not_fit():
    result = select_answer_items([item("A label")], budget=10, selector="pointer-v1")

    assert result["items"] == []
    assert result["omitted_count"] == 1
    assert result["status"] == "abstain"


def test_legacy_selector_remains_explicitly_unchanged():
    result = select_answer_items([item("short")], budget=200, selector="legacy")

    assert result["items"] == [{"action": "keep", **item("short")}]
    assert result["omitted_count"] == 0


def statement(rank, carried, source, line, text):
    return (rank, -carried, rank, source, line, text)


def test_group_selector_keeps_heading_condition_and_value_together():
    rows = [
        statement(0, 2, "knowledge/a.html", 100, "NODE value"),
        statement(1, 0, "knowledge/a.html", 95, "NODE heading"),
        statement(2, 0, "knowledge/a.html", 105, "NODE unit"),
        statement(3, 1, "knowledge/b.html", 100, "NODE other"),
    ]

    kept, omitted = select_statement_groups(rows, budget=40)

    assert kept == [rows[1], rows[0], rows[2]]
    assert omitted == 1


def test_group_selector_does_not_mix_sources_or_cut_a_group():
    rows = [
        statement(0, 1, "knowledge/a.html", 10, "NODE first"),
        statement(1, 1, "knowledge/a.html", 10, "NODE second"),
        statement(2, 1, "knowledge/b.html", 10, "NODE third"),
    ]

    kept, omitted = select_statement_groups(rows, budget=len(rows[0][-1]) - 1)

    assert kept == []
    assert omitted == 3


def test_cost_aware_selector_protects_carrier_from_expensive_context():
    carrier = statement(0, 2, "knowledge/a.html", 100, "NODE information gain result")
    heading = statement(1, 0, "knowledge/a.html", 99, "NODE " + ("generic heading " * 40))

    kept, omitted, diagnostics = select_cost_aware_rows(
        [carrier, heading], budget=len(carrier[-1]) + 1, question="information gain result"
    )

    assert kept == [carrier]
    assert omitted == 1
    assert diagnostics["protected_carriers"] == 1


def test_cost_aware_selector_adds_valuable_companion_only_after_carriers():
    carrier = statement(0, 2, "knowledge/a.html", 100, "NODE answer")
    qualifier = statement(1, 0, "knowledge/a.html", 101, "NODE wind speed 20 km")
    bare_heading = statement(2, 0, "knowledge/a.html", 102, "NODE Search strategy")
    budget = max(600, sum(len(row[-1]) + 1 for row in (carrier, qualifier)))

    kept, omitted, diagnostics = select_cost_aware_rows(
        [carrier, qualifier, bare_heading], budget=budget, question="wind search strategy"
    )

    assert kept == [carrier, qualifier]
    assert omitted == 1
    assert diagnostics["optional_companions"] == 1


def test_cost_aware_selector_never_lets_companion_evict_later_carrier():
    first = statement(0, 1, "knowledge/a.html", 100, "NODE first answer")
    companion = statement(1, 0, "knowledge/a.html", 101, "NODE if condition applies, preserve this qualifier")
    second = statement(2, 1, "knowledge/a.html", 200, "NODE second answer")
    budget = sum(len(row[-1]) + 1 for row in (first, second))

    kept, omitted, diagnostics = select_cost_aware_rows(
        [first, companion, second], budget=budget, question="answer condition"
    )

    assert kept == [first, second]
    assert omitted == 1
    assert diagnostics["protected_carriers"] == 2


def test_cost_aware_selector_is_deterministic_for_equal_companions():
    carrier = statement(0, 1, "knowledge/a.html", 100, "NODE answer")
    first = statement(1, 0, "knowledge/a.html", 100, "NODE one note.")
    second = statement(2, 0, "knowledge/a.html", 100, "NODE two note.")
    budget = 200

    result_a = select_cost_aware_rows([carrier, first, second], budget, question="answer")
    result_b = select_cost_aware_rows([carrier, first, second], budget, question="answer")

    assert result_a == result_b
    assert result_a[0] == [carrier, first]


def test_cost_aware_selector_counts_unicode_by_characters_and_reports_bytes_separately():
    carrier = statement(0, 1, "knowledge/a.html", 1, "NODE 답변 설명")

    kept, omitted, diagnostics = select_cost_aware_rows([carrier], budget=len(carrier[-1]) + 1)

    assert kept == [carrier]
    assert omitted == 0
    assert diagnostics["selected_cost"] == len(carrier[-1]) + 1


def test_cost_aware_selector_returns_explicit_empty_outcomes():
    carrier = statement(0, 1, "knowledge/a.html", 1, "NODE answer")

    empty, empty_omitted, empty_diagnostics = select_cost_aware_rows([], 10)
    oversize, oversize_omitted, oversize_diagnostics = select_cost_aware_rows([carrier], 1)
    invalid, invalid_omitted, invalid_diagnostics = select_cost_aware_rows([carrier], 0)

    assert empty == [] and empty_omitted == 0
    assert oversize == [carrier] and oversize_omitted == 0
    assert invalid == [carrier] and invalid_omitted == 0
    assert invalid_diagnostics["fallback_legacy"] is True


def test_cost_aware_selector_keeps_same_line_claims_distinct():
    first = statement(0, 1, "knowledge/a.html", 10, "NODE first claim")
    second = statement(1, 1, "knowledge/a.html", 10, "NODE second claim")
    kept, omitted, _diagnostics = select_cost_aware_rows(
        [first, second], budget=sum(len(row[-1]) + 1 for row in (first, second))
    )

    assert kept == [first, second]
    assert omitted == 0


def test_cost_aware_selector_protects_critical_qualifier_in_legacy_floor():
    carrier = statement(0, 1, "knowledge/a.html", 10, "NODE permission")
    qualifier = statement(1, 0, "knowledge/a.html", 11, "NODE Do not redistribute without permission")
    budget = sum(len(row[-1]) + 1 for row in (carrier, qualifier))

    kept, _omitted, _diagnostics = select_cost_aware_rows(
        [carrier, qualifier], budget=budget, question="permission"
    )

    assert kept == [carrier, qualifier]


def test_cost_aware_selector_deduplicates_optional_rows():
    carrier = statement(0, 1, "knowledge/a.html", 10, "NODE answer")
    companion = statement(1, 0, "knowledge/a.html", 10, "NODE context applies.")
    budget = 600

    kept, _omitted, diagnostics = select_cost_aware_rows(
        [carrier, companion, companion], budget=budget, question="answer condition"
    )

    assert kept.count(companion) == 1
    assert diagnostics["omission_reasons"]["duplicate"] == 1


def test_cost_aware_selector_enforces_per_carrier_character_cap():
    carrier = statement(0, 1, "knowledge/a.html", 10, "NODE answer")
    long_companion = statement(1, 0, "knowledge/a.html", 10, "NODE detail " + ("detail " * 100) + ".")

    kept, _omitted, _diagnostics = select_cost_aware_rows(
        [carrier, long_companion], budget=5000, question="answer detail"
    )

    assert long_companion not in kept


def test_cost_aware_selector_matches_legacy_first_row_fallback_when_oversize():
    oversize = statement(0, 1, "knowledge/a.html", 10, "NODE " + ("answer " * 100))

    kept, omitted, diagnostics = select_cost_aware_rows([oversize], budget=10)

    assert kept == [oversize]
    assert omitted == 0
    assert diagnostics["fallback_legacy"] is True


def test_cost_aware_selector_ignores_rendering_locator_when_scoring_heading():
    carrier = statement(0, 1, "knowledge/a.html", 10, "NODE answer")
    heading = statement(1, 0, "knowledge/a.html", 10,
                       "NODE Generic heading\n     [src=knowledge/a.html loc=10]")

    kept, _omitted, _diagnostics = select_cost_aware_rows(
        [carrier, heading], budget=500, question="answer"
    )

    assert heading not in kept


def test_condense_merge_keeps_distinct_labels_on_the_same_source_line():
    raw = "NODE Existing claim [src=knowledge/a.html loc=10]"
    direct = [(0, -1, "Distinct table-cell claim", "knowledge/a.html", 10)]

    output = condense_answer(raw, question="", direct=direct)

    assert "Existing claim" in output
    assert "Distinct table-cell claim" in output


def test_condense_merge_deduplicates_identical_source_line_and_label():
    raw = "NODE Existing claim [src=knowledge/a.html loc=10]"
    direct = [(0, -1, "Existing claim", "knowledge/a.html", 10)]

    output = condense_answer(raw, question="", direct=direct)

    assert output.count("NODE Existing claim") == 1


def test_identifier_priority_promotes_the_exact_source_line_carrier():
    generic = statement(0, 0, "knowledge/a.html", 69, "NODE generic context")
    identifier = statement(8, 1, "knowledge/a.html", 69, "NODE CQ-KE-002")

    result = prioritize_identifier_rows([generic, identifier],
                                       "What does CQ-KE-002 require?")

    assert result == [identifier, generic]


def test_identifier_priority_leaves_ordinary_questions_unchanged():
    rows = [statement(0, -1, "knowledge/a.html", 69, "NODE generic")]

    assert prioritize_identifier_rows(rows, "What is the generic context?") == rows


def test_identifier_priority_declines_ambiguous_same_locator():
    rows = [
        statement(0, -1, "knowledge/a.html", 69, "NODE CQ-KE-001"),
        statement(1, -1, "knowledge/a.html", 69, "NODE CQ-KE-002"),
    ]

    assert prioritize_identifier_rows(rows, "Compare CQ-KE-001 and CQ-KE-002") == rows


def test_identifier_priority_does_not_cross_source_or_line():
    rows = [
        statement(0, -1, "knowledge/a.html", 69, "NODE generic"),
        statement(1, -1, "knowledge/b.html", 69, "NODE CQ-KE-002"),
    ]

    assert prioritize_identifier_rows(rows, "What does CQ-KE-002 require?") == rows


def test_identifier_priority_declines_oversized_locator_context():
    rows = [
        statement(0, -1, "knowledge/a.html", 69, "NODE CQ-KE-002"),
        *[
            statement(index, -1, "knowledge/a.html", 69, "NODE context " + ("x" * 200))
            for index in range(1, 9)
        ],
    ]

    assert prioritize_identifier_rows(rows, "What does CQ-KE-002 require?") == rows
