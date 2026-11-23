"""Diagnose synchronization commands and preserve main before a hard reset."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn, Self, final

from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps


@final
class MainSyncGit:
    """Run post-merge Git operations with a recoverable main checkpoint."""

    __slots__ = ("_ops", "_root")

    _root: Path
    _ops: ReleaseOps

    def __new__(cls, root: Path, *, ops: ReleaseOps) -> Self:
        """Bind the checkout and diagnosed release operations."""
        self = super().__new__(cls)
        self._root = root
        self._ops = ops
        return self

    def preserve_main(self, local_only: str) -> None:
        """Save main and report recovery commands before replacing its history.

        Raises:
            ReleaseError: Reading main or saving the recovery ref fails.
            subprocess.TimeoutExpired: Git exceeds its timeout.
            OSError: Git cannot start.
        """
        ref = "refs/punt-release/main-before-sync"
        sha = self.checked(["rev-parse", "main"])
        self.checked(["update-ref", ref, sha])
        self._ops.info(
            f"Saved pre-reset main {sha} at {ref}. Local-only commits: {local_only}. "
            f"Recover individual commits with git cherry-pick <sha>, "
            f"or restore main with git reset --hard {ref}"
        )

    def checked(self, args: list[str]) -> str:
        """Run a diagnosed Git command and return its stripped output.

        Raises:
            ReleaseError: Git exits unsuccessfully.
            subprocess.TimeoutExpired: Git exceeds its timeout.
            OSError: Git cannot start.
        """
        result = self.run(args)
        if result.returncode != 0:
            self._ops.fail(
                f"git {' '.join(args)} failed:\n{result.stderr.strip()}\n"
                "Inspect the repository and retry with --resume-from tag"
            )
        return result.stdout.strip()

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run Git with the shared hook timeout and unchecked exit status.

        Raises:
            subprocess.TimeoutExpired: Git exceeds its timeout.
            OSError: Git cannot start.
        """
        return self._ops.run(
            ["git", *args], cwd=str(self._root), check=False, timeout=GIT_HOOK
        )

    def fail(self, message: str) -> NoReturn:
        """Report an unsafe synchronization state through release operations.

        Raises:
            ReleaseError: Always, with the supplied diagnosis.
        """
        self._ops.fail(message)
