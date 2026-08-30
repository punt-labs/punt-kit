"""Phase 2: bump the version everywhere it's pinned, on the release branch."""

from __future__ import annotations

import datetime
import json
import re
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.timeouts import UV

if TYPE_CHECKING:
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

        # 2b. Bump version in pyproject.toml
        pyproject_path = root / "pyproject.toml"
        if pyproject_path.exists():
            content = pyproject_path.read_text(encoding="utf-8")
            new_content = re.sub(
                r'^(version\s*=\s*")[^"]*(")',
                rf"\g<1>{version}\2",
                content,
                count=1,
                flags=re.MULTILINE,
            )
            if dry_run:
                ops.dry(f'pyproject.toml: version = "{version}"')
            else:
                pyproject_path.write_text(new_content, encoding="utf-8")
                ops.ok(f'pyproject.toml: version = "{version}"')

        # Bump __init__.py __version__ (skip if version comes from
        # importlib.metadata)
        pkg_dir = project.package_dir()
        if pkg_dir is not None:
            init_py = pkg_dir / "__init__.py"
            if init_py.exists():
                content = init_py.read_text(encoding="utf-8")
                uses_metadata = (
                    "importlib.metadata" in content or "importlib_metadata" in content
                )
                if "__version__" in content and not uses_metadata:
                    new_content = re.sub(
                        r'^(__version__\s*=\s*")[^"]*(")',
                        rf"\g<1>{version}\2",
                        content,
                        count=1,
                        flags=re.MULTILINE,
                    )
                    if dry_run:
                        ops.dry(f'{init_py.name}: __version__ = "{version}"')
                    else:
                        init_py.write_text(new_content, encoding="utf-8")
                        ops.ok(f'{init_py.name}: __version__ = "{version}"')

        # Bump plugin.json version. None for a non-plugin project — absence
        # is the contract, and 2d below stages only the files that exist.
        plugin_json = info.plugin_manifest if info.is_plugin else None
        if plugin_json is not None:
            data = json.loads(plugin_json.read_text(encoding="utf-8"))
            data["version"] = version
            if dry_run:
                ops.dry(f'plugin.json: version = "{version}"')
            else:
                plugin_json.write_text(
                    json.dumps(data, indent=2) + "\n", encoding="utf-8"
                )
                ops.ok(f'plugin.json: version = "{version}"')

        # Bump install.sh VERSION pin
        install_sh = root / "install.sh"
        if install_sh.exists():
            content = install_sh.read_text(encoding="utf-8")
            new_content = re.sub(
                r'^(VERSION=")[^"]*(")',
                rf"\g<1>{version}\2",
                content,
                count=1,
                flags=re.MULTILINE,
            )
            if new_content != content:
                if dry_run:
                    ops.dry(f'install.sh: VERSION="{version}"')
                else:
                    install_sh.write_text(new_content, encoding="utf-8")
                    ops.ok(f'install.sh: VERSION="{version}"')

        # 2c. Update CHANGELOG.md
        changelog_path = root / "CHANGELOG.md"
        if changelog_path.exists():
            today = datetime.date.today().isoformat()
            content = changelog_path.read_text(encoding="utf-8")
            new_content = content.replace(
                "## [Unreleased]",
                f"## [Unreleased]\n\n## [{version}] - {today}",
                1,
            )
            if dry_run:
                ops.dry(f"CHANGELOG.md: [Unreleased] → [{version}] - {today}")
            else:
                changelog_path.write_text(new_content, encoding="utf-8")
                ops.ok(f"CHANGELOG.md: [{version}] - {today}")

        # 2d. Rewrite self-referential template pins
        template_pins = project.rewrite_template_pins(version, dry_run=dry_run)

        # 2e. Refresh lock file and commit
        if dry_run:
            ops.dry("uv lock (refresh lock file)")
            ops.dry(f'git commit -m "chore: release v{version}"')
            return

        lock_file = root / "uv.lock"
        if lock_file.exists():
            ops.run(["uv", "lock"], cwd=str(root), timeout=UV)
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
