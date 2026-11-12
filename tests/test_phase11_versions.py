"""Tests for Phase 11's version-in-every-file checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_kit.detect import detect
from punt_kit.phases.phase11_versions import VersionPinChecks
from tests.harness.fault_ops import FaultInjectingOps
from tests.helpers import (
    refuse_run as _unused,
)

if TYPE_CHECKING:
    from pathlib import Path


def _checks(root: Path, version: str) -> dict[str, tuple[bool, str]]:
    ops = FaultInjectingOps(real_run=_unused, rules=[], passthrough=[])
    found = VersionPinChecks(detect(root), version, ops=ops).checks()
    return {check.name: (check.passed, check.detail) for check in found}


def test_a_matching_pyproject_passes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "1.2.3"\n'
    )

    assert _checks(tmp_path, "1.2.3") == {"pyproject.toml": (True, "version=1.2.3")}


def test_a_stale_install_sh_fails(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text('VERSION="1.0.0"\n')

    assert _checks(tmp_path, "1.2.3") == {"install.sh": (False, "VERSION=1.0.0")}


def test_a_tool_table_version_before_project_is_not_the_project_version(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.other]\nversion = "1.2.3"\n\n[project]\nname = "p"\nversion = "0.9.0"\n'
    )

    assert _checks(tmp_path, "1.2.3") == {"pyproject.toml": (False, "version=0.9.0")}


def test_a_pyproject_without_a_project_version_is_not_found(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.other]\nversion = "1.2.3"\n\n[project]\nname = "p"\n'
    )

    assert _checks(tmp_path, "1.2.3") == {
        "pyproject.toml": (False, "version=not found")
    }


def _project_with_deployed_workflow(tmp_path: Path, pin: str) -> None:
    """A punt-named project whose deployed notifier pins its own package to ``pin``."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "punt-thing"\nversion = "1.2.3"\n'
    )
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "notify.yml").write_text(f"- run: uvx --from punt-thing=={pin} thing\n")


def test_a_deployed_workflow_pin_at_the_release_passes(tmp_path: Path) -> None:
    _project_with_deployed_workflow(tmp_path, "1.2.3")

    assert _checks(tmp_path, "1.2.3")[".github/workflows/notify.yml"] == (
        True,
        "punt-thing==1.2.3",
    )


def test_a_deployed_workflow_pin_left_at_the_previous_release_fails(
    tmp_path: Path,
) -> None:
    # The missed-bump case: phase 9 did not advance this deployed pin, so at
    # Phase 11 (post-publish) it still names the prior release. Must fail here
    # rather than passing unnoticed until the next release.
    _project_with_deployed_workflow(tmp_path, "1.1.0")

    assert _checks(tmp_path, "1.2.3")[".github/workflows/notify.yml"] == (
        False,
        "punt-thing==1.1.0",
    )


def test_a_foreign_pin_in_a_deployed_workflow_is_not_checked(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "punt-thing"\nversion = "1.2.3"\n'
    )
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "notify.yml").write_text("- run: uvx --from punt-other==9.9.9 other\n")

    assert ".github/workflows/notify.yml" not in _checks(tmp_path, "1.2.3")
