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
        'VERSION="1.0"#x\n',
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
        'typeset -r VERSION="1.0"\n',
    ],
)
def test_a_shell_value_ends_at_whitespace_a_semicolon_a_spaced_hash_or_the_end(
    text: str,
) -> None:
    assert VersionAssignment.in_shell("VERSION").read(text) == "1.0"


def test_every_shell_assignment_is_listed_in_order() -> None:
    text = 'VERSION="1.0"\n  VERSION="$(git describe)"\nFOO="1"\nVERSION="2"\n'

    assert VersionAssignment.in_shell("VERSION").assigned_lines(text) == (
        'VERSION="1.0"',
        'VERSION="$(git describe)"',
        'VERSION="2"',
    )


def test_no_shell_assignment_lists_nothing() -> None:
    assert VersionAssignment.in_shell("VERSION").assigned_lines('FOO="1"\n') == ()


def test_every_plain_shell_assignment_is_rewritten() -> None:
    text = 'VERSION="1"\nif x; then\n  VERSION=\'1\'\nfi\nVERSION="$(f)"\n'

    assert VersionAssignment.in_shell("VERSION").rewritten(text, "2") == (
        'VERSION="2"\nif x; then\n  VERSION=\'2\'\nfi\nVERSION="$(f)"\n',
        2,
    )


def test_a_computed_first_shell_assignment_rewrites_nothing() -> None:
    text = 'VERSION="$(f)"\nVERSION="1"\n'

    assert VersionAssignment.in_shell("VERSION").rewritten(text, "2") == (text, 0)


def test_a_shell_value_never_spans_a_newline() -> None:
    assignment = VersionAssignment.in_shell("VERSION")
    text = 'VERSION=\n"0.1.0"\n'

    assert (assignment.read(text), assignment.rewritten(text, "2")) == (
        "",
        (text, 0),
    )


def test_an_unquoted_shell_literal_is_a_readable_pin() -> None:
    assignment = VersionAssignment.in_shell("VERSION")
    text = "VERSION=0.0.9\n"

    assert (assignment.read(text), assignment.values(text)) == ("0.0.9", ("0.0.9",))


@pytest.mark.parametrize(
    "text",
    [
        "VERSION=0.1$SUFFIX\n",
        'VERSION=0.1"x"\n',
        "VERSION=0.1#x\n",
        "VERSION=$(git describe)\n",
        "VERSION=`git describe`\n",
        "VERSION=0.1\\ 2\n",
    ],
)
def test_a_computed_unquoted_shell_value_is_still_not_plain(text: str) -> None:
    assignment = VersionAssignment.in_shell("VERSION")

    assert (assignment.is_assigned(text), assignment.read(text)) == (True, None)


def test_a_stale_unquoted_pin_after_a_current_quoted_one_is_not_pinned() -> None:
    text = 'VERSION="0.1.0"\nVERSION=0.0.9\n'

    assert VersionAssignment.in_shell("VERSION").is_pinned_to(text, "0.1.0") is False


def test_an_unquoted_pin_is_rewritten_and_stays_unquoted() -> None:
    assignment = VersionAssignment.in_shell("VERSION")
    text = 'VERSION="0.1.0"\nVERSION=0.0.9 # old\n'

    new, count = assignment.rewritten(text, "0.2.0")

    assert (new, count, assignment.is_pinned_to(new, "0.2.0")) == (
        'VERSION="0.2.0"\nVERSION=0.2.0 # old\n',
        2,
        True,
    )


@pytest.mark.parametrize("empty", ['""', "''"])
def test_an_empty_shell_reset_is_never_rewritten(empty: str) -> None:
    assignment = VersionAssignment.in_shell("VERSION")
    text = f'VERSION="0.1.0"\nVERSION={empty}\n'

    assert assignment.rewritten(text, "0.2.0") == (
        f'VERSION="0.2.0"\nVERSION={empty}\n',
        1,
    )


def test_an_empty_shell_reset_is_not_a_value_and_does_not_unpin() -> None:
    assignment = VersionAssignment.in_shell("VERSION")
    text = 'VERSION="0.2.0"\nVERSION=""\n'

    assert (assignment.values(text), assignment.is_pinned_to(text, "0.2.0")) == (
        ("0.2.0",),
        True,
    )


def test_a_file_with_only_empty_resets_is_not_pinned() -> None:
    assert not VersionAssignment.in_shell("VERSION").is_pinned_to('VERSION=""\n', "1")


def test_every_assignment_is_described_with_what_becomes_of_it() -> None:
    text = (
        'VERSION="0.1.0"\n'
        'f() {\n  local VERSION="x"\n  local VERSION=""\n}\n'
        "VERSION=\"$(f)\"\nVERSION=''\n"
    )

    assert VersionAssignment.in_shell("VERSION").described_lines(text) == (
        '`VERSION="0.1.0"` (rewritten)',
        '`local VERSION="x"` (local, rewritten)',
        '`local VERSION=""` (local, empty reset, left as is)',
        '`VERSION="$(f)"` (computed, left as is)',
        "`VERSION=''` (empty reset, left as is)",
    )


@pytest.mark.parametrize(
    "line",
    ["VERSION=\n", "VERSION= \n", "VERSION=; export VERSION\n", "VERSION= # reset\n"],
)
def test_a_bare_valueless_shell_assignment_is_an_empty_reset(line: str) -> None:
    assignment = VersionAssignment.in_shell("VERSION")
    text = f'{line}VERSION="1.0"\n'

    assert (
        assignment.values(text),
        assignment.rewritten(text, "2.0"),
        assignment.is_pinned_to(text, "1.0"),
    ) == (("1.0",), (text.replace("1.0", "2.0"), 1), True)


def test_a_bare_valueless_assignment_is_labelled_an_empty_reset() -> None:
    text = 'VERSION="1.0"\nf() {\n  local VERSION=\n}\nVERSION=#x\n'

    assert VersionAssignment.in_shell("VERSION").described_lines(text) == (
        '`VERSION="1.0"` (rewritten)',
        "`local VERSION=` (local, empty reset, left as is)",
        "`VERSION=#x` (computed, left as is)",
    )


def test_pinned_to_needs_every_plain_assignment_to_match() -> None:
    assignment = VersionAssignment.in_shell("VERSION")

    assert [
        assignment.is_pinned_to(text, "2")
        for text in (
            'VERSION="2"\nVERSION="2"\n',
            'VERSION="2"\nVERSION="1"\n',
            'VERSION="2"\nVERSION="$(f)"\n',
            'VERSION="$(f)"\nVERSION="2"\n',
        )
    ] == [True, False, True, False]
