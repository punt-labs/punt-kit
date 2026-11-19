"""Prepare checkouts, commit changes, and push release refs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_kit.phases.shared import timeouts

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


@final
class GitWorkspace:
    """Run Git operations against one project or sibling checkout."""

    __slots__ = ("_ops", "_root")

    _root: Path
    _ops: ReleaseOps

    def __new__(cls, root: Path, *, ops: ReleaseOps) -> Self:
        """Bind release operations to a repository checkout."""
        self = super().__new__(cls)
        self._root = root
        self._ops = ops
        return self

    def current_branch(self) -> str:
        """Return the current branch name, or an empty string if detached.

        Raises:
            subprocess.CalledProcessError: Git could not query the branch.
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        return self._ops.run(
            ["git", "branch", "--show-current"], cwd=str(self._root)
        ).stdout.strip()

    def ensure_on_main(self) -> None:
        """Check out main if needed and fast-forward it from origin.

        Pull even on main and specify the remote branch so no upstream
        configuration is required.

        Raises:
            ReleaseError: Checkout or fast-forward pull failed.
            subprocess.CalledProcessError: Git could not query the current branch.
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        if self.current_branch() != "main":
            checkout = self._ops.run(
                ["git", "checkout", "main"],
                cwd=str(self._root),
                check=False,
                timeout=timeouts.GIT_HOOK,
            )
            if checkout.returncode != 0:
                self._ops.fail(f"git checkout main failed:\n{checkout.stderr.strip()}")
        # A network call: check=False under a hook-aware budget, and a
        # non-zero exit becomes a diagnosed fail.
        pull = self._ops.run(
            ["git", "pull", "--ff-only", "origin", "main"],
            cwd=str(self._root),
            check=False,
            timeout=timeouts.GIT_HOOK,
        )
        if pull.returncode != 0:
            self._ops.fail(
                f"git pull --ff-only origin main failed:\n{pull.stderr.strip()}"
            )

    def checkout_or_create(self, branch: str) -> bool:
        """Check out a branch, creating it if absent.

        Returns:
            Whether the branch already existed.

        Raises:
            ReleaseError: Git could not check out or create the branch.
            subprocess.CalledProcessError: Git could not list branches.
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        existing = self._ops.run(
            ["git", "branch", "--list", branch], cwd=str(self._root)
        ).stdout.strip()
        if existing:
            checkout = self._ops.run(
                ["git", "checkout", branch],
                cwd=str(self._root),
                check=False,
                timeout=timeouts.GIT_HOOK,
            )
            if checkout.returncode != 0:
                self._ops.fail(
                    f"git checkout {branch} failed:\n{checkout.stderr.strip()}"
                )
            return True
        create = self._ops.run(
            ["git", "checkout", "-b", branch],
            cwd=str(self._root),
            check=False,
            timeout=timeouts.GIT_HOOK,
        )
        if create.returncode != 0:
            self._ops.fail(f"git checkout -b {branch} failed:\n{create.stderr.strip()}")
        return False

    def commit_if_staged(self, paths: Sequence[str], message: str) -> bool:
        """Stage the paths and commit if the index contains changes.

        Returns:
            Whether a commit was created.

        Raises:
            ReleaseError: Git rejected the commit.
            subprocess.CalledProcessError: Git could not stage or inspect the index.
            subprocess.TimeoutExpired: Git exceeded its timeout.
            OSError: Git could not start.
        """
        self._ops.run(["git", "add", "--", *paths], cwd=str(self._root))
        staged = self._ops.run(
            ["git", "diff", "--cached", "--name-only"], cwd=str(self._root)
        ).stdout.strip()
        if staged:
            commit = self._ops.run(
                ["git", "commit", "-m", message],
                cwd=str(self._root),
                check=False,
                timeout=timeouts.GIT_HOOK,
            )
            if commit.returncode != 0:
                self._ops.fail(f"git commit failed:\n{commit.stderr.strip()}")
            return True
        return False

    def push(self, branch_or_tag: str) -> None:
        """Push a branch or tag to origin.

        Raises:
            ReleaseError: Git rejected the push or could not reach origin.
            subprocess.TimeoutExpired: Git exceeded the hook timeout.
            OSError: Git could not start.
        """
        result = self._ops.run(
            ["git", "push", "origin", branch_or_tag],
            cwd=str(self._root),
            capture=False,
            check=False,
            timeout=timeouts.GIT_HOOK,
        )
        if result.returncode != 0:
            self._ops.fail(f"git push origin {branch_or_tag} failed — see output above")
