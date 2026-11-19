"""Tag the release commit and push the tag."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.timeouts import GIT_NETWORK

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.shared.ops import ReleaseOps

_console = Console()


@final
class Phase5Tag:
    """Tag the release commit and push the tag."""

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

    @staticmethod
    def _remote_tag_commit_sha(ls_remote_output: str, tag: str) -> str | None:
        """Extract a remote tag's commit SHA, or return None if absent.

        Require unfiltered git ls-remote --tags output: explicit-ref filtering
        omits annotated tags' peeled refs and leaves only the tag object's SHA.
        Prefer the peeled ref when present; lightweight tags use the plain ref.
        """
        plain_ref = f"refs/tags/{tag}"
        peeled_ref = f"{plain_ref}^{{}}"
        plain_sha: str | None = None
        for line in ls_remote_output.splitlines():
            sha, _, ref = line.partition("\t")
            if ref == peeled_ref:
                return sha
            if ref == plain_ref:
                plain_sha = sha
        return plain_sha

    def _find_release_commit_sha(self) -> str:
        """Resolve the release commit from main when no captured SHA is available.

        Match the exact release subject with an optional GitHub PR-number suffix,
        not an arbitrary parenthesized suffix. HEAD may include a later README pin.
        """
        ops = self._ops
        root = self._info.root
        target = f"chore: release v{self._version}"
        pattern = re.compile(rf"{re.escape(target)}( \(#\d+\))?")
        log = ops.run(["git", "log", "--format=%H %s", "main"], cwd=str(root))
        for line in log.stdout.splitlines():
            sha, _, subject = line.partition(" ")
            if pattern.fullmatch(subject):
                return sha
        ops.fail(
            f"Could not resolve the release commit for v{self._version} — no "
            f"commit on main has the subject {target!r}. Re-run "
            f"`punt release {self._version} --resume-from release-pr` "
            "(the explicit version is required — a Go project resuming "
            "before the tag phase cannot infer it from git tags alone), "
            "or tag the correct commit manually."
        )

    def run(self, *, release_sha: str | None = None) -> None:
        """Tag the release commit and push the tag.

        Args:
            release_sha: Release commit SHA; resolve from main's release subject if
                omitted.

        Raises:
            ReleaseError: The release commit is missing, tags disagree, or git
                operations fail.
            subprocess.CalledProcessError: A checked repository command fails.
            subprocess.TimeoutExpired: An external command exceeds its timeout.
        """
        info = self._info
        version = self._version
        ops = self._ops
        _console.print(f"\n[bold]Phase 5: Tag v{version}[/bold]")

        root = info.root
        tag = f"v{version}"

        if self._dry_run:
            ops.dry(f"git tag {tag} <release-sha>")
            ops.dry(f"git push origin {tag}")
            return

        workspace = GitWorkspace(root, ops=ops)
        workspace.ensure_on_main()

        # Both the merge result and git log return full-length SHAs.
        if release_sha is None:
            release_sha = self._find_release_commit_sha()

        # A local tag does not prove its push succeeded; check the remote on resume.
        existing = ops.run(["git", "tag", "--list", tag], cwd=str(root)).stdout.strip()
        if existing:
            # The tag must point to the release commit, not a later main HEAD.
            tag_sha = ops.run(["git", "rev-parse", tag], cwd=str(root)).stdout.strip()
            if tag_sha != release_sha:
                ops.fail(
                    f"Tag {tag} exists but points to {tag_sha[:8]}, not the "
                    f"release commit ({release_sha[:8]})"
                )
                return

            # Use an unfiltered listing to retain annotated tags' peeled commit refs.
            ls_remote = ops.run(
                ["git", "ls-remote", "--tags", "origin"],
                cwd=str(root),
                check=False,
                timeout=GIT_NETWORK,
            )
            if ls_remote.returncode != 0:
                ops.fail(
                    f"git ls-remote --tags origin failed:\n{ls_remote.stderr.strip()}"
                )
            remote_listing = ls_remote.stdout
            remote_sha = self._remote_tag_commit_sha(remote_listing, tag)
            if remote_sha is not None:
                # Compare the commit SHA, not just tag presence. Never force-push over a
                # potentially intentional remote tag; require manual resolution.
                if remote_sha != tag_sha:
                    ops.fail(
                        f"Tag {tag} exists on the remote but points to "
                        f"{remote_sha[:8]}, not {tag_sha[:8]} — resolve "
                        "manually before resuming"
                    )
                    return
                ops.ok(f"Tag {tag} already exists at HEAD")
                return

            ops.info(f"Tag {tag} exists locally but was never pushed — pushing now")
            workspace.push(tag)
            ops.ok(f"Pushed tag {tag}")
            return

        # Tag the captured release commit rather than a potentially newer HEAD.
        tag_result = ops.run(
            ["git", "tag", tag, release_sha], cwd=str(root), check=False
        )
        if tag_result.returncode != 0:
            ops.fail(
                f"git tag {tag} failed (release commit {release_sha[:8]}):\n"
                f"{tag_result.stderr.strip()}"
            )
        ops.ok(f"Tagged {tag}")

        # Tag pushes bypass branch protection but still run pre-push hooks.
        workspace.push(tag)
        ops.ok(f"Pushed tag {tag}")
