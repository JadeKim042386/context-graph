import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from ask import (LABEL_CAP, MIN_STATEMENTS, USAGE, asked_words, build_graphify_command,
                 document_labels,
                 condense_answer, fold_long_label, matching_word_count, stale_documents,
                 statements_carrying_the_words, truncation_notice)


def every_form(words):
    """Flatten the word groups so a test can ask whether a form is in there at all."""
    return {form for forms in words for form in forms}


def an_answer_of(statement_count, label_length=200):
    """Build a query answer the size the real tool returns for a broad question."""
    lines = ["Start: ['seed'] | depth 2"]
    for index in range(statement_count):
        lines.append(f"NODE {'value ' + str(index):.<{label_length}} "
                     f"[src=C:/vault/note.md loc={index + 2}]")
    return "\n".join(lines)


def test_finds_documents_newer_than_the_map(tmp_path):
    source = tmp_path / "docs"; source.mkdir()
    (source / "a.md").write_text("body", encoding="utf-8")
    map_path = tmp_path / "graph.json"
    map_path.write_text("{}", encoding="utf-8")
    assert stale_documents([str(source)], str(map_path)) == []
    time.sleep(0.01)
    (source / "b.md").write_text("new body", encoding="utf-8")
    assert stale_documents([str(source)], str(map_path)) == ["b"]


def test_a_missing_map_counts_everything_as_stale(tmp_path):
    source = tmp_path / "docs"; source.mkdir()
    (source / "a.md").write_text("body", encoding="utf-8")
    assert stale_documents([str(source)], str(tmp_path / "missing.json")) == ["(no map)"]


def test_the_query_command_carries_the_budget(tmp_path):
    command = build_graphify_command("query", ["chunk criterion"], "C:/maps/graph.json", 20000)
    assert command[:2] == ["graphify", "query"]
    assert "--budget" in command and "20000" in command
    assert "--graph" in command and "C:/maps/graph.json" in command


def test_path_finding_does_not_carry_a_budget():
    command = build_graphify_command("path", ["a", "b"], "C:/maps/graph.json", 20000)
    assert command[:2] == ["graphify", "path"]
    assert "--budget" not in command


def test_an_answer_that_fills_the_budget_is_reported():
    truncated_answer = "... budget 20000 tokens, 12 results cut by budget ..."
    assert "Narrow" in truncation_notice(truncated_answer)


def test_a_short_answer_gets_no_notice():
    assert truncation_notice("The median is 1.19 m (a.md:8)") == ""


def test_the_usage_text_tells_you_to_ask_narrowly():
    assert "narrowly" in USAGE


RAW_ANSWER = """Traversal: BFS depth=2 | Start: ['Median 1.19 m.'] | 3 nodes found

NODE Tray Facts [src=facts/Tray.md loc=1 community=]
NODE Piece size: median 1.19 m. [src=facts/Tray.md loc=192 community=]
NODE Central Index [src= loc=None community=]
EDGE Piece size: median 1.19 m. --part_of []--> Tray Facts
"""


def test_the_answer_keeps_the_statement_with_its_line():
    condensed = condense_answer(RAW_ANSWER)
    assert "NODE Piece size: median 1.19 m." in condensed
    assert "[src=facts/Tray.md loc=192]" in condensed


def test_the_answer_drops_edges_and_nodes_with_no_location():
    condensed = condense_answer(RAW_ANSWER)
    assert "EDGE" not in condensed
    assert "Central Index" not in condensed
    assert "Traversal:" not in condensed


def test_the_documents_are_named_once_at_the_end():
    assert condense_answer(RAW_ANSWER).endswith("[also touched: Tray Facts]")


def test_an_unrecognised_answer_is_shown_as_it_came():
    assert condense_answer("graphify: no results") == "graphify: no results"


def test_the_matched_statement_comes_first():
    raw = ("Traversal: BFS depth=2 | Start: ['Piece size: median 1.19 m.'] | 2 nodes found\n"
           "NODE A neighbour statement. [src=facts/Tray.md loc=8 community=]\n"
           "NODE Piece size: median 1.19 m. [src=facts/Tray.md loc=192 community=]\n")
    assert condense_answer(raw).startswith("NODE Piece size: median 1.19 m.")


def test_the_document_tail_names_only_a_few():
    raw = "".join(f"NODE Doc {i} [src=d{i}.md loc=1 community=]\n" for i in range(7))
    raw += "NODE A statement. [src=d0.md loc=4 community=]\n"
    tail = condense_answer(raw).splitlines()[-1]
    assert tail.endswith("and 3 more]")


def test_the_answer_stays_inside_the_character_budget():
    """The point of asking is to spend less than opening the document, so the cap is characters."""
    raw = an_answer_of(400)
    assert len(condense_answer(raw)) > 40000            # without a budget it runs to the full size
    condensed = condense_answer(raw, budget=4000)
    assert len(condensed) <= 4000


def test_what_was_left_out_is_counted():
    """A narrowed answer must never read as a complete one."""
    condensed = condense_answer(an_answer_of(400), budget=4000)
    assert "further statement(s) left out" in condensed
    assert "narrow the words" in condensed


def test_a_small_answer_is_untouched_by_the_budget():
    raw = an_answer_of(3)
    assert condense_answer(raw, budget=20000) == condense_answer(raw)
    assert "left out" not in condense_answer(raw, budget=20000)


def test_one_statement_still_comes_back_when_it_alone_fills_the_budget():
    """Returning nothing would be worse than going over: the first statement always survives."""
    condensed = condense_answer(an_answer_of(1, label_length=5000), budget=1000)
    assert "NODE" in condensed


def test_a_paragraph_written_as_one_line_is_folded_not_printed_whole():
    """One physical line becomes one statement, so a whole paragraph can arrive as one label."""
    label = "opening words " + "x" * 9000
    folded = fold_long_label(label, "C:/vault/note.md", 147)
    assert folded.startswith("opening words")
    assert len(folded) < len(label)
    assert "C:/vault/note.md:147" in folded


def test_a_label_that_fits_is_left_exactly_as_it_is():
    label = "tray width is 0.66 m"
    assert fold_long_label(label, "C:/vault/note.md", 4) == label
    assert fold_long_label("y" * LABEL_CAP, "C:/vault/note.md", 4) == "y" * LABEL_CAP


RAW_WITH_A_HEADING_AND_A_VALUE = """Start: ['Bending radius'] | depth 2
NODE Bending radius [src=C:/vault/cable.md loc=48]
NODE Sizing workflow and routing coupling [src=C:/vault/cable.md loc=64]
NODE Voltage drop [src=C:/vault/cable.md loc=36]
NODE [value] Minimum bend radius is 12 x D for MV power cable [src=C:/vault/cable.md loc=49]
"""


def test_the_statement_carrying_the_asked_words_comes_before_unrelated_headings():
    """Walk order puts a heading before the line under it, so the value can sit far down."""
    condensed = condense_answer(RAW_WITH_A_HEADING_AND_A_VALUE, question="bend radius")
    lines = [line for line in condensed.splitlines() if line.startswith("NODE ")]
    assert "12 x D" in lines[1]                      # right after the seed heading itself
    assert "Voltage drop" in lines[-1] or "Sizing workflow" in lines[-1]


def test_without_a_question_the_walk_order_is_left_alone():
    condensed = condense_answer(RAW_WITH_A_HEADING_AND_A_VALUE)
    lines = [line for line in condensed.splitlines() if line.startswith("NODE ")]
    assert "Sizing workflow" in lines[1]


def test_common_words_are_not_counted_as_a_match():
    assert every_form(asked_words("how many cables are in the WHRP dataset")) == {
        "cables", "whrp", "dataset"}
    assert asked_words("") == set()


def test_the_document_tail_and_the_notice_count_against_the_budget():
    """The tail has no length limit of its own, so guessing at it lets the cap slip."""
    long_names = "\n".join(
        f"NODE {'ADR 00' + str(index) + ' ' + 'a very long decision title ' * 4} "
        f"[src=C:/vault/adr{index}.md loc=1]" for index in range(6))
    raw = an_answer_of(300) + "\n" + long_names
    condensed = condense_answer(raw, budget=20000)
    assert "also touched" in condensed and "left out" in condensed
    assert len(condensed) <= 20000


def test_a_capital_single_letter_is_part_of_the_question():
    assert every_form(asked_words("role letters S T V E meaning")) >= {"s", "t", "v", "e"}
    assert "a" not in every_form(asked_words("a value for the tray"))


def test_a_korean_word_matches_with_its_particle_taken_off():
    assert "케이블" in every_form(asked_words("케이블은 어디에 있나"))
    assert "트레이" in every_form(asked_words("트레이의 폭"))


def test_a_single_letter_has_to_stand_as_a_word_of_its_own():
    """Counting `s` inside "statements" would make every English sentence a match."""
    words = asked_words("role letters S T V E meaning")
    assert matching_word_count("Voltage drop", words) == 0
    assert matching_word_count("role S means the plant is split", words) >= 2


def test_a_thin_answer_keeps_the_statement_that_carried_the_words():
    """The walk puts seed labels first, so taking the head can drop the only real answer."""
    seeds = "Start: [" + ", ".join(f"'heading {index}'" for index in range(9)) + "] | depth 2"
    lines = [seeds]
    for index in range(9):
        lines.append(f"NODE heading {index} [src=C:/vault/a.md loc={index + 2}]")
    lines.append("NODE the tray width is 0.66 m [src=C:/vault/b.md loc=400]")
    condensed = condense_answer("\n".join(lines), question="tray width")
    assert "0.66 m" in condensed


def test_the_map_is_read_for_the_words_the_walk_may_have_missed(tmp_path):
    """A statement can hold the answer and never be visited, so the map is read for it too."""
    map_path = tmp_path / "graph.json"
    map_path.write_text(json.dumps({"nodes": [
        {"id": "t1", "kind": "statement", "label": "the tray width is 0.66 m",
         "source_file": "C:/vault/a.md", "source_location": 12},
        {"id": "t2", "kind": "statement", "label": "unrelated line",
         "source_file": "C:/vault/a.md", "source_location": 13},
        {"id": "d1", "kind": "document", "label": "a", "source_file": "C:/vault/a.md",
         "source_location": 1},
    ]}, ensure_ascii=False), encoding="utf-8")
    found = statements_carrying_the_words(str(map_path),
                                         {frozenset({"tray"}), frozenset({"width"})})
    assert [row[2] for row in found] == ["the tray width is 0.66 m"]
    assert statements_carrying_the_words(str(tmp_path / "missing.json"),
                                        {frozenset({"tray"})}) == []


def test_what_the_map_found_is_merged_into_the_answer_without_repeating_it():
    raw = "Start: ['seed'] | depth 2\nNODE seed line [src=C:/vault/a.md loc=5]"
    direct = [(-2, 24, "the tray width is 0.66 m", "C:/vault/a.md", 12),
              (-2, 11, "seed line", "C:/vault/a.md", 5)]
    condensed = condense_answer(raw, question="tray width", direct=direct)
    assert "0.66 m" in condensed
    assert condensed.count("seed line") == 1


def test_an_answer_nobody_recognised_is_still_capped():
    """If the tool ever changes its output shape, this is the path every answer takes."""
    unrecognised = "some other shape entirely\n" * 4000
    assert len(unrecognised) > 60000
    capped = condense_answer(unrecognised, budget=2000)
    assert len(capped) <= 2000
    assert "not in the expected shape" in capped


def test_a_short_unrecognised_answer_is_shown_as_it_came():
    assert condense_answer("odd but short", budget=2000) == "odd but short"


def test_a_single_korean_syllable_is_a_whole_word():
    """Hangul has no capitals, so the rule that saves S and T would throw 폭 and 값 away."""
    assert "폭" in every_form(asked_words("트레이 폭 기준"))
    assert matching_word_count("트레이 폭은 0.66 m", {frozenset({"폭"})}) == 1


def test_a_korean_word_is_counted_once_however_it_was_written():
    """Both forms of one word live in one group, and a group counts once.

    Counting them as separate words put a statement holding no value ("트레이 목록과 배치",
    which carries both 트레 and 트레이) above one that did ("폭은 0.66 m").
    """
    words = asked_words("트레이 폭")
    assert matching_word_count("트레이 목록과 배치", words) == 1
    assert matching_word_count("트레이 폭은 0.66 m", words) == 2


def test_a_particle_is_only_taken_off_when_two_syllables_are_left():
    """The letters a particle is written with end plenty of ordinary words too.

    Trimming 결과 to 결 or 경로 to 경 leaves a syllable that matches half the vocabulary -
    measured against the vault, trimming down to one syllable mangles 1,512 of its 4,085
    Korean words. Two syllables have to survive for the trim to be safe.
    """
    assert every_form(asked_words("결과")) == {"결과"}
    assert every_form(asked_words("경로")) == {"경로"}
    assert every_form(asked_words("추가")) == {"추가"}
    assert "사용자" in every_form(asked_words("사용자가"))


def test_the_cap_holds_even_when_it_is_smaller_than_the_notice():
    """A budget too small to hold the explanation still caps the answer."""
    assert len(condense_answer("y" * 5000, budget=100)) <= 100
    assert len(condense_answer("y" * 5000, budget=20)) <= 20


def test_the_cap_holds_when_the_tail_and_the_first_statement_would_burst_it():
    """The first statement is kept whatever its size and the document tail is not trimmed."""
    lines = ["Start: ['a'] | depth 2"]
    lines += [f"NODE statement {index} carrying the word tray [src=C:/vault/note{index}.md "
              f"loc={index + 2}]" for index in range(5)]
    lines += [f"NODE a rather long document name number {index} [src=C:/vault/note{index}.md "
              f"loc=1]" for index in range(5)]
    raw = "\n".join(lines)
    for budget in (20, 300, 900):
        assert len(condense_answer(raw, budget=budget, question="tray")) <= budget


def test_the_walk_budget_does_not_follow_the_answer_budget():
    """Tying them together cut statements upstream before the ranking here could see them."""
    command = build_graphify_command("query", ["tray width"], "C:/maps/graph.json", 500)
    assert "500" not in command
    assert "--budget" in command


def test_the_map_says_which_labels_are_documents(tmp_path):
    """A document written on one line has every statement at line 1, and the guess threw
    all of them away."""
    map_path = tmp_path / "graph.json"
    map_path.write_text(json.dumps({"nodes": [
        {"id": "d1", "kind": "document", "label": "report",
         "source_file": "C:/vault/report.html", "source_location": 1},
        {"id": "t1", "kind": "statement", "label": "the tray width is 0.66 m",
         "source_file": "C:/vault/report.html", "source_location": 1},
    ]}, ensure_ascii=False), encoding="utf-8")
    named = document_labels(str(map_path))
    assert named == {"report"}

    raw = ("Start: ['x'] | depth 2\n"
           "NODE report [src=C:/vault/report.html loc=1]\n"
           "NODE the tray width is 0.66 m [src=C:/vault/report.html loc=1]")
    kept = condense_answer(raw, question="tray width", documents_named=named)
    assert "0.66 m" in kept                        # the statement survives its line number
    assert "also touched: report" in kept          # and the document is still named as one


def test_without_the_map_the_line_number_is_still_used():
    raw = ("Start: ['x'] | depth 2\n"
           "NODE report [src=C:/vault/report.md loc=1]\n"
           "NODE the tray width is 0.66 m [src=C:/vault/report.md loc=8]")
    kept = condense_answer(raw, question="tray width")
    assert "0.66 m" in kept
    assert "also touched: report" in kept


def test_one_word_written_two_ways_is_still_one_word():
    """Sets stopped a word counting twice; sets that overlap brought it straight back.

    "트레이는 ... 트레이의" built two sets, both carrying 트레이, so a statement with the noun
    and no value scored above one with the value - the inversion the sets were built against.
    """
    words = asked_words("트레이는 어디에 있고 트레이의 폭은")
    assert matching_word_count("트레이 목록과 배치", words) == 1
    assert matching_word_count("폭은 0.66 m", words) == 1


def test_a_single_syllable_stem_reaches_the_note_that_drops_the_particle():
    """폭은 has no two-syllable stem to fall back on, so the bare syllable joins its set."""
    assert matching_word_count("트레이 폭: 0.66 m", asked_words("폭은 얼마인가")) == 1
    assert matching_word_count("값이 다르다", asked_words("값을 알려줘")) == 1


def test_only_four_particles_may_leave_one_syllable_behind():
    """The other particle letters end ordinary nouns, and 결 would match half the vocabulary."""
    for word in ("결과", "경로", "추가", "정도"):
        assert every_form(asked_words(word)) == {word}


def test_a_statement_is_not_cut_in_the_middle_without_saying_so():
    """A value usually sits at the end of a line, so a silent mid-line cut loses it."""
    raw = ("Start: ['x'] | depth 2\nNODE the tray width "
           + "and more words " * 10 + "0.66 m [src=C:/vault/a.md loc=12]")
    cut = condense_answer(raw, budget=100, question="tray width")
    assert len(cut) <= 100
    assert "cut mid-statement" in cut
    for budget in (20, 40):
        assert len(condense_answer(raw, budget=budget, question="tray width")) <= budget


def test_the_walk_is_never_narrower_than_what_will_be_printed():
    """Raising answer_budget past the fixed walk budget used to buy nothing."""
    wide = build_graphify_command("query", ["tray width"], "C:/maps/graph.json", 90000)
    assert "90000" in wide
    narrow = build_graphify_command("query", ["tray width"], "C:/maps/graph.json", 500)
    assert "500" not in narrow
