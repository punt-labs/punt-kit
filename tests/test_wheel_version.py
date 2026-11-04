"""The run-time ``__version__`` check on a built wheel (Phase 3)."""

from __future__ import annotations

import base64
import hashlib
import re
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_kit.detect import ProjectInfo, detect
from punt_kit.phases.phase03_build import Phase3Build
from punt_kit.phases.shared import timeouts
from punt_kit.phases.shared.command_runner import CommandRunner
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.skips import SkipRecorder
from punt_kit.phases.shared.wheel_contents import WheelContents
from punt_kit.phases.shared.wheel_version import WheelVersionCheck
from tests.harness.fault_ops import CompletedProcessSpec, FaultRule
from tests.helpers import fault_ops, flat

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.harness.fault_ops import FaultInjectingOps

_PROBE = ["uv", "run", "--isolated", "--no-project", "--with"]
_RELEASE = "1.0.0"
_ORIGIN = "/venv/lib/python3.13/site-packages/test_pkg/__init__.py"

# What the probe prints, given the head (marker plus nonce) it was handed.
type Answer = Callable[[str], str]


@pytest.fixture
def skips() -> SkipRecorder:
    return SkipRecorder(ops=fault_ops())


# --- fixtures on disk ---


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


def _layout(root: Path, packages: tuple[str, ...]) -> None:
    """Create each ``a/b`` package directory under ``root`` with an init."""
    for package in packages:
        path = root.joinpath(*package.split("/"))
        path.mkdir(parents=True, exist_ok=True)
        (path / "__init__.py").write_text("")


def _module_name(module: str) -> str:
    return f'\n[tool.uv.build-backend]\nmodule-name = "{module}"\n'


def _wheel(
    dist: Path,
    files: dict[str, str],
    *,
    name: str = "test_pkg",
    requires: tuple[str, ...] = (),
    unhashed: tuple[str, ...] = (),
    also_unhashed: tuple[str, ...] = (),
) -> Path:
    """Write a minimal, installable wheel of distribution ``name`` with ``files``.

    RECORD hashes every file, except those in ``unhashed`` (listed with no
    hash instead) and those in ``also_unhashed`` (listed a second time, with
    no hash).
    """
    info = f"{name}-{_RELEASE}.dist-info"
    depends = "".join(f"Requires-Dist: {req}\n" for req in requires)
    contents = {
        **files,
        f"{info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {_RELEASE}\n{depends}"
        ),
        f"{info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ),
    }
    record = [
        f"{path},,"
        if path in unhashed
        else f"{path},sha256={_digest(text)},{len(text.encode())}"
        for path, text in contents.items()
    ]
    record += [f"{path},," for path in also_unhashed]
    contents[f"{info}/RECORD"] = "\n".join([*record, f"{info}/RECORD,,"]) + "\n"
    wheel = dist / f"{name}-{_RELEASE}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, text in contents.items():
            archive.writestr(path, text)
    return wheel


def _digest(text: str) -> str:
    raw = hashlib.sha256(text.encode()).digest()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _built(root: Path, files: dict[str, str] | None = None) -> Path:
    """``root``'s ``dist/`` with a placeholder wheel, for scripted probes."""
    _wheel(root / "dist", files or {"test_pkg/__init__.py": ""})
    return root / "dist"


# --- the scripted probe ---


def _record(
    kind: str,
    value: str,
    *,
    origin: str = _ORIGIN,
    in_stdlib: bool = False,
    from_wheel: bool = True,
) -> Answer:
    """The probe's one record, under whatever nonce it was handed."""
    fields = (kind, value, origin, in_stdlib, from_wheel)
    return lambda head: f"\n{head}{ascii(fields)}\n"


def _version(value: str) -> Answer:
    return _record("str", value)


@dataclass
class _Probe:
    """A ``RunFn`` that answers the wheel probe and stands in for ``uv build``."""

    answer: Answer
    returncode: int = 0
    stderr: str = ""
    # (argv, timeout, errors) for each probe run
    calls: list[tuple[list[str], int, str]] = field(
        default_factory=list[tuple[list[str], int, str]]
    )

    def __call__(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = timeouts.DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
        errors: str = "strict",
    ) -> subprocess.CompletedProcess[str]:
        del check, capture
        if cmd[:2] == ["uv", "build"]:
            assert cwd is not None
            (Path(cwd) / "dist").mkdir(exist_ok=True)  # Phase 3 removed it
            _built(Path(cwd))
            (Path(cwd) / "dist" / f"test_pkg-{_RELEASE}.tar.gz").write_bytes(b"sdist")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        self.calls.append((cmd, timeout, errors))
        stdout = self.answer(f"\x00PUNT_VERSION:{cmd[-2]}")
        return subprocess.CompletedProcess(cmd, self.returncode, stdout, self.stderr)

    def ops(self, *rules: FaultRule) -> FaultInjectingOps:
        passthrough = [_PROBE, ["uv", "build"]]
        return fault_ops(list(rules), real_run=self, passthrough=passthrough)


def _check(
    root: Path,
    ops: FaultInjectingOps,
    skips: SkipRecorder,
    *,
    version: str = _RELEASE,
) -> WheelVersionCheck:
    return WheelVersionCheck(detect(root), version, ops=ops, skips=skips)


def test_matching_version_passes(tmp_path: Path, skips: SkipRecorder) -> None:
    root = _project(tmp_path, "")
    probe = _Probe(_version(_RELEASE))

    _check(root, probe.ops(), skips).verify(_built(root))

    assert len(probe.calls) == 1


def test_probe_imports_the_module_in_an_isolated_interpreter(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    dist = _built(root)
    probe = _Probe(_version(_RELEASE))

    _check(root, probe.ops(), skips).verify(dist)

    [(cmd, timeout, errors)] = probe.calls
    wheel = str(next(dist.glob("*.whl")))
    shape = (cmd[: len(_PROBE) + 4], cmd[-3], timeout, errors)
    assert shape == (
        [*_PROBE, wheel, "python", "-I", "-c"],
        "test_pkg",
        timeouts.UV,
        "replace",
    )


def test_each_probe_carries_a_fresh_random_nonce(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    probe = _Probe(_version(_RELEASE))
    check = _check(root, probe.ops(), skips)

    check.verify(_built(root))
    check.verify(root / "dist")

    nonces = [cmd[-2] for cmd, _, _ in probe.calls]
    assert all(re.fullmatch(r"[0-9a-f]{32}", n) for n in nonces) and len(
        set(nonces)
    ) == len(nonces)


def test_requires_python_is_passed_to_uv(tmp_path: Path, skips: SkipRecorder) -> None:
    root = _project(tmp_path, "", pyproject_extra='requires-python = ">=3.13"\n')
    probe = _Probe(_version(_RELEASE))

    _check(root, probe.ops(), skips).verify(_built(root))

    [(cmd, _, _)] = probe.calls
    assert cmd[len(_PROBE) + 1 : len(_PROBE) + 3] == ["--python", ">=3.13"]


def test_no_requires_python_passes_no_python(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    probe = _Probe(_version(_RELEASE))

    _check(root, probe.ops(), skips).verify(_built(root))

    [(cmd, _, _)] = probe.calls
    assert "--python" not in cmd


@pytest.mark.parametrize(
    ("release", "found"),
    [
        pytest.param("1.0.0-rc1", "1.0.0rc1", id="canonical-form"),
        pytest.param("1.0.0-rc1", "1.0.0-rc1", id="as-written"),
    ],
)
def test_the_release_version_as_written_or_canonical_passes(
    tmp_path: Path, skips: SkipRecorder, release: str, found: str
) -> None:
    root = _project(tmp_path, "")
    probe = _Probe(_version(found))

    _check(root, probe.ops(), skips, version=release).verify(_built(root))

    assert len(probe.calls) == 1


@pytest.mark.parametrize(
    ("release", "found"),
    [
        pytest.param(_RELEASE, "0.0.1", id="stale"),
        pytest.param(_RELEASE, "v1.0.0", id="v-prefix"),
        pytest.param(_RELEASE, "1.0", id="short"),
        pytest.param(_RELEASE, "1", id="major-only"),
        pytest.param(_RELEASE, "1.0.0.0.0", id="zero-padded"),
        pytest.param(_RELEASE, "stale\n1.0.0", id="embedded-newline"),
        pytest.param(_RELEASE, "1.0.0 ", id="trailing-space"),
        pytest.param(_RELEASE, " 1.0.0", id="leading-space"),
        pytest.param("1.0.0rc1", "1.0.0RC1", id="case"),
    ],
)
def test_anything_but_the_exact_version_fails(
    tmp_path: Path, skips: SkipRecorder, release: str, found: str
) -> None:
    root = _project(tmp_path, "")
    ops = _Probe(_version(found)).ops()

    with pytest.raises(ReleaseError, match="at run time, but the release version"):
        _check(root, ops, skips, version=release).verify(_built(root))


def test_mismatched_version_fails_naming_both_values_and_the_wheel(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    dist = _built(root)

    with pytest.raises(ReleaseError) as caught:
        _check(root, _Probe(_version("0.0.1")).ops(), skips).verify(dist)

    wheel = next(dist.glob("*.whl")).name
    assert all(part in str(caught.value) for part in ("0.0.1", _RELEASE, wheel))


def test_an_invalid_release_version_blames_the_release_version(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")

    with pytest.raises(ReleaseError, match="release version 'not-a-version' is not"):
        _check(root, fault_ops(), skips, version="not-a-version")


@pytest.mark.parametrize("type_name", ["int", "tuple", "Version"])
def test_a_value_that_is_not_a_string_fails(
    tmp_path: Path, skips: SkipRecorder, type_name: str
) -> None:
    root = _project(tmp_path, "")
    ops = _Probe(_record("type", type_name)).ops()

    with pytest.raises(ReleaseError, match=f"is a {type_name}, not a string"):
        _check(root, ops, skips).verify(_built(root))


def _raw(payload: str) -> Answer:
    """The probe printing ``payload`` straight after its head."""

    def answer(head: str) -> str:
        return f"\n{head}{payload}\n"

    return answer


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("<Version('1.0.0')>", id="no-literal"),
        pytest.param("('str', '1.0.0')", id="short-tuple"),
        pytest.param("('weird', '1.0.0', '/x', False, True)", id="bad-kind"),
    ],
)
def test_a_malformed_record_fails(
    tmp_path: Path, skips: SkipRecorder, payload: str
) -> None:
    root = _project(tmp_path, "")

    with pytest.raises(ReleaseError, match="malformed version record"):
        _check(root, _Probe(_raw(payload)).ops(), skips).verify(_built(root))


def _unframed(head: str) -> str:
    """The version alone, with no record around it."""
    del head
    return f"{_RELEASE}\n"


def _forged(head: str) -> str:
    """A record under some other nonce, as a package that guessed would print."""
    del head
    fields = ("str", _RELEASE, _ORIGIN, False, True)
    return f"\n\x00PUNT_VERSION:{'0' * 32}{ascii(fields)}\n"


def _twice(head: str) -> str:
    """The right record, printed twice."""
    return _version(_RELEASE)(head) * 2


@pytest.mark.parametrize(
    ("answer", "count"),
    [
        pytest.param(_unframed, 0, id="none"),
        pytest.param(_forged, 0, id="wrong-nonce"),
        pytest.param(_twice, 2, id="two"),
    ],
)
def test_anything_but_exactly_one_record_fails(
    tmp_path: Path, skips: SkipRecorder, answer: Answer, count: int
) -> None:
    root = _project(tmp_path, "")

    with pytest.raises(ReleaseError, match=f"gave {count} version records"):
        _check(root, _Probe(answer).ops(), skips).verify(_built(root))


def test_a_module_loaded_from_the_stdlib_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    answer = _record("str", _RELEASE, origin="/usr/lib/python3.13/x.py", in_stdlib=True)

    with pytest.raises(ReleaseError, match="from the standard library"):
        _check(root, _Probe(answer).ops(), skips).verify(_built(root))


def test_a_module_not_from_the_wheels_distribution_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    answer = _record("str", _RELEASE, from_wheel=False)

    with pytest.raises(ReleaseError, match="another installed package shadows"):
        _check(root, _Probe(answer).ops(), skips).verify(_built(root))


def test_the_probe_is_told_the_wheels_distribution(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    probe = _Probe(_version(_RELEASE))

    _check(root, probe.ops(), skips).verify(_built(root))

    assert [cmd[-1] for cmd, _, _ in probe.calls] == ["test_pkg"]


def test_import_error_fails(tmp_path: Path, skips: SkipRecorder) -> None:
    root = _project(tmp_path, "")
    probe = _Probe(lambda head: "", returncode=1, stderr="ModuleNotFoundError: x")

    with pytest.raises(ReleaseError, match="importing test_pkg"):
        _check(root, probe.ops(), skips).verify(_built(root))


def test_no_version_at_run_time_records_a_skip(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")

    _check(root, _Probe(_record("absent", "")).ops(), skips).verify(_built(root))

    assert any("no __version__ at run time" in note for note in skips.drain())


@pytest.mark.parametrize(
    ("module", "files"),
    [
        pytest.param("ghost", {"ghost/__init__.py": ""}, id="package"),
        pytest.param("single", {"single.py": ""}, id="module-file"),
        pytest.param("nspkg", {"nspkg/sub.py": ""}, id="namespace"),
        pytest.param("ns.inner", {"ns/inner/__init__.py": ""}, id="dotted"),
    ],
)
def test_a_module_the_wheel_ships_is_imported_whatever_the_source_tree(
    tmp_path: Path, skips: SkipRecorder, module: str, files: dict[str, str]
) -> None:
    root = _project(tmp_path, "", pyproject_extra=_module_name(module))
    probe = _Probe(_version(_RELEASE))

    _check(root, probe.ops(), skips).verify(_built(root, files))

    assert [cmd[-3] for cmd, _, _ in probe.calls] == [module]


def test_a_module_the_wheel_lacks_fails_before_any_import(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "", pyproject_extra=_module_name("ghost"))
    # No probe: an import would be an unmatched command and fail the test.
    with pytest.raises(ReleaseError, match="does not contain ghost"):
        _check(root, fault_ops(), skips).verify(_built(root))


@pytest.mark.parametrize(
    ("module", "files"),
    [
        pytest.param(
            "fastmod",
            {"fastmod.cpython-313-x86_64-linux-gnu.so": ""},
            id="tagged-so",
        ),
        pytest.param("fastmod", {"fastmod.so": ""}, id="bare-so"),
        pytest.param("fastmod", {"fastmod.cp313-win_amd64.pyd": ""}, id="tagged-pyd"),
        pytest.param("fastmod", {"fastmod.pyd": ""}, id="bare-pyd"),
        pytest.param(
            "datapkg",
            {f"test_pkg-{_RELEASE}.data/purelib/datapkg/__init__.py": ""},
            id="purelib",
        ),
        pytest.param(
            "datapkg",
            {f"test_pkg-{_RELEASE}.data/platlib/datapkg/core.so": ""},
            id="platlib",
        ),
    ],
)
def test_extension_and_data_scheme_modules_count_as_shipped(
    tmp_path: Path, skips: SkipRecorder, module: str, files: dict[str, str]
) -> None:
    root = _project(tmp_path, "", pyproject_extra=_module_name(module))
    probe = _Probe(_version(_RELEASE))

    _check(root, probe.ops(), skips).verify(_built(root, files))

    assert len(probe.calls) == 1


def test_a_module_directory_without_python_files_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "", pyproject_extra=_module_name("emptypkg"))
    files = {"emptypkg/data.txt": "x"}

    with pytest.raises(ReleaseError, match="ships emptypkg/ with no Python files"):
        _check(root, fault_ops(), skips).verify(_built(root, files))


def test_a_wheel_that_is_not_a_zip_fails_naming_it(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    (root / "dist" / f"test_pkg-{_RELEASE}-py3-none-any.whl").write_bytes(b"no")

    with pytest.raises(ReleaseError, match=r"test_pkg-1\.0\.0-py3-none-any\.whl is"):
        _check(root, fault_ops(), skips).verify(root / "dist")


def test_an_unlocated_module_fails(tmp_path: Path, skips: SkipRecorder) -> None:
    root = _project(tmp_path, "")
    answer = _record("unlocated", "", origin="")

    with pytest.raises(ReleaseError, match="has no file origin"):
        _check(root, _Probe(answer).ops(), skips).verify(_built(root))


def test_no_wheel_in_dist_fails(tmp_path: Path, skips: SkipRecorder) -> None:
    root = _project(tmp_path, "")

    with pytest.raises(ReleaseError, match="no wheel"):
        _check(root, fault_ops(), skips).verify(root / "dist")


# --- which module ---


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


def test_root_scripts_do_not_count_as_a_flat_layouts_module(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _flat_project(tmp_path, "other-name", ("thepkg",))
    for script in ("noxfile.py", "conftest.py"):
        (root / script).write_text("")

    assert _check(root, fault_ops(), skips).module_names() == ("thepkg",)


def test_a_root_module_named_for_the_project_resolves(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _flat_project(tmp_path, "flat-mod", ())
    for script in ("flat_mod.py", "noxfile.py"):
        (root / script).write_text("")

    assert _check(root, fault_ops(), skips).module_names() == ("flat_mod",)


def _single_file_project(tmp_path: Path, name: str, module: str) -> Path:
    """A project ``name`` whose code is the one file ``src/<module>.py``."""
    root = tmp_path / "single"
    (root / "src").mkdir(parents=True)
    (root / "src" / f"{module}.py").write_text("")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{_RELEASE}"\n'
    )
    return root


@pytest.mark.parametrize(
    ("name", "module"),
    [
        pytest.param("test-pkg", "test_pkg", id="named-for-project"),
        pytest.param("other-name", "lonely", id="the-only-module"),
    ],
)
def test_a_single_file_module_resolves(
    tmp_path: Path, skips: SkipRecorder, name: str, module: str
) -> None:
    root = _single_file_project(tmp_path, name, module)

    assert _check(root, fault_ops(), skips).module_names() == (module,)


def test_two_packages_none_named_for_the_project_fail(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "", name="other-name")
    _layout(root, ("src/second",))

    with pytest.raises(ReleaseError, match="2 modules under"):
        _check(root, fault_ops(), skips).module_names()


def test_nothing_found_in_the_source_leaves_it_to_the_wheel(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _flat_project(tmp_path, "nothing-here", ())

    assert _check(root, fault_ops(), skips).module_names() == ()


def test_a_package_the_source_scan_misses_is_read_from_the_wheel(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _flat_project(tmp_path, "lib-project", ())
    (root / "lib" / "pkg").mkdir(parents=True)
    (root / "lib" / "pkg" / "__init__.py").write_text("")
    (root / "dist").mkdir()
    probe = _Probe(_version(_RELEASE))

    _check(root, probe.ops(), skips).verify(_built(root, {"pkg/__init__.py": ""}))

    assert [cmd[-3] for cmd, _, _ in probe.calls] == ["pkg"]


def test_a_wheel_with_several_top_level_names_fails_listing_them(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _flat_project(tmp_path, "nothing-here", ())
    (root / "dist").mkdir()
    files = {"alpha/__init__.py": "", "beta.py": ""}

    with pytest.raises(ReleaseError, match=r"2 top-level importable names \(alpha"):
        _check(root, fault_ops(), skips).verify(_built(root, files))


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        pytest.param(
            ("pkg/__init__.py", "test_pkg-1.0.0.dist-info/RECORD"),
            ("pkg",),
            id="package",
        ),
        pytest.param(
            ("mod.py", "fast.cpython-313-x86_64-linux-gnu.so", "win.pyd"),
            ("fast", "mod", "win"),
            id="module-files",
        ),
        pytest.param(
            (
                "test_pkg-1.0.0.data/purelib/datapkg/__init__.py",
                "test_pkg-1.0.0.data/scripts/tool",
            ),
            ("datapkg",),
            id="data-schemes",
        ),
    ],
)
def test_wheel_top_level_names(
    paths: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert WheelContents(paths).top_level() == expected


def test_a_data_directory_deeper_in_the_wheel_is_not_a_scheme() -> None:
    contents = WheelContents(("pkg/a.data/purelib/mod.py",))

    assert contents.shipping("pkg.mod") == "missing"


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


# --- Phase 3 ---


def _phase3(root: Path, probe: _Probe, skips: SkipRecorder) -> Phase3Build:
    twine = FaultRule(match=["uvx", "twine", "check"], response=CompletedProcessSpec())
    ops = probe.ops(twine)
    return Phase3Build(detect(root), _RELEASE, dry_run=False, ops=ops, skips=skips)


def test_phase3_imports_the_built_wheel_once(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")
    probe = _Probe(_version(_RELEASE))

    _phase3(root, probe, skips).run()

    assert len(probe.calls) == 1


def test_phase3_fails_on_a_mismatched_wheel(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "")

    with pytest.raises(ReleaseError, match="'0.0.1' at run time"):
        _phase3(root, _Probe(_version("0.0.1")), skips).run()


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


def _real(
    tmp_path: Path,
    init: str,
    skips: SkipRecorder,
    *,
    module: str = "test_pkg",
    files: dict[str, str] | None = None,
) -> None:
    """Build a real wheel and check ``module`` in it for real.

    The wheel holds ``files``, or ``test_pkg/__init__.py`` reading ``init``.
    """
    extra = _module_name(module) if module != "test_pkg" else ""
    root = _project(tmp_path, init, pyproject_extra=extra)
    _wheel(root / "dist", files or {"test_pkg/__init__.py": init})
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
        pytest.param(
            "import os\n"
            "_real_write = os.write\n"
            "def _forge(fd, data):\n"
            "    data = data.replace(b\"'0.0.1'\", "
            f"b\"'{_RELEASE}'\")\n"
            "    return _real_write(fd, data)\n"
            "os.write = _forge\n"
            '__version__ = "0.0.1"\n',
            id="replaced-os-write",
        ),
        pytest.param(_STALE_GETATTR, id="pep562"),
        pytest.param(
            f'import atexit\natexit.register(print, "{_RELEASE}")\n'
            '__version__ = "0.0.1"\n',
            id="atexit",
        ),
        pytest.param(f'print("{_RELEASE}")\n__version__ = "0.0.1"\n', id="prints"),
        pytest.param(
            "class S(str):\n"
            "    def __repr__(self):\n"
            f"        return \"'{_RELEASE}'\"\n"
            "    def __str__(self):\n"
            f'        return "{_RELEASE}"\n'
            '__version__ = S("0.0.1")\n',
            id="str-subclass",
        ),
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
        pytest.param(
            f'import os\nos.write(1, b"\\xff\\xfe\\n")\n__version__ = "{_RELEASE}"\n',
            id="non-utf8-output",
        ),
    ],
)
def test_a_real_wheel_reporting_the_release_version_passes(
    tmp_path: Path, skips: SkipRecorder, init: str
) -> None:
    _real(tmp_path, init, skips)


@pytest.mark.parametrize(
    "init",
    [
        pytest.param(
            "class _Meta:\n"
            "    pass\n"
            "_meta = _Meta()\n"
            "def __getattr__(name):\n"
            '    if name == "__version__":\n'
            "        return _meta.version\n"
            "    raise AttributeError(name)\n",
            id="missing-field",
        ),
        pytest.param(
            "_meta = None\n"
            "def __getattr__(name):\n"
            '    if name == "__version__":\n'
            '        return getattr(_meta, "__version__")\n'
            "    raise AttributeError(name)\n",
            id="asks-none",
        ),
        pytest.param(
            "def _lookup(name):\n"
            "    raise AttributeError(name)\n"
            "def __getattr__(name):\n"
            "    return _lookup(name)\n",
            id="p_lazybare",
        ),
        pytest.param(
            "import sys, types\n"
            "class _Versioned(types.ModuleType):\n"
            "    @property\n"
            "    def __version__(self):\n"
            "        raise AttributeError()\n"
            "sys.modules[__name__].__class__ = _Versioned\n",
            id="p_propbare",
        ),
        # A lazy module with no version at all fails too, by design: it is
        # told to define __version__ as a plain attribute.
        pytest.param(
            "def __getattr__(name):\n    raise AttributeError(name)\n",
            id="pep562-bare",
        ),
        pytest.param(
            "def __getattr__(name):\n"
            '    raise AttributeError(f"module {__name__!r} has no attribute '
            '{name!r}")\n',
            id="pep562-message",
        ),
    ],
)
def test_a_real_version_read_that_raises_fails(
    tmp_path: Path, skips: SkipRecorder, init: str
) -> None:
    with pytest.raises(
        ReleaseError,
        match=r"reading test_pkg\.__version__ raised \w+.*define __version__ as a "
        "plain attribute",
    ):
        _real(tmp_path, init, skips)


def test_a_real_plain_module_with_no_version_records_a_skip(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    _real(tmp_path, '"""No version here."""\n', skips)

    assert any("no __version__ at run time" in note for note in skips.drain())


def test_a_real_module_class_swap_is_read(tmp_path: Path, skips: SkipRecorder) -> None:
    init = (
        "import sys, types\n"
        "class _Versioned(types.ModuleType):\n"
        "    @property\n"
        "    def __version__(self):\n"
        '        return "0.0.1"\n'
        "sys.modules[__name__].__class__ = _Versioned\n"
    )

    with pytest.raises(ReleaseError, match="'0.0.1' at run time"):
        _real(tmp_path, init, skips)


def test_a_real_module_rewriting_argv_passes(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    init = f'import sys\nsys.argv[:] = sys.argv[:1]\n__version__ = "{_RELEASE}"\n'

    _real(tmp_path, init, skips)


def test_a_real_module_replaced_in_sys_modules_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    init = (
        "import sys, types\n"
        f'sys.modules[__name__] = types.SimpleNamespace(__version__="{_RELEASE}")\n'
    )

    with pytest.raises(ReleaseError, match="has no file origin"):
        _real(tmp_path, init, skips)


def test_a_real_forged_record_fails(tmp_path: Path, skips: SkipRecorder) -> None:
    init = (
        "import os\n"
        "os.write(1, b\"\\n\\x00PUNT_VERSION:deadbeef('str', '1.0.0', '/x', "
        'False)\\n")\n'
        "os._exit(0)\n"
    )

    with pytest.raises(ReleaseError, match="gave 0 version records"):
        _real(tmp_path, init, skips)


def test_a_real_namespace_package_records_a_skip(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    _real(tmp_path, "", skips, module="nspkg", files={"nspkg/sub.py": ""})

    assert any("nspkg has no __version__" in note for note in skips.drain())


@pytest.mark.parametrize("module", ["json", "calendar"])
def test_a_real_module_shadowed_by_the_stdlib_fails(
    tmp_path: Path, skips: SkipRecorder, module: str
) -> None:
    files = {f"{module}/__init__.py": f'__version__ = "{_RELEASE}"\n'}

    with pytest.raises(ReleaseError, match="from the standard library"):
        _real(tmp_path, "", skips, module=module, files=files)


@dataclass(frozen=True)
class _Dependency:
    """A wheel the checked wheel depends on, installed beside it."""

    name: str
    files: dict[str, str]


def _with_dependency(
    tmp_path: Path,
    module: str,
    own: dict[str, str],
    dependency: _Dependency,
    skips: SkipRecorder,
) -> None:
    """Check, for real, a wheel holding ``own`` that requires ``dependency``.

    The wheel's distribution is named for ``module``. uv resolves the
    dependency from a local ``--find-links`` directory, as it would from an
    index, and installs it beside the wheel.
    """
    root = _project(tmp_path, "", pyproject_extra=_module_name(module))
    _wheel(root / "dist", own, requires=(dependency.name,), name=module)
    links = tmp_path / "links"
    links.mkdir()
    _wheel(links, dependency.files, name=dependency.name)

    def with_links(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = timeouts.DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
        errors: str = "strict",
    ) -> subprocess.CompletedProcess[str]:
        at = cmd.index("--no-project") + 1
        cmd = [*cmd[:at], "--no-index", "--find-links", str(links), *cmd[at:]]
        return CommandRunner.run(
            cmd, cwd=cwd, timeout=timeout, check=check, capture=capture, errors=errors
        )

    ops = fault_ops(real_run=with_links, passthrough=[_PROBE])
    _check(root, ops, skips).verify(root / "dist")


def test_a_real_dependency_shadowing_the_module_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    """An installed package of the same name, not this wheel, answers the import.

    The wheel ships ``shadowed.py``; its dependency ships the package
    ``shadowed/``, which the import system prefers.
    """
    own = {"shadowed.py": f'__version__ = "{_RELEASE}"\n'}
    decoy = _Dependency("decoy", {"shadowed/__init__.py": "__version__ = '1.0.0'\n"})

    with pytest.raises(ReleaseError, match="another installed package shadows"):
        _with_dependency(tmp_path, "shadowed", own, decoy, skips)


def test_a_real_dependency_overwriting_the_module_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    """A dependency installing the same path must not pass for the wheel.

    The wheel ``sfhpkg``'s ``sfhpkg/__init__.py`` reports a stale version;
    its dependency ``zzdep`` ships the same path with the release version
    (the reviewer's case). uv installs the two in no fixed order: when zzdep's
    copy lands last, the path is still the wheel's but its RECORD hash no
    longer matches; when the wheel's lands last, the stale version is read.
    Either way the release fails. The hash path alone is pinned down by
    ``test_a_real_file_no_longer_matching_its_record_hash_fails``.
    """
    own = {"sfhpkg/__init__.py": '__version__ = "0.0.1"\n'}
    zzdep = _Dependency("zzdep", {"sfhpkg/__init__.py": "__version__ = '1.0.0'\n"})
    either = "was overwritten by another installed|'0.0.1' at run time"

    with pytest.raises(ReleaseError, match=either):
        _with_dependency(tmp_path, "sfhpkg", own, zzdep, skips)


def test_a_real_file_no_longer_matching_its_record_hash_fails(
    tmp_path: Path, skips: SkipRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overwrite, made deterministic: the module rewrites its own file.

    It then reports the release version, so only the RECORD hash check can
    tell that what is on disk is not what the wheel installed. Installed by
    copy into a private cache, so the rewrite cannot reach uv's shared cache
    through a hard link.
    """
    monkeypatch.setenv("UV_LINK_MODE", "copy")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "private-cache"))
    init = (
        "import pathlib\n"
        f"pathlib.Path(__file__).write_text('__version__ = \"{_RELEASE}\"\\n')\n"
        f'__version__ = "{_RELEASE}"\n'
    )

    with pytest.raises(ReleaseError, match="was overwritten by another installed"):
        _real(tmp_path, init, skips)


_VERSION_FROM_SUBMODULE = "from ._version import __version__\n"


def test_a_real_dependency_overwriting_a_submodule_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    """The reviewer's ``_version.py`` case: only the submodule is replaced.

    ``__init__.py`` is the wheel's own, so a check of the origin alone would
    pass; the dependency's copy of ``_version.py`` carries the release
    version over the wheel's stale one. As with the ``__init__`` case, uv
    installs the two in no fixed order, so the release fails either as an
    overwrite or on the stale version.
    """
    own = {
        "sfhpkg/__init__.py": _VERSION_FROM_SUBMODULE,
        "sfhpkg/_version.py": '__version__ = "0.0.1"\n',
    }
    zzdep = _Dependency("zzdep", {"sfhpkg/_version.py": "__version__ = '1.0.0'\n"})
    either = "was overwritten by another installed|'0.0.1' at run time"

    with pytest.raises(ReleaseError, match=either):
        _with_dependency(tmp_path, "sfhpkg", own, zzdep, skips)


def test_a_real_submodule_no_longer_matching_its_record_hash_fails(
    tmp_path: Path, skips: SkipRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The submodule overwrite, made deterministic.

    ``__init__.py`` rewrites the wheel's stale ``_version.py`` before reading
    it, so the version read is the release version and ``__init__.py`` still
    matches its hash: only hashing every file under the package catches it.
    """
    monkeypatch.setenv("UV_LINK_MODE", "copy")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "private-cache"))
    init = (
        "import pathlib\n"
        "pathlib.Path(__file__).with_name('_version.py').write_text(\n"
        f"    '__version__ = \"{_RELEASE}\"\\n'\n"
        ")\n" + _VERSION_FROM_SUBMODULE
    )
    files = {
        "test_pkg/__init__.py": init,
        "test_pkg/_version.py": '__version__ = "0.0.1"\n',
    }

    with pytest.raises(ReleaseError, match=r"overwritten.*_version\.py"):
        _real(tmp_path, init, skips, files=files)


def _record_case(
    tmp_path: Path,
    skips: SkipRecorder,
    *,
    unhashed: tuple[str, ...] = (),
    also_unhashed: tuple[str, ...] = (),
) -> None:
    """Check, for real, a wheel whose RECORD omits or repeats hashes."""
    root = _project(tmp_path, "")
    _wheel(
        root / "dist",
        {"test_pkg/__init__.py": f'__version__ = "{_RELEASE}"\n'},
        unhashed=unhashed,
        also_unhashed=also_unhashed,
    )
    ops = fault_ops(real_run=CommandRunner.run, passthrough=[_PROBE])
    _check(root, ops, skips).verify(root / "dist")


def test_a_real_code_file_with_no_record_hash_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    with pytest.raises(ReleaseError, match=r"malformed RECORD.*__init__\.py"):
        _record_case(tmp_path, skips, unhashed=("test_pkg/__init__.py",))


def test_a_real_duplicate_record_entry_prefers_the_hashed_one(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    _record_case(tmp_path, skips, also_unhashed=("test_pkg/__init__.py",))


def test_a_non_identifier_top_level_name_is_not_importable() -> None:
    contents = WheelContents(("realpkg/__init__.py", "realpkg.libs/libfoo.so"))

    assert contents.top_level() == ("realpkg",)


def test_a_real_namespace_package_under_symlinked_installs_records_a_skip(
    tmp_path: Path, skips: SkipRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Site-packages files that are symlinks into uv's cache still match."""
    monkeypatch.setenv("UV_LINK_MODE", "symlink")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "fresh-cache"))

    _real(tmp_path, "", skips, module="nspkg", files={"nspkg/sub.py": ""})

    assert any("nspkg has no __version__" in note for note in skips.drain())


def test_a_real_module_missing_from_the_wheel_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    with pytest.raises(ReleaseError, match="does not contain ghost"):
        _real(tmp_path, "", skips, module="ghost")
