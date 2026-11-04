"""The ``__version__`` a built wheel reports when its package is imported."""

from __future__ import annotations

import re
import secrets
import zipfile
from typing import TYPE_CHECKING, Self, cast, final

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


@final
class WheelVersionCheck:
    """Import each built wheel in a fresh environment and read ``__version__``.

    ``ModuleVersion`` reads ``__version__`` from the syntax tree, so it cannot
    see a ``globals()``, ``vars()``, ``setattr`` or ``exec`` binding, a PEP 562
    ``__getattr__``, a monkeypatched reader, or a helper module that returns a
    stale literal. Importing the wheel the release is about to publish can,
    so the syntax tree has no say here: every module is imported, and the
    version it reports must be the release version exactly as written, or its
    PEP 440 canonical form (``1.0.0rc1`` for a ``1.0.0-rc1`` release).

    The modules imported are, first match wins:

    1. ``[tool.uv.build-backend] module-name`` (a string or a list);
    2. the project name normalized as uv does (``Punt-Kit`` is ``punt_kit``),
       when that directory or ``.py`` file exists under the module root
       (``module-root``, default ``src``) or, for a flat layout, the repo root;
    3. the one package or ``.py`` module under the module root, or, when it
       holds none, the one at the repo root.

    Anything else fails, naming what was searched. Steps 2 and 3 name one
    module, so a wheel shipping several top-level packages has only that one
    checked unless ``module-name`` lists them all.

    Each module must be in the wheel, and must import from the wheel's own
    installed files: one that a stdlib module or another installed package of
    the same name shadows fails. The import runs under the
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
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._ops = ops
        self._skips = skips
        self._canonical = self._canonical_release()
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
        if any(
            (base / name).is_dir() or (base / f"{name}.py").is_file() for base in bases
        ):
            return (name,)
        for base in bases:
            modules = _top_level_modules(base)
            if len(modules) == 1:
                return modules
            if modules:
                self._ops.fail(
                    f"cannot tell which module the wheel ships: {len(modules)} "
                    f"modules under {base} ({', '.join(modules)}) and none is "
                    f"{name}; set [tool.uv.build-backend] module-name"
                )
        searched = " or ".join(str(base) for base in bases)
        self._ops.fail(
            "cannot tell which module the wheel ships: no [tool.uv.build-backend] "
            f"module-name, no {name} package or module, and nothing under "
            f"{searched}; set [tool.uv.build-backend] module-name"
        )

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

    def _require_shipped(self, wheel: Path, module: str) -> None:
        """Fail unless ``wheel`` is a readable zip that ships ``module``."""
        try:
            contents = WheelContents.of(wheel)
        except zipfile.BadZipFile as exc:
            self._ops.fail(f"{wheel.name} is not a readable wheel: {exc}")
        match contents.shipping(module):
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
        if result.returncode != 0:
            self._ops.fail(
                f"{wheel.name}: importing {module} to read __version__ failed "
                f"(release version {self._version}):\n{result.stderr.strip()}"
            )
        lines = ProbeRecord.lines(result.stdout, nonce)
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
        """The release version's PEP 440 canonical form; fail if it has none."""
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
        """The ``[project]`` table; empty when absent."""
        project = (self._info.pyproject or {}).get("project")
        if not isinstance(project, dict):
            return {}
        return cast("dict[str, object]", project)

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


def _top_level_modules(base: Path) -> tuple[str, ...]:
    """The regular packages and ``.py`` modules directly under ``base``, sorted."""
    if not base.is_dir():
        return ()
    return tuple(
        sorted(
            child.stem if child.is_file() else child.name
            for child in base.iterdir()
            if (child.is_dir() and (child / "__init__.py").is_file())
            or (child.is_file() and child.suffix == ".py")
        )
    )


def _distribution(wheel: Path) -> str:
    """The distribution name a wheel's filename starts with (PEP 427)."""
    return wheel.name.split("-", 1)[0]
