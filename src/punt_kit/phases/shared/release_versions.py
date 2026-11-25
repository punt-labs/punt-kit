"""Bump static versions in release project files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, cast, final

from punt_kit.phases.shared.version_assignment import VersionAssignment
from punt_kit.phases.shared.workspace_versions import WorkspaceVersions

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


class _VersionFile(Protocol):
    def read(self) -> str:
        """Read versioned text without normalizing line endings."""
        ...

    def write(self, text: str) -> None:
        """Write the new versioned text."""
        ...

    @staticmethod
    def parse_toml(text: str, *, source: str) -> dict[str, object]:
        """Parse the root manifest with a diagnostic on invalid TOML."""
        ...


@final
class ReleaseVersions:
    """Bump static versions in Python manifests and the install script."""

    __slots__ = ("_dry_run", "_file", "_ops", "_version")

    _dry_run: bool
    _file: Callable[[Path], _VersionFile]
    _ops: ReleaseOps
    _version: str

    def __new__(
        cls,
        version: str,
        *,
        dry_run: bool,
        ops: ReleaseOps,
        file: Callable[[Path], _VersionFile],
    ) -> Self:
        """Bind the target version and release operations."""
        self = super().__new__(cls)
        self._version = version
        self._dry_run = dry_run
        self._ops = ops
        self._file = file
        return self

    @staticmethod
    def _project_version(manifest: dict[str, object]) -> object:
        project = manifest.get("project")
        if isinstance(project, dict):
            return cast("dict[str, object]", project).get("version")
        return None

    def bump_pyproject(self, path: Path) -> list[Path]:
        """Bump the manifest, returning additional workspace paths to commit.

        Raises:
            ReleaseError: A manifest cannot be read or updated.
            OSError: A manifest cannot be written.
        """
        file = self._file(path)
        content = file.read()
        manifest = file.parse_toml(content, source="pyproject.toml")
        current = self._project_version(manifest)
        if current is None:
            self._ops.info("pyproject.toml: no static version field — not bumped")
            return []
        workspace = WorkspaceVersions.from_manifest(
            path.parent, manifest, read=lambda member: self._file(member).read()
        )
        if workspace is not None and isinstance(current, str):
            return self._bump_workspace(path.parent, workspace, content, current)
        self._bump_single(file, content)
        return []

    def _bump_single(self, file: _VersionFile, content: str) -> None:
        new_content, count = VersionAssignment("version").rewritten(
            content, self._version
        )
        rewritten = (
            self._project_version(file.parse_toml(new_content, source="pyproject.toml"))
            if count
            else None
        )
        if rewritten != self._version:
            self._ops.fail(
                "pyproject.toml: [project] version is present but is not a line "
                f'of the form version = "X.Y.Z", so it cannot be bumped to '
                f"{self._version}; set it by hand"
            )
        if self._dry_run:
            self._ops.dry(f'pyproject.toml: version = "{self._version}"')
        else:
            file.write(new_content)
            self._ops.ok(f'pyproject.toml: version = "{self._version}"')

    def _bump_workspace(
        self, root: Path, workspace: WorkspaceVersions, content: str, current: str
    ) -> list[Path]:
        def previous(path: Path) -> str | None:
            return self._committed_version(root, path)

        if current == self._version:
            current = previous(root / "pyproject.toml") or current
        rewrites = workspace.rewrites(content, current, self._version, previous)
        for path, updated in rewrites.items():
            message = f"{path.relative_to(root)}: synchronize with {self._version}"
            if self._dry_run:
                self._ops.dry(message)
            elif current != self._version:
                self._file(path).write(updated)
                self._ops.ok(message)
        return [path for path in rewrites if path.parent != root]

    def _committed_version(self, root: Path, path: Path) -> str | None:
        ref = f"HEAD:{path.relative_to(root).as_posix()}"
        result = self._ops.run(["git", "show", ref], cwd=str(root), check=False)
        if result.returncode != 0:
            return None
        manifest = self._file(path).parse_toml(
            result.stdout.removeprefix("\ufeff"), source=ref
        )
        version = self._project_version(manifest)
        return version if isinstance(version, str) else None

    def bump_install_sh(self, path: Path) -> None:
        """Set ``VERSION``; fail when it is assigned but cannot be set."""
        file = self._file(path)
        content = file.read()
        assignment = VersionAssignment.in_shell("VERSION")
        new_content, count = assignment.rewritten(content, self._version)
        if count == 0 and assignment.assigns_a_value(content):
            self._ops.fail(
                f"install.sh: `{assignment.computed_lines(content)[0]}` is not a plain "
                f'quoted string (VERSION="X.Y.Z"), so VERSION cannot be bumped to '
                f"{self._version}; set it by hand"
            )
        if count == 0 and assignment.is_assigned(content):
            self._ops.warn(
                "install.sh: VERSION is only ever reset to empty, so there is "
                f"nothing to bump to {self._version}"
            )
        if len(lines := assignment.assigned_lines(content)) > 1:
            shown = "; ".join(assignment.described_lines(content))
            self._ops.warn(
                f"install.sh: VERSION is assigned on {len(lines)} lines ({shown}); "
                f"every plain one is bumped to {self._version}, but a "
                "branch or a computed value may change which takes effect"
            )
        if new_content == content:
            return
        if self._dry_run:
            self._ops.dry(f'install.sh: VERSION="{self._version}"')
        else:
            file.write(new_content)
            self._ops.ok(f'install.sh: VERSION="{self._version}"')
