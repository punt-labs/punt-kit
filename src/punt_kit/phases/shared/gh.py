"""GitHub repo resolution, branch protection, and required-check polling."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast, final
from urllib.parse import urlparse

from punt_kit.phases.shared.timeouts import NO_CHECKS_GRACE

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from punt_kit.phases.shared.ops import ReleaseOps

# A check has failed if it completed with a failure conclusion.
_FAILURE_CONCLUSIONS = frozenset(
    {
        "failure",
        "cancelled",
        "timed_out",
        "action_required",
        "startup_failure",
        "error",
    }
)


@final
class GithubRepo:
    """A project's GitHub repository, resolved from its git remote."""

    __slots__ = ("_ops", "_root")

    _root: Path
    _ops: ReleaseOps

    def __new__(cls, root: Path, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._root = root
        self._ops = ops
        return self

    def resolve(self) -> str | None:
        """Extract GitHub owner/repo from git remote. ``None`` if unresolvable."""
        try:
            result = self._ops.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(self._root),
                check=False,
            )
            if result.returncode != 0:
                return None
            url = result.stdout.strip()
            if url.startswith("git@github.com:"):
                return url.removeprefix("git@github.com:").removesuffix(".git")
            parsed = urlparse(url)
            if parsed.hostname == "github.com":
                repo = parsed.path.lstrip("/").removesuffix(".git")
                if repo:
                    return repo
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None

    def has_branch_protection(self, gh: str, owner: str, repo_name: str) -> bool:
        """True if ``main`` has a branch protection rule.

        ``gh api .../branches/main/protection`` returns HTTP 404 with the
        message body ``"Branch not protected"`` when no protection rule is
        configured. The SAME endpoint also 404s when the token lacks
        ``admin:repo`` permissions on a repo that DOES have protection —
        with a different error message (typically ``"Not Found"`` or an
        HTTP-401 that gh surfaces as 404). Distinguishing the two requires
        the explicit ``"branch not protected"`` marker: any 404 without
        that marker is ambiguous and falls through as protected=True, along
        with every other failure mode (network, rate limit, timeout, wrong
        scope). Fail-safe direction: the isRequired-only wait behavior is
        preserved for anything we cannot confirm is genuinely unprotected.
        """
        try:
            result = self._ops.run(
                [gh, "api", f"repos/{owner}/{repo_name}/branches/main/protection"],
                cwd=str(self._root),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return True
        if result.returncode == 0:
            return True
        combined = (result.stderr + result.stdout).lower()
        return "branch not protected" not in combined

    def has_ruleset(self, gh: str, owner: str, repo_name: str) -> bool:
        """True if a GitHub ruleset (not the legacy branch-protection API)
        governs ``main``.

        ``gh api repos/{owner}/{repo}/rules/branches/main`` returns the list
        of *active* rules for the branch — a JSON array, empty when no
        ruleset targets it. This is a distinct mechanism from classic branch
        protection: a repo can be fully governed (required status checks,
        required conversation resolution) by a ruleset while
        ``has_branch_protection`` reports "branch not protected", because
        the legacy endpoint only ever sees the legacy feature. ``ethos``
        governs ``main`` this way — 2 required status checks plus
        conversation resolution, entirely via rulesets.

        Fail-safe direction matches ``has_branch_protection``: any failure
        to positively confirm a ruleset (timeout, non-zero exit, unparsable
        body) reports ``False`` rather than risk suppressing the "no branch
        protection" warning on a repo that turns out to be genuinely
        unprotected.
        """
        try:
            result = self._ops.run(
                [gh, "api", f"repos/{owner}/{repo_name}/rules/branches/main"],
                cwd=str(self._root),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False
        if result.returncode != 0:
            return False
        try:
            rules = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False
        return isinstance(rules, list) and len(cast("list[object]", rules)) > 0


@final
class RequiredChecksWaiter:
    """Polls required CI checks on a PR until all pass or any fail."""

    __slots__ = ("_ops", "_repo")

    _repo: GithubRepo
    _ops: ReleaseOps

    def __new__(cls, repo: GithubRepo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._repo = repo
        self._ops = ops
        return self

    def wait(
        self,
        gh: str,
        cwd: str,
        pr_number: int,
        *,
        resolve_repo: Callable[[Path], str | None],
        interrupted: threading.Event,
    ) -> None:
        """Poll required CI checks until all pass or any fail.

        Uses a direct GraphQL query to get ``isRequired(pullRequestNumber:
        N)`` which the ``gh pr view --json statusCheckRollup`` path cannot
        populate (the ``isRequired`` field is always null without the PR
        number argument). Ignores non-required checks (e.g. Anthropic's
        'Claude Code Review') when the repo is governed — by legacy branch
        protection or by a modern ruleset. A repo governed by neither has no
        ``isRequired`` checks at all, so this falls back to waiting for
        every check instead of failing after the no-checks grace window.

        ``resolve_repo`` is injected rather than calling
        ``self._repo.resolve()`` directly so callers that expose repo
        resolution as a monkeypatchable seam
        (``punt_kit.release._get_github_repo``) can pass that seam through
        unchanged.

        ``interrupted`` is release.py's own ``threading.Event`` — checked at
        the top of every loop iteration so an operator's Ctrl-C reaches a
        worker thread blocked here (e.g. inside Phase 10's sibling PR merge)
        within one poll interval instead of only after the full two-hour
        deadline. Worker threads never receive the SIGINT that sets the
        event directly — only the main thread does — so without this check a
        hung wait blocks ``ThreadPoolExecutor.__exit__``'s join for the
        remainder of the deadline, which is what let interrupting a vox
        v5.0.4-style hang leave the release silently unfinished instead of
        failing fast (pkit-d7mz).
        """
        repo_slug = resolve_repo(Path(cwd))
        if not repo_slug or "/" not in repo_slug:
            self._ops.fail(
                f"Cannot determine GitHub owner/repo from git remote in {cwd}"
            )
        owner, repo_name = repo_slug.split("/", 1)

        branch_protected = self._repo.has_branch_protection(gh, owner, repo_name)
        ruleset_governed = self._repo.has_ruleset(gh, owner, repo_name)
        governed = branch_protected or ruleset_governed
        if not governed:
            self._ops.warn(
                f"No branch protection or ruleset configured on {owner}/{repo_name}'s "
                "main branch — waiting for ALL checks to pass instead of only "
                "required ones"
            )

        self._ops.info(
            f"Waiting for {'required' if governed else 'all'} CI checks "
            f"on PR #{pr_number}..."
        )
        deadline = time.time() + 7200
        no_checks_deadline = time.time() + NO_CHECKS_GRACE
        consecutive_errors = 0

        query = (
            "{"
            f'  repository(owner: "{owner}", name: "{repo_name}") {{'
            f"    pullRequest(number: {pr_number}) {{"
            "      commits(last: 1) {"
            "        nodes {"
            "          commit {"
            "            statusCheckRollup {"
            "              contexts(first: 100) {"
            "                nodes {"
            "                  ... on CheckRun {"
            "                    name"
            f"                    isRequired(pullRequestNumber: {pr_number})"
            "                    conclusion"
            "                    status"
            "                  }"
            "                  ... on StatusContext {"
            "                    context"
            f"                    isRequired(pullRequestNumber: {pr_number})"
            "                    state"
            "                  }"
            "                }"
            "              }"
            "            }"
            "          }"
            "        }"
            "      }"
            "    }"
            "  }"
            "}"
        )

        while time.time() < deadline:
            if interrupted.is_set():
                self._ops.fail(
                    f"Interrupted while waiting for CI checks on PR #{pr_number} — "
                    "resume once checks are healthy."
                )
            try:
                result = self._ops.run(
                    [gh, "api", "graphql", "-f", f"query={query}"],
                    cwd=cwd,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                # A query that does not return is a query that failed. Route
                # the timeout through the same five-strikes path a non-zero
                # exit takes, so an isolated slow response costs one strike
                # instead of aborting a release whose polling window has
                # barely opened. Five consecutive failures still stop the
                # release — a GitHub that never answers is not something to
                # wait out.
                result = subprocess.CompletedProcess(
                    args=[],
                    returncode=1,
                    stdout="",
                    stderr="gh api graphql timed out",
                )
            if result.returncode != 0:
                consecutive_errors += 1
                self._ops.info(
                    f"GraphQL query failed ({consecutive_errors}/5): "
                    f"{(result.stderr or result.stdout).strip()}"
                )
                if consecutive_errors >= 5:
                    self._ops.fail(
                        f"GraphQL query failed 5 consecutive times on PR "
                        f"#{pr_number} — check GitHub token and network "
                        "connectivity"
                    )
                time.sleep(15)
                continue

            try:
                raw = cast("dict[str, object]", json.loads(result.stdout))
            except json.JSONDecodeError as exc:
                consecutive_errors += 1
                self._ops.info(
                    f"Could not parse GraphQL response ({consecutive_errors}/5): "
                    f"{exc} — output: {result.stdout[:100]!r}"
                )
                if consecutive_errors >= 5:
                    self._ops.fail(
                        f"GraphQL query failed 5 consecutive times on PR "
                        f"#{pr_number} — unparseable responses"
                    )
                time.sleep(15)
                continue

            # Check for GraphQL-level errors
            if "errors" in raw:
                consecutive_errors += 1
                self._ops.info(
                    f"GraphQL returned errors ({consecutive_errors}/5): {raw['errors']}"
                )
                if consecutive_errors >= 5:
                    self._ops.fail(
                        f"GraphQL query failed 5 consecutive times on PR "
                        f"#{pr_number} — errors: {raw['errors']}"
                    )
                time.sleep(15)
                continue

            # Reset only after we have a valid, error-free GraphQL response
            consecutive_errors = 0

            # Navigate the nested GraphQL response to extract check nodes
            try:
                data = cast("dict[str, object]", raw["data"])
                repository = cast("dict[str, object]", data["repository"])
                pull_request = cast("dict[str, object]", repository["pullRequest"])
                commits = cast("dict[str, object]", pull_request["commits"])
                nodes = cast("list[dict[str, object]]", commits["nodes"])
                commit = cast("dict[str, object]", nodes[0]["commit"])
                rollup = commit["statusCheckRollup"]
                # GitHub returns a null rollup until the first check run is
                # attached to the commit, which on a freshly-opened PR is
                # every poll for the first few seconds. That is the normal
                # state, not a malformed response — reporting it as
                # "unexpected" fired on every PR of every release and taught
                # the operator to read warnings as noise. Say what is
                # actually happening and keep waiting.
                if rollup is None:
                    self._no_checks_grace_check(
                        no_checks_deadline, pr_number, checks_present=False
                    )
                    self._ops.info(
                        "No checks registered on the commit yet — waiting..."
                    )
                    time.sleep(15)
                    continue
                rollup_obj = cast("dict[str, object]", rollup)
                contexts = cast("dict[str, object]", rollup_obj["contexts"])
                check_nodes = cast("list[dict[str, object]]", contexts["nodes"])
            except (KeyError, IndexError, TypeError) as exc:
                self._ops.info(
                    f"Unexpected GraphQL response structure (will retry): {exc}"
                )
                time.sleep(15)
                continue

            # Normalize CheckRun and StatusContext into a uniform format.
            # CheckRun has: name, isRequired, conclusion, status
            # StatusContext has: context (not name), isRequired, state (not status)
            checks: list[dict[str, object]] = []
            for node in check_nodes:
                if "name" in node:
                    # CheckRun — conclusion is the terminal result, status is
                    # the lifecycle state (QUEUED, IN_PROGRESS, COMPLETED)
                    checks.append(
                        {
                            "name": node["name"],
                            "isRequired": node.get("isRequired"),
                            "conclusion": node.get("conclusion"),
                            "status": node.get("status"),
                        }
                    )
                elif "context" in node:
                    # StatusContext — state is SUCCESS/FAILURE/PENDING/ERROR/EXPECTED
                    # PENDING and EXPECTED mean the check hasn't completed
                    state = str(node.get("state", "")).upper()
                    checks.append(
                        {
                            "name": node["context"],
                            "isRequired": node.get("isRequired"),
                            "conclusion": state.lower() if state else None,
                            "status": (
                                "PENDING"
                                if state in ("PENDING", "EXPECTED")
                                else "COMPLETED"
                            ),
                        }
                    )

            relevant = (
                [c for c in checks if c.get("isRequired")] if governed else checks
            )
            # "Required" only means something when the repo is governed —
            # otherwise every check is being waited on.
            prefix = "Required " if governed else ""

            if not relevant:
                # ``checks`` (pre-isRequired-filter) distinguishes two
                # distinct zero-check states: nothing has attached to the
                # commit yet (checks empty), vs. checks have attached but
                # none are required (checks non-empty, relevant empty —
                # only possible when governed).
                self._no_checks_grace_check(
                    no_checks_deadline, pr_number, checks_present=bool(checks)
                )
                time.sleep(5)
                continue

            failed = [
                c
                for c in relevant
                if str(c.get("conclusion", "")).lower() in _FAILURE_CONCLUSIONS
            ]
            if failed:
                names = ", ".join(str(c.get("name", "?")) for c in failed)
                self._ops.fail(f"{prefix}CI checks failed on PR #{pr_number}: {names}")

            # A check is pending if it has not reached COMPLETED status.
            pending = [
                c for c in relevant if str(c.get("status", "")).upper() != "COMPLETED"
            ]

            if not pending:
                names = ", ".join(str(c.get("name", "?")) for c in relevant)
                self._ops.ok(f"{prefix}CI checks passed: {names}")
                return

            names = ", ".join(str(c.get("name", "?")) for c in pending)
            self._ops.info(f"Waiting for: {names}")
            time.sleep(15)

        label = "required" if governed else "all"
        self._ops.fail(f"Timed out waiting for {label} CI checks on PR #{pr_number}")

    def _no_checks_grace_check(
        self, no_checks_deadline: float, pr_number: int, *, checks_present: bool
    ) -> None:
        """Fail loudly once the no-checks grace window expires.

        Called from both zero-``relevant``-check states — a null
        ``statusCheckRollup`` (no CheckRun has attached to the commit at
        all) and a non-null rollup whose ``contexts`` list has nothing
        relevant — because both mean "there is nothing to wait on yet" from
        the caller's point of view and must share one bounded window rather
        than each restarting it. ``checks_present`` distinguishes the two
        for the failure message: ``False`` means nothing has registered on
        the commit at all (a null rollup); ``True`` means checks exist but
        none are required (a non-null rollup whose contexts were filtered
        to empty by the ``isRequired`` narrowing — only possible when the
        repo is governed). Never merges a PR on the strength of zero
        checks: this always raises, so the caller can only proceed once a
        required check registers.
        """
        if time.time() <= no_checks_deadline:
            return
        # Ceiling division: a non-minute-multiple grace window (e.g.
        # 90s) must round up to "2 minutes", not floor to "1 minute"
        # and under-report how long the wait actually was.
        grace_minutes = -(-NO_CHECKS_GRACE // 60)
        if checks_present:
            self._ops.fail(
                f"CI checks are registered on PR #{pr_number}, but none are "
                f"required, and none became required within {grace_minutes} "
                "minutes. Likely causes: branch protection/ruleset names a "
                "required check that has not run on this PR, or the wrong "
                "workflow is configured as required. Fix the required-checks "
                "configuration, then resume."
            )
        self._ops.fail(
            f"No CI checks registered at all on PR #{pr_number} within "
            f"{grace_minutes} minutes. Likely causes: a `[skip ci]` marker "
            "on the head commit, or every workflow's `paths:` filter "
            "excluding the changed files. Fix the commit or workflow "
            "configuration, then resume."
        )


@final
class PrThreadResolver:
    """Resolves unresolved review threads on a PR (Copilot/Bugbot auto-review)."""

    __slots__ = ("_ops", "_repo")

    _repo: GithubRepo
    _ops: ReleaseOps

    def __new__(cls, repo: GithubRepo, *, ops: ReleaseOps) -> Self:
        self = super().__new__(cls)
        self._repo = repo
        self._ops = ops
        return self

    def resolve(self, gh: str, cwd: str, pr_number: int) -> None:
        """Resolve all unresolved review threads on a PR.

        Copilot and Bugbot auto-post reviews on every PR. With
        required_review_thread_resolution=true, unresolved threads block
        merge.
        """
        repo = self._repo.resolve()
        if repo is None:
            return
        owner, name = repo.split("/", 1)

        query = (
            f'{{ repository(owner: "{owner}", name: "{name}") {{'
            f" pullRequest(number: {pr_number}) {{"
            " reviewThreads(first: 50) {"
            " nodes { id isResolved } } } } }"
        )

        result = self._ops.run(
            [gh, "api", "graphql", "-f", f"query={query}"],
            cwd=cwd,
            check=False,
        )
        if result.returncode != 0:
            self._ops.info("Could not fetch review threads — merge may fail")
            return

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            self._ops.info(
                f"Could not parse review thread response for PR #{pr_number} "
                f"({result.stdout[:100]!r}) — thread resolution skipped, merge "
                "may fail"
            )
            return

        threads = (
            data.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
            .get("nodes", [])
        )

        unresolved = [t["id"] for t in threads if not t.get("isResolved")]
        if not unresolved:
            return

        resolved = 0
        for tid in unresolved:
            mutation = (
                f'mutation {{ resolveReviewThread(input: {{threadId: "{tid}"}})'
                " { thread { isResolved } } }"
            )
            res = self._ops.run(
                [gh, "api", "graphql", "-f", f"query={mutation}"],
                cwd=cwd,
                check=False,
            )
            if res.returncode == 0:
                resolved += 1
            else:
                self._ops.info(f"Could not resolve thread {tid}: {res.stderr.strip()}")
        if resolved:
            self._ops.ok(f"Resolved {resolved}/{len(unresolved)} review thread(s)")
