"""Bump pinned versions on the release branch."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.module_version import (
    ComputedVersion,
    LiteralVersion,
    ModuleVersion,
    UnpinnableVersionError,
)
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.release_versions import ReleaseVersions
from punt_kit.phases.shared.text_file import TextFile
from punt_kit.phases.shared.timeouts import UV

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase2VersionBump:
    """Bump pinned versions on the release branch."""

    __slots__ = ("_dry_run", "_info", "_ops", "_version")

    _info: ProjectInfo
    _version: str
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(
        cls, info: ProjectInfo, version: str, *, dry_run: bool, ops: ReleaseOps
    ) -> Self:
        """Create the phase with its release inputs and operations."""
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._dry_run = dry_run
        self._ops = ops
        return self

    def _bump_init(self, path: Path) -> None:
        """Set a literal ``__version__``; leave a computed one; fail on the rest."""
        content = TextFile(path).read()
        try:
            found = ModuleVersion(content).resolved()
        except UnpinnableVersionError as exc:
            self._ops.fail(
                f"{path.name}: __version__ cannot be bumped to {self._version}: "
                f"{exc}; set it by hand"
            )
        match found:
            case None:  # the module never binds __version__
                return
            case ComputedVersion(source=source):
                # Computed versions read installed metadata; pyproject.toml is the
                # single pin.
                self._ops.info(
                    f"{path.name}: __version__ is computed — not bumped ({source})"
                )
                return
            case LiteralVersion():
                new_content = found.rewritten(content, self._version)
        if self._dry_run:
            self._ops.dry(f'{path.name}: __version__ = "{self._version}"')
        else:
            TextFile(path).write(new_content)
            self._ops.ok(f'{path.name}: __version__ = "{self._version}"')

    def _prepare_branch(self) -> GitWorkspace:
        # Refresh main before branching, including when resuming without phase 1.
        workspace = GitWorkspace(self._info.root, ops=self._ops)
        branch = f"release/v{self._version}"
        if self._dry_run:
            self._ops.dry(f"git checkout -b {branch}")
            return workspace
        workspace.ensure_on_main()
        if workspace.checkout_or_create(branch):
            self._ops.info(f"Checked out existing branch {branch}")
        else:
            self._ops.ok(f"Created branch {branch}")
        return workspace

    def run(self) -> None:
        """Bump pinned versions on the release branch.

        Raises:
            ReleaseError: Release files cannot be parsed or bumped, or git or locking
                fails.
            subprocess.CalledProcessError: A checked repository command fails.
            subprocess.TimeoutExpired: An external command exceeds its timeout.
            OSError: Writing a version pin or manifest fails.
        """
        info = self._info
        version = self._version
        dry_run = self._dry_run
        ops = self._ops
        _console.print(f"\n[bold]Phase 2: Version bump → {version}[/bold]")

        root = info.root
        project = ReleaseProject(info, ops=ops)
        versions = ReleaseVersions(version, dry_run=dry_run, ops=ops, file=TextFile)
        workspace = self._prepare_branch()

        # A present static version must be rewritten successfully before tagging.
        pyproject_path = root / "pyproject.toml"
        workspace_manifests = (
            versions.bump_pyproject(pyproject_path) if pyproject_path.exists() else []
        )

        pkg_dir = project.package_dir()
        if pkg_dir is not None:
            init_py = pkg_dir / "__init__.py"
            if init_py.exists():
                self._bump_init(init_py)

        # Non-plugin projects have no manifest; only existing files are staged.
        plugin_json = info.plugin_manifest if info.is_plugin else None
        if plugin_json is not None:
            manifest = JsonFile(plugin_json)
            data = cast("dict[str, object]", manifest.load())
            data["version"] = version
            if dry_run:
                ops.dry(f'plugin.json: version = "{version}"')
            else:
                manifest.save(data)
                ops.ok(f'plugin.json: version = "{version}"')

        install_sh = root / "install.sh"
        if install_sh.exists():
            versions.bump_install_sh(install_sh)

        changelog_path = root / "CHANGELOG.md"
        if changelog_path.exists():
            Changelog(root, ops=ops).stamp(
                version, datetime.date.today().isoformat(), dry_run=dry_run
            )

        template_pins = project.rewrite_template_pins(version, dry_run=dry_run)

        if dry_run:
            ops.dry("uv lock (refresh lock file)")
            ops.dry(f'git commit -m "chore: release v{version}"')
            return

        lock_file = root / "uv.lock"
        if lock_file.exists():
            # Stream resolver output so a failure's diagnosis refers to visible output.
            lock_result = ops.run(
                ["uv", "lock"], cwd=str(root), capture=False, check=False, timeout=UV
            )
            if lock_result.returncode != 0:
                ops.fail("uv lock failed — see output above")
            ops.ok("uv.lock refreshed")
        # Stage only release files; git add -A could include unrelated untracked files.
        release_files = [pyproject_path, changelog_path, install_sh, lock_file]
        if plugin_json is not None:
            release_files.append(plugin_json)
        if pkg_dir is not None:
            release_files.append(pkg_dir / "__init__.py")
        release_files.extend(template_pins)
        release_files.extend(workspace_manifests)
        to_stage = [str(p.relative_to(root)) for p in release_files if p.exists()]
        if workspace.commit_if_staged(to_stage, f"chore: release v{version}"):
            ops.ok("Release commit created")
        else:
            ops.ok("Release commit already exists (resume)")
