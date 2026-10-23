"""Phase 11: the version recorded in every file that pins the release version."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.phase11_checks import VerificationCheck
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.text_file import TextFile
from punt_kit.phases.shared.version_assignment import VersionAssignment

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps


@final
class VersionPinChecks:
    """One verdict per file that pins the release version, read fresh from disk.

    ``info.pyproject`` is stale after Phase 2 bumps the version, so every file
    is read again here.
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

    def checks(self) -> list[VerificationCheck]:
        """The verdicts for pyproject.toml, __init__.py, plugin.json and install.sh."""
        return [
            *self._pyproject(),
            *self._init_py(),
            *self._plugin_json(),
            *self._install_sh(),
        ]

    def _pyproject(self) -> list[VerificationCheck]:
        path = self._info.root / "pyproject.toml"
        if not path.exists():
            return []
        current = VersionAssignment("version").read(TextFile(path).read())
        shown = current or "not found"
        return [
            VerificationCheck(
                "pyproject.toml", shown == self._version, f"version={shown}"
            )
        ]

    def _init_py(self) -> list[VerificationCheck]:
        pkg_dir = ReleaseProject(self._info, ops=self._ops).package_dir()
        if pkg_dir is None or not (pkg_dir / "__init__.py").exists():
            return []
        content = TextFile(pkg_dir / "__init__.py").read()
        uses_metadata = (
            "importlib.metadata" in content or "importlib_metadata" in content
        )
        assignment = VersionAssignment("__version__")
        if uses_metadata or not assignment.is_assigned(content):
            return []
        init_ver = assignment.read(content)
        if init_ver is None:
            return [
                VerificationCheck(
                    "__init__.py",
                    False,
                    "__version__ is assigned but not as a plain quoted string, "
                    "so it cannot be verified",
                )
            ]
        return [
            VerificationCheck(
                "__init__.py", init_ver == self._version, f"__version__={init_ver}"
            )
        ]

    def _plugin_json(self) -> list[VerificationCheck]:
        if not self._info.is_plugin:
            return []
        pj_data = JsonFile(self._info.plugin_manifest).load_object()
        pj_ver = pj_data.get("version", "not found")
        return [
            VerificationCheck(
                "plugin.json", pj_ver == self._version, f"version={pj_ver}"
            )
        ]

    def _install_sh(self) -> list[VerificationCheck]:
        install_sh = self._info.root / "install.sh"
        if not install_sh.exists():
            return []
        match = re.search(r'VERSION="([^"]*)"', TextFile(install_sh).read())
        if not match:
            return []
        install_ver = match.group(1)
        return [
            VerificationCheck(
                "install.sh", install_ver == self._version, f"VERSION={install_ver}"
            )
        ]
