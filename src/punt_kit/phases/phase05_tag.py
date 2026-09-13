"""Phase 5: tag the release commit and push the tag.

Tags the commit Phase 4's squash-merge produced — not whatever ``main`` HEAD
happens to be at tag-time. A later commit (Phase 4c's README-install-SHA
pin) lands on ``main`` right after the squash-merge (see
``phase04_release_pr.py``'s module docstring), so by the time this phase
runs, ``main`` HEAD can already be one commit past the actual release.
Tagging HEAD blindly would drift the tag onto that commit instead.
"""

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
    """Phase 5: tag the release commit and push the tag."""

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

    def _find_release_commit_sha(self) -> str:
        """Resolve the release commit from git history when no captured SHA
        is available.

        ``--resume-from tag`` re-enters this phase without running Phase 4
        first, so there is no ``merge()`` return value to thread through
        this run. Falling back to ``git rev-parse HEAD`` here would
        reproduce the exact defect this phase exists to fix — see the
        module docstring. Phase 4's squash-merge always carries the commit
        message ``chore: release vX.Y.Z`` (the ``title=`` it passes to
        ``merge()``) as the *subject line* — GitHub's default squash commit
        appends `` (#<pr-number>)`` to that subject, so the safe fallback
        matches on that subject either bare (hand-committed, e.g. in tests)
        or followed by a `` (`` PR-number suffix, not on exact equality.
        """
        ops = self._ops
        root = self._info.root
        target = f"chore: release v{self._version}"
        log = ops.run(["git", "log", "--format=%H %s", "main"], cwd=str(root))
        for line in log.stdout.splitlines():
            sha, _, subject = line.partition(" ")
            if subject == target or subject.startswith(f"{target} ("):
                return sha
        ops.fail(
            f"Could not resolve the release commit for v{self._version} — no "
            f"commit on main has the subject {target!r}. Re-run "
            "`punt release --resume-from release-pr`, or tag the correct "
            "commit manually."
        )

    def run(self, *, release_sha: str | None = None) -> None:
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

        if release_sha is None:
            release_sha = self._find_release_commit_sha()

        # Check if tag already exists locally. A local tag alone is not
        # proof the push succeeded: Phase 5 creates the tag *before*
        # pushing it (below), so a push that failed on a prior run — a
        # network blip, a transient auth failure — leaves the tag sitting
        # at the release commit locally while the remote has nothing.
        # Re-entering via --resume-from tag must tell "exists locally and
        # was already pushed" apart from "exists locally and was never
        # pushed", or the resume silently skips the retry it exists to
        # enable.
        existing = ops.run(["git", "tag", "--list", tag], cwd=str(root)).stdout.strip()
        if existing:
            # Verify it points to the release commit, not wherever main
            # HEAD has since moved to.
            tag_sha = ops.run(["git", "rev-parse", tag], cwd=str(root)).stdout.strip()
            if tag_sha != release_sha:
                ops.fail(
                    f"Tag {tag} exists but points to {tag_sha[:8]}, not the "
                    f"release commit ({release_sha[:8]})"
                )
                return

            # Unfiltered (no ref argument) — see _remote_tag_commit_sha's
            # docstring for why the filtered, explicit-ref form cannot be
            # used here. A network read, same risk class as `git fetch
            # origin` (Phase 1) and this phase's own tag push, both already
            # diagnosed (pkit-f85t.7).
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

        # A local write (disk full, permission, or a lock held by a
        # concurrent git process) — kept in the same diagnosed convention as
        # the push two lines below rather than left as the odd one out
        # (pkit-f85t.7). Tags `release_sha` explicitly rather than bare
        # `git tag {tag}` (which would tag HEAD) — see the module docstring.
        tag_result = ops.run(
            ["git", "tag", tag, release_sha], cwd=str(root), check=False
        )
        if tag_result.returncode != 0:
            ops.fail(
                f"git tag {tag} failed (release commit {release_sha[:8]}):\n"
                f"{tag_result.stderr.strip()}"
            )
        ops.ok(f"Tagged {tag}")

        # Push tag (not blocked by branch protection — targets refs/tags/*).
        # pre-push still fires bd hooks, so use the hook budget.
        workspace.push(tag)
        ops.ok(f"Pushed tag {tag}")
