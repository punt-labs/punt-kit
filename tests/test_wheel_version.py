"""The run-time ``__version__`` check on a built wheel (Phase 3)."""

from __future__ import annotations

import base64
import hashlib
import subprocess
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_kit.detect import ProjectInfo, detect
from punt_kit.phases.phase03_build import Phase3Build
from punt_kit.phases.shared import timeouts
from punt_kit.phases.shared.command_runner import CommandRunner
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.skips import SkipRecorder
from punt_kit.phases.shared.wheel_version import WheelVersionCheck
from tests.harness.fault_ops import CompletedProcessSpec, FaultRule
from tests.helpers import fault_ops, flat

if TYPE_CHECKING:
    from tests.harness.fault_ops import FaultInjectingOps

_PROBE = ["uv", "run", "--isolated", "--no-project", "--with"]
_RELEASE = "1.0.0"
_ABSENT = "\n\x00PUNT_VERSION absent\n"


@pytest.fixture
def skips() -> SkipRecorder:
    return SkipRecorder(ops=fault_ops())


def _project(
    tmp_path: Path,
    init: str,
    *,
    pyproject_extra: str = "",
    name: str = "test-pkg",
) -> Path:
    """A src-layout project ``name`` with ``src/test_pkg/__init__.py`` = ``init``."""
    root = tmp_path / "proj"
    package = root / "src" / "test_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(init)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{_RELEASE}"\n{pyproject_extra}'
    )
    (root / "dist").mkdir()
    return root


def _flat_project(tmp_path: Path, name: str, packages: tuple[str, ...]) -> Path:
    """A flat-layout project ``name``: ``packages`` at the repo root, no ``src``."""
    root = tmp_path / "flat"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{_RELEASE}"\n'
    )
    _layout(root, packages)
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


def _record(value: object) -> str:
    """The probe's output for a module whose ``__version__`` is ``value``."""
    return f"\n\x00PUNT_VERSION={ascii(value)}\n"


def _probe_rule(
    *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> FaultRule:
    return FaultRule(
        match=_PROBE,
        response=CompletedProcessSpec(
            returncode=returncode, stdout=stdout, stderr=stderr
        ),
    )


def _check(
    root: Path,
    ops: FaultInjectingOps,
    skips: SkipRecorder,
    *,
    version: str = _RELEASE,
) -> WheelVersionCheck:
    return WheelVersionCheck(detect(root), version, ops=ops, skips=skips)


def _built(root: Path) -> Path:
    """``root``'s ``dist/`` with a placeholder wheel, for scripted probes."""
    _wheel(root / "dist", {"test_pkg/__init__.py": ""})
    return root / "dist"


# --- scripted probe ---


def test_matching_version_passes(tmp_path: Path, skips: SkipRecorder) -> None:
    root = _project(tmp_path, "")
    rule = _probe_rule(stdout=_record(_RELEASE))

    _check(root, fault_ops([rule]), skips).verify(_built(root))

    assert rule.consumed == 1


def test_probe_imports_the_module_in_an_isolated_interpreter(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    dist = _built(root)
    seen: list[tuple[list[str], int]] = []

    def run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = timeouts.DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check, capture
        seen.append((cmd, timeout))
        return subprocess.CompletedProcess(cmd, 0, stdout=_record(_RELEASE))

    _check(root, fault_ops(real_run=run, passthrough=[_PROBE]), skips).verify(dist)

    [(cmd, timeout)] = seen
    wheel = str(next(dist.glob("*.whl")))
    shape = (cmd[: len(_PROBE) + 4], cmd[-1], timeout)
    assert shape == ([*_PROBE, wheel, "python", "-I", "-c"], "test_pkg", timeouts.UV)


def test_pep440_equal_versions_pass(tmp_path: Path, skips: SkipRecorder) -> None:
    root = _project(tmp_path, "")
    rule = _probe_rule(stdout=_record("1.0.0rc1"))

    _check(root, fault_ops([rule]), skips, version="1.0.0-rc1").verify(_built(root))

    assert rule.consumed == 1


def test_mismatched_version_fails_naming_both_values_and_the_wheel(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    dist = _built(root)
    ops = fault_ops([_probe_rule(stdout=_record("0.0.1"))])

    with pytest.raises(ReleaseError) as caught:
        _check(root, ops, skips).verify(dist)

    wheel = next(dist.glob("*.whl")).name
    assert all(part in str(caught.value) for part in ("0.0.1", _RELEASE, wheel))


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param(_record("stale\n1.0.0"), id="embedded-newline"),
        pytest.param(_record("1.0.0 "), id="trailing-space"),
        pytest.param(_record(" 1.0.0"), id="leading-space"),
        pytest.param(_record("not-a-version"), id="not-pep440"),
    ],
)
def test_a_value_that_is_not_exactly_a_version_fails(
    tmp_path: Path, skips: SkipRecorder, stdout: str
) -> None:
    root = _project(tmp_path, "")
    ops = fault_ops([_probe_rule(stdout=stdout)])

    with pytest.raises(ReleaseError, match="not a PEP 440 version"):
        _check(root, ops, skips).verify(_built(root))


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param(_record(100), id="int"),
        pytest.param(_record((1, 0, 0)), id="tuple"),
        pytest.param("\n\x00PUNT_VERSION=<Version('1.0.0')>\n", id="no-literal"),
    ],
)
def test_a_value_that_is_not_a_string_fails(
    tmp_path: Path, skips: SkipRecorder, stdout: str
) -> None:
    root = _project(tmp_path, "")
    ops = fault_ops([_probe_rule(stdout=stdout)])

    with pytest.raises(ReleaseError, match="not a string"):
        _check(root, ops, skips).verify(_built(root))


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param("1.0.0\n", id="none"),
        pytest.param(_record(_RELEASE) + _record(_RELEASE), id="two"),
        pytest.param(_record(_RELEASE) + _ABSENT, id="value-and-absent"),
    ],
)
def test_anything_but_exactly_one_record_fails(
    tmp_path: Path, skips: SkipRecorder, stdout: str
) -> None:
    root = _project(tmp_path, "")
    ops = fault_ops([_probe_rule(stdout=stdout)])

    with pytest.raises(ReleaseError, match="expected exactly 1"):
        _check(root, ops, skips).verify(_built(root))


def test_import_error_fails(tmp_path: Path, skips: SkipRecorder) -> None:
    root = _project(tmp_path, "")
    stderr = "ModuleNotFoundError: No module named 'x'"
    ops = fault_ops([_probe_rule(returncode=1, stderr=stderr)])

    with pytest.raises(ReleaseError, match="importing test_pkg"):
        _check(root, ops, skips).verify(_built(root))


def test_no_version_at_run_time_records_a_skip(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    ops = fault_ops([_probe_rule(stdout=_ABSENT)])

    _check(root, ops, skips).verify(_built(root))

    assert any("no __version__ at run time" in note for note in skips.drain())


def test_a_module_without_init_in_the_source_tree_is_still_imported(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    extra = '\n[tool.uv.build-backend]\nmodule-name = "ghost"\n'
    root = _project(tmp_path, "", pyproject_extra=extra)
    rule = _probe_rule(stdout=_record(_RELEASE))

    _check(root, fault_ops([rule]), skips).verify(_built(root))

    assert rule.consumed == 1


def test_two_packages_none_named_for_the_project_fail(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "", name="other-name")
    _layout(root, ("src/second",))

    with pytest.raises(ReleaseError, match="2 packages under"):
        _check(root, fault_ops(), skips).module_names()


def test_no_package_anywhere_fails_naming_what_was_searched(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _flat_project(tmp_path, "nothing-here", ())

    with pytest.raises(ReleaseError, match=r"no nothing_here directory.*src"):
        _check(root, fault_ops(), skips).module_names()


def test_no_wheel_in_dist_fails(tmp_path: Path, skips: SkipRecorder) -> None:
    root = _project(tmp_path, "")

    with pytest.raises(ReleaseError, match="no wheel"):
        _check(root, fault_ops(), skips).verify(root / "dist")


# --- which module ---


def _layout(root: Path, packages: tuple[str, ...]) -> None:
    """Create each ``a/b`` package directory under ``root`` with an init."""
    for package in packages:
        path = root.joinpath(*package.split("/"))
        path.mkdir(parents=True, exist_ok=True)
        (path / "__init__.py").write_text("")


@pytest.mark.parametrize(
    ("backend", "packages", "expected"),
    [
        pytest.param("", (), ("test_pkg",), id="single-package"),
        pytest.param(
            'module-name = ["test_pkg", "extra"]',
            (),
            ("test_pkg", "extra"),
            id="list",
        ),
        pytest.param('module-name = "ns.inner"', (), ("ns.inner",), id="dotted"),
        pytest.param('module-root = "lib"', ("lib/libpkg",), ("libpkg",), id="root"),
        pytest.param('module-root = ""', ("flat",), ("flat",), id="empty-root"),
    ],
)
def test_module_names(
    tmp_path: Path,
    skips: SkipRecorder,
    backend: str,
    packages: tuple[str, ...],
    expected: tuple[str, ...],
) -> None:
    extra = f"\n[tool.uv.build-backend]\n{backend}\n"
    root = _project(tmp_path, "", pyproject_extra=extra)
    _layout(root, packages)

    assert _check(root, fault_ops(), skips).module_names() == expected


def test_uv_default_naming_picks_the_package_named_for_the_project(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "", name="Punt.Kit--Demo")
    _layout(root, ("src/punt_kit_demo", "src/aaa_first"))

    names = _check(root, fault_ops(), skips).module_names()

    assert names == ("punt_kit_demo",)


@pytest.mark.parametrize(
    ("name", "packages", "expected"),
    [
        pytest.param(
            "flat-pkg", ("flat_pkg", "tests"), ("flat_pkg",), id="named-for-project"
        ),
        pytest.param("flat-pkg", ("only",), ("only",), id="single-package"),
    ],
)
def test_a_flat_layout_resolves(
    tmp_path: Path,
    skips: SkipRecorder,
    name: str,
    packages: tuple[str, ...],
    expected: tuple[str, ...],
) -> None:
    root = _flat_project(tmp_path, name, packages)

    assert _check(root, fault_ops(), skips).module_names() == expected


@pytest.mark.parametrize(
    "backend",
    [
        pytest.param("module-name = 42", id="int"),
        pytest.param("module-name = []", id="empty-list"),
        pytest.param('module-name = ["ok", 1]', id="mixed-list"),
    ],
)
def test_a_non_string_module_name_fails(
    tmp_path: Path, skips: SkipRecorder, backend: str
) -> None:
    extra = f"\n[tool.uv.build-backend]\n{backend}\n"
    root = _project(tmp_path, "", pyproject_extra=extra)

    with pytest.raises(ReleaseError, match="module-name is not a string"):
        _check(root, fault_ops(), skips).module_names()


def test_a_dotted_module_is_imported_by_its_dotted_name(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    extra = '\n[tool.uv.build-backend]\nmodule-name = "ns.inner"\n'
    root = _project(tmp_path, "", pyproject_extra=extra)
    _layout(root, ("src/ns/inner",))
    seen: list[str] = []

    def run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = timeouts.DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout, check, capture
        seen.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, stdout=_record(_RELEASE))

    ops = fault_ops(real_run=run, passthrough=[_PROBE])
    _check(root, ops, skips).verify(_built(root))

    assert seen == ["ns.inner"]


# --- Phase 3 ---


def _uv_build(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = timeouts.DEFAULT_RUN,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Stand in for ``uv build``: leave a wheel and an sdist in ``dist/``."""
    del timeout, check, capture
    assert cwd is not None
    dist = Path(cwd) / "dist"
    dist.mkdir(exist_ok=True)
    _wheel(dist, {"test_pkg/__init__.py": ""})
    (dist / f"test_pkg-{_RELEASE}.tar.gz").write_bytes(b"sdist")
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def _phase3(root: Path, probe: FaultRule, skips: SkipRecorder) -> Phase3Build:
    twine = FaultRule(match=["uvx", "twine", "check"], response=CompletedProcessSpec())
    ops = fault_ops([twine, probe], real_run=_uv_build, passthrough=[["uv", "build"]])
    return Phase3Build(detect(root), _RELEASE, dry_run=False, ops=ops, skips=skips)


def test_phase3_imports_the_built_wheel_once(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    probe = _probe_rule(stdout=_record(_RELEASE))

    _phase3(root, probe, skips).run()

    assert probe.consumed == 1


def test_phase3_fails_on_a_mismatched_wheel(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")

    with pytest.raises(ReleaseError, match="'0.0.1' at run time"):
        _phase3(root, _probe_rule(stdout=_record("0.0.1")), skips).run()


def test_phase3_dry_run_reports_the_import(
    tmp_path: Path, skips: SkipRecorder, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path, "")
    # No rule: any real command would be unmatched and fail the test.
    Phase3Build(
        detect(root), _RELEASE, dry_run=True, ops=fault_ops(), skips=skips
    ).run()

    out = flat(capsys.readouterr().out)
    assert f"import test_pkg; __version__ == {_RELEASE}" in out


def test_phase3_skips_a_non_python_project(tmp_path: Path, skips: SkipRecorder) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    info = ProjectInfo(root=root)
    # No rule: `uv build` or the probe would be an unmatched command.
    Phase3Build(info, _RELEASE, dry_run=False, ops=fault_ops(), skips=skips).run()

    assert not (root / "dist").exists()


# --- real uv, real interpreter ---


def _real(tmp_path: Path, init: str, skips: SkipRecorder) -> None:
    """Build a wheel whose ``__init__`` is ``init`` and check it for real."""
    root = _project(tmp_path, init)
    _wheel(root / "dist", {"test_pkg/__init__.py": init})
    ops = fault_ops(real_run=CommandRunner.run, passthrough=[_PROBE])
    _check(root, ops, skips).verify(root / "dist")


_STALE_GETATTR = (
    "def __getattr__(name):\n"
    '    if name == "__version__":\n'
    '        return "0.0.1"\n'
    "    raise AttributeError(name)\n"
)


@pytest.mark.parametrize(
    "init",
    [
        pytest.param('globals()["__version__"] = "0.0.1"\n', id="globals"),
        pytest.param('vars()["__version__"] = "0.0.1"\n', id="vars"),
        pytest.param(
            'import sys\nsetattr(sys.modules[__name__], "__version__", "0.0.1")\n',
            id="setattr",
        ),
        pytest.param("exec(\"__version__ = '0.0.1'\")\n", id="exec"),
        pytest.param(_STALE_GETATTR, id="pep562"),
        pytest.param(
            f'import atexit\natexit.register(print, "{_RELEASE}")\n'
            '__version__ = "0.0.1"\n',
            id="atexit",
        ),
        pytest.param(f'print("{_RELEASE}")\n__version__ = "0.0.1"\n', id="prints"),
    ],
)
def test_a_real_wheel_reporting_a_stale_version_fails(
    tmp_path: Path, skips: SkipRecorder, init: str
) -> None:
    with pytest.raises(ReleaseError, match="'0.0.1' at run time"):
        _real(tmp_path, init, skips)


@pytest.mark.parametrize(
    "init",
    [
        pytest.param(f'__version__ = "{_RELEASE}"\n', id="literal"),
        pytest.param(f'globals()["__version__"] = "{_RELEASE}"\n', id="globals"),
        pytest.param(_STALE_GETATTR.replace("0.0.1", _RELEASE), id="pep562"),
    ],
)
def test_a_real_wheel_reporting_the_release_version_passes(
    tmp_path: Path, skips: SkipRecorder, init: str
) -> None:
    _real(tmp_path, init, skips)


def test_a_real_wheel_with_no_version_records_a_skip(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    _real(tmp_path, '"""No version here."""\n', skips)

    assert any("no __version__ at run time" in note for note in skips.drain())


def _real_module(tmp_path: Path, module: str, skips: SkipRecorder) -> None:
    """Check a real wheel holding namespace package ``nspkg`` as ``module``."""
    extra = f'\n[tool.uv.build-backend]\nmodule-name = "{module}"\n'
    root = _project(tmp_path, "", pyproject_extra=extra)
    _wheel(root / "dist", {"nspkg/sub.py": ""})
    ops = fault_ops(real_run=CommandRunner.run, passthrough=[_PROBE])
    _check(root, ops, skips).verify(root / "dist")


def test_a_real_namespace_package_records_a_skip(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    _real_module(tmp_path, "nspkg", skips)

    assert any("nspkg has no __version__" in note for note in skips.drain())


def test_a_real_module_missing_from_the_wheel_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    with pytest.raises(ReleaseError, match="importing ghost"):
        _real_module(tmp_path, "ghost", skips)
