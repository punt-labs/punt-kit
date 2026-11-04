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


def _built(root: Path, files: dict[str, str] | None = None) -> Path:
    """``root``'s ``dist/`` with a placeholder wheel, for scripted probes."""
    _wheel(root / "dist", files or {"test_pkg/__init__.py": ""})
    return root / "dist"


# --- the scripted probe ---


def _record(
    kind: str, value: str, *, origin: str = _ORIGIN, in_stdlib: bool = False
) -> Answer:
    """The probe's one record, under whatever nonce it was handed."""
    fields = (kind, value, origin, in_stdlib)
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
        stdout = self.answer(f"\x00PUNT_VERSION:{cmd[-1]}")
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
    shape = (cmd[: len(_PROBE) + 4], cmd[-2], timeout, errors)
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

    nonces = [cmd[-1] for cmd, _, _ in probe.calls]
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
        pytest.param("('weird', '1.0.0', '/x', False)", id="bad-kind"),
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
    fields = ("str", _RELEASE, _ORIGIN, False)
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

    assert [cmd[-2] for cmd, _, _ in probe.calls] == [module]


def test_a_module_the_wheel_lacks_fails_before_any_import(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    root = _project(tmp_path, "", pyproject_extra=_module_name("ghost"))
    # No probe: an import would be an unmatched command and fail the test.
    with pytest.raises(ReleaseError, match="does not contain ghost"):
        _check(root, fault_ops(), skips).verify(_built(root))


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


def test_a_real_lazy_version_that_raises_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    init = "def __getattr__(name):\n    raise AttributeError(name)\n"

    with pytest.raises(ReleaseError, match="importing test_pkg to read"):
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


def test_a_real_wheel_with_no_version_records_a_skip(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    _real(tmp_path, '"""No version here."""\n', skips)

    assert any("no __version__ at run time" in note for note in skips.drain())


def test_a_real_namespace_package_records_a_skip(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    _real(tmp_path, "", skips, module="nspkg", files={"nspkg/sub.py": ""})

    assert any("nspkg has no __version__" in note for note in skips.drain())


def test_a_real_module_shadowed_by_the_stdlib_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    files = {"json/__init__.py": f'__version__ = "{_RELEASE}"\n'}

    with pytest.raises(ReleaseError, match="from the standard library"):
        _real(tmp_path, "", skips, module="json", files=files)


def test_a_real_module_missing_from_the_wheel_fails(
    tmp_path: Path, skips: SkipRecorder
) -> None:
    with pytest.raises(ReleaseError, match="does not contain ghost"):
        _real(tmp_path, "", skips, module="ghost")
