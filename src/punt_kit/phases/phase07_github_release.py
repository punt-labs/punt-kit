"""Phase 7: create the GitHub release for a tagged version."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.changelog import Changelog, extract_version_notes

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase7GithubRelease:
    """Phase 7: create GitHub release."""

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
        ops = self._ops
        _console.print(f"\n[bold]Phase 7: GitHub release v{version}[/bold]")

        tag = f"v{version}"

        if self._dry_run:
            ops.dry(f'gh release create {tag} --title "{tag}" --notes "..."')
            return

        gh = shutil.which("gh")
        if gh is None:
            ops.fail("gh CLI not found")

        # Check if CI already created the release (e.g., Go projects use
        # softprops/action-gh-release in their release workflow).
        existing = ops.run(
            [gh, "release", "view", tag],
            cwd=str(info.root),
            check=False,
        )
        if existing.returncode == 0:
            ops.ok(f"GitHub release {tag} already exists (created by CI)")
            return

        changelog = Changelog(info.root, ops=ops).text()
        notes = extract_version_notes(changelog, version)

        result = ops.run(
            [gh, "release", "create", tag, "--title", tag, "--notes", notes],
            cwd=str(info.root),
            check=False,
        )
        if result.returncode != 0:
            ops.fail(f"Failed to create release: {result.stderr}")
        ops.ok(f"GitHub release {tag} created")
