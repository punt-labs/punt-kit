"""The ``__version__`` a built wheel reports when its package is imported."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.phases.shared.module_version import (
    ModuleVersion,
    UnpinnableVersionError,
)
from punt_kit.phases.shared.text_file import TextFile
from punt_kit.phases.shared.timeouts import UV

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

# Run inside the isolated interpreter. The module name arrives as an argument,
# never spliced into the code, and the version is the last line printed so
# anything the package prints on import cannot be mistaken for it.
_PROBE = (
    "import importlib, sys; "
    "print(); print(importlib.import_module(sys.argv[1]).__version__)"
)
# uv_build's default when [tool.uv.build-backend] sets no module-root.
_DEFAULT_MODULE_ROOT = "src"


@final
class WheelVersionCheck:
    """Import each built wheel in a fresh environment and read ``__version__``.

    ``ModuleVersion`` reads ``__version__`` from the syntax tree, so it cannot
    see a monkeypatched reader, a ``globals()`` or ``setattr`` rebind, or a
    helper module that returns a stale literal. Importing the wheel the
    release is about to publish can: the version the package reports at run
    time must equal the release version.

    The module imported is ``[tool.uv.build-backend] module-name`` (a string
    or a list), found under its ``module-root`` (default ``src``); with no
    module-name, the one package under the module root. A module whose
    ``__init__.py`` binds no ``__version__`` is skipped, and the skip is
    reported. A project with no ``pyproject.toml`` is not checked.
    """

    __slots__ = ("_info", "_ops", "_version")

    _info: ProjectInfo
    _version: str
    _ops: ReleaseOps

    def __new__(cls, info: ProjectInfo, version: str, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._ops = ops
        return self

    def verify(self, dist: Path) -> None:
        """Fail unless every wheel in ``dist`` reports the release version."""
        if self._info.pyproject is None:
            return
        modules = [name for name in self._module_names() if self._binds_version(name)]
        if not modules:
            return
        wheels = sorted(dist.glob("*.whl"))
        if not wheels:
            self._ops.fail(f"no wheel in {dist} to import for the __version__ check")
        for wheel in wheels:
            for module in modules:
                self._verify_wheel(wheel, module)

    def dry_run(self) -> None:
        """Report the import the check would run."""
        if self._info.pyproject is None:
            return
        for module in self._module_names():
            self._ops.dry(
                f"uv run --isolated --no-project --with dist/*.whl python -I: "
                f"import {module}; __version__ == {self._version}"
            )

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
        lines = result.stdout.strip().splitlines()
        found = lines[-1].strip() if lines else ""
        if found != self._version:
            self._ops.fail(
                f"{wheel.name}: {module}.__version__ is {found!r} at run time, "
                f"but the release version is {self._version!r}"
            )
        self._ops.ok(f"{wheel.name}: {module}.__version__ == {self._version}")

    def _binds_version(self, module: str) -> bool:
        """Whether ``module``'s ``__init__.py`` binds ``__version__``; report a skip."""
        init_py = self._module_root().joinpath(*module.split("."), "__init__.py")
        if not init_py.is_file():
            self._ops.info(
                f"{module}: no {init_py} — runtime __version__ check skipped"
            )
            return False
        try:
            found = ModuleVersion(TextFile(init_py).read()).resolved()
        except UnpinnableVersionError:
            # Bound, in a shape the syntax tree cannot classify: the import is
            # the only evidence left, so it runs.
            return True
        if found is None:
            self._ops.info(
                f"{module}: no __version__ binding — runtime __version__ check skipped"
            )
            return False
        return True

    def _module_names(self) -> tuple[str, ...]:
        """The import names the wheel ships, from config or the module root."""
        configured = self._build_backend().get("module-name")
        if isinstance(configured, str):
            return (configured,)
        if isinstance(configured, list):
            names = tuple(cast("list[object]", configured))
            if names and all(isinstance(name, str) for name in names):
                return cast("tuple[str, ...]", names)
        if configured is not None:
            self._ops.fail(
                "[tool.uv.build-backend] module-name is not a string or a "
                f"list of strings: {configured!r}"
            )
        root = self._module_root()
        packages = (
            sorted(
                child.name
                for child in root.iterdir()
                if child.is_dir() and (child / "__init__.py").is_file()
            )
            if root.is_dir()
            else []
        )
        if len(packages) != 1:
            found = ", ".join(packages) or "none"
            self._ops.fail(
                f"cannot tell which module the wheel ships: {len(packages)} "
                f"packages under {root.name}/ ({found}); set "
                "[tool.uv.build-backend] module-name"
            )
        return (packages[0],)

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
