"""Tests for Phase 11's version-in-every-file checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_kit.detect import detect
from punt_kit.phases.phase11_versions import VersionPinChecks
from tests.harness.fault_ops import FaultInjectingOps

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path


def _checks(root: Path, version: str) -> dict[str, tuple[bool, str]]:
    ops = FaultInjectingOps(real_run=_unused, rules=[], passthrough=[])
    found = VersionPinChecks(detect(root), version, ops=ops).checks()
    return {check.name: (check.passed, check.detail) for check in found}


def _unused(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 0,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    raise AssertionError(f"version checks read files only, not {cmd}")


def test_a_matching_pyproject_passes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\nversion = "1.2.3"\n'
    )

    assert _checks(tmp_path, "1.2.3") == {"pyproject.toml": (True, "version=1.2.3")}


def test_a_stale_install_sh_fails(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text('VERSION="1.0.0"\n')

    assert _checks(tmp_path, "1.2.3") == {"install.sh": (False, "VERSION=1.0.0")}
