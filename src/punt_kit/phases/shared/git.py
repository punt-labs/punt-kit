"""Common git workspace operations shared across release phases.

Consolidates the "ensure on main / checkout-or-create branch / commit if
staged / push" sequence that today is duplicated near-verbatim across five
call sites in ``punt_kit.release`` — each hand-rolling the same three
``_run`` calls. A genuine PY-RF-3 Extract Method opportunity the procedural
structure never surfaced, not just a relocation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared import timeouts

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


@final
class GitWorkspace:
    """Git operations against one project or sibling repo checkout."""

    __slots__ = ("_ops", "_root")

    _root: Path
    _ops: ReleaseOps

    def __new__(cls, root: Path, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._root = root
        self._ops = ops
        return self

    def current_branch(self) -> str:
        return self._ops.run(
            ["git", "branch", "--show-current"], cwd=str(self._root)
        ).stdout.strip()

    def ensure_on_main(self) -> None:
        """Check out main (if needed) and fast-forward pull.

        Resume may leave the working tree on a release/propagation branch
        from an interrupted prior run — checkout handles that case. The
        pull always runs, even when already on main: a ``--resume-from``
        that skips phase 1 can leave main checked out but stale, and
        basing a new branch off it would silently root the release on an
        outdated commit. Pulling from an explicit ``origin main`` refspec
        (rather than bare ``git pull``) works even when the local branch
        has no configured upstream tracking.
        """
        if self.current_branch() != "main":
            self._ops.run(
                ["git", "checkout", "main"],
                cwd=str(self._root),
                timeout=timeouts.GIT_HOOK,
            )
        self._ops.run(
            ["git", "pull", "--ff-only", "origin", "main"],
            cwd=str(self._root),
            timeout=timeouts.GIT_HOOK,
        )

    def checkout_or_create(self, branch: str) -> bool:
        """Check out ``branch``, creating it if absent.

        Returns whether the branch already existed (resume case).
        """
        existing = self._ops.run(
            ["git", "branch", "--list", branch], cwd=str(self._root)
        ).stdout.strip()
        if existing:
            self._ops.run(
                ["git", "checkout", branch],
                cwd=str(self._root),
                timeout=timeouts.GIT_HOOK,
            )
            return True
        self._ops.run(
            ["git", "checkout", "-b", branch],
            cwd=str(self._root),
            timeout=timeouts.GIT_HOOK,
        )
        return False

    def commit_if_staged(self, paths: Sequence[str], message: str) -> bool:
        """Stage ``paths`` and commit ``message`` if anything is staged.

        Returns whether a commit was created (``False`` means the paths
        were already at the target state — the resume case).
        """
        self._ops.run(["git", "add", "--", *paths], cwd=str(self._root))
        staged = self._ops.run(
            ["git", "diff", "--cached", "--name-only"], cwd=str(self._root)
        ).stdout.strip()
        if staged:
            self._ops.run(
                ["git", "commit", "-m", message],
                cwd=str(self._root),
                timeout=timeouts.GIT_HOOK,
            )
            return True
        return False

    def push(self, branch_or_tag: str) -> None:
        self._ops.run(
            ["git", "push", "origin", branch_or_tag],
            cwd=str(self._root),
            capture=False,
            timeout=timeouts.GIT_HOOK,
        )
