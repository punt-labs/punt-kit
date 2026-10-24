"""Tests for finding here-document bodies in a shell script."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.shell_heredoc import HeredocBodies


def _inside(text: str) -> list[str]:
    """The lines of ``text`` that lie inside a body, by their stripped text."""
    bodies = HeredocBodies(text)
    found: list[str] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if bodies.contains(offset):
            found.append(line.strip())
        offset += len(line)
    return found


@pytest.mark.parametrize("opener", ["<<EOF", "<<-EOF", "<<'EOF'", '<<"EOF"', "<< EOF"])
def test_the_lines_after_an_opener_up_to_the_delimiter_are_the_body(
    opener: str,
) -> None:
    text = f"cat {opener}\nbody\nEOF\nafter\n"

    assert _inside(text) == ["body", "EOF"]


def test_a_script_without_a_heredoc_has_no_body() -> None:
    assert _inside("a=1\nb=2\n") == []


def test_a_body_never_closed_runs_to_the_end() -> None:
    assert _inside("cat <<EOF\none\ntwo\n") == ["one", "two"]


def test_a_dash_opener_strips_leading_tabs_from_the_delimiter() -> None:
    assert _inside("cat <<-EOF\n\tbody\n\t\tEOF\nafter\n") == ["body", "EOF"]


def test_a_plain_opener_needs_the_delimiter_alone_on_its_line() -> None:
    assert _inside("cat <<EOF\n EOF\nEOF \nEOF\nafter\n") == ["EOF", "EOF", "EOF"]


def test_here_strings_comments_and_shifts_open_nothing() -> None:
    text = "cat <<<word\n# cat <<EOF\nn=$((1<<k))\nm=$(( x <<EOF ))\nz\n"

    assert _inside(text) == []


def test_two_openers_on_one_line_are_read_in_order() -> None:
    assert _inside("cat <<A <<B\na\nA\nb\nB\nafter\n") == ["a", "A", "b", "B"]


@pytest.mark.parametrize(
    "opener", ["cat 0<<'EOF'", "cmd 3<<-EOF", "0<<EOF cat", "cat 12<<EOF"]
)
def test_an_explicit_file_descriptor_still_opens_a_body(opener: str) -> None:
    assert _inside(f"{opener}\nbody\nEOF\nafter\n") == ["body", "EOF"]


@pytest.mark.parametrize(
    "line", ["n=$((1<<k))", "(( x << y ))", "n=$[1<<k]", "x=a1<<k"]
)
def test_a_shift_is_not_mistaken_for_a_descriptor_redirection(line: str) -> None:
    assert _inside(f"{line}\nbody\n") == []
