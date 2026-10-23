"""install.sh's VERSION pin: Phase 2 writes it and Phase 11 reads it by one rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_kit.detect import detect
from punt_kit.phases.phase11_versions import VersionPinChecks
from punt_kit.phases.shared.errors import ReleaseError
from tests.harness.fault_ops import FaultInjectingOps
from tests.helpers import (
    bump,
    commit_all,
    flat,
    make_release_project,
    refuse_run,
)

if TYPE_CHECKING:
    from pathlib import Path

_FORMS = [
    pytest.param('VERSION="0.1.0"\n', 'VERSION="0.2.0"\n', id="double-quoted"),
    pytest.param("VERSION='0.1.0'\n", "VERSION='0.2.0'\n", id="single-quoted"),
    pytest.param("VERSION=0.1.0\n", "VERSION=0.2.0\n", id="unquoted"),
    pytest.param(
        "VERSION=0.1.0; export VERSION\n",
        "VERSION=0.2.0; export VERSION\n",
        id="unquoted-semicolon",
    ),
    pytest.param('  VERSION="0.1.0"\n', '  VERSION="0.2.0"\n', id="indented"),
    pytest.param(
        'readonly VERSION="0.1.0"\n', 'readonly VERSION="0.2.0"\n', id="readonly"
    ),
    pytest.param('local VERSION="0.1.0"\n', 'local VERSION="0.2.0"\n', id="local"),
    pytest.param(
        'declare VERSION="0.1.0"\n', 'declare VERSION="0.2.0"\n', id="declare"
    ),
    pytest.param(
        'readonly -r VERSION="0.1.0"\n',
        'readonly -r VERSION="0.2.0"\n',
        id="readonly-flag",
    ),
    pytest.param("VERSION='$0.1.0'\n", "VERSION='0.2.0'\n", id="single-quoted-dollar"),
    pytest.param(
        'typeset VERSION="0.1.0"\n', 'typeset VERSION="0.2.0"\n', id="typeset"
    ),
    pytest.param(
        'typeset -r VERSION="0.1.0"\n',
        'typeset -r VERSION="0.2.0"\n',
        id="typeset-flag",
    ),
    pytest.param(
        'VERSION="0.1.0"; export VERSION\n',
        'VERSION="0.2.0"; export VERSION\n',
        id="semicolon-after",
    ),
    pytest.param(
        'VERSION="0.1.0" # pinned\n',
        'VERSION="0.2.0" # pinned\n',
        id="comment-after",
    ),
    pytest.param(
        'VERSION="0.1.0"  \n', 'VERSION="0.2.0"  \n', id="trailing-whitespace"
    ),
    pytest.param(
        'FOO_VERSION="9.9.9"\nVERSION="0.1.0"\n',
        'FOO_VERSION="9.9.9"\nVERSION="0.2.0"\n',
        id="earlier-look-alike",
    ),
]


@pytest.mark.parametrize(("before", "after"), _FORMS)
def test_phase2_rewrites_every_form_of_the_install_sh_pin(
    tmp_path: Path, before: str, after: str
) -> None:
    root = make_release_project(tmp_path)
    (root / "install.sh").write_text(f"#!/bin/sh\n{before}")
    commit_all(root, "install.sh form")

    bump(root)

    assert (root / "install.sh").read_text() == f"#!/bin/sh\n{after}"


_DYNAMIC = [
    pytest.param("VERSION=$(git describe)\n", id="unquoted-command"),
    pytest.param('VERSION="${VERSION:-0.1.0}"\n', id="default-expansion"),
    pytest.param('VERSION="$(git describe)"\n', id="quoted-command"),
    pytest.param('VERSION="`git describe`"\n', id="backtick"),
    pytest.param('local VERSION="$V"\n', id="local-variable"),
    pytest.param('VERSION="1.0"$SUFFIX\n', id="quoted-then-variable"),
    pytest.param("VERSION='1'\"$x\"\n", id="single-then-double-quoted"),
    pytest.param('typeset VERSION="$(git describe)"\n', id="typeset-computed"),
    pytest.param('VERSION="1.0"#x\n', id="hash-glued-to-the-quote"),
]


@pytest.mark.parametrize("line", _DYNAMIC)
def test_phase2_fails_when_the_install_sh_version_cannot_be_rewritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str
) -> None:
    root = make_release_project(tmp_path)
    (root / "install.sh").write_text(f"#!/bin/sh\n{line}")
    commit_all(root, "computed install.sh version")

    with pytest.raises(ReleaseError, match=r"install\.sh.*VERSION") as caught:
        bump(root)

    assert line.strip() in str(caught.value)
    assert (root / "install.sh").read_text() == f"#!/bin/sh\n{line}"

    assert "✓ install.sh" not in capsys.readouterr().out


def test_phase2_warns_naming_every_assignment_when_there_are_several(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_release_project(tmp_path)
    (root / "install.sh").write_text(
        '#!/bin/sh\nVERSION="0.1.0"\nVERSION="$(git describe)"\n'
    )
    commit_all(root, "later computed")

    bump(root)

    assert (root / "install.sh").read_text() == (
        '#!/bin/sh\nVERSION="0.2.0"\nVERSION="$(git describe)"\n'
    )
    out = flat(capsys.readouterr().out)
    assert 'VERSION="0.1.0"' in out
    assert 'VERSION="$(git describe)"' in out
    assert "assigned on 2 lines" in out


def test_phase2_rewrites_a_re_pin_in_an_if_block(tmp_path: Path) -> None:
    root = make_release_project(tmp_path)
    script = '#!/bin/sh\nVERSION="0.1.0"\nif [ -n "$X" ]; then\n  VERSION="0.1.0"\nfi\n'
    (root / "install.sh").write_text(script)
    commit_all(root, "re-pin")

    bump(root)

    assert (root / "install.sh").read_text() == script.replace("0.1.0", "0.2.0")


def test_phase2_leaves_a_heredoc_body_alone_and_rewrites_the_real_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_release_project(tmp_path)
    script = '#!/bin/sh\nVERSION="0.1.0"\ncat <<EOF\nVERSION="0.1.0"\nEOF\n'
    (root / "install.sh").write_text(script)
    commit_all(root, "heredoc")

    bump(root)

    assert (root / "install.sh").read_text() == (
        '#!/bin/sh\nVERSION="0.2.0"\ncat <<EOF\nVERSION="0.1.0"\nEOF\n'
    )
    assert "assigned on" not in flat(capsys.readouterr().out)


def test_phase11_ignores_a_stale_line_inside_a_heredoc(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text(
        '#!/bin/sh\nVERSION="0.2.0"\ncat <<EOF\nVERSION="0.1.0"\nEOF\n'
    )

    assert _install_sh_checks(tmp_path) == {"install.sh": (True, "VERSION=0.2.0")}


def test_phase2_does_not_warn_for_a_single_assignment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_release_project(tmp_path)
    (root / "install.sh").write_text('#!/bin/sh\nVERSION="0.1.0"\n')
    commit_all(root, "single")

    bump(root)

    assert "assigned on" not in flat(capsys.readouterr().out)


def test_phase2_does_not_take_a_newline_split_value_for_the_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``VERSION=`` ends at the newline: an empty reset; the next line is no value."""
    root = make_release_project(tmp_path)
    (root / "install.sh").write_text('#!/bin/sh\nVERSION=\n"0.1.0"\n')
    commit_all(root, "split")

    bump(root)

    assert (root / "install.sh").read_text() == '#!/bin/sh\nVERSION=\n"0.1.0"\n'
    assert "nothing to bump" in flat(capsys.readouterr().out)


def test_phase2_ignores_an_install_sh_without_a_version(tmp_path: Path) -> None:
    root = make_release_project(tmp_path)
    (root / "install.sh").write_text('#!/bin/sh\nFOO_VERSION="1"\n')
    commit_all(root, "no VERSION")

    bump(root)

    assert (root / "install.sh").read_text() == '#!/bin/sh\nFOO_VERSION="1"\n'


def _install_sh_checks(root: Path) -> dict[str, tuple[bool, str]]:
    ops = FaultInjectingOps(real_run=refuse_run, rules=[], passthrough=[])
    found = VersionPinChecks(detect(root), "0.2.0", ops=ops).checks()
    return {check.name: (check.passed, check.detail) for check in found}


@pytest.mark.parametrize(("_before", "after"), _FORMS)
def test_phase11_reads_every_form_phase2_writes(
    tmp_path: Path, _before: str, after: str
) -> None:
    (tmp_path / "install.sh").write_text(f"#!/bin/sh\n{after}")

    assert _install_sh_checks(tmp_path) == {"install.sh": (True, "VERSION=0.2.0")}


def test_phase11_does_not_mistake_a_look_alike_for_the_pin(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text('#!/bin/sh\nFOO_VERSION="9.9.9"\n')

    assert _install_sh_checks(tmp_path) == {}


@pytest.mark.parametrize("line", _DYNAMIC)
def test_phase11_reports_an_unreadable_version_as_unverifiable(
    tmp_path: Path, line: str
) -> None:
    (tmp_path / "install.sh").write_text(f"#!/bin/sh\n{line}")

    passed, detail = _install_sh_checks(tmp_path)["install.sh"]

    assert (passed, "assigned but unverifiable" in detail) == (False, True)


def test_phase11_fails_when_a_later_plain_assignment_is_stale(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text(
        '#!/bin/sh\nVERSION="0.2.0"\nif x; then\n  VERSION="0.1.0"\nfi\n'
    )

    passed, detail = _install_sh_checks(tmp_path)["install.sh"]

    assert (passed, "0.1.0" in detail) == (False, True)


def test_phase2_leaves_an_empty_reset_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_release_project(tmp_path)
    script = '#!/bin/sh\nVERSION="0.1.0"\nVERSION=""\n'
    (root / "install.sh").write_text(script)
    commit_all(root, "empty reset")

    bump(root)

    assert (root / "install.sh").read_text() == (
        '#!/bin/sh\nVERSION="0.2.0"\nVERSION=""\n'
    )
    assert '`VERSION=""` (empty reset, left as is)' in flat(capsys.readouterr().out)


def test_phase2_rewrites_a_local_in_a_function_and_marks_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_release_project(tmp_path)
    script = '#!/bin/sh\nVERSION="0.1.0"\nf() {\n  local VERSION="0.1.0"\n}\n'
    (root / "install.sh").write_text(script)
    commit_all(root, "local")

    bump(root)

    assert (root / "install.sh").read_text() == script.replace("0.1.0", "0.2.0")
    assert '`local VERSION="0.1.0"` (local, rewritten)' in flat(capsys.readouterr().out)


def test_phase11_ignores_an_empty_reset(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text('#!/bin/sh\nVERSION="0.2.0"\nVERSION=""\n')

    assert _install_sh_checks(tmp_path) == {"install.sh": (True, "VERSION=0.2.0")}


def test_phase2_warns_and_leaves_a_file_with_only_empty_resets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_release_project(tmp_path)
    script = '#!/bin/sh\nVERSION=""\nVERSION=\n'
    (root / "install.sh").write_text(script)
    commit_all(root, "only resets")

    bump(root)

    assert (root / "install.sh").read_text() == script
    assert "nothing to bump" in flat(capsys.readouterr().out)


def test_phase2_fails_naming_the_computed_line_not_the_leading_reset(
    tmp_path: Path,
) -> None:
    root = make_release_project(tmp_path)
    script = '#!/bin/sh\nVERSION=""\nVERSION="$2"\n'
    (root / "install.sh").write_text(script)
    commit_all(root, "reset then computed")

    with pytest.raises(ReleaseError, match=r"install\.sh.*VERSION") as caught:
        bump(root)

    assert (
        '`VERSION="$2"`' in str(caught.value),
        'VERSION=""' in str(caught.value),
    ) == (
        True,
        False,
    )
    assert (root / "install.sh").read_text() == script


def test_phase11_skips_a_file_of_only_empty_resets(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text('#!/bin/sh\nVERSION=""\n')

    assert _install_sh_checks(tmp_path) == {}


def test_phase11_reports_a_reset_then_computed_version_as_unverifiable(
    tmp_path: Path,
) -> None:
    (tmp_path / "install.sh").write_text('#!/bin/sh\nVERSION=""\nVERSION="$2"\n')

    passed, detail = _install_sh_checks(tmp_path)["install.sh"]

    assert (passed, "assigned but unverifiable" in detail) == (False, True)


def test_phase2_rewrites_a_stale_unquoted_pin_after_a_quoted_one(
    tmp_path: Path,
) -> None:
    root = make_release_project(tmp_path)
    (root / "install.sh").write_text('#!/bin/sh\nVERSION="0.1.0"\nVERSION=0.0.9\n')
    commit_all(root, "unquoted re-pin")

    bump(root)

    assert (root / "install.sh").read_text() == (
        '#!/bin/sh\nVERSION="0.2.0"\nVERSION=0.2.0\n'
    )


def test_phase11_fails_when_a_later_unquoted_pin_is_stale(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text('#!/bin/sh\nVERSION="0.2.0"\nVERSION=0.0.9\n')

    passed, detail = _install_sh_checks(tmp_path)["install.sh"]

    assert (passed, "0.0.9" in detail) == (False, True)


def test_phase11_passes_when_every_plain_assignment_matches(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text(
        '#!/bin/sh\nVERSION="0.2.0"\nif x; then\n  VERSION="0.2.0"\nfi\n'
    )

    assert _install_sh_checks(tmp_path) == {"install.sh": (True, "VERSION=0.2.0")}
