"""Phase 5: tag main HEAD and push the tag."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.git import GitWorkspace

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase5Tag:
    """Phase 5: tag main HEAD and push tag."""

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
        _console.print(f"\n[bold]Phase 5: Tag v{version}[/bold]")

        root = info.root
        tag = f"v{version}"

        if self._dry_run:
            ops.dry(f"git tag {tag}")
            ops.dry(f"git push origin {tag}")
            return

        workspace = GitWorkspace(root, ops=ops)
        workspace.ensure_on_main()

        # Check if tag already exists
        existing = ops.run(["git", "tag", "--list", tag], cwd=str(root)).stdout.strip()
        if existing:
            # Verify it points to HEAD
            tag_sha = ops.run(["git", "rev-parse", tag], cwd=str(root)).stdout.strip()
            head_sha = ops.run(
                ["git", "rev-parse", "HEAD"], cwd=str(root)
            ).stdout.strip()
            if tag_sha == head_sha:
                ops.ok(f"Tag {tag} already exists at HEAD")
            else:
                ops.fail(
                    f"Tag {tag} exists but points to {tag_sha[:8]}, "
                    f"not HEAD ({head_sha[:8]})"
                )
            return

        ops.run(["git", "tag", tag], cwd=str(root))
        ops.ok(f"Tagged {tag}")

        # Push tag (not blocked by branch protection — targets refs/tags/*).
        # pre-push still fires bd hooks, so use the hook budget.
        workspace.push(tag)
        ops.ok(f"Pushed tag {tag}")
