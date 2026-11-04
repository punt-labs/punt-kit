"""The run-time ``__version__`` check on a built wheel (Phase 3)."""

from __future__ import annotations

import base64
import hashlib
import subprocess
import zipfile
from typing import TYPE_CHECKING

import pytest

from punt_kit.detect import ProjectInfo, detect
from punt_kit.phases.phase03_build import Phase3Build
from punt_kit.phases.shared import timeouts
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.wheel_version import WheelVersionCheck
from tests.harness.fault_ops import CompletedProcessSpec, FaultRule
from tests.helpers import fault_ops, flat

if TYPE_CHECKING:
    from pathlib import Path

_PROBE = ["uv", "run", "--isolated", "--no-project", "--with"]
_RELEASE = "0.2.0"


def _project(tmp_path: Path, init: str, *, pyproject_extra: str = "") -> Path:
    """A src-layout project ``test-pkg`` whose ``__init__.py`` is ``init``."""
    root = tmp_path / "proj"
    package = root / "src" / "test_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(init)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "test-pkg"\nversion = "{_RELEASE}"\n{pyproject_extra}'
    )
    (root / "dist").mkdir()
    return root


def _wheel(dist: Path, files: dict[str, str]) -> Path:
    """Write a minimal, installable ``test-pkg`` wheel holding ``files``."""
    info = f"test_pkg-{_RELEASE}.dist-info"
    contents = {
        **files,
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: test-pkg\nVersion: {_RELEASE}\n"
        ),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ),
    }
    record = [
        f"{name},sha256={_digest(text)},{len(text.encode())}"
        for name, text in contents.items()
    ]
    contents[f"{info}/RECORD"] = "\n".join([*record, f"{info}/RECORD,,"]) + "\n"
    wheel = dist / f"test_pkg-{_RELEASE}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, text in contents.items():
            archive.writestr(name, text)
    return wheel


def _digest(text: str) -> str:
    raw = hashlib.sha256(text.encode()).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _probe_rule(
    *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> FaultRule:
    return FaultRule(
        match=_PROBE,
        response=CompletedProcessSpec(
            returncode=returncode, stdout=stdout, stderr=stderr
        ),
    )


def test_matching_version_passes(tmp_path: Path) -> None:
    root = _project(tmp_path, f'__version__ = "{_RELEASE}"\n')
    _wheel(root / "dist", {"test_pkg/__init__.py": ""})
    rule = _probe_rule(stdout=f"\n{_RELEASE}\n")

    WheelVersionCheck(detect(root), _RELEASE, ops=fault_ops([rule])).verify(
        root / "dist"
    )

    assert rule.consumed == 1


def test_probe_imports_the_module_in_an_isolated_interpreter(tmp_path: Path) -> None:
    root = _project(tmp_path, f'__version__ = "{_RELEASE}"\n')
    wheel = _wheel(root / "dist", {"test_pkg/__init__.py": ""})
    calls: list[tuple[list[str], int]] = []

    def recording_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = timeouts.DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check, capture
        calls.append((cmd, timeout))
        return subprocess.CompletedProcess(cmd, 0, stdout=_RELEASE, stderr="")

    ops = fault_ops(real_run=recording_run, passthrough=[_PROBE])
    WheelVersionCheck(detect(root), _RELEASE, ops=ops).verify(root / "dist")

    [(cmd, timeout)] = calls
    shape = (cmd[: len(_PROBE) + 4], cmd[-1], timeout)
    assert shape == (
        [*_PROBE, str(wheel), "python", "-I", "-c"],
        "test_pkg",
        timeouts.UV,
    )


def test_mismatched_version_fails_naming_both_values_and_the_wheel(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path, f'__version__ = "{_RELEASE}"\n')
    wheel = _wheel(root / "dist", {"test_pkg/__init__.py": ""})
    ops = fault_ops([_probe_rule(stdout="0.1.0\n")])

    with pytest.raises(ReleaseError) as caught:
        WheelVersionCheck(detect(root), _RELEASE, ops=ops).verify(root / "dist")

    assert all(part in str(caught.value) for part in ("0.1.0", _RELEASE, wheel.name))


def test_import_error_fails(tmp_path: Path) -> None:
    root = _project(tmp_path, f'__version__ = "{_RELEASE}"\n')
    _wheel(root / "dist", {"test_pkg/__init__.py": ""})
    ops = fault_ops(
        [_probe_rule(returncode=1, stderr="ModuleNotFoundError: No module named 'x'")]
    )

    with pytest.raises(ReleaseError, match="importing test_pkg"):
        WheelVersionCheck(detect(root), _RELEASE, ops=ops).verify(root / "dist")


def test_no_version_binding_reports_a_skip_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path, '"""No version here."""\n')
    # No rule: a probe would be an unmatched command and fail the test.
    WheelVersionCheck(detect(root), _RELEASE, ops=fault_ops()).verify(root / "dist")

    assert "no __version__ binding" in flat(capsys.readouterr().out)


def test_non_python_project_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "dist").mkdir(parents=True)
    # No rule: a probe would be an unmatched command and fail the test.
    WheelVersionCheck(ProjectInfo(root=root), _RELEASE, ops=fault_ops()).verify(
        root / "dist"
    )


def test_phase3_skips_a_non_python_project(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    # No rule: `uv build` or the probe would be an unmatched command.
    Phase3Build(ProjectInfo(root=root), _RELEASE, dry_run=False, ops=fault_ops()).run()

    assert not (root / "dist").exists()


def test_module_name_comes_from_the_build_backend(tmp_path: Path) -> None:
    root = _project(
        tmp_path,
        '"""Not the shipped module."""\n',
        pyproject_extra='\n[tool.uv.build-backend]\nmodule-name = "other_pkg"\n',
    )
    (root / "src" / "other_pkg").mkdir()
    (root / "src" / "other_pkg" / "__init__.py").write_text(
        f'__version__ = "{_RELEASE}"\n'
    )
    _wheel(root / "dist", {"other_pkg/__init__.py": ""})
    rule = FaultRule(
        match=[*_PROBE],
        response=CompletedProcessSpec(stdout=_RELEASE),
    )
    ops = fault_ops([rule])

    WheelVersionCheck(detect(root), _RELEASE, ops=ops).verify(root / "dist")

    assert rule.consumed == 1


def test_two_packages_without_module_name_fail(tmp_path: Path) -> None:
    root = _project(tmp_path, f'__version__ = "{_RELEASE}"\n')
    (root / "src" / "second").mkdir()
    (root / "src" / "second" / "__init__.py").write_text("")

    with pytest.raises(ReleaseError, match="module-name"):
        WheelVersionCheck(detect(root), _RELEASE, ops=fault_ops()).verify(root / "dist")


def test_no_wheel_in_dist_fails(tmp_path: Path) -> None:
    root = _project(tmp_path, f'__version__ = "{_RELEASE}"\n')

    with pytest.raises(ReleaseError, match="no wheel"):
        WheelVersionCheck(detect(root), _RELEASE, ops=fault_ops()).verify(root / "dist")


def test_a_real_wheel_rebinding_its_version_fails(tmp_path: Path) -> None:
    """The case the syntax tree misses: a ``globals()`` rebind after the literal."""
    init = f'__version__ = "{_RELEASE}"\nglobals()["__version__"] = "0.1.0"\n'
    root = _project(tmp_path, init)
    _wheel(root / "dist", {"test_pkg/__init__.py": init})
    ops = fault_ops(passthrough=[_PROBE])

    with pytest.raises(ReleaseError, match="'0.1.0' at run time"):
        WheelVersionCheck(detect(root), _RELEASE, ops=ops).verify(root / "dist")


def test_a_real_wheel_reporting_the_release_version_passes(tmp_path: Path) -> None:
    init = f'__version__ = "{_RELEASE}"\n'
    root = _project(tmp_path, init)
    _wheel(root / "dist", {"test_pkg/__init__.py": init})

    WheelVersionCheck(
        detect(root), _RELEASE, ops=fault_ops(passthrough=[_PROBE])
    ).verify(root / "dist")
