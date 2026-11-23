"""Safely reconcile local main after a release PR's squash merge."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


@final
class LocalMainSync:
    """Bind a checkout and pushed release head for post-merge reconciliation."""

    __slots__ = ("_local_head", "_ops", "_root")

    _root: Path
    _local_head: str
    _ops: ReleaseOps

    def __new__(cls, root: Path, local_head: str, *, ops: ReleaseOps) -> Self:
        """Bind the pushed PR head whose commits are represented by the squash."""
        self = super().__new__(cls)
        self._root = root
        self._local_head = local_head
        self._ops = ops
        return self

    def run(self) -> None:
        """Sync main, discarding only clean divergence owned by the merged head.

        Raises:
            ReleaseError: Git fails or divergence cannot safely be discarded.
            subprocess.TimeoutExpired: Git exceeds its timeout.
            OSError: Git cannot start.
        """
        self._git(["checkout", "main"])
        self._git(["fetch", "origin", "main"])
        if self._can_fast_forward():
            self._git(["merge", "--ff-only", "origin/main"])
            return
        self._check_divergence()
        self._git(["reset", "--hard", "origin/main"])

    def _can_fast_forward(self) -> bool:
        """Distinguish ancestry from a failed Git query."""
        ancestor = self._run(["merge-base", "--is-ancestor", "main", "origin/main"])
        if ancestor.returncode not in (0, 1):
            self._ops.fail(
                f"Could not compare main with origin/main: {ancestor.stderr.strip()} "
                "— inspect the repository and retry with --resume-from tag"
            )
        return ancestor.returncode == 0

    def _check_divergence(self) -> None:
        """Reject foreign commits or uncommitted work before a hard reset."""
        local_only = self._git(["rev-list", "origin/main..main"])
        foreign = self._git(
            ["rev-list", "origin/main..main", "--not", self._local_head]
        )
        dirty = self._git(["status", "--porcelain"])
        if foreign or dirty:
            reason = (
                "commits outside the pushed release head"
                if foreign
                else "a dirty working tree"
            )
            self._ops.fail(
                f"Local main diverges from origin/main with {reason}. "
                f"Local-only commits: {local_only}. "
                "Preserve unrelated work, reconcile main with origin/main, "
                "then retry with --resume-from tag"
            )

    def _git(self, args: list[str]) -> str:
        """Run a diagnosed Git command while reconciling main."""
        result = self._run(args)
        if result.returncode != 0:
            self._ops.fail(
                f"git {' '.join(args)} failed:\n{result.stderr.strip()}\n"
                "Inspect the repository and retry with --resume-from tag"
            )
        return result.stdout.strip()

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Apply the shared hook timeout and diagnosed-failure convention."""
        return self._ops.run(
            ["git", *args], cwd=str(self._root), check=False, timeout=GIT_HOOK
        )
