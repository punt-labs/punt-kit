"""Phase 2: bump the version everywhere it's pinned, on the release branch."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Self, cast, final

from rich.console import Console

from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.text_file import TextFile
from punt_kit.phases.shared.timeouts import UV
from punt_kit.phases.shared.version_assignment import VersionAssignment

if TYPE_CHECKING:
    from pathlib import Path

    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase2VersionBump:
    """Phase 2: bump version on release branch."""

    __slots__ = ("_dry_run", "_info", "_ops", "_version")

    _info: ProjectInfo
    _version: str
    _dry_run: bool
    _ops: ReleaseOps

    def __new__(
        cls, info: ProjectInfo, version: str, *, dry_run: bool, ops: ReleaseOps
    ) -> Self:
        self = super().__new__(cls)
        self._info = info
        self._version = version
        self._dry_run = dry_run
        self._ops = ops
        return self

    @staticmethod
    def _project_version(toml_text: str) -> object:
        """``[project] version`` of ``toml_text``; ``None`` when there is none."""
        project = TextFile.parse_toml(toml_text, source="pyproject.toml").get("project")
        if isinstance(project, dict):
            return cast("dict[str, object]", project).get("version")
        return None

    def _bump_pyproject(self, path: Path) -> None:
        """Set ``[project] version``; fail when it is there but cannot be set."""
        content = TextFile(path).read()
        if self._project_version(content) is None:
            self._ops.info("pyproject.toml: no static version field — not bumped")
            return
        new_content, count = VersionAssignment("version").rewritten(
            content, self._version
        )
        rewritten = self._project_version(new_content) if count else None
        if rewritten != self._version:
            self._ops.fail(
                "pyproject.toml: [project] version is present but is not a line "
                f'of the form version = "X.Y.Z", so it cannot be bumped to '
                f"{self._version}; set it by hand"
            )
        if self._dry_run:
            self._ops.dry(f'pyproject.toml: version = "{self._version}"')
        else:
            TextFile(path).write(new_content)
            self._ops.ok(f'pyproject.toml: version = "{self._version}"')

    def _bump_init(self, path: Path) -> None:
        """Set ``__version__``; fail when it is assigned but cannot be set."""
        content = TextFile(path).read()
        uses_metadata = (
            "importlib.metadata" in content or "importlib_metadata" in content
        )
        assignment = VersionAssignment("__version__")
        if uses_metadata or not assignment.is_assigned(content):
            return
        new_content, count = assignment.rewritten(content, self._version)
        if count == 0:
            self._ops.fail(
                f"{path.name}: __version__ is assigned but not as a plain quoted "
                f'string (__version__ = "X.Y.Z"), so it cannot be bumped to '
                f"{self._version}; set it by hand"
            )
        if self._dry_run:
            self._ops.dry(f'{path.name}: __version__ = "{self._version}"')
        else:
            TextFile(path).write(new_content)
            self._ops.ok(f'{path.name}: __version__ = "{self._version}"')

    def _bump_install_sh(self, path: Path) -> None:
        """Set ``VERSION``; fail when it is assigned but cannot be set."""
        content = TextFile(path).read()
        assignment = VersionAssignment.in_shell("VERSION")
        new_content, count = assignment.rewritten(content, self._version)
        if count == 0 and assignment.is_assigned(content):
            self._ops.fail(
                f"install.sh: `{assignment.assigned_lines(content)[0]}` is not a plain "
                f'quoted string (VERSION="X.Y.Z"), so VERSION cannot be bumped to '
                f"{self._version}; set it by hand"
            )
        if len(lines := assignment.assigned_lines(content)) > 1:
            shown = "; ".join(f"`{line}`" for line in lines)
            self._ops.warn(
                f"install.sh: VERSION is assigned on {len(lines)} lines ({shown}); "
                f"every plain one is bumped to {self._version}, but a heredoc, a "
                "branch or a computed value may change which takes effect"
            )
        if new_content == content:
            return
        if self._dry_run:
            self._ops.dry(f'install.sh: VERSION="{self._version}"')
        else:
            TextFile(path).write(new_content)
            self._ops.ok(f'install.sh: VERSION="{self._version}"')

    def run(self) -> None:
        info = self._info
        version = self._version
        dry_run = self._dry_run
        ops = self._ops
        _console.print(f"\n[bold]Phase 2: Version bump → {version}[/bold]")

        root = info.root
        branch = f"release/v{version}"
        project = ReleaseProject(info, ops=ops)
        workspace = GitWorkspace(root, ops=ops)

        # Create release branch. Ensure main is checked out and current
        # first — a `--resume-from bump` that skips phase 1 can otherwise
        # leave the release branch rooted on whatever stale commit happened
        # to be checked out.
        if dry_run:
            ops.dry(f"git checkout -b {branch}")
        else:
            workspace.ensure_on_main()
            if workspace.checkout_or_create(branch):
                ops.info(f"Checked out existing branch {branch}")
            else:
                ops.ok(f"Created branch {branch}")

        # 2b. Bump version in pyproject.toml. A present version field that the
        # rewrite does not change is a failure: printing ok for a no-op would
        # tag a release whose pyproject still names the previous version.
        pyproject_path = root / "pyproject.toml"
        if pyproject_path.exists():
            self._bump_pyproject(pyproject_path)

        # Bump __init__.py __version__ (skip if version comes from
        # importlib.metadata)
        pkg_dir = project.package_dir()
        if pkg_dir is not None:
            init_py = pkg_dir / "__init__.py"
            if init_py.exists():
                self._bump_init(init_py)

        # Bump plugin.json version. None for a non-plugin project — absence
        # is the contract, and 2d below stages only the files that exist.
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

        # Bump install.sh VERSION pin
        install_sh = root / "install.sh"
        if install_sh.exists():
            self._bump_install_sh(install_sh)

        # 2c. Update CHANGELOG.md
        changelog_path = root / "CHANGELOG.md"
        if changelog_path.exists():
            Changelog(root, ops=ops).stamp(
                version, datetime.date.today().isoformat(), dry_run=dry_run
            )

        # 2d. Rewrite self-referential template pins
        template_pins = project.rewrite_template_pins(version, dry_run=dry_run)

        # 2e. Refresh lock file and commit
        if dry_run:
            ops.dry("uv lock (refresh lock file)")
            ops.dry(f'git commit -m "chore: release v{version}"')
            return

        lock_file = root / "uv.lock"
        if lock_file.exists():
            # A network resolver op: check=False, and a non-zero exit becomes
            # a diagnosed fail. capture=False streams the resolver's own
            # output to the terminal as it runs, matching `uv build` and the
            # quality gates, so the "see output above" message points at
            # output that was actually shown.
            lock_result = ops.run(
                ["uv", "lock"], cwd=str(root), capture=False, check=False, timeout=UV
            )
            if lock_result.returncode != 0:
                ops.fail("uv lock failed — see output above")
            ops.ok("uv.lock refreshed")
        # Stage only the files this phase edits — `git add -A` would sweep
        # unrelated untracked files into the release commit.
        release_files = [pyproject_path, changelog_path, install_sh, lock_file]
        if plugin_json is not None:
            release_files.append(plugin_json)
        if pkg_dir is not None:
            release_files.append(pkg_dir / "__init__.py")
        release_files.extend(template_pins)
        to_stage = [str(p.relative_to(root)) for p in release_files if p.exists()]
        if workspace.commit_if_staged(to_stage, f"chore: release v{version}"):
            ops.ok("Release commit created")
        else:
            ops.ok("Release commit already exists (resume)")
