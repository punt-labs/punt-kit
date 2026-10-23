"""install.sh's VERSION pin: Phase 2 writes it and Phase 11 reads it by one rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_kit.detect import detect
from punt_kit.phases.phase11_versions import VersionPinChecks
from punt_kit.release import ReleaseError
from tests.harness.fault_ops import FaultInjectingOps
from tests.test_phase11_versions import _unused  # pyright: ignore[reportPrivateUsage]
from tests.test_release import (
    _bump,  # pyright: ignore[reportPrivateUsage]
    _commit_all,  # pyright: ignore[reportPrivateUsage]
    _make_release_project,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from pathlib import Path

_FORMS = [
    pytest.param('VERSION="0.1.0"\n', 'VERSION="0.2.0"\n', id="double-quoted"),
    pytest.param("VERSION='0.1.0'\n", "VERSION='0.2.0'\n", id="single-quoted"),
    pytest.param('  VERSION="0.1.0"\n', '  VERSION="0.2.0"\n', id="indented"),
    pytest.param(
        'readonly VERSION="0.1.0"\n', 'readonly VERSION="0.2.0"\n', id="readonly"
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
    root = _make_release_project(tmp_path)
    (root / "install.sh").write_text(f"#!/bin/sh\n{before}")
    _commit_all(root, "install.sh form")

    _bump(root)

    assert (root / "install.sh").read_text() == f"#!/bin/sh\n{after}"


def test_phase2_fails_when_the_install_sh_version_cannot_be_rewritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_release_project(tmp_path)
    (root / "install.sh").write_text("#!/bin/sh\nVERSION=$(git describe)\n")
    _commit_all(root, "computed install.sh version")

    with pytest.raises(ReleaseError, match=r"install\.sh.*VERSION"):
        _bump(root)

    assert "✓ install.sh" not in capsys.readouterr().out


def test_phase2_ignores_an_install_sh_without_a_version(tmp_path: Path) -> None:
    root = _make_release_project(tmp_path)
    (root / "install.sh").write_text('#!/bin/sh\nFOO_VERSION="1"\n')
    _commit_all(root, "no VERSION")

    _bump(root)

    assert (root / "install.sh").read_text() == '#!/bin/sh\nFOO_VERSION="1"\n'


def _install_sh_checks(root: Path) -> dict[str, tuple[bool, str]]:
    ops = FaultInjectingOps(real_run=_unused, rules=[], passthrough=[])
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


def test_phase11_reports_an_unreadable_version_as_unverifiable(
    tmp_path: Path,
) -> None:
    (tmp_path / "install.sh").write_text("#!/bin/sh\nVERSION=$(git describe)\n")

    passed, detail = _install_sh_checks(tmp_path)["install.sh"]

    assert (passed, "assigned but unverifiable" in detail) == (False, True)
