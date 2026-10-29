"""Step paths round-trip through format and parse, reject what the grammar
doesn't allow, and match scopes by whole segments."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from paths import (
    Branch,
    Call,
    Item,
    Name,
    Path,
    format_path,
    is_prefix,
    parse_address,
    parse_path,
    slug,
    workflow_id,
)

names = st.from_regex(r"[a-z][a-z0-9._-]{0,15}", fullmatch=True).map(Name)
calls = st.builds(
    Call, st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,15}", fullmatch=True), st.integers(0, 10**6)
)
branches = st.builds(Branch, st.integers(0, 10**6))
items = st.builds(Item, st.text(max_size=30))
paths = st.lists(st.one_of(names, calls, branches, items), max_size=8).map(tuple)


@given(paths)
def test_given_any_path_when_formatted_and_parsed_then_it_comes_back(path: Path) -> None:
    assert parse_path(format_path(path)) == path


@given(paths)
def test_given_any_path_text_when_parsed_and_formatted_then_the_text_comes_back(path: Path) -> None:
    text = format_path(path)
    assert format_path(parse_path(text)) == text


@given(paths, paths)
def test_given_two_paths_when_joined_then_the_first_is_a_prefix(scope: Path, rest: Path) -> None:
    assert is_prefix(scope, scope + rest)


def test_given_the_vision_examples_when_parsed_then_each_segment_has_its_kind() -> None:
    assert parse_path("review/parallel#0/1/agent#0") == (
        Name("review"),
        Call("parallel", 0),
        Branch(1),
        Call("agent", 0),
    )
    assert parse_path("audit/pipeline#0/item[src/a.ts]/stage#1/agent#0") == (
        Name("audit"),
        Call("pipeline", 0),
        Item("src/a.ts"),
        Call("stage", 1),
        Call("agent", 0),
    )
    assert parse_path("review/security-review") == (Name("review"), Name("security-review"))


def test_given_an_item_key_with_brackets_and_backslashes_then_it_is_escaped() -> None:
    path = (Item("a]b\\c/d"),)
    assert format_path(path) == "item[a\\]b\\\\c/d]"
    assert parse_path("item[a\\]b\\\\c/d]") == path


@pytest.mark.parametrize(
    "text",
    ["Review", "agent#", "agent#01", "#0", "01", "item[open", "review//agent#0", "a b", "@x"],
)
def test_given_text_outside_the_grammar_when_parsed_then_it_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_path(text)


def test_given_addresses_when_parsed_then_the_run_and_path_split_at_the_first_slash() -> None:
    assert parse_address("@last") == ("@last", ())
    assert parse_address("@last:review/plan") == ("@last:review", (Name("plan"),))
    run = "20260930T121500-review-abcd"
    assert parse_address(f"{run}/review/parallel#0/1") == (
        run,
        (Name("review"), Call("parallel", 0), Branch(1)),
    )


def test_given_a_prefix_when_matched_then_whole_segments_count() -> None:
    assert is_prefix(parse_path("implement"), parse_path("implement/agent#2"))
    assert not is_prefix(parse_path("impl"), parse_path("implement/agent#2"))


def test_given_phase_names_when_slugged_then_they_become_names() -> None:
    assert slug("Plan") == "plan"
    assert slug("Security review") == "security-review"
    with pytest.raises(ValueError):
        slug("!!!")


def test_given_a_scope_when_mapped_then_its_workflow_id_is_the_run_and_the_path() -> None:
    scope = parse_path("review/parallel#0/1")
    assert workflow_id("run-1", scope) == "run-1/review/parallel#0/1"
    assert workflow_id("run-1", ()) == "run-1"
