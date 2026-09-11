"""Phase 5: tag main HEAD and push the tag."""

from __future__ import annotations

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

    @staticmethod
    def _remote_tag_commit_sha(ls_remote_output: str, tag: str) -> str | None:
        """Extract the commit SHA a remote tag points at, or ``None`` if
        the remote has no tag by that name.

        ``ls_remote_output`` must come from the *unfiltered*
        ``git ls-remote --tags origin`` (no ref argument) — the filtered,
        explicit-ref form (``git ls-remote --tags origin <tag>``) never
        emits the peeled ``^{}`` line at all (server-side ref-advertisement
        filtering strips it), and for an ANNOTATED tag its one remaining
        line reports the tag *object's own* SHA, not the commit it points
        at. Comparing that against a local lightweight tag's commit SHA
        (`Phase5Tag` only ever creates lightweight tags itself, but the
        remote's copy can be annotated by other tooling) would treat every
        annotated remote tag as a mismatch — even one at the exact right
        commit. The peeled line, present only in the unfiltered listing,
        is the one that actually names a commit, so it is preferred when
        both are present.
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

        # Check if tag already exists locally. A local tag alone is not
        # proof the push succeeded: Phase 5 creates the tag *before*
        # pushing it (below), so a push that failed on a prior run — a
        # network blip, a transient auth failure — leaves the tag sitting
        # at HEAD locally while the remote has nothing. Re-entering via
        # --resume-from tag must tell "exists locally and was already
        # pushed" apart from "exists locally and was never pushed", or the
        # resume silently skips the retry it exists to enable.
        existing = ops.run(["git", "tag", "--list", tag], cwd=str(root)).stdout.strip()
        if existing:
            # Verify it points to HEAD
            tag_sha = ops.run(["git", "rev-parse", tag], cwd=str(root)).stdout.strip()
            head_sha = ops.run(
                ["git", "rev-parse", "HEAD"], cwd=str(root)
            ).stdout.strip()
            if tag_sha != head_sha:
                ops.fail(
                    f"Tag {tag} exists but points to {tag_sha[:8]}, "
                    f"not HEAD ({head_sha[:8]})"
                )
                return

            # Unfiltered (no ref argument) — see _remote_tag_commit_sha's
            # docstring for why the filtered, explicit-ref form cannot be
            # used here.
            remote_listing = ops.run(
                ["git", "ls-remote", "--tags", "origin"],
                cwd=str(root),
                timeout=GIT_NETWORK,
            ).stdout
            remote_sha = self._remote_tag_commit_sha(remote_listing, tag)
            if remote_sha is not None:
                # A remote tag's mere presence only proves *some* ref named
                # `tag` exists — an earlier, wrong-commit attempt (operator
                # recovery, a stale push from a prior run) can leave one
                # there. Compare the SHA, not just presence: a blind
                # "already exists" here would be the exact silent
                # wrong-state this phase's fix exists to close, one branch
                # over. A bare `git push` (no `--force`) is not a safe
                # correction either — it would just fail non-fast-forward
                # with a worse diagnosis, and force-pushing over a possibly
                # intentional remote tag is not this code's call to make.
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

        ops.run(["git", "tag", tag], cwd=str(root))
        ops.ok(f"Tagged {tag}")

        # Push tag (not blocked by branch protection — targets refs/tags/*).
        # pre-push still fires bd hooks, so use the hook budget.
        workspace.push(tag)
        ops.ok(f"Pushed tag {tag}")
