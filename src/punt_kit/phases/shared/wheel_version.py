"""The ``__version__`` a built wheel reports when its package is imported."""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, NoReturn, Self, cast, final

from packaging.version import InvalidVersion, Version

from punt_kit.phases.shared.timeouts import UV

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.skips import SkipRecorder

# The probe frames its one answer as a record no ordinary output starts with.
_RECORD = "\x00PUNT_VERSION"
_VALUE = f"{_RECORD}="
_ABSENT = f"{_RECORD} absent"
# Run inside the isolated interpreter. The module name arrives as an argument,
# never spliced into the code. The record goes straight to file descriptor 1,
# after a newline so it starts its own line, and ``os._exit`` ends the process
# before atexit handlers or buffered ``sys.stdout`` output can add to it.
# ``ascii`` keeps the value literal-evaluable whatever the output encoding.
_PROBE = (
    "import importlib, os, sys\n"
    "module = importlib.import_module(sys.argv[1])\n"
    "missing = object()\n"
    "value = getattr(module, '__version__', missing)\n"
    f"record = {_ABSENT!r} if value is missing else {_VALUE!r} + ascii(value)\n"
    "os.write(1, ('\\n' + record + '\\n').encode('ascii'))\n"
    "os._exit(0)\n"
)
# uv_build's default when [tool.uv.build-backend] sets no module-root.
_DEFAULT_MODULE_ROOT = "src"
# uv_build's default module-name: the project name, lowercased, with each run
# of "-", "_" and "." turned into "_".
_NORMALIZE = re.compile(r"[-_.]+")


@final
class WheelVersionCheck:
    """Import each built wheel in a fresh environment and read ``__version__``.

    ``ModuleVersion`` reads ``__version__`` from the syntax tree, so it cannot
    see a ``globals()``, ``vars()``, ``setattr`` or ``exec`` binding, a PEP 562
    ``__getattr__``, a monkeypatched reader, or a helper module that returns a
    stale literal. Importing the wheel the release is about to publish can,
    so the syntax tree has no say here: every module is imported, and the
    version it reports must equal the release version under PEP 440.

    The modules imported are, first match wins:

    1. ``[tool.uv.build-backend] module-name`` (a string or a list);
    2. the project name normalized as uv does (``Punt-Kit`` is ``punt_kit``),
       when that directory exists under the module root (``module-root``,
       default ``src``) or, for a flat layout, the repo root;
    3. the one package under the module root, or, when it holds none, the one
       package at the repo root.

    Anything else fails, naming what was searched. The import always runs
    against the installed wheel, never the source tree: a module that will
    not import fails the release, and one with no ``__version__`` once
    imported is skipped, with the skip recorded for the release recap.
    """

    __slots__ = ("_info", "_ops", "_skips", "_version")

    _info: ProjectInfo
    _version: str
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
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._ops = ops
        self._skips = skips
        return self

    def verify(self, dist: Path) -> None:
        """Fail unless every wheel in ``dist`` reports the release version."""
        modules = self.module_names()
        wheels = sorted(dist.glob("*.whl"))
        if not wheels:
            self._ops.fail(f"no wheel in {dist} to import for the __version__ check")
        for wheel in wheels:
            for module in modules:
                self._verify_wheel(wheel, module)

    def dry_run(self) -> None:
        """Report the import the check would run."""
        for module in self.module_names():
            self._ops.dry(
                "uv run --isolated --no-project --with dist/*.whl python -I: "
                f"import {module}; __version__ == {self._version}"
            )

    def module_names(self) -> tuple[str, ...]:
        """The import names the wheel ships; see the class docstring for the order."""
        configured = self._configured_names()
        if configured:
            return configured
        # The module root first, then the repo root for a flat layout; one
        # entry when module-root is "" and the two are the same directory.
        bases = tuple(dict.fromkeys((self._module_root(), self._info.root)))
        name = _NORMALIZE.sub("_", self._project_name()).lower()
        if any((base / name).is_dir() for base in bases):
            return (name,)
        for base in bases:
            packages = _packages(base)
            if len(packages) == 1:
                return packages
            if packages:
                self._ops.fail(
                    f"cannot tell which module the wheel ships: {len(packages)} "
                    f"packages under {base} ({', '.join(packages)}) and none is "
                    f"{name}; set [tool.uv.build-backend] module-name"
                )
        searched = " or ".join(str(base) for base in bases)
        self._ops.fail(
            "cannot tell which module the wheel ships: no [tool.uv.build-backend] "
            f"module-name, no {name} directory, and no package under {searched}; "
            "set [tool.uv.build-backend] module-name"
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
        project = (self._info.pyproject or {}).get("project")
        name = (
            cast("dict[str, object]", project).get("name")
            if isinstance(project, dict)
            else None
        )
        if not isinstance(name, str):
            self._ops.fail("pyproject.toml has no [project] name to find the module by")
        return name

    def _verify_wheel(self, wheel: Path, module: str) -> None:
        """Fail unless ``module`` imported from ``wheel`` reports the version."""
        result = self._ops.run(
            [
                "uv",
                "run",
                "--isolated",
                "--no-project",
                "--with",
                str(wheel),
                "python",
                "-I",
                "-c",
                _PROBE,
                module,
            ],
            cwd=str(wheel.parent),
            timeout=UV,
            check=False,
        )
        if result.returncode != 0:
            self._ops.fail(
                f"{wheel.name}: importing {module} to read __version__ failed "
                f"(release version {self._version}):\n{result.stderr.strip()}"
            )
        records = [
            line for line in result.stdout.split("\n") if line.startswith(_RECORD)
        ]
        if len(records) != 1:
            self._ops.fail(
                f"{wheel.name}: importing {module} gave {len(records)} version "
                f"records, expected exactly 1 (release version {self._version})"
            )
        [record] = records
        if record == _ABSENT:
            self._skips.record(
                f"SKIPPED — {wheel.name}: {module} has no __version__ at run "
                "time, so the runtime __version__ check did not apply"
            )
            return
        found = self._reported(record, wheel, module)
        if self._parsed(found, wheel, module) != self._parsed(
            self._version, wheel, module
        ):
            self._ops.fail(
                f"{wheel.name}: {module}.__version__ is {found!r} at run time, "
                f"but the release version is {self._version!r}"
            )
        self._ops.ok(f"{wheel.name}: {module}.__version__ == {self._version}")

    def _reported(self, record: str, wheel: Path, module: str) -> str:
        """The ``__version__`` string ``record`` carries; fail on anything else."""
        payload = record.removeprefix(_VALUE)
        value: object = None
        if record.startswith(_VALUE):
            try:
                value = ast.literal_eval(payload)
            except (ValueError, SyntaxError):
                value = None
        if not isinstance(value, str):
            self._ops.fail(
                f"{wheel.name}: {module}.__version__ is not a string at run time "
                f"({payload}); the release version is {self._version!r}"
            )
        return value

    def _parsed(self, text: str, wheel: Path, module: str) -> Version:
        """``text`` as a PEP 440 version, exactly as written; fail otherwise."""
        # Version() forgives surrounding whitespace; a release must not.
        if text != text.strip():
            self._not_a_version(text, wheel, module)
        try:
            return Version(text)
        except InvalidVersion:
            self._not_a_version(text, wheel, module)

    def _not_a_version(self, text: str, wheel: Path, module: str) -> NoReturn:
        self._ops.fail(
            f"{wheel.name}: {module}.__version__ check: {text!r} is not a PEP 440 "
            f"version (release version {self._version!r})"
        )

    def _module_root(self) -> Path:
        """The directory uv_build finds the module in."""
        configured = self._build_backend().get("module-root", _DEFAULT_MODULE_ROOT)
        if not isinstance(configured, str):
            self._ops.fail(
                f"[tool.uv.build-backend] module-root is not a string: {configured!r}"
            )
        return self._info.root / configured

    def _build_backend(self) -> dict[str, object]:
        """The ``[tool.uv.build-backend]`` table; empty when absent."""
        table = (self._info.pyproject or {}).get("tool")
        for key in ("uv", "build-backend"):
            if not isinstance(table, dict):
                return {}
            table = cast("dict[str, object]", table).get(key)
        if not isinstance(table, dict):
            return {}
        return cast("dict[str, object]", table)


def _packages(base: Path) -> tuple[str, ...]:
    """The regular packages directly under ``base``, sorted; empty if none."""
    if not base.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in base.iterdir()
            if child.is_dir() and (child / "__init__.py").is_file()
        )
    )
