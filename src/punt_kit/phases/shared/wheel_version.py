"""Verify the version reported by a built wheel at import time."""

from __future__ import annotations

import re
import secrets
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, cast, final

from packaging.version import InvalidVersion, Version

from punt_kit.phases.shared.timeouts import UV
from punt_kit.phases.shared.wheel_contents import WheelContents
from punt_kit.phases.shared.wheel_probe import PROBE_SOURCE, ProbeRecord

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.skips import SkipRecorder

# uv_build's default when [tool.uv.build-backend] sets no module-root.
_DEFAULT_MODULE_ROOT = "src"
# uv_build's default module-name: the project name, lowercased, with each run
# of "-", "_" and "." turned into "_".
_NORMALIZE = re.compile(r"[-_.]+")

type _Source = Literal[
    "configured", "project-name", "module-root", "repo-root", "nothing"
]


@dataclass(frozen=True, slots=True)
class _ModuleChoice:
    """The import names steps 1 to 3 found, and which step found them."""

    names: tuple[str, ...]
    source: _Source

    def falls_back_to(self, contents: WheelContents) -> bool:
        """Whether ``contents`` must be read for the module instead (step 4).

        Only when nothing was found, or the one name is a repo-root guess
        the wheel holds nothing of.
        """
        match self.source:
            case "nothing":
                return True
            case "repo-root":
                return all(contents.shipping(n) == "missing" for n in self.names)
            case "configured" | "project-name" | "module-root":
                return False


@final
class WheelVersionCheck:
    """Import each built wheel in a fresh environment and read ``__version__``.

    Static inspection cannot see dynamic bindings or lazy attributes. The
    installed module must report the release version or its PEP 440 canonical
    form.

    The modules imported are, first match wins:

    1. ``[tool.uv.build-backend] module-name`` (a string or a list);
    2. the normalized project name if it exists under the module or repo root;
    3. the sole package or module under the module root, or the sole repo-root
       package (loose Python files at the repo root may be tooling);
    4. the wheel's sole importable name when source discovery finds nothing
       or the wheel lacks the sole repo-root guess.

    An explicit name or a module-root match is not replaced by a wheel guess:
    if the wheel lacks it, the build may have dropped a package.

    Each module must be in the wheel, and must import from the wheel's own
    installed files: one that a stdlib module or another installed package of
    the same name shadows fails, and so does one with any file under its path
    overwritten since install or listed in RECORD with no hash. A module that
    defines no ``__version__`` and no ``__getattr__`` and is a plain module is
    skipped; any other reads ``__version__``, and a read that raises fails
    with a request to define ``__version__`` as a plain attribute (a lazy
    module with no version fails loudly, by design). The import runs under the
    project's ``requires-python`` when it sets one. A module that will not
    import fails the release, and one with no ``__version__`` once imported
    is skipped, with the skip recorded for the release recap.
    """

    __slots__ = ("_canonical", "_info", "_ops", "_skips", "_version")

    _info: ProjectInfo
    _version: str
    _canonical: str
    _ops: ReleaseOps
    _skips: SkipRecorder

    def __new__(
        cls,
        info: ProjectInfo,
        version: str,
        *,
        ops: ReleaseOps,
        skips: SkipRecorder,
    ) -> Self:
        """Bind project metadata and the version to verify.

        Raises:
            ReleaseError: The release version is not a valid PEP 440 version.
        """
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._ops = ops
        self._skips = skips
        self._canonical = self._canonical_release()
        return self

    def verify(self, dist: Path) -> None:
        """Verify the release version by importing from every wheel in ``dist``.

        Raises:
            ReleaseError: No wheel exists, module discovery or isolated import fails, or
                the wheel does not provide the expected version.
            subprocess.TimeoutExpired: The isolated import command timed out.
            OSError: A probe could not start or a source directory could not be read.
        """
        wheels = sorted(dist.glob("*.whl"))
        if not wheels:
            self._ops.fail(f"no wheel in {dist} to import for the __version__ check")
        for wheel in wheels:
            for module in self._modules_in(wheel):
                self._verify_wheel(wheel, module)

    def dry_run(self) -> None:
        """Report the import the check would run.

        Raises:
            ReleaseError: Project metadata is invalid or module discovery is ambiguous.
            OSError: A source directory could not be read.
        """
        modules = self.module_names() or ("<the one module the wheel ships>",)
        for module in modules:
            self._ops.dry(
                "uv run --isolated --no-project --with dist/*.whl python -I: "
                f"import {module}; __version__ == {self._version}"
            )

    def module_names(self) -> tuple[str, ...]:
        """Discover import names from project configuration and source files.

        Return an empty tuple if verification must inspect the wheel for its
        one top-level importable name.

        Raises:
            ReleaseError: Project metadata is invalid or module discovery is ambiguous.
            OSError: A source directory could not be read.
        """
        return self._choice().names

    def _choice(self) -> _ModuleChoice:
        """Discover import names and whether the result is conclusive."""
        configured = self._configured_names()
        if configured:
            return _ModuleChoice(configured, "configured")
        module_root = self._module_root()
        # An empty module-root and the repo root name the same directory.
        bases = tuple(dict.fromkeys((module_root, self._info.root)))
        name = _NORMALIZE.sub("_", self._project_name()).lower()
        if any(
            (base / name).is_dir() or (base / f"{name}.py").is_file() for base in bases
        ):
            return _ModuleChoice((name,), "project-name")
        for base in bases:
            # The repo root holds tooling scripts (noxfile.py, conftest.py),
            # so there only a package counts; a root <name>.py is accepted
            # through the project-name step above.
            modules = _top_level_modules(base, files=base != self._info.root)
            if len(modules) == 1:
                source: _Source = "module-root" if base == module_root else "repo-root"
                return _ModuleChoice(modules, source)
            if modules:
                self._ops.fail(
                    f"cannot tell which module the wheel ships: {len(modules)} "
                    f"modules under {base} ({', '.join(modules)}) and none is "
                    f"{name}; set [tool.uv.build-backend] module-name"
                )
        return _ModuleChoice((), "nothing")

    def _verify_wheel(self, wheel: Path, module: str) -> None:
        """Fail unless ``module`` imported from ``wheel`` reports the version."""
        self._require_shipped(wheel, module)
        record = self._probe(wheel, module)
        if record.kind == "unlocated":
            self._ops.fail(
                f"{wheel.name}: {module} has no file origin (replaced in "
                "sys.modules?); cannot verify it came from the wheel"
            )
        if record.in_stdlib:
            self._ops.fail(
                f"{wheel.name}: importing {module} loaded {record.origin!r}, "
                "from the standard library, not the wheel; rename the module"
            )
        if not record.from_wheel:
            self._ops.fail(
                f"{wheel.name}: importing {module} loaded {record.origin!r}, "
                f"which is not one of the files {_distribution(wheel)} installs; "
                "another installed package shadows the wheel"
            )
        match record.kind:
            case "overwritten":
                self._ops.fail(
                    f"{wheel.name}: {module} was overwritten by another installed "
                    f"distribution ({record.value!r} no longer matches the hash "
                    f"{_distribution(wheel)} recorded for it)"
                )
            case "malformed":
                self._ops.fail(
                    f"{wheel.name}: malformed RECORD: {_distribution(wheel)} lists "
                    f"the code file {record.value!r} with no hash"
                )
            case "raised":
                self._ops.fail(
                    f"{wheel.name}: reading {module}.__version__ raised "
                    f"{record.value}; define __version__ as a plain attribute"
                )
            case "absent":
                self._skips.record(
                    f"SKIPPED — {wheel.name}: {module} has no __version__ at run "
                    "time, so the runtime __version__ check did not apply"
                )
                return
            case "type":
                self._ops.fail(
                    f"{wheel.name}: {module}.__version__ is a {record.value}, not "
                    f"a string, at run time; the release version is "
                    f"{self._version!r}"
                )
            case "str" if record.value not in (self._version, self._canonical):
                self._ops.fail(
                    f"{wheel.name}: {module}.__version__ is {record.value!r} at "
                    f"run time, but the release version is {self._version!r}"
                )
            case "str":
                self._ops.ok(f"{wheel.name}: {module}.__version__ == {self._version}")

    def _contents(self, wheel: Path) -> WheelContents:
        """Inspect the wheel archive for installed import names."""
        try:
            return WheelContents.of(wheel)
        except zipfile.BadZipFile as exc:
            self._ops.fail(f"{wheel.name} is not a readable wheel: {exc}")

    def _modules_in(self, wheel: Path) -> tuple[str, ...]:
        """Choose modules from the project metadata or, failing that, the wheel.

        The wheel is read only when steps 1 to 3 found nothing, or when the
        one name came from the repo-root package scan and the wheel holds
        nothing of it: in a ``lib/`` layout that scan can land on a root
        ``tests/`` the wheel never ships. Every other name stands, and
        ``_require_shipped`` fails on it if the wheel lacks it or ships it
        without code: a configured ``module-name``, the project-name match,
        a module-root match, and a repo-root guess the wheel ships empty all
        say the build dropped the package, not that the guess was wrong.
        """
        choice = self._choice()
        contents = self._contents(wheel)
        if not choice.falls_back_to(contents):
            return choice.names
        importable = contents.top_level()
        if len(importable) != 1:
            guessed = (
                f"guessed {', '.join(choice.names)} at the repo root, which "
                f"{wheel.name} lacks"
                if choice.names
                else "gave nothing"
            )
            self._ops.fail(
                "cannot tell which module the wheel ships: no [tool.uv.build-"
                f"backend] module-name, the source tree {guessed}, and "
                f"{wheel.name} holds {len(importable)} top-level importable "
                f"names ({', '.join(importable) or 'none'}); set module-name"
            )
        return importable

    def _require_shipped(self, wheel: Path, module: str) -> None:
        """Fail unless ``wheel`` is a readable zip that ships ``module``."""
        match self._contents(wheel).shipping(module):
            case "missing":
                self._ops.fail(f"{wheel.name} does not contain {module}")
            case "empty":
                path = module.replace(".", "/")
                self._ops.fail(f"{wheel.name} ships {path}/ with no Python files")
            case "module":
                pass

    def _probe(self, wheel: Path, module: str) -> ProbeRecord:
        """Import ``module`` from ``wheel`` in isolation; the one record it gave."""
        nonce = secrets.token_hex(16)
        result = self._ops.run(
            [
                "uv",
                "run",
                "--isolated",
                "--no-project",
                "--with",
                str(wheel),
                *self._python(),
                "python",
                "-I",
                "-c",
                PROBE_SOURCE,
                module,
                nonce,
                _distribution(wheel),
            ],
            cwd=str(wheel.parent),
            timeout=UV,
            check=False,
            # The package may write any bytes while it imports.
            errors="replace",
        )
        lines = ProbeRecord.lines(result.stdout, nonce)
        if result.returncode != 0:
            raised = ProbeRecord.parse(lines[0]) if len(lines) == 1 else None
            if raised is not None and raised.kind == "raised":
                self._ops.fail(
                    f"{wheel.name}: reading {module}.__version__ raised "
                    f"{raised.value}; define __version__ as a plain attribute"
                )
            self._ops.fail(
                f"{wheel.name}: importing {module} to read __version__ failed "
                f"(release version {self._version}):\n{result.stderr.strip()}"
            )
        if len(lines) != 1:
            self._ops.fail(
                f"{wheel.name}: importing {module} gave {len(lines)} version "
                f"records, expected exactly 1 (release version {self._version})"
            )
        record = ProbeRecord.parse(lines[0])
        if record is None:
            self._ops.fail(
                f"{wheel.name}: importing {module} gave a malformed version "
                f"record {lines[0]!r} (release version {self._version})"
            )
        return record

    def _python(self) -> tuple[str, ...]:
        """``--python <requires-python>`` when the project sets one; else nothing."""
        requires = self._project().get("requires-python")
        return ("--python", requires) if isinstance(requires, str) else ()

    def _canonical_release(self) -> str:
        """Normalize the release version according to PEP 440."""
        # Version() forgives surrounding whitespace; a release version must not.
        try:
            if self._version != self._version.strip():
                raise InvalidVersion(self._version)
            return str(Version(self._version))
        except InvalidVersion:
            self._ops.fail(
                f"the release version {self._version!r} is not a PEP 440 version, "
                "so no wheel's __version__ can be checked against it"
            )

    def _configured_names(self) -> tuple[str, ...]:
        """``[tool.uv.build-backend] module-name``; empty when it is not set."""
        configured = self._build_backend().get("module-name")
        if configured is None:
            return ()
        if isinstance(configured, str):
            return (configured,)
        if isinstance(configured, list):
            names = tuple(cast("list[object]", configured))
            if names and all(isinstance(name, str) for name in names):
                return cast("tuple[str, ...]", names)
        self._ops.fail(
            "[tool.uv.build-backend] module-name is not a string or a "
            f"list of strings: {configured!r}"
        )

    def _project_name(self) -> str:
        """``[project] name``."""
        name = self._project().get("name")
        if not isinstance(name, str):
            self._ops.fail("pyproject.toml has no [project] name to find the module by")
        return name

    def _project(self) -> dict[str, object]:
        """Return the ``[project]`` table, or an empty table if absent."""
        project = (self._info.pyproject or {}).get("project")
        if not isinstance(project, dict):
            return {}
        return cast("dict[str, object]", project)

    def _module_root(self) -> Path:
        """Find the module directory specified for uv_build."""
        configured = self._build_backend().get("module-root", _DEFAULT_MODULE_ROOT)
        if not isinstance(configured, str):
            self._ops.fail(
                f"[tool.uv.build-backend] module-root is not a string: {configured!r}"
            )
        return self._info.root / configured

    def _build_backend(self) -> dict[str, object]:
        """Return the uv build-backend table, or an empty table if absent."""
        table = (self._info.pyproject or {}).get("tool")
        for key in ("uv", "build-backend"):
            if not isinstance(table, dict):
                return {}
            table = cast("dict[str, object]", table).get(key)
        if not isinstance(table, dict):
            return {}
        return cast("dict[str, object]", table)


def _top_level_modules(base: Path, *, files: bool) -> tuple[str, ...]:
    """List regular packages directly under ``base`` in sorted order.

    With ``files``, its ``.py`` modules count too.
    """
    if not base.is_dir():
        return ()
    return tuple(
        sorted(
            child.stem if child.is_file() else child.name
            for child in base.iterdir()
            if (child.is_dir() and (child / "__init__.py").is_file())
            or (files and child.is_file() and child.suffix == ".py")
        )
    )


def _distribution(wheel: Path) -> str:
    """Normalize the distribution name for a wheel filename (PEP 427)."""
    return wheel.name.split("-", 1)[0]
