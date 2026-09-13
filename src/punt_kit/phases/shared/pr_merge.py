"""Pushing a branch, opening a PR, waiting for CI, and squash-merging."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from typing import TYPE_CHECKING, Self, cast, final

from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.timeouts import GIT_HOOK

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from punt_kit.phases.shared.ops import ReleaseOps
    from punt_kit.phases.shared.siblings import SkipRecorder


@final
class PrMerger:
    """Composes a release/propagation PR from branch push through squash-merge.

    ``wait_for_checks`` and ``resolve_threads`` are required, injected
    callables rather than composed ``RequiredChecksWaiter``/``PrThreadResolver``
    collaborators: ``tests/test_release.py`` monkeypatches
    ``punt_kit.release._wait_for_required_checks`` and
    ``punt_kit.release._resolve_pr_threads`` directly and calls
    ``punt_kit.release._pr_merge`` — the wrapper this class backs — expecting
    those patches to be observed. Composing the waiter/resolver classes
    directly here would bypass that seam entirely (§0's mechanism only
    reaches call sites that use the bare release.py name), so the caller
    passes the bare name through instead, mirroring
    ``SiblingRegistry.reset_all``'s injected ``resolve`` collaborator.
    """

    __slots__ = ("_ops", "_skips")

    _ops: ReleaseOps
    # Absent by default — only the Phase 10 sibling-merge path
    # (_sibling_pr_merge) has a sibling to record a skip against; Phase 4's
    # own release-PR merge (_pr_merge) has no such concept and leaves this
    # None.
    _skips: SkipRecorder | None

    def __new__(cls, *, ops: ReleaseOps, skips: SkipRecorder | None = None) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._skips = skips
        return self

    @staticmethod
    def _select_existing(
        prs: list[dict[str, object]], local_head: str
    ) -> tuple[int | None, bool]:
        """Pick which same-named PR, if any, represents the current release.

        Returns ``(pr_number, already_merged)``. An OPEN PR is always the
        current release. A MERGED PR counts only when its head commit
        matches the local branch head — a merged PR at a different head is
        a stale earlier attempt, and treating it as current would skip the
        version bump and tag an unbumped commit. CLOSED PRs are never
        current: their CI is dead and waiting on it never completes.
        """
        for pr in prs:
            if pr.get("state") == "OPEN":
                return cast("int", pr["number"]), False
        for pr in prs:
            if pr.get("state") == "MERGED" and pr.get("headRefOid") == local_head:
                return cast("int", pr["number"]), True
        return None, False

    def _is_merged(self, gh: str, cwd: str, pr_number: int) -> bool:
        """Check whether a PR has reached the MERGED state."""
        state = self._ops.run(
            [gh, "pr", "view", str(pr_number), "--json", "state"],
            cwd=cwd,
            check=False,
        )
        if state.returncode != 0:
            return False
        try:
            data = cast("dict[str, object]", json.loads(state.stdout))
        except json.JSONDecodeError:
            return False
        return data.get("state") == "MERGED"

    def merge(
        self,
        *,
        cwd: Path,
        branch: str,
        title: str,
        body: str = "",
        dry_run: bool = False,
        wait_for_checks: Callable[[str, str, int], None],
        resolve_threads: Callable[[str, str, int], None],
    ) -> str:
        """Push branch, create PR, wait for CI, squash-merge. Return merge SHA."""
        gh = shutil.which("gh")
        if gh is None:
            self._ops.fail("gh CLI not found — install from https://cli.github.com")

        root = str(cwd)

        if dry_run:
            self._ops.dry(f"git push -u origin {branch}")
            self._ops.dry(f'gh pr create --base main --head {branch} --title "{title}"')
            self._ops.dry(
                "gh pr view <number> --json statusCheckRollup  # poll required checks"
            )
            self._ops.dry("gh pr merge <number> --squash --delete-branch")
            return "<SHA>"

        # 1. Push branch (idempotent). pre-push fires bd hooks — needs the
        # hook budget, which subsumes the network timeout.
        result = self._ops.run(
            ["git", "push", "-u", "origin", branch],
            cwd=root,
            check=False,
            capture=False,
            timeout=GIT_HOOK,
        )
        if result.returncode != 0:
            self._ops.fail(f"Failed to push branch {branch} — fix and retry")
        self._ops.ok(f"Pushed branch {branch}")

        # 2. Check for existing PRs (include merged/closed for resume). Only
        # an OPEN PR or a MERGED PR at this exact head represents the
        # current release — see _select_existing for why CLOSED and stale
        # MERGED PRs must be ignored.
        local_head = self._ops.run(
            ["git", "rev-parse", branch], cwd=root
        ).stdout.strip()
        existing = self._ops.run(
            [
                gh,
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "all",
                "--json",
                "number,state,headRefOid",
                "--limit",
                "20",
            ],
            cwd=root,
            check=False,
        )
        pr_number: int | None = None
        if existing.returncode == 0:
            try:
                prs = cast("list[dict[str, object]]", json.loads(existing.stdout))
            except json.JSONDecodeError:
                self._ops.fail(
                    f"Failed to parse gh pr list output: {existing.stdout[:200]}"
                )
            pr_number, already_merged = self._select_existing(prs, local_head)
            if pr_number is not None:
                if already_merged:
                    self._ops.ok(f"PR #{pr_number} already merged")
                    # Unconditional (not GitWorkspace.ensure_on_main): a PR
                    # merged by an earlier run may already have left the
                    # workspace on main, but the pull --ff-only must still
                    # run to pick up that merge commit.
                    self._sync_local_main(root)
                    return self._merge_commit_oid(gh, root, pr_number)
                self._ops.info(f"Found existing open PR #{pr_number}")

        # 3. Create PR if none exists
        if pr_number is None:
            create_cmd = [
                gh,
                "pr",
                "create",
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                title,
            ]
            create_cmd.extend(["--body", body or ""])
            result = self._ops.run(create_cmd, cwd=root, check=False)
            if result.returncode != 0:
                self._ops.fail(f"Failed to create PR: {result.stderr.strip()}")
            pr_url = result.stdout.strip()
            try:
                pr_number = int(pr_url.rstrip("/").split("/")[-1])
            except ValueError:
                self._ops.fail(f"Failed to extract PR number from gh output: {pr_url}")
            self._ops.ok(f"Created PR #{pr_number}")

        # 4. Wait for CI (required checks only — ignores non-required checks
        # such as "Claude Code Review").
        wait_for_checks(gh, root, pr_number)

        # 5. Check if already merged (handles resume)
        state = self._ops.run(
            [gh, "pr", "view", str(pr_number), "--json", "state"],
            cwd=root,
            check=False,
        )
        if state.returncode != 0:
            self._ops.fail(
                f"Failed to check PR #{pr_number} state: {state.stderr.strip()}"
            )
        try:
            pr_state = json.loads(state.stdout).get("state")
        except json.JSONDecodeError:
            self._ops.fail(f"Failed to parse gh pr view output: {state.stdout[:200]}")
        if pr_state == "MERGED":
            self._ops.ok(f"PR #{pr_number} already merged")
            self._sync_local_main(root)
            return self._merge_commit_oid(gh, root, pr_number)

        # 6. Resolve review threads (Copilot/Bugbot auto-post on PRs)
        resolve_threads(gh, root, pr_number)

        # 7. Squash-merge (retry on branch protection / pending checks). Some
        # repos have long-running checks (CodeQL) that gh pr checks --watch
        # doesn't wait for if they aren't required. Branch protection may
        # also require conversation resolution that takes a moment to
        # propagate.
        merge_cmd = [gh, "pr", "merge", str(pr_number), "--squash", "--delete-branch"]
        for merge_attempt in range(6):
            result = self._ops.run(merge_cmd, cwd=root, check=False)
            if result.returncode == 0:
                break
            # gh exits non-zero when the post-merge branch deletion fails
            # even though the merge itself succeeded: repos with
            # "automatically delete head branches" remove the branch during
            # the merge, so gh's own DELETE gets a 404 (or a transient 503).
            # The postcondition that matters is the PR state — check it
            # before classifying the exit code as a failure.
            if self._is_merged(gh, root, pr_number):
                self._ops.info(
                    f"PR #{pr_number} merged; remote branch already deleted — "
                    "continuing"
                )
                break
            combined = (result.stderr.strip() + "\n" + result.stdout.strip()).strip()
            combined_lower = combined.lower()
            is_transient = (
                "policy prohibits" in combined_lower
                or "required status check" in combined_lower
                or "review is required" in combined_lower
                or "conversation must be resolved" in combined_lower
            )
            if is_transient and merge_attempt < 5:
                wait = 10 * (merge_attempt + 1)
                self._ops.info(
                    f"Merge blocked (attempt {merge_attempt + 1}/6), "
                    f"retrying in {wait}s..."
                )
                time.sleep(wait)
                # Re-resolve threads in case new ones appeared (best-effort)
                try:
                    resolve_threads(gh, root, pr_number)
                except (ReleaseError, SystemExit, subprocess.CalledProcessError):
                    self._ops.info(
                        "Could not re-resolve threads, proceeding with retry"
                    )
                continue
            self._ops.fail(f"Failed to merge PR #{pr_number}: {combined}")
        self._ops.ok(f"PR #{pr_number} merged")

        # 8. Update local main
        self._sync_local_main(root)
        return self._merge_commit_oid(gh, root, pr_number)

    def _sync_local_main(self, root: str) -> None:
        """Fast-forward local main to the just-merged remote state.

        Workspace-state only — the caller's return value comes from
        ``_merge_commit_oid`` instead. Local HEAD after this pull is not
        reliably the squash-merge commit: any further commit landing on
        main between the squash-merge and this pull (a concurrent release,
        a hotfix) would fast-forward past it too, making local HEAD the
        LATER commit — the exact race class this method's caller exists to
        avoid.

        Extracted from three near-identical inline blocks (existing-PR
        resume, mid-wait resume, and the normal post-merge path) that each
        hand-rolled the same checkout + pull sequence with an unqualified
        ``check=True`` default (pkit-f85t.7).
        """
        checkout = self._ops.run(
            ["git", "checkout", "main"], cwd=root, check=False, timeout=GIT_HOOK
        )
        if checkout.returncode != 0:
            self._ops.fail(f"git checkout main failed:\n{checkout.stderr.strip()}")
        # A network call, same risk class as the branch push above.
        pull = self._ops.run(
            ["git", "pull", "--ff-only"], cwd=root, check=False, timeout=GIT_HOOK
        )
        if pull.returncode != 0:
            self._ops.fail(f"git pull --ff-only failed:\n{pull.stderr.strip()}")

    def _merge_commit_oid(self, gh: str, root: str, pr_number: int) -> str:
        """Resolve PR #<pr_number>'s authoritative squash-merge commit oid
        from GitHub itself, rather than reading local main HEAD.

        GitHub's own record of the merge is the one source that cannot
        drift: local main HEAD (even freshly pulled by
        ``_sync_local_main``) is only correct as long as nothing else has
        landed on main since the squash-merge — a race, not a guarantee.
        """
        result = self._ops.run(
            [
                gh,
                "pr",
                "view",
                str(pr_number),
                "--json",
                "mergeCommit",
                "--jq",
                ".mergeCommit.oid",
            ],
            cwd=root,
        )
        oid = result.stdout.strip()
        if not oid:
            self._ops.fail(
                f"PR #{pr_number} has no mergeCommit oid — gh reports it "
                "merged but the commit oid is missing"
            )
        return oid

    def merge_in_sibling(
        self,
        path: Path,
        branch: str,
        files: list[str],
        message: str,
        name: str,
        *,
        dry_run: bool,
        merge: Callable[..., str],
    ) -> bool:
        """Create branch, stage files, commit, and merge via PR in a sibling repo.

        Returns True if a PR was created and merged, False if no changes.

        ``merge`` is injected (not ``self.merge``) for the same reason
        ``wait_for_checks``/``resolve_threads`` are injected on ``merge``
        itself — tests monkeypatch ``punt_kit.release._pr_merge`` directly
        and call ``punt_kit.release._sibling_pr_merge`` expecting the patch
        to be observed.
        """
        cwd = str(path)
        # A sibling checkout is far less controlled than the project's own
        # repo (pkit-f85t.7 sweep boundary) — same reasoning as
        # SiblingRepo.validate's reads and _sync_profile_readme's git log,
        # both already diagnosed.
        status_result = self._ops.run(
            ["git", "status", "--porcelain", "--", *files], cwd=cwd, check=False
        )
        if status_result.returncode != 0:
            self._ops.fail(
                f"git status on sibling {name} failed:\n{status_result.stderr.strip()}"
            )
        status = status_result.stdout.strip()
        if not status:
            return False

        if dry_run:
            self._ops.dry(f"{name}: {message}")
            return True

        # Use try/except/finally to ensure sibling returns to main on any
        # failure — ReleaseError from ops.fail(), CalledProcessError from
        # ops.run(), etc. (stale propagation branches break subsequent
        # releases). The except clause exists only to capture the primary
        # exception for the finally block's secondary-failure message
        # below; it always re-raises, never swallows.
        primary_exc: BaseException | None = None
        try:
            workspace = GitWorkspace(path, ops=self._ops)
            workspace.checkout_or_create(branch)
            workspace.commit_if_staged(files, message)

            merge(cwd=path, branch=branch, title=message, dry_run=False)
        except BaseException as exc:
            primary_exc = exc
            raise
        finally:
            self._return_sibling_to_main(cwd, name, primary_exc)

        return True

    def _return_sibling_to_main(
        self, cwd: str, name: str, primary_exc: BaseException | None
    ) -> None:
        """Best-effort cleanup after ``merge_in_sibling``: leave the sibling
        checked out on ``main``.

        ``merge()`` already checks out main on success, so this is a no-op
        in that case; on failure it prevents a stale branch from breaking a
        subsequent release. Runs from a ``finally`` block, so a
        ``TimeoutExpired`` here (a hung git hook) must not silently replace
        whatever exception is already propagating when ``primary_exc`` is
        set — it is folded into the same secondary-failure reporting as a
        non-zero checkout exit instead. When there is no primary exception
        in flight, a cleanup timeout is itself the only failure and
        propagates exactly as it did before this method existed.
        """
        try:
            branch_result = self._ops.run(
                ["git", "branch", "--show-current"], cwd=cwd, check=False
            )
        except subprocess.TimeoutExpired:
            if primary_exc is None:
                raise
            self._report_cleanup_failure(name, primary_exc, "branch lookup timed out")
            return
        current = (
            branch_result.stdout.strip() if branch_result.returncode == 0 else None
        )
        if current is None:
            # A failed branch lookup is exactly as much a secondary
            # cleanup failure as a failed checkout below — route it the
            # same way when a primary exception is in flight, instead of
            # only info-logging it and leaving it out of the recap.
            self._report_cleanup_failure(
                name, primary_exc, "could not read current branch"
            )
            return
        if current == "main":
            return
        try:
            checkout = self._ops.run(
                ["git", "checkout", "main"], cwd=cwd, check=False, timeout=GIT_HOOK
            )
        except subprocess.TimeoutExpired:
            if primary_exc is None:
                raise
            self._report_cleanup_failure(name, primary_exc, "checkout timed out")
            return
        if checkout.returncode != 0:
            self._report_cleanup_failure(name, primary_exc, checkout.stderr.strip())

    def _report_cleanup_failure(
        self, name: str, primary_exc: BaseException | None, detail: str
    ) -> None:
        """Report a sibling-cleanup secondary failure.

        A secondary failure on top of a primary one leaves the sibling in a
        worse state than the primary alone would suggest — route it through
        ``SkipRecorder`` (when the caller threaded one through) so it
        reaches the end-of-run recap instead of only an info line, which
        can scroll past among Phase 10's concurrent output. Falls back to
        the original info-only warning when no recorder is present, or when
        this cleanup failure isn't secondary to anything (no primary
        exception in flight).
        """
        if self._skips is not None and primary_exc is not None:
            self._skips.record(
                f"Sibling {name} failed ({primary_exc}) AND could not be "
                f"returned to main: {detail} — inspect and clean up manually"
            )
        else:
            self._ops.info(
                f"Warning: could not return sibling {name} to main: {detail}"
            )
