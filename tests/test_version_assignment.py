"""Tests for the one rule for a quoted version assignment."""

from __future__ import annotations

import pytest

from punt_kit.phases.shared.version_assignment import VersionAssignment


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ('version = "1.2.3"\n', "1.2.3"),
        ("version = '1.2.3'\n", "1.2.3"),
        ('__version__: str = "1.2.3"\n', "1.2.3"),
        ('[project]\nname = "x"\nversion="1.2.3"\n', "1.2.3"),
    ],
)
def test_reads_a_quoted_assignment(text: str, value: str) -> None:
    name = "__version__" if "__version__" in text else "version"

    assert VersionAssignment(name).read(text) == value


@pytest.mark.parametrize(
    "text",
    [
        "version = compute()\n",
        'project = {version = "1.2.3"}\n',
        '    version = "1.2.3"\n',
        'target-version = "py313"\n',
    ],
)
def test_does_not_read_what_is_not_a_line_start_quoted_assignment(text: str) -> None:
    assert VersionAssignment("version").read(text) is None


def test_a_computed_value_is_assigned_but_not_readable() -> None:
    assignment = VersionAssignment("__version__")
    text = "__version__ = compute()\n"

    assert (assignment.is_assigned(text), assignment.read(text)) == (True, None)


def test_rewriting_keeps_the_quote_style_and_reports_the_count() -> None:
    assignment = VersionAssignment("version")

    assert assignment.rewritten("version = '1'\n", "2") == ("version = '2'\n", 1)
    assert assignment.rewritten("version = f()\n", "2") == ("version = f()\n", 0)


@pytest.mark.parametrize(
    "text",
    [
        'VERSION="1.0"$SUFFIX\n',
        "VERSION='1'\"$x\"\n",
        'VERSION="1.0"suffix\n',
        'typeset VERSION="1.0"$S\n',
    ],
)
def test_a_shell_value_continued_after_its_quote_is_assigned_but_not_plain(
    text: str,
) -> None:
    assignment = VersionAssignment.in_shell("VERSION")

    assert (assignment.is_assigned(text), assignment.read(text)) == (True, None)


@pytest.mark.parametrize(
    "text",
    [
        'VERSION="1.0"\n',
        'VERSION="1.0"',
        'VERSION="1.0" # note\n',
        'VERSION="1.0"; export VERSION\n',
        'VERSION="1.0"#note\n',
        'typeset -r VERSION="1.0"\n',
    ],
)
def test_a_shell_value_ends_at_whitespace_a_semicolon_a_hash_or_the_end(
    text: str,
) -> None:
    assert VersionAssignment.in_shell("VERSION").read(text) == "1.0"


def test_a_later_computed_shell_assignment_is_named() -> None:
    text = 'VERSION="1.0"\n  VERSION="$(git describe)"\nVERSION="2"\n'

    assert (
        VersionAssignment.in_shell("VERSION").later_computed_line(text)
        == 'VERSION="$(git describe)"'
    )


@pytest.mark.parametrize(
    "text",
    ['VERSION="1.0"\n', 'VERSION="1.0"\nVERSION="2.0"\n', 'FOO="1"\nVERSION="1"\n'],
)
def test_no_later_computed_line_when_every_assignment_is_plain(text: str) -> None:
    assert VersionAssignment.in_shell("VERSION").later_computed_line(text) == ""
