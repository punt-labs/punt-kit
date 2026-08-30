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

    __slots__ = ("_ops",)

    _ops: ReleaseOps

    def __new__(cls, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._ops = ops
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
                    self._ops.run(
                        ["git", "checkout", "main"], cwd=root, timeout=GIT_HOOK
                    )
                    self._ops.run(
                        ["git", "pull", "--ff-only"], cwd=root, timeout=GIT_HOOK
                    )
                    sha = self._ops.run(
                        ["git", "rev-parse", "--short", "HEAD"], cwd=root
                    ).stdout.strip()
                    return sha
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
            self._ops.run(["git", "checkout", "main"], cwd=root, timeout=GIT_HOOK)
            self._ops.run(["git", "pull", "--ff-only"], cwd=root, timeout=GIT_HOOK)
            return self._ops.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=root
            ).stdout.strip()

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
        self._ops.run(["git", "checkout", "main"], cwd=root, timeout=GIT_HOOK)
        self._ops.run(["git", "pull", "--ff-only"], cwd=root, timeout=GIT_HOOK)
        return self._ops.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root
        ).stdout.strip()

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
        status = self._ops.run(
            ["git", "status", "--porcelain", "--", *files], cwd=cwd
        ).stdout.strip()
        if not status:
            return False

        if dry_run:
            self._ops.dry(f"{name}: {message}")
            return True

        # Use try/finally to ensure sibling returns to main on any failure —
        # ReleaseError from ops.fail(), CalledProcessError from ops.run(),
        # etc. (stale propagation branches break subsequent releases).
        try:
            workspace = GitWorkspace(path, ops=self._ops)
            workspace.checkout_or_create(branch)
            workspace.commit_if_staged(files, message)

            merge(cwd=path, branch=branch, title=message, dry_run=False)
        finally:
            # merge() checks out main on success; this is a no-op in that
            # case. On failure, this ensures we don't leave the sibling on a
            # stale branch.
            branch_result = self._ops.run(
                ["git", "branch", "--show-current"], cwd=cwd, check=False
            )
            current = (
                branch_result.stdout.strip() if branch_result.returncode == 0 else None
            )
            if current is None:
                self._ops.info(
                    f"Could not read current branch for sibling {name} after operation"
                )
            elif current != "main":
                checkout = self._ops.run(
                    ["git", "checkout", "main"],
                    cwd=cwd,
                    check=False,
                    timeout=GIT_HOOK,
                )
                if checkout.returncode != 0:
                    self._ops.info(
                        f"Warning: could not return sibling {name} to main: "
                        f"{checkout.stderr.strip()}"
                    )

        return True
