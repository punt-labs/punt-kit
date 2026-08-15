"""punt release — deterministic release workflow for Punt Labs projects."""

from __future__ import annotations

import datetime
import json
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Self, cast, final
from urllib.parse import urlparse

from rich.console import Console

from punt_kit.detect import ProjectInfo, detect

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

console = Console()


class ReleaseError(Exception):
    """Raised by release phases to indicate a failure with a message."""


# Set by the signal handler so threads can drain before cleanup runs.
_interrupted = threading.Event()

# Sibling repos checked during preflight and used during propagation (phase 10).
# Must stay in sync with the _propagate_* functions.
PROPAGATION_SIBLINGS = ["claude-plugins", ".github", "public-website"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = 7200,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with standard options."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
    )


def _fail(msg: str) -> NoReturn:
    """Print error and exit."""
    console.print(f"[red]Error:[/red] {msg}")
    raise ReleaseError(msg)


def _ok(msg: str) -> None:
    console.print(f"  [green]✓[/green] {msg}")


def _info(msg: str) -> None:
    console.print(f"  [dim]▶[/dim] {msg}")


def _dry(msg: str) -> None:
    console.print(f"  [yellow]DRY[/yellow] {msg}")


def _get_install_sh_sha(root: Path) -> str:
    """Get the short SHA of the commit that last modified install.sh.

    This is the correct SHA for install URL pinning.  Using the tag SHA
    is wrong for hybrid projects because the tag sits on the
    "prepare plugin for release" commit, which comes *after* the version-bump
    commit that actually changes install.sh.
    """
    result = _run(
        ["git", "log", "-1", "--format=%h", "--", "install.sh"],
        cwd=str(root),
    )
    sha = result.stdout.strip()
    if not sha:
        _fail("No commit found that touches install.sh")
    return sha


def _get_project_version(info: ProjectInfo) -> str:
    """Extract current version from pyproject.toml or git tags (Go)."""
    if info.language == "go":
        return _get_latest_tag_version(info.root)
    if info.pyproject is None:
        _fail("No pyproject.toml found")
    project = info.pyproject.get("project")
    if not isinstance(project, dict):
        _fail("No [project] section in pyproject.toml")
    version = cast("dict[str, object]", project).get("version")
    if not isinstance(version, str):
        _fail("No version in pyproject.toml [project]")
    return version


def _get_latest_tag_version(root: Path) -> str:
    """Get the latest semantic version from git tags."""
    result = _run(
        ["git", "tag", "--list", "v*", "--sort=-v:refname"],
        cwd=str(root),
    )
    tags = result.stdout.strip().splitlines()
    if not tags:
        return "0.0.0"
    # Strip 'v' prefix
    return tags[0].removeprefix("v")


def _get_package_name(info: ProjectInfo) -> str:
    """Extract package name from pyproject.toml."""
    if info.pyproject is None:
        _fail("No pyproject.toml found")
    project = info.pyproject.get("project")
    if not isinstance(project, dict):
        _fail("No [project] section in pyproject.toml")
    name = cast("dict[str, object]", project).get("name")
    if not isinstance(name, str):
        _fail("No name in pyproject.toml [project]")
    return name


def _find_package_dir(info: ProjectInfo) -> Path | None:
    """Find the Python package directory (src layout)."""
    src_dir = info.root / "src"
    if not src_dir.is_dir():
        return None
    for child in sorted(src_dir.iterdir()):
        if child.is_dir() and (child / "__init__.py").exists():
            return child
    return None


def _get_github_repo(root: Path) -> str | None:
    """Extract GitHub owner/repo from git remote."""
    try:
        result = _run(
            ["git", "remote", "get-url", "origin"], cwd=str(root), check=False
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


def _read_changelog(root: Path) -> str:
    """Read CHANGELOG.md content."""
    changelog = root / "CHANGELOG.md"
    if not changelog.exists():
        _fail("CHANGELOG.md not found")
    return changelog.read_text(encoding="utf-8")


def _extract_version_notes(changelog: str, version: str) -> str:
    """Extract release notes for a specific version from changelog."""
    # Match ## [X.Y.Z] - YYYY-MM-DD or ## [X.Y.Z]
    pattern = rf"## \[{re.escape(version)}\][^\n]*\n"
    match = re.search(pattern, changelog)
    if not match:
        return f"Release v{version}"

    start = match.end()
    # Find next ## heading
    next_heading = re.search(r"\n## \[", changelog[start:])
    end = start + next_heading.start() if next_heading else len(changelog)

    return changelog[start:end].strip()


def _resolve_pr_threads(gh: str, cwd: str, pr_number: int) -> None:
    """Resolve all unresolved review threads on a PR.

    Copilot and Bugbot auto-post reviews on every PR. With
    required_review_thread_resolution=true, unresolved threads block merge.
    """
    repo = _get_github_repo(Path(cwd))
    if repo is None:
        return
    owner, name = repo.split("/", 1)

    query = (
        f'{{ repository(owner: "{owner}", name: "{name}") {{'
        f" pullRequest(number: {pr_number}) {{"
        " reviewThreads(first: 50) {"
        " nodes { id isResolved } } } } }"
    )

    result = _run(
        [gh, "api", "graphql", "-f", f"query={query}"],
        cwd=cwd,
        check=False,
    )
    if result.returncode != 0:
        _info("Could not fetch review threads — merge may fail")
        return

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        _info(
            f"Could not parse review thread response for PR #{pr_number} "
            f"({result.stdout[:100]!r}) — thread resolution skipped, merge may fail"
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
        res = _run(
            [gh, "api", "graphql", "-f", f"query={mutation}"],
            cwd=cwd,
            check=False,
        )
        if res.returncode == 0:
            resolved += 1
        else:
            _info(f"Could not resolve thread {tid}: {res.stderr.strip()}")
    if resolved:
        _ok(f"Resolved {resolved}/{len(unresolved)} review thread(s)")


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------


def _phase1_preflight(info: ProjectInfo, *, dry_run: bool) -> None:
    """Phase 1: Pre-flight checks."""
    console.print("\n[bold]Phase 1: Pre-flight[/bold]")

    # 1a. Git state
    branch = _run(
        ["git", "branch", "--show-current"], cwd=str(info.root)
    ).stdout.strip()
    if branch != "main":
        _fail(f"Must be on main branch (currently on '{branch}')")
    _ok("On main branch")

    status = _run(["git", "status", "--porcelain"], cwd=str(info.root)).stdout.strip()
    dirty_lines: list[str] = []
    untracked_lines: list[str] = []
    for ln in status.splitlines():
        path = ln[3:] if len(ln) > 3 else ""
        if path == ".beads" or path.startswith(".beads/"):
            continue
        if ln.startswith("?? "):
            untracked_lines.append(ln)
        else:
            dirty_lines.append(ln)
    if dirty_lines:
        dirty = "\n".join(dirty_lines)
        _fail(f"Working tree is not clean:\n{dirty}")
    if untracked_lines:
        # Untracked files at release time are almost always noise (temp
        # files, forgotten artifacts) that must not ride along in release
        # commits — force the operator to commit, gitignore, or remove them.
        untracked = "\n".join(untracked_lines)
        _fail(
            "Untracked files present — commit, gitignore, or remove them "
            f"before releasing:\n{untracked}"
        )
    _ok("Working tree clean")

    fetch = _run(["git", "fetch", "origin"], cwd=str(info.root), check=False)
    if fetch.returncode != 0:
        _fail(f"git fetch origin failed:\n{fetch.stderr.strip()}")
    diff = _run(
        ["git", "diff", "HEAD", "origin/main", "--stat"],
        cwd=str(info.root),
        check=False,
    )
    if diff.returncode != 0:
        _fail(f"git diff failed:\n{diff.stderr.strip()}")
    if diff.stdout.strip():
        _fail(f"Not up to date with origin/main:\n{diff.stdout.strip()}")
    _ok("Up to date with origin/main")

    # 1b. Project type (already detected)
    if info.is_hybrid:
        ptype = "hybrid"
    elif info.is_plugin:
        ptype = "plugin"
    else:
        ptype = "CLI-only"
    _ok(f"Project type: {ptype}")

    if info.is_hybrid or info.is_plugin:
        release_script = info.root / "scripts" / "release-plugin.sh"
        restore_script = info.root / "scripts" / "restore-dev-plugin.sh"
        if not release_script.exists() or not restore_script.exists():
            _fail("Missing release-plugin.sh or restore-dev-plugin.sh")
        _ok("Release/restore scripts present")

    # 1c. Changelog check
    changelog = _read_changelog(info.root)
    if "## [Unreleased]" not in changelog:
        _fail("No [Unreleased] section in CHANGELOG.md")

    unreleased_match = re.search(
        r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|\Z)", changelog, re.DOTALL
    )
    if not unreleased_match or not unreleased_match.group(1).strip():
        _fail("[Unreleased] section is empty — nothing to release")
    _ok("Changelog has unreleased entries")

    # 1d. Sibling repos (propagation targets) must be clean and on main
    # Check early so we fail before quality gates, not mid-propagation (91t).
    # Also catches stale propagation branches from prior releases (5b4/zay).
    siblings_checked = 0
    for sib_name in PROPAGATION_SIBLINGS:
        sib_path = _resolve_sibling(info.root, sib_name)
        if sib_path is not None:
            _validate_sibling(sib_path, sib_name)
            siblings_checked += 1
    if siblings_checked > 0:
        _ok(f"Sibling repos ready ({siblings_checked} checked)")
    else:
        _info("No sibling repos found (propagation will be skipped)")

    # 1e. Quality gates
    if not dry_run and info.language == "python":
        _info("Running quality gates...")
        gates = [
            ["uv", "run", "ruff", "check", "src/", "tests/"],
            ["uv", "run", "ruff", "format", "--check", "src/", "tests/"],
            ["uv", "run", "mypy", "src/", "tests/"],
            ["uv", "run", "pyright", "src/", "tests/"],
            ["uv", "run", "pytest", "tests/", "-v"],
        ]
        for gate in gates:
            result = _run(gate, cwd=str(info.root), check=False, capture=False)
            if result.returncode != 0:
                _fail(f"Quality gate failed: {' '.join(gate)}")
        _ok("All quality gates passed")
    elif not dry_run and info.language == "go":
        _info("Running quality gates...")
        makefile = info.root / "Makefile"
        if makefile.exists():
            result = _run(
                ["make", "check"], cwd=str(info.root), check=False, capture=False
            )
            if result.returncode != 0:
                _fail("Quality gate failed: make check")
        else:
            for gate in [["go", "vet", "./..."], ["go", "test", "-race", "./..."]]:
                result = _run(gate, cwd=str(info.root), check=False, capture=False)
                if result.returncode != 0:
                    _fail(f"Quality gate failed: {' '.join(gate)}")
        _ok("All quality gates passed")
    elif dry_run:
        _dry("Would run quality gates")


def _suggest_version(changelog: str, current: str) -> str:
    """Suggest a version bump based on changelog content."""
    unreleased = re.search(
        r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|\Z)", changelog, re.DOTALL
    )
    if not unreleased:
        return current

    content = unreleased.group(1)
    parts = current.split(".")
    if len(parts) != 3:
        return current

    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    # Check for breaking changes only within the ### Changed subsection
    changed_match = re.search(r"### Changed\n(.*?)(?=\n### |\Z)", content, re.DOTALL)
    has_breaking = (
        changed_match is not None and "breaking" in changed_match.group(1).lower()
    )
    if has_breaking:
        return f"{major + 1}.0.0"
    if "### Added" in content:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _wait_for_required_checks(gh: str, cwd: str, pr_number: int) -> None:
    """Poll required CI checks until all pass or any fail.

    Uses a direct GraphQL query to get ``isRequired(pullRequestNumber: N)``
    which the ``gh pr view --json statusCheckRollup`` path cannot populate
    (the ``isRequired`` field is always null without the PR number argument).
    Ignores non-required checks (e.g. Anthropic's 'Claude Code Review').
    """
    repo_slug = _get_github_repo(Path(cwd))
    if not repo_slug or "/" not in repo_slug:
        _fail(f"Cannot determine GitHub owner/repo from git remote in {cwd}")
    owner, repo_name = repo_slug.split("/", 1)

    _info(f"Waiting for required CI checks on PR #{pr_number}...")
    deadline = time.time() + 7200
    no_checks_attempts = 0
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
        result = _run(
            [gh, "api", "graphql", "-f", f"query={query}"],
            cwd=cwd,
            check=False,
        )
        if result.returncode != 0:
            consecutive_errors += 1
            _info(
                f"GraphQL query failed ({consecutive_errors}/5): "
                f"{(result.stderr or result.stdout).strip()}"
            )
            if consecutive_errors >= 5:
                _fail(
                    f"GraphQL query failed 5 consecutive times on PR #{pr_number} — "
                    "check GitHub token and network connectivity"
                )
            time.sleep(15)
            continue

        try:
            raw = cast("dict[str, object]", json.loads(result.stdout))
        except json.JSONDecodeError as exc:
            consecutive_errors += 1
            _info(
                f"Could not parse GraphQL response ({consecutive_errors}/5): {exc} — "
                f"output: {result.stdout[:100]!r}"
            )
            if consecutive_errors >= 5:
                _fail(
                    f"GraphQL query failed 5 consecutive times on PR #{pr_number} — "
                    "unparseable responses"
                )
            time.sleep(15)
            continue

        # Check for GraphQL-level errors
        if "errors" in raw:
            consecutive_errors += 1
            _info(f"GraphQL returned errors ({consecutive_errors}/5): {raw['errors']}")
            if consecutive_errors >= 5:
                _fail(
                    f"GraphQL query failed 5 consecutive times on PR #{pr_number} — "
                    f"errors: {raw['errors']}"
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
            rollup_obj = cast("dict[str, object]", commit["statusCheckRollup"])
            contexts = cast("dict[str, object]", rollup_obj["contexts"])
            check_nodes = cast("list[dict[str, object]]", contexts["nodes"])
        except (KeyError, IndexError, TypeError) as exc:
            _info(f"Unexpected GraphQL response structure (will retry): {exc}")
            time.sleep(15)
            continue

        # Normalize CheckRun and StatusContext into a uniform format.
        # CheckRun has: name, isRequired, conclusion, status
        # StatusContext has: context (not name), isRequired, state (not status)
        checks: list[dict[str, object]] = []
        for node in check_nodes:
            if "name" in node:
                # CheckRun — conclusion is the terminal result,
                # status is the lifecycle state (QUEUED, IN_PROGRESS, COMPLETED)
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

        required = [c for c in checks if c.get("isRequired")]

        if not required:
            no_checks_attempts += 1
            if no_checks_attempts > 24:  # 2 minutes at 5s intervals
                _fail(
                    f"No required checks found on PR #{pr_number} after 2 minutes — "
                    "check branch protection configuration"
                )
            time.sleep(5)
            continue

        no_checks_attempts = 0

        # A check has failed if it completed with a failure conclusion.
        _failure_conclusions = frozenset(
            {
                "failure",
                "cancelled",
                "timed_out",
                "action_required",
                "startup_failure",
                "error",
            }
        )
        failed = [
            c
            for c in required
            if str(c.get("conclusion", "")).lower() in _failure_conclusions
        ]
        if failed:
            names = ", ".join(str(c.get("name", "?")) for c in failed)
            _fail(f"Required CI checks failed on PR #{pr_number}: {names}")

        # A check is pending if it has not reached COMPLETED status.
        pending = [
            c for c in required if str(c.get("status", "")).upper() != "COMPLETED"
        ]

        if not pending:
            names = ", ".join(str(c.get("name", "?")) for c in required)
            _ok(f"Required CI checks passed: {names}")
            return

        names = ", ".join(str(c.get("name", "?")) for c in pending)
        _info(f"Waiting for: {names}")
        time.sleep(15)

    _fail(f"Timed out waiting for required CI checks on PR #{pr_number}")


def _select_existing_pr(
    prs: list[dict[str, object]], local_head: str
) -> tuple[int | None, bool]:
    """Pick which same-named PR, if any, represents the current release.

    Returns ``(pr_number, already_merged)``. An OPEN PR is always the
    current release. A MERGED PR counts only when its head commit matches
    the local branch head — a merged PR at a different head is a stale
    earlier attempt, and treating it as current would skip the version
    bump and tag an unbumped commit. CLOSED PRs are never current: their
    CI is dead and waiting on it never completes.
    """
    for pr in prs:
        if pr.get("state") == "OPEN":
            return cast("int", pr["number"]), False
    for pr in prs:
        if pr.get("state") == "MERGED" and pr.get("headRefOid") == local_head:
            return cast("int", pr["number"]), True
    return None, False


def _pr_is_merged(gh: str, cwd: str, pr_number: int) -> bool:
    """Check whether a PR has reached the MERGED state."""
    state = _run(
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


def _pr_merge(
    *,
    cwd: Path,
    branch: str,
    title: str,
    body: str = "",
    dry_run: bool = False,
) -> str:
    """Push branch, create PR, wait for CI, squash-merge. Return merge SHA."""
    gh = shutil.which("gh")
    if gh is None:
        _fail("gh CLI not found — install from https://cli.github.com")

    root = str(cwd)

    if dry_run:
        _dry(f"git push -u origin {branch}")
        _dry(f'gh pr create --base main --head {branch} --title "{title}"')
        _dry("gh pr view <number> --json statusCheckRollup  # poll required checks")
        _dry("gh pr merge <number> --squash --delete-branch")
        return "<SHA>"

    # 1. Push branch (idempotent)
    result = _run(
        ["git", "push", "-u", "origin", branch], cwd=root, check=False, capture=False
    )
    if result.returncode != 0:
        _fail(f"Failed to push branch {branch} — fix and retry")
    _ok(f"Pushed branch {branch}")

    # 2. Check for existing PRs (include merged/closed for resume). Only an
    # OPEN PR or a MERGED PR at this exact head represents the current
    # release — see _select_existing_pr for why CLOSED and stale MERGED
    # PRs must be ignored.
    local_head = _run(["git", "rev-parse", branch], cwd=root).stdout.strip()
    existing = _run(
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
            _fail(f"Failed to parse gh pr list output: {existing.stdout[:200]}")
        pr_number, already_merged = _select_existing_pr(prs, local_head)
        if pr_number is not None:
            if already_merged:
                _ok(f"PR #{pr_number} already merged")
                _run(["git", "checkout", "main"], cwd=root)
                _run(["git", "pull", "--ff-only"], cwd=root)
                sha = _run(
                    ["git", "rev-parse", "--short", "HEAD"], cwd=root
                ).stdout.strip()
                return sha
            _info(f"Found existing open PR #{pr_number}")

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
        if body:
            create_cmd.extend(["--body", body])
        else:
            create_cmd.extend(["--body", ""])
        result = _run(create_cmd, cwd=root, check=False)
        if result.returncode != 0:
            _fail(f"Failed to create PR: {result.stderr.strip()}")
        # Extract PR number from output URL
        pr_url = result.stdout.strip()
        try:
            pr_number = int(pr_url.rstrip("/").split("/")[-1])
        except ValueError:
            _fail(f"Failed to extract PR number from gh output: {pr_url}")
        _ok(f"Created PR #{pr_number}")

    # 4. Wait for CI (required checks only — ignores non-required like "Claude Code Review")  # noqa: E501
    _wait_for_required_checks(gh, root, pr_number)

    # 5. Check if already merged (handles resume)
    state = _run(
        [gh, "pr", "view", str(pr_number), "--json", "state"],
        cwd=root,
        check=False,
    )
    if state.returncode != 0:
        _fail(f"Failed to check PR #{pr_number} state: {state.stderr.strip()}")
    try:
        pr_state = json.loads(state.stdout).get("state")
    except json.JSONDecodeError:
        _fail(f"Failed to parse gh pr view output: {state.stdout[:200]}")
    if pr_state == "MERGED":
        _ok(f"PR #{pr_number} already merged")
        _run(["git", "checkout", "main"], cwd=root)
        _run(["git", "pull", "--ff-only"], cwd=root)
        sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=root).stdout.strip()
        return sha

    # 6. Resolve review threads (Copilot/Bugbot auto-post on PRs)
    _resolve_pr_threads(gh, root, pr_number)

    # 7. Squash-merge (retry on branch protection / pending checks)
    # Some repos have long-running checks (CodeQL) that gh pr checks --watch
    # doesn't wait for if they aren't required. Branch protection may also
    # require conversation resolution that takes a moment to propagate. (n5i)
    merge_cmd = [
        gh,
        "pr",
        "merge",
        str(pr_number),
        "--squash",
        "--delete-branch",
    ]
    for merge_attempt in range(6):
        result = _run(merge_cmd, cwd=root, check=False)
        if result.returncode == 0:
            break
        # gh exits non-zero when the post-merge branch deletion fails even
        # though the merge itself succeeded: repos with "automatically
        # delete head branches" remove the branch during the merge, so
        # gh's own DELETE gets a 404 (or a transient 503). The
        # postcondition that matters is the PR state — check it before
        # classifying the exit code as a failure.
        if _pr_is_merged(gh, root, pr_number):
            _info(f"PR #{pr_number} merged; remote branch already deleted — continuing")
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
            _info(
                f"Merge blocked (attempt {merge_attempt + 1}/6), retrying in {wait}s..."
            )
            time.sleep(wait)
            # Re-resolve threads in case new ones appeared (best-effort)
            try:
                _resolve_pr_threads(gh, root, pr_number)
            except (ReleaseError, SystemExit, subprocess.CalledProcessError):
                _info("Could not re-resolve threads, proceeding with retry")
            continue
        _fail(f"Failed to merge PR #{pr_number}: {combined}")
    _ok(f"PR #{pr_number} merged")

    # 7. Update local main
    _run(["git", "checkout", "main"], cwd=root)
    _run(["git", "pull", "--ff-only"], cwd=root)
    sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=root).stdout.strip()
    return sha


def _phase2_version_bump(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 2: Bump version on release branch."""
    console.print(f"\n[bold]Phase 2: Version bump → {version}[/bold]")

    root = info.root
    branch = f"release/v{version}"

    # Create release branch
    if dry_run:
        _dry(f"git checkout -b {branch}")
    else:
        # Check if branch already exists (resume case)
        existing = _run(
            ["git", "branch", "--list", branch], cwd=str(root)
        ).stdout.strip()
        if existing:
            _run(["git", "checkout", branch], cwd=str(root))
            _info(f"Checked out existing branch {branch}")
        else:
            _run(["git", "checkout", "-b", branch], cwd=str(root))
            _ok(f"Created branch {branch}")

    # 2b. Bump version in pyproject.toml
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        new_content = re.sub(
            r'^(version\s*=\s*")[^"]*(")',
            rf"\g<1>{version}\2",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if dry_run:
            _dry(f'pyproject.toml: version = "{version}"')
        else:
            pyproject_path.write_text(new_content, encoding="utf-8")
            _ok(f'pyproject.toml: version = "{version}"')

    # Bump __init__.py __version__ (skip if version comes from importlib.metadata)
    pkg_dir = _find_package_dir(info)
    if pkg_dir is not None:
        init_py = pkg_dir / "__init__.py"
        if init_py.exists():
            content = init_py.read_text(encoding="utf-8")
            uses_metadata = (
                "importlib.metadata" in content or "importlib_metadata" in content
            )
            if "__version__" in content and not uses_metadata:
                new_content = re.sub(
                    r'^(__version__\s*=\s*")[^"]*(")',
                    rf"\g<1>{version}\2",
                    content,
                    count=1,
                    flags=re.MULTILINE,
                )
                if dry_run:
                    _dry(f'{init_py.name}: __version__ = "{version}"')
                else:
                    init_py.write_text(new_content, encoding="utf-8")
                    _ok(f'{init_py.name}: __version__ = "{version}"')

    # Bump plugin.json version
    plugin_json = root / ".claude-plugin" / "plugin.json"
    if plugin_json.exists():
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
        data["version"] = version
        if dry_run:
            _dry(f'plugin.json: version = "{version}"')
        else:
            plugin_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            _ok(f'plugin.json: version = "{version}"')

    # Bump install.sh VERSION pin
    install_sh = root / "install.sh"
    if install_sh.exists():
        content = install_sh.read_text(encoding="utf-8")
        new_content = re.sub(
            r'^(VERSION=")[^"]*(")',
            rf"\g<1>{version}\2",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if new_content != content:
            if dry_run:
                _dry(f'install.sh: VERSION="{version}"')
            else:
                install_sh.write_text(new_content, encoding="utf-8")
                _ok(f'install.sh: VERSION="{version}"')

    # 2c. Update CHANGELOG.md
    changelog_path = root / "CHANGELOG.md"
    if changelog_path.exists():
        today = datetime.date.today().isoformat()
        content = changelog_path.read_text(encoding="utf-8")
        new_content = content.replace(
            "## [Unreleased]",
            f"## [Unreleased]\n\n## [{version}] - {today}",
            1,
        )
        if dry_run:
            _dry(f"CHANGELOG.md: [Unreleased] → [{version}] - {today}")
        else:
            changelog_path.write_text(new_content, encoding="utf-8")
            _ok(f"CHANGELOG.md: [{version}] - {today}")

    # 2d. Refresh lock file and commit
    if dry_run:
        _dry("uv lock (refresh lock file)")
        _dry(f'git commit -m "chore: release v{version}"')
    else:
        lock_file = root / "uv.lock"
        if lock_file.exists():
            _run(["uv", "lock"], cwd=str(root))
            _ok("uv.lock refreshed")
        # Stage only the files this phase edits — `git add -A` would sweep
        # unrelated untracked files into the release commit.
        release_files = [
            pyproject_path,
            changelog_path,
            install_sh,
            plugin_json,
            lock_file,
        ]
        if pkg_dir is not None:
            release_files.append(pkg_dir / "__init__.py")
        to_stage = [str(p.relative_to(root)) for p in release_files if p.exists()]
        _run(["git", "add", "--", *to_stage], cwd=str(root))
        staged = _run(
            ["git", "diff", "--cached", "--name-only"], cwd=str(root)
        ).stdout.strip()
        if staged:
            _run(
                ["git", "commit", "-m", f"chore: release v{version}"],
                cwd=str(root),
            )
            _ok("Release commit created")
        else:
            _ok("Release commit already exists (resume)")


def _phase3_build(info: ProjectInfo, *, dry_run: bool) -> None:
    """Phase 3: Build validation."""
    if info.language != "python":
        return

    console.print("\n[bold]Phase 3: Build validation[/bold]")

    if dry_run:
        _dry("rm -rf dist/ && uv build && uvx twine check dist/*")
        return

    dist = info.root / "dist"
    if dist.exists():
        shutil.rmtree(dist)

    _run(["uv", "build"], cwd=str(info.root), capture=False)

    # twine check on built artifacts only (.whl and .tar.gz)
    dist_dir = info.root / "dist"
    artifacts = sorted(p for p in dist_dir.iterdir() if p.suffix in {".whl", ".gz"})
    if not artifacts:
        _fail("No build artifacts found in dist/ for twine check")

    result = _run(
        ["uvx", "twine", "check", *[str(p) for p in artifacts]],
        cwd=str(info.root),
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        _fail(f"twine check failed:\n{result.stdout}\n{result.stderr}")
    _ok("Build artifacts pass twine check")


def _phase4_release_pr(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 4: Plugin swap, push branch, create PR, merge."""
    console.print(f"\n[bold]Phase 4: Release PR v{version}[/bold]")

    root = info.root
    branch = f"release/v{version}"

    # 4a. Plugin swap (hybrid/plugin — idempotent: skip if already prod)
    if info.is_hybrid or info.is_plugin:
        release_script = root / "scripts" / "release-plugin.sh"
        if dry_run:
            _dry("bash scripts/release-plugin.sh")
        else:
            plugin_json = root / ".claude-plugin" / "plugin.json"
            pj_data = json.loads(plugin_json.read_text(encoding="utf-8"))
            if pj_data.get("name", "").endswith("-dev"):
                _run(
                    ["bash", str(release_script)],
                    cwd=str(root),
                    capture=False,
                )
                _ok("Plugin swapped to prod")
            else:
                _ok("Plugin already in prod state (resume)")

    # 4b. Push branch, create PR, wait for CI, squash-merge
    _pr_merge(
        cwd=root,
        branch=branch,
        title=f"chore: release v{version}",
        dry_run=dry_run,
    )


def _phase5_tag(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 5: Tag main HEAD and push tag."""
    console.print(f"\n[bold]Phase 5: Tag v{version}[/bold]")

    root = info.root
    tag = f"v{version}"

    if dry_run:
        _dry(f"git tag {tag}")
        _dry(f"git push origin {tag}")
        return

    # Ensure we're on main (resume may leave us on release branch)
    current = _run(["git", "branch", "--show-current"], cwd=str(root)).stdout.strip()
    if current != "main":
        _run(["git", "checkout", "main"], cwd=str(root))
        _run(["git", "pull", "--ff-only"], cwd=str(root))

    # Check if tag already exists
    existing = _run(["git", "tag", "--list", tag], cwd=str(root)).stdout.strip()
    if existing:
        # Verify it points to HEAD
        tag_sha = _run(["git", "rev-parse", tag], cwd=str(root)).stdout.strip()
        head_sha = _run(["git", "rev-parse", "HEAD"], cwd=str(root)).stdout.strip()
        if tag_sha == head_sha:
            _ok(f"Tag {tag} already exists at HEAD")
        else:
            _fail(
                f"Tag {tag} exists but points to {tag_sha[:8]}, "
                f"not HEAD ({head_sha[:8]})"
            )
        return

    _run(["git", "tag", tag], cwd=str(root))
    _ok(f"Tagged {tag}")

    # Push tag (not blocked by branch protection — targets refs/tags/*)
    _run(["git", "push", "origin", tag], cwd=str(root), capture=False)
    _ok(f"Pushed tag {tag}")


def _bump_readme_install_sha(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Update SHA-pinned install.sh URLs in README to the install.sh commit."""
    root = info.root
    readme_path = root / "README.md"
    install_sh = root / "install.sh"
    if not readme_path.exists() or not install_sh.exists():
        return

    tag = f"v{version}"
    github_repo = _get_github_repo(root)
    if github_repo:
        owner, repo_name = github_repo.split("/", 1)
    else:
        owner, repo_name = "punt-labs", root.name

    # Get the short SHA of the commit that last modified install.sh
    short_sha = "<SHA>" if dry_run else _get_install_sh_sha(root)

    content = readme_path.read_text(encoding="utf-8")
    esc_owner = re.escape(owner)
    esc_repo = re.escape(repo_name)

    # Replace SHA-pinned install URLs: <owner>/<repo>/<hex-sha>/install.sh
    new_content = re.sub(
        rf"(raw\.githubusercontent\.com/{esc_owner}/{esc_repo}/)[0-9a-fA-F]{{7,40}}(/install\.sh)",
        rf"\g<1>{short_sha}\2",
        content,
    )

    # Also replace version-tag install URLs: <owner>/<repo>/v1.2.3/install.sh
    new_content = re.sub(
        rf"(raw\.githubusercontent\.com/{esc_owner}/{esc_repo}/)v[0-9]+\.[0-9]+\.[0-9]+(/install\.sh)",
        rf"\g<1>{short_sha}\2",
        new_content,
    )

    if new_content == content:
        return

    if dry_run:
        _dry(f"README.md: install URLs → {short_sha} ({tag})")
        return

    readme_path.write_text(new_content, encoding="utf-8")
    _ok(f"README.md: install URLs → {short_sha} ({tag})")


# GitHub does not register a tag-triggered run instantly, so phase 6 polls
# rather than sleeping a fixed interval: a slow registration extends the wait
# instead of selecting whatever run happens to be newest at the moment we look.
_CI_RUN_POLL_INTERVAL = 5.0
_CI_RUN_POLL_ATTEMPTS = 24


@final
class _TagRunSelector:
    """Picks the workflow run that one specific tag push triggered.

    Three predicates, each rejecting a distinct kind of wrong run.
    ``headBranch`` rejects a run belonging to a different tag. ``event``
    rejects a manual dispatch rather than the tag push. ``headSha`` rejects a
    run left on the remote by an earlier tag of the same name pointing at a
    different commit, which is what a delete-and-recreate leaves behind. A run
    passing all three either is this push's run or ran against identical code,
    so its verdict is this release's verdict either way.

    There is deliberately no fallback to "some other recent run". A wait that
    cannot find its run has learned nothing about the release, and reporting a
    result the tag never earned is worse than stopping.
    """

    __slots__ = ("_commit", "_tag")

    _commit: str
    _tag: str

    def __new__(cls, tag: str, commit: str) -> Self:
        self = super().__new__(cls)
        self._tag = tag
        self._commit = commit
        return self

    @classmethod
    def list_command(cls, gh: str, tag: str) -> list[str]:
        """The gh invocation listing the runs worth considering for ``tag``.

        ``--branch`` filters by ref server-side, so the list holds only this
        tag's runs. Without it the limit is a truncation risk: enough
        unrelated releases between a failure and a ``--resume-from ci`` retry
        would push the target run off the end, which reads identically to the
        tag never having triggered CI.

        Built here rather than at the call site so the dry run prints the
        command the real run executes, instead of a paraphrase that can drift.
        """
        return [
            gh,
            "run",
            "list",
            "--workflow",
            "release.yml",
            "--branch",
            tag,
            "--limit",
            "20",
            "--json",
            "databaseId,headBranch,event,headSha,conclusion",
        ]

    def describe_misses(self, runs: Sequence[Mapping[str, object]]) -> str:
        """Name the runs that were seen and rejected, and why.

        ``list_command`` filters by ref, so every run offered here already
        belongs to this tag. A non-match therefore means a commit or trigger
        mismatch — never that the tag failed to trigger CI. Reporting what was
        rejected turns the phase's most misleading message into its most
        useful one: a delete-and-recreate leaves a run at the old commit, and
        its conclusion is usually the fact the operator most needs.
        """
        seen: list[str] = []
        for run in runs:
            if self.matches(run):
                continue
            sha = run.get("headSha")
            where = sha[:8] if isinstance(sha, str) else "an unknown commit"
            conclusion = run.get("conclusion") or "still running"
            seen.append(f"a {run.get('event')} run at {where} ({conclusion})")
        if not seen:
            return ""
        return f"{'; '.join(seen)}, but the local tag is at {self._commit[:8]}"

    def matches(self, run: Mapping[str, object]) -> bool:
        """True when ``run`` was triggered by this tag at this commit."""
        return (
            run.get("headBranch") == self._tag
            and run.get("event") == "push"
            and run.get("headSha") == self._commit
        )

    def run_id(self, run: Mapping[str, object]) -> int:
        """Return the run's numeric id, or raise when the payload lacks one."""
        candidate = run.get("databaseId")
        if not isinstance(candidate, int):
            msg = f"CI run for {self._tag} has no usable databaseId: {run!r}"
            raise ReleaseError(msg)
        return candidate

    def poll(
        self,
        list_runs: Callable[[], Sequence[Mapping[str, object]]],
        *,
        attempts: int,
        interval: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> int:
        """Return this tag's run id, waiting for the run to appear.

        Raises ``ReleaseError`` when no run matches within ``attempts`` polls.
        """
        for attempt in range(1, attempts + 1):
            # gh lists runs newest first, so the first match is the most
            # recent attempt for this tag.
            for run in list_runs():
                if self.matches(run):
                    return self.run_id(run)
            if attempt < attempts:
                sleep(interval)
        # The loop sleeps between polls, not after the last one, so the time
        # actually spent waiting is one interval short of attempts * interval.
        # Formatted with :g rather than int() so a sub-second interval is not
        # truncated to a figure smaller than the wait actually performed.
        waited = (attempts - 1) * interval
        msg = (
            f"no release.yml run found for {self._tag} at {self._commit[:8]} "
            f"after {waited:g}s — the tag push may not have triggered CI"
        )
        raise ReleaseError(msg)


# Conclusions that are a genuine verdict from CI, as opposed to gh being
# unable to tell us one. Anything outside this set means the watch exited
# non-zero for a reason of its own — a deleted run, an expired token, a
# dropped connection — and phase 6 has no verdict to report.
_CI_ADVERSE_CONCLUSIONS = frozenset(
    {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}
)
_CI_WATCH_TIMEOUT = 7200
# Listing runs is a fast metadata call, so it does not inherit the watch's
# two-hour budget — a listing that blocks that long has failed, and waiting
# on it burns the poll window that exists to find the run.
_CI_RUN_LIST_TIMEOUT = 60


def _watch_failure_message(gh: str, root: Path, run_id: int, returncode: int) -> str:
    """Explain a non-zero ``gh run watch`` without inventing a CI verdict.

    ``gh run watch`` exits non-zero when the run failed, but also when it
    cannot reach the run at all: a deleted run answers 404 and an expired
    token answers 401, both with the same exit code. Reporting either as
    "CI failed" sends the operator to a green run, from which the natural
    recovery is to resume past this phase — publishing to PyPI and
    propagating to the fleet with no CI verdict ever obtained.
    """
    # A verdict query that never answers leaves no conclusion, which is a
    # state this function already models — so None routes into the same
    # "could not confirm" path rather than escaping as TimeoutExpired. The
    # broken connection that made the watch exit non-zero is the likeliest
    # reason this call hangs too, so the failure-reporting path must survive
    # it; dying here would kill the diagnosis it was written to produce.
    verdict: subprocess.CompletedProcess[str] | None
    try:
        verdict = _run(
            [gh, "run", "view", str(run_id), "--json", "status,conclusion"],
            cwd=str(root),
            check=False,
            timeout=_CI_RUN_LIST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        verdict = None
    conclusion = ""
    if verdict is not None and verdict.returncode == 0:
        try:
            parsed = json.loads(verdict.stdout)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            raw = cast("dict[str, object]", parsed).get("conclusion")
            conclusion = raw if isinstance(raw, str) else ""
    if conclusion in _CI_ADVERSE_CONCLUSIONS:
        return f"CI run {run_id} concluded {conclusion} — fix before continuing"
    return (
        f"could not confirm CI run {run_id} passed: gh run watch exited "
        f"{returncode} and the run reports {conclusion or 'no conclusion'}. "
        f"Check the run itself — do not resume past this phase until it is green"
    )


def _phase6_ci_wait(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 6: Wait for CI."""
    console.print("\n[bold]Phase 6: Wait for CI[/bold]")

    tag = f"v{version}"

    if dry_run:
        _dry(" ".join(_TagRunSelector.list_command("gh", tag)))
        _dry(f"gh run watch <run-id matching {tag}> --exit-status")
        return

    gh = shutil.which("gh")
    if gh is None:
        _fail("gh CLI not found — install from https://cli.github.com")

    # Resolve the tag to a commit so the run's headSha can be checked against
    # it. Annotated tags need the ^{commit} peel; lightweight tags ignore it.
    peel = _run(
        ["git", "rev-parse", f"{tag}^{{commit}}"], cwd=str(info.root), check=False
    )
    if peel.returncode != 0:
        _fail(f"Cannot resolve {tag} to a commit — is the tag fetched locally?")
    commit = peel.stdout.strip()

    selector = _TagRunSelector(tag, commit)
    _info(f"Looking for the release.yml run for {tag} ({commit[:8]})...")

    list_cmd = _TagRunSelector.list_command(gh, tag)
    # A gh failure must not masquerade as "no run yet", and a lookup that never
    # happened must not be silently dropped from the account. Counting both
    # outcomes keeps the two facts separable: a blip after clean polls is not
    # "gh never worked", and 23 failures after one success is not "no run".
    gh_ok = 0
    gh_failed = 0
    last_gh_error = ""
    latest: Sequence[Mapping[str, object]] = ()

    def list_runs() -> Sequence[Mapping[str, object]]:
        nonlocal gh_ok, gh_failed, last_gh_error, latest
        try:
            result = _run(
                list_cmd,
                cwd=str(info.root),
                check=False,
                timeout=_CI_RUN_LIST_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            # A listing that hangs is a lookup that did not happen, not a
            # reason to end the release in a traceback. Polling already
            # tolerates a failed lookup, so route it there.
            gh_failed += 1
            last_gh_error = f"gh run list timed out after {_CI_RUN_LIST_TIMEOUT}s"
            return ()
        if result.returncode != 0:
            gh_failed += 1
            last_gh_error = result.stderr.strip() or "gh run list failed"
            return ()
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            # A zero exit with unparseable stdout is still a failed lookup.
            # Letting the decode error escape would bypass both _fail sites
            # and end the release in a traceback instead of a diagnosis.
            gh_failed += 1
            last_gh_error = f"gh run list returned unparseable JSON: {exc}"
            return ()
        # Valid JSON of the wrong shape is the same problem one step later: gh
        # reports errors as an object, and casting one to a run sequence would
        # surface as a TypeError from inside poll rather than a diagnosis.
        if not isinstance(parsed, list) or not all(
            isinstance(run, dict) for run in cast("list[object]", parsed)
        ):
            gh_failed += 1
            last_gh_error = (
                f"gh run list returned an unexpected JSON shape: "
                f"{result.stdout.strip()[:200]}"
            )
            return ()
        gh_ok += 1
        latest = cast("Sequence[Mapping[str, object]]", parsed)
        return latest

    try:
        run_id = selector.poll(
            list_runs,
            attempts=_CI_RUN_POLL_ATTEMPTS,
            interval=_CI_RUN_POLL_INTERVAL,
        )
    except ReleaseError as exc:
        if gh_ok == 0:
            _fail(f"gh run list never succeeded: {last_gh_error}")
        reasons = [str(exc)]
        # Failed lookups shrink the real search budget, so say how many there
        # were. Silence here reads as "we looked 24 times and found nothing".
        if gh_failed:
            reasons.append(
                f"{gh_failed} of {gh_ok + gh_failed} lookups failed ({last_gh_error})"
            )
        # Every run in the list is already this tag's, so a near-miss is the
        # most useful thing phase 6 knows — and the thing that contradicts
        # "the tag push may not have triggered CI".
        if misses := selector.describe_misses(latest):
            reasons.append(f"saw {misses}")
        _fail("; ".join(reasons))

    _info(f"Watching run {run_id}...")

    try:
        result = _run(
            [gh, "run", "watch", str(run_id), "--exit-status"],
            cwd=str(info.root),
            check=False,
            capture=False,
            timeout=_CI_WATCH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        # The pypi job gates on a manually-approved environment, so a release
        # left overnight can outlast the watch while the run is perfectly
        # healthy. Dying in a traceback here tells the operator nothing about
        # which of those two happened.
        _fail(
            f"stopped watching run {run_id} after "
            f"{_CI_WATCH_TIMEOUT // 3600}h — it may still be waiting for the "
            f"release environment approval. Check the run, then "
            f"--resume-from github-release once it is green"
        )
    if result.returncode != 0:
        _fail(_watch_failure_message(gh, info.root, run_id, result.returncode))
    _ok("CI passed")


def _phase7_github_release(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 7: Create GitHub release."""
    console.print(f"\n[bold]Phase 7: GitHub release v{version}[/bold]")

    tag = f"v{version}"

    if dry_run:
        _dry(f'gh release create {tag} --title "{tag}" --notes "..."')
        return

    gh = shutil.which("gh")
    if gh is None:
        _fail("gh CLI not found")

    # Check if CI already created the release (e.g., Go projects use
    # softprops/action-gh-release in their release workflow).
    existing = _run(
        [gh, "release", "view", tag],
        cwd=str(info.root),
        check=False,
    )
    if existing.returncode == 0:
        _ok(f"GitHub release {tag} already exists (created by CI)")
        return

    changelog = _read_changelog(info.root)
    notes = _extract_version_notes(changelog, version)

    result = _run(
        [gh, "release", "create", tag, "--title", tag, "--notes", notes],
        cwd=str(info.root),
        check=False,
    )
    if result.returncode != 0:
        _fail(f"Failed to create release: {result.stderr}")
    _ok(f"GitHub release {tag} created")


def _phase8_verify_pypi(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 8: Verify PyPI install."""
    if info.language != "python":
        return

    console.print("\n[bold]Phase 8: Verify PyPI install[/bold]")

    package_name = _get_package_name(info)

    if dry_run:
        _dry(f"uv tool install --force --refresh {package_name}=={version}")
        if info.cli_commands:
            _dry(f"{info.cli_commands[0]} doctor (if available)")
        _dry("uv tool install --force --editable .")
        return

    _info(f"Installing {package_name}=={version} from PyPI...")

    # Retry loop — PyPI propagation can take a minute
    for attempt in range(10):
        result = _run(
            [
                "uv",
                "tool",
                "install",
                "--force",
                "--refresh",
                f"{package_name}=={version}",
            ],
            cwd=str(info.root),
            check=False,
            capture=False,
        )
        if result.returncode == 0:
            break
        if attempt < 9:
            _info(f"Attempt {attempt + 1}/10 — waiting 30s for PyPI propagation...")
            time.sleep(30)
    else:
        _fail(
            f"Failed to install {package_name}=={version} from PyPI after 10 attempts"
        )

    _ok(f"Installed {package_name}=={version} from PyPI")

    # Run doctor if available
    if info.cli_commands:
        cli_name = info.cli_commands[0]
        cli_path = shutil.which(cli_name)
        if cli_path:
            doctor_result = _run([cli_path, "doctor"], check=False, capture=False)
            if doctor_result.returncode == 0:
                _ok(f"{cli_name} doctor passed")

    # Restore editable install
    _info("Restoring editable install...")
    _run(
        ["uv", "tool", "install", "--force", "--editable", "."],
        cwd=str(info.root),
        capture=False,
    )
    _ok("Editable install restored")


# ---------------------------------------------------------------------------
# Phase 9: Post-release (dev restore + README SHA bump via PR)
# ---------------------------------------------------------------------------


def _phase9_post_release(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 9: Dev plugin restore and README SHA bump via PR."""
    console.print(f"\n[bold]Phase 9: Post-release v{version}[/bold]")

    root = info.root
    branch = f"post-release/v{version}"
    has_changes = False

    if dry_run:
        if info.is_hybrid or info.is_plugin:
            _dry("bash scripts/restore-dev-plugin.sh")
        _dry("_bump_readme_install_sha(...)")
        _dry(f'git commit -m "chore: post-release v{version}"')
        _dry(f"_pr_merge(branch={branch})")
        return

    # Create post-release branch
    # Ensure we're on main first
    current = _run(["git", "branch", "--show-current"], cwd=str(root)).stdout.strip()
    if current != "main":
        _run(["git", "checkout", "main"], cwd=str(root))
        _run(["git", "pull", "--ff-only"], cwd=str(root))

    existing = _run(["git", "branch", "--list", branch], cwd=str(root)).stdout.strip()
    if existing:
        _run(["git", "checkout", branch], cwd=str(root))
        _info(f"Checked out existing branch {branch}")
    else:
        _run(["git", "checkout", "-b", branch], cwd=str(root))
        _ok(f"Created branch {branch}")

    # Dev restore (hybrid/plugin — idempotent: skip if already dev)
    if info.is_hybrid or info.is_plugin:
        plugin_json = root / ".claude-plugin" / "plugin.json"
        pj_data = json.loads(plugin_json.read_text(encoding="utf-8"))
        if not pj_data.get("name", "").endswith("-dev"):
            restore_script = root / "scripts" / "restore-dev-plugin.sh"
            _run(["bash", str(restore_script)], cwd=str(root), capture=False)
            # Re-stamp version — the restore script does
            # `git checkout HEAD~1 -- plugin.json` which reverts the
            # version field along with the name.
            pj_data = json.loads(plugin_json.read_text(encoding="utf-8"))
            if pj_data.get("version") != version:
                pj_data["version"] = version
                plugin_json.write_text(
                    json.dumps(pj_data, indent=2) + "\n",
                    encoding="utf-8",
                )
                _run(["git", "add", str(plugin_json)], cwd=str(root))
                _run(
                    [
                        "git",
                        "commit",
                        "--amend",
                        "--no-edit",
                        "--no-verify",
                    ],
                    cwd=str(root),
                )
            _ok("Dev plugin state restored")
            has_changes = True
        else:
            _ok("Plugin already in dev state (resume)")

    # README SHA bump. Stage README.md explicitly — `git add -A` would
    # sweep unrelated untracked files into the post-release commit.
    _bump_readme_install_sha(info, version, dry_run=False)
    status = _run(
        ["git", "status", "--porcelain", "--", "README.md"], cwd=str(root)
    ).stdout.strip()
    if status:
        _run(["git", "add", "--", "README.md"], cwd=str(root))
        msg = f"chore: update README install SHA to v{version}"
        _run(["git", "commit", "-m", msg], cwd=str(root))
        has_changes = True

    if not has_changes:
        # Check if branch has commits ahead of main (resume case)
        ahead = _run(
            ["git", "log", "main..HEAD", "--oneline"],
            cwd=str(root),
        ).stdout.strip()
        if ahead:
            has_changes = True
        else:
            _run(["git", "checkout", "main"], cwd=str(root))
            _run(["git", "branch", "-D", branch], cwd=str(root))
            _ok("No post-release changes needed")
            return

    _pr_merge(
        cwd=root,
        branch=branch,
        title=f"chore: post-release v{version}",
        dry_run=False,
    )
    _ok("Post-release PR merged")


# ---------------------------------------------------------------------------
# Sibling repo helpers
# ---------------------------------------------------------------------------


def _resolve_sibling(root: Path, name: str) -> Path | None:
    """Resolve a sibling repo directory.

    Checks root's parent for a directory named ``name`` with a ``.git``
    directory.  Returns ``None`` if not found.
    """
    parent = root.parent
    sibling = parent / name
    if sibling.is_dir() and (sibling / ".git").exists():
        return sibling
    return None


def _validate_sibling(path: Path, name: str) -> None:
    """Validate a sibling repo is ready for propagation."""
    branch = _run(["git", "branch", "--show-current"], cwd=str(path)).stdout.strip()
    if branch != "main":
        _fail(f"Sibling {name} is on branch '{branch}', expected main")

    # Only block on modified/staged files — untracked files and .beads/ are harmless
    status = _run(["git", "status", "--porcelain"], cwd=str(path)).stdout.strip()
    dirty_lines: list[str] = []
    for ln in status.splitlines():
        if ln.startswith("?? "):
            continue
        file_path = ln[3:] if len(ln) > 3 else ""
        if file_path == ".beads" or file_path.startswith(".beads/"):
            continue
        dirty_lines.append(ln)
    dirty = "\n".join(dirty_lines)
    if dirty:
        _fail(f"Sibling {name} has uncommitted changes:\n{dirty}")

    result = _run(
        ["git", "pull", "--ff-only", "origin", "main"],
        cwd=str(path),
        check=False,
    )
    if result.returncode != 0:
        _fail(f"Sibling {name}: git pull --ff-only failed:\n{result.stderr.strip()}")


def _sibling_pr_merge(
    path: Path,
    branch: str,
    files: list[str],
    message: str,
    name: str,
    *,
    dry_run: bool,
) -> bool:
    """Create branch, stage files, commit, and merge via PR in a sibling repo.

    Returns True if a PR was created and merged, False if no changes.
    """
    cwd = str(path)
    status = _run(
        ["git", "status", "--porcelain", "--", *files], cwd=cwd
    ).stdout.strip()
    if not status:
        return False

    if dry_run:
        _dry(f"{name}: {message}")
        return True

    # Create branch (handle resume: branch may already exist)
    # Use try/finally to ensure sibling returns to main on any failure —
    # ReleaseError from _fail(), CalledProcessError from _run(), etc.
    # (5b4/zay: stale propagation branches break subsequent releases).
    try:
        existing = _run(["git", "branch", "--list", branch], cwd=cwd).stdout.strip()
        if existing:
            _run(["git", "checkout", branch], cwd=cwd)
        else:
            _run(["git", "checkout", "-b", branch], cwd=cwd)
        for f in files:
            _run(["git", "add", f], cwd=cwd)
        # Skip commit if nothing staged (resume case: already committed)
        staged = _run(
            ["git", "status", "--porcelain", "--", *files], cwd=cwd
        ).stdout.strip()
        if staged:
            _run(["git", "commit", "-m", message], cwd=cwd)

        _pr_merge(
            cwd=path,
            branch=branch,
            title=message,
            dry_run=False,
        )
    finally:
        # _pr_merge checks out main on success; this is a no-op in that case.
        # On failure, this ensures we don't leave the sibling on a stale branch.
        branch_result = _run(["git", "branch", "--show-current"], cwd=cwd, check=False)
        current = (
            branch_result.stdout.strip() if branch_result.returncode == 0 else None
        )
        if current is None:
            _info(f"Could not read current branch for sibling {name} after operation")
        elif current != "main":
            checkout = _run(["git", "checkout", "main"], cwd=cwd, check=False)
            if checkout.returncode != 0:
                _info(
                    f"Warning: could not return sibling {name} to main: "
                    f"{checkout.stderr.strip()}"
                )

    return True


# ---------------------------------------------------------------------------
# Phase 10: Local propagation via PRs
# ---------------------------------------------------------------------------


def _propagate_install_all(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """10a. Update project's install.sh SHA in .github/install-all.sh.

    Also updates the org profile README with the install-all.sh commit SHA
    so that both changes land in a single .github PR.
    """
    if not (info.root / "install.sh").exists():
        return

    repo = _get_github_repo(info.root)
    if repo is None:
        return
    project_name = repo.split("/")[-1]

    sibling = _resolve_sibling(info.root, ".github")
    if sibling is None:
        _fail("Sibling .github not found — required for install-all.sh propagation")
        return  # unreachable, makes type checker happy

    install_all = sibling / "install-all.sh"
    if not install_all.exists():
        _fail("install-all.sh not found in .github — required for propagation")
        return  # unreachable

    tag = f"v{version}"
    install_sha = _get_install_sh_sha(info.root)

    content = install_all.read_text(encoding="utf-8")
    esc = re.escape(project_name)
    pattern = rf"(\$GH/{esc}/)[0-9a-fA-F]{{7,40}}(/install\.sh)"
    new_content, count = re.subn(pattern, rf"\g<1>{install_sha}\2", content)

    if count == 0:
        _info(f"install-all.sh: no entry for {project_name} — skipping")
        return

    if dry_run:
        if new_content != content:
            _dry(
                f"../.github/install-all.sh: {project_name} SHA → {install_sha} ({tag})"
            )
        _dry("../.github/profile/README.md: pin post-merge install-all.sh SHA")
        return

    _validate_sibling(sibling, ".github")

    if new_content == content:
        _ok(f"install-all.sh: {project_name} SHA already current")
    else:
        install_all.write_text(new_content, encoding="utf-8")
        branch = f"propagate/v{version}-{project_name}-github"
        if _sibling_pr_merge(
            sibling,
            branch,
            ["install-all.sh"],
            f"chore: update {project_name} install SHA to {tag}",
            ".github",
            dry_run=False,
        ):
            _ok(f"install-all.sh: {project_name} SHA → {install_sha} ({tag})")

    # The sibling is back on main with the merge pulled, so the profile can
    # now pin the commit that actually contains the propagated content.
    # Pinning before the merge would point one commit behind and serve the
    # previous installer on every release.
    _sync_profile_readme(sibling, version, project_name)


def _sync_profile_readme(sibling: Path, version: str, project_name: str) -> None:
    """Pin the org profile README to the install-all.sh commit on main.

    Must run after the install-all.sh PR merges: the profile references
    install-all.sh by commit SHA, and only the merged commit contains the
    just-propagated content. Also repairs a stale pin left by an earlier
    interrupted release even when install-all.sh itself needs no update.
    """
    readme = sibling / "profile" / "README.md"
    if not readme.exists():
        return

    github_sha = _run(
        ["git", "log", "-1", "--format=%h", "--", "install-all.sh"],
        cwd=str(sibling),
    ).stdout.strip()
    if not github_sha:
        _info(
            "profile/README.md: no commits touch install-all.sh yet — "
            "skipping SHA update"
        )
        return

    readme_content = readme.read_text(encoding="utf-8")
    new_readme, readme_count = re.subn(
        r"(punt-labs/\.github/)[0-9a-fA-F]{7,40}(/install-all\.sh)",
        rf"\g<1>{github_sha}\2",
        readme_content,
    )
    if readme_count == 0:
        _info(
            "profile/README.md: no install-all.sh SHA reference found — skipping update"
        )
        return
    if new_readme == readme_content:
        _ok(f"profile/README.md: install-all.sh SHA already current ({github_sha})")
        return

    readme.write_text(new_readme, encoding="utf-8")
    branch = f"propagate/v{version}-{project_name}-github-profile"
    if _sibling_pr_merge(
        sibling,
        branch,
        ["profile/README.md"],
        f"chore: pin profile install-all.sh SHA to {github_sha}",
        ".github",
        dry_run=False,
    ):
        _ok(f"profile/README.md: install-all.sh SHA → {github_sha}")


def _propagate_marketplace(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """10b. Update version and ref in claude-plugins marketplace.json."""
    if not info.is_plugin and not info.is_hybrid:
        return

    repo = _get_github_repo(info.root)
    if repo is None:
        return
    project_name = repo.split("/")[-1]
    tag = f"v{version}"

    sibling = _resolve_sibling(info.root, "claude-plugins")
    if sibling is None:
        _fail("Sibling claude-plugins not found — required for marketplace propagation")
        return

    marketplace_path = sibling / ".claude-plugin" / "marketplace.json"
    if not marketplace_path.exists():
        _fail("marketplace.json not found in claude-plugins")
        return

    if dry_run:
        _dry(
            f"../claude-plugins/marketplace.json: "
            f"{project_name} version={version}, ref={tag}"
        )
        return

    _validate_sibling(sibling, "claude-plugins")

    raw = json.loads(marketplace_path.read_text(encoding="utf-8"))
    data = cast("dict[str, object]", raw)
    plugins = cast("list[dict[str, object]]", data.get("plugins", []))

    found = False
    for plugin in plugins:
        src = cast("dict[str, str]", plugin.get("source", {}))
        repo_url = str(src.get("repo", ""))
        if repo_url.endswith("/" + project_name) or plugin.get("name") == project_name:
            plugin["version"] = version
            if "source" not in plugin:
                plugin["source"] = src
            src["ref"] = tag
            found = True
            break

    if not found:
        _fail(
            f"No marketplace entry for {project_name} in marketplace.json "
            "— required for plugin/hybrid releases"
        )

    marketplace_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    branch = f"propagate/v{version}-{project_name}-claude-plugins"
    if _sibling_pr_merge(
        sibling,
        branch,
        [".claude-plugin/marketplace.json"],
        f"chore: bump {project_name} to {tag} in marketplace",
        "claude-plugins",
        dry_run=dry_run,
    ):
        _ok(f"marketplace: {project_name} version={version}, ref={tag}")
    else:
        _ok(f"marketplace: {project_name} already current")


def _propagate_website(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """10d. Update version in public-website projects.json."""
    repo = _get_github_repo(info.root)
    if repo is None:
        return
    project_name = repo.split("/")[-1]

    sibling = _resolve_sibling(info.root, "public-website")
    if sibling is None:
        _info("Sibling public-website not found — skipping website update")
        return

    projects_json = sibling / "src" / "data" / "projects.json"
    if not projects_json.exists():
        _info("projects.json not found in public-website — skipping")
        return

    if dry_run:
        _dry(f"../public-website/projects.json: {project_name} version={version}")
        return

    _validate_sibling(sibling, "public-website")

    data = json.loads(projects_json.read_text(encoding="utf-8"))

    found = False
    for project in data:
        github_url = project.get("githubUrl") or ""
        if project.get("id") == project_name or github_url.endswith("/" + project_name):
            project["version"] = version
            # Update installCommand SHA if present
            install_cmd = project.get("installCommand") or ""
            if install_cmd and f"/{project_name}/" in install_cmd:
                install_sha = _get_install_sh_sha(info.root)
                project["installCommand"] = re.sub(
                    rf"({re.escape(project_name)}/)[0-9a-fA-F]{{7,40}}"
                    r"(/install\.sh)",
                    rf"\g<1>{install_sha}\2",
                    install_cmd,
                )
            found = True
            break

    if not found:
        _info(f"No website entry for {project_name} — skipping")
        return

    projects_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    branch = f"propagate/v{version}-{project_name}-public-website"
    if _sibling_pr_merge(
        sibling,
        branch,
        ["src/data/projects.json"],
        f"chore: bump {project_name} to v{version}",
        "public-website",
        dry_run=dry_run,
    ):
        _ok(f"website: {project_name} version={version}")
    else:
        _ok(f"website: {project_name} already current")


def _reset_propagation_siblings(
    info: ProjectInfo, *, fail_on_error: bool = True
) -> None:
    """Return all propagation sibling repos to the main branch.

    No-op for siblings already on main. Used by the interrupt handler and
    at the start of Phase 10 to recover from prior interrupted runs.

    ``fail_on_error=False`` should be used from the signal handler so that a
    checkout failure on one sibling does not abort cleanup of the remaining
    siblings.  The Phase 10 call site uses the default ``fail_on_error=True``
    so that release failures are loud.
    """
    for sib_name in PROPAGATION_SIBLINGS:
        sib_path = _resolve_sibling(info.root, sib_name)
        if sib_path is None:
            continue
        branch_result = _run(
            ["git", "branch", "--show-current"],
            cwd=str(sib_path),
            check=False,
        )
        if branch_result.returncode != 0:
            _info(
                f"Could not read branch for sibling {sib_name} "
                f"({branch_result.stderr.strip()}) — skipping reset"
            )
            continue
        branch = branch_result.stdout.strip()
        if branch and branch != "main":
            if not branch.startswith("propagate/v"):
                _info(
                    f"Sibling {sib_name} is on '{branch}' (not a propagation branch) — "
                    "skipping reset to avoid disrupting active work"
                )
                continue
            _info(f"Returning sibling {sib_name} to main (was on '{branch}')...")
            checkout = _run(["git", "checkout", "main"], cwd=str(sib_path), check=False)
            if checkout.returncode != 0:
                msg = (
                    f"Could not return sibling {sib_name} to main: "
                    f"{checkout.stderr.strip()}\n"
                    "Fix manually before retrying propagation."
                )
                if fail_on_error:
                    _fail(msg)
                else:
                    _info(f"Warning: {msg}")


def _collect_thread_results(
    futures: dict[Future[None], str],
) -> None:
    """Wait for all futures, collect errors, and fail if any occurred.

    If ``_interrupted`` is set after threads drain, raises
    ``KeyboardInterrupt`` so the caller's ``finally`` block handles
    cleanup (avoiding double-cleanup with ``run_release``).
    """
    errors: list[tuple[str, BaseException]] = []
    for f in as_completed(futures):
        name = futures[f]
        try:
            f.result()
        except ReleaseError as e:
            errors.append((name, RuntimeError(str(e))))
        except SystemExit as e:
            if isinstance(e.code, int):
                msg = f"{name} failed (exit code {e.code})"
            elif isinstance(e.code, str) and e.code.strip():
                msg = e.code
            else:
                msg = f"{name} failed"
            errors.append((name, RuntimeError(msg)))
        except BaseException as e:  # noqa: BLE001
            errors.append((name, e))
    if _interrupted.is_set():
        raise KeyboardInterrupt
    if errors:
        for name, err in errors:
            console.print(f"  [red]✗[/red] {name}: {err}")
        names = ", ".join(n for n, _ in errors)
        _fail(f"{len(errors)} task(s) failed: {names}")


def _phase10_propagate(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 10: Local cross-repo propagation via PRs."""
    console.print("\n[bold]Phase 10: Propagate[/bold]")

    # Auto-recover siblings left on propagation branches from a prior interrupted run.
    # No-op when all siblings are already on main.
    if not dry_run:
        _reset_propagation_siblings(info)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                _propagate_install_all, info, version, dry_run=dry_run
            ): ".github",
            pool.submit(
                _propagate_marketplace, info, version, dry_run=dry_run
            ): "claude-plugins",
            pool.submit(
                _propagate_website, info, version, dry_run=dry_run
            ): "public-website",
        }
        _collect_thread_results(futures)


# ---------------------------------------------------------------------------
# Phases 9+10: concurrent post-release + propagation
# ---------------------------------------------------------------------------


def _run_phases_9_10(
    info: ProjectInfo, version: str, *, dry_run: bool, start: int
) -> None:
    """Run phases 9 and 10 concurrently when both are in scope.

    If only P10 is in scope (``start == 10``), run it alone.
    """
    if start > 10:
        return

    if start <= 9:
        # Both phases in scope — run concurrently
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(_phase9_post_release, info, version, dry_run=dry_run): "P9",
                pool.submit(_phase10_propagate, info, version, dry_run=dry_run): "P10",
            }
            _collect_thread_results(futures)
    else:
        # start == 10: only P10
        _phase10_propagate(info, version, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Phase 11: Verify
# ---------------------------------------------------------------------------


def _phase11_verify(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 11: Run release verification checks."""
    console.print("\n[bold]Phase 11: Verify[/bold]")

    if dry_run:
        _dry("Would run release verification checks")
        return

    tag = f"v{version}"
    checks: list[tuple[str, bool, str]] = []

    # 1. Git tag exists
    result = _run(["git", "tag", "--list", tag], cwd=str(info.root), check=False)
    tag_exists = tag in result.stdout.strip()
    checks.append(("Git tag", tag_exists, tag if tag_exists else "not found"))

    # 2. Version consistency (read fresh from disk — info.pyproject is stale
    # after Phase 2 bumps the version)
    pyproject_path = info.root / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]*)"', content, re.MULTILINE)
        current = match.group(1) if match else "not found"
        checks.append(("pyproject.toml", current == version, f"version={current}"))

    pkg_dir = _find_package_dir(info)
    if pkg_dir is not None:
        init_py = pkg_dir / "__init__.py"
        if init_py.exists():
            content = init_py.read_text(encoding="utf-8")
            uses_metadata = (
                "importlib.metadata" in content or "importlib_metadata" in content
            )
            if not uses_metadata:
                match = re.search(r'__version__\s*=\s*"([^"]*)"', content)
                if match:
                    init_ver = match.group(1)
                    checks.append(
                        ("__init__.py", init_ver == version, f"__version__={init_ver}")
                    )

    plugin_json = info.root / ".claude-plugin" / "plugin.json"
    if plugin_json.exists():
        pj_data = json.loads(plugin_json.read_text(encoding="utf-8"))
        pj_ver = pj_data.get("version", "not found")
        checks.append(("plugin.json", pj_ver == version, f"version={pj_ver}"))

    install_sh = info.root / "install.sh"
    if install_sh.exists():
        content = install_sh.read_text(encoding="utf-8")
        match = re.search(r'VERSION="([^"]*)"', content)
        if match:
            install_ver = match.group(1)
            checks.append(
                ("install.sh", install_ver == version, f"VERSION={install_ver}")
            )

    # 3. Changelog stamped (must have date: ## [X.Y.Z] - YYYY-MM-DD)
    changelog = _read_changelog(info.root)
    stamped = bool(
        re.search(
            rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}",
            changelog,
            re.MULTILINE,
        )
    )
    checks.append(("CHANGELOG", stamped, "stamped" if stamped else "not stamped"))

    # 4. install-all.sh entry (curl SHA for CLI projects, plugin loop for pure plugins)
    repo = _get_github_repo(info.root)
    if repo and (install_sh.exists() or info.is_plugin):
        project_name = repo.split("/")[-1]
        sibling = _resolve_sibling(info.root, ".github")
        if not sibling:
            checks.append(("install-all.sh", False, "sibling .github not found"))
        else:
            install_all = sibling / "install-all.sh"
            if not install_all.exists():
                checks.append(("install-all.sh", False, "install-all.sh not found"))
            else:
                iac = install_all.read_text(encoding="utf-8")
                curl_match = re.search(
                    rf"\$GH/{re.escape(project_name)}/"
                    r"([0-9a-fA-F]{7,40})/install\.sh",
                    iac,
                )
                if curl_match:
                    sha = curl_match.group(1)
                    vr = _run(
                        ["git", "show", f"{sha}:install.sh"],
                        cwd=str(info.root),
                        check=False,
                    )
                    if vr.returncode != 0:
                        sha_ok = False
                    elif f'VERSION="{version}"' in vr.stdout:
                        # Python/hybrid: VERSION pin matches
                        sha_ok = True
                    else:
                        # Go/other: no VERSION pin — SHA resolves
                        sha_ok = 'VERSION="' not in vr.stdout
                    checks.append(("install-all.sh", sha_ok, f"SHA={sha}"))
                elif re.search(
                    rf"for plugin in [^;]*\b{re.escape(project_name)}\b",
                    iac,
                ):
                    # Pure-plugin loop entry (no SHA to verify)
                    checks.append(("install-all.sh", True, "in plugin loop"))
                else:
                    checks.append(("install-all.sh", False, "entry not found"))

    # 5. Marketplace
    if info.is_plugin or info.is_hybrid:
        repo = _get_github_repo(info.root)
        if repo:
            project_name = repo.split("/")[-1]
            sibling = _resolve_sibling(info.root, "claude-plugins")
            if not sibling:
                checks.append(
                    ("marketplace", False, "sibling claude-plugins not found")
                )
            else:
                mp = sibling / ".claude-plugin" / "marketplace.json"
                if not mp.exists():
                    checks.append(("marketplace", False, "marketplace.json not found"))
                else:
                    data = cast(
                        "dict[str, object]",
                        json.loads(mp.read_text(encoding="utf-8")),
                    )
                    plugins = cast("list[dict[str, object]]", data.get("plugins", []))
                    mp_found = False
                    for p in plugins:
                        src = cast("dict[str, str]", p.get("source", {}))
                        if (
                            str(src.get("repo", "")).endswith("/" + project_name)
                            or p.get("name") == project_name
                        ):
                            mp_ver = str(p.get("version", ""))
                            mp_ref = str(src.get("ref", ""))
                            ok = mp_ver == version and mp_ref == tag
                            checks.append(
                                (
                                    "marketplace",
                                    ok,
                                    f"version={mp_ver}, ref={mp_ref}",
                                )
                            )
                            mp_found = True
                            break
                    if not mp_found:
                        checks.append(
                            ("marketplace", False, f"no entry for {project_name}")
                        )

    # 6. Profile SHA (install-all.sh URL resolves)
    repo = _get_github_repo(info.root)
    if repo and install_sh.exists():
        sibling = _resolve_sibling(info.root, ".github")
        if not sibling:
            checks.append(("profile SHA", False, "sibling .github not found"))
        else:
            readme = sibling / "profile" / "README.md"
            if not readme.exists():
                checks.append(("profile SHA", False, "profile/README.md not found"))
            else:
                content = readme.read_text(encoding="utf-8")
                sha_match = re.search(
                    r"punt-labs/\.github/([0-9a-fA-F]{7,40})/install-all\.sh",
                    content,
                )
                if not sha_match:
                    checks.append(
                        (
                            "profile SHA",
                            False,
                            "no .github install-all.sh URL in profile",
                        )
                    )
                else:
                    profile_sha = sha_match.group(1)
                    # The pinned SHA must resolve AND its content must carry
                    # this project's current install SHA — a resolvable pin
                    # that predates the propagation merge is stale and serves
                    # the previous installer.
                    show_result = _run(
                        ["git", "show", f"{profile_sha}:install-all.sh"],
                        cwd=str(sibling),
                        check=False,
                    )
                    if show_result.returncode != 0:
                        checks.append(
                            (
                                "profile SHA",
                                False,
                                f"SHA={profile_sha} (does not resolve)",
                            )
                        )
                    else:
                        project_name = repo.split("/")[-1]
                        install_sha = _get_install_sh_sha(info.root)
                        current_entry = re.search(
                            rf"\$GH/{re.escape(project_name)}/"
                            rf"{re.escape(install_sha)}[0-9a-fA-F]*/install\.sh",
                            show_result.stdout,
                        )
                        checks.append(
                            (
                                "profile SHA",
                                current_entry is not None,
                                f"SHA={profile_sha}"
                                + (
                                    ""
                                    if current_entry
                                    else (
                                        f" (stale — lacks {project_name}@{install_sha})"
                                    )
                                ),
                            )
                        )

    # 7. Website (optional — sibling may not exist)
    if repo:
        project_name = repo.split("/")[-1]
        sibling = _resolve_sibling(info.root, "public-website")
        if sibling:
            pj = sibling / "src" / "data" / "projects.json"
            if pj.exists():
                data = json.loads(pj.read_text(encoding="utf-8"))
                web_found = False
                for entry in data:
                    github_url = entry.get("githubUrl") or ""
                    if entry.get("id") == project_name or github_url.endswith(
                        "/" + project_name
                    ):
                        web_ver = entry.get("version")
                        checks.append(
                            (
                                "website",
                                web_ver == version,
                                f"version={web_ver}",
                            )
                        )
                        web_found = True
                        break
                if not web_found:
                    checks.append(("website", False, f"no entry for {project_name}"))

    # 8. PyPI
    if info.language == "python":
        package_name = _get_package_name(info)
        result = _run(
            ["uv", "run", "pip", "index", "versions", package_name],
            check=False,
        )
        pypi_ok = (
            bool(re.search(rf"\b{re.escape(version)}\b", result.stdout))
            if result.returncode == 0
            else False
        )
        checks.append(("PyPI", pypi_ok, f"{package_name}=={version}"))

    # Print results
    all_pass = True
    for name, passed, detail in checks:
        if passed:
            _ok(f"{name}: {detail}")
        else:
            console.print(f"  [red]✗[/red] {name}: {detail}")
            all_pass = False

    if not all_pass:
        _fail("Some verification checks failed — see above")


def _phase_summary(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Print release summary."""
    tag = f"v{version}"
    package = _get_package_name(info) if info.language == "python" else info.root.name
    if info.is_hybrid:
        ptype = "hybrid"
    elif info.is_plugin:
        ptype = "plugin"
    else:
        ptype = "CLI-only"

    dr = "(dry run) " if dry_run else ""
    console.print(f"\n[bold green]Release {tag} {dr}Complete[/bold green]\n")
    console.print(f"  Package:        {package}")
    console.print(f"  Version:        {version}")
    console.print(f"  Type:           {ptype}")
    console.print(f"  Tag:            {tag}")
    console.print()
    if not dry_run and (info.is_plugin or info.is_hybrid):
        console.print("  Restart Claude Code to pick up marketplace changes.")
    console.print()


# ---------------------------------------------------------------------------
# Phase name → number mapping for --resume-from
# ---------------------------------------------------------------------------

PHASE_NAMES: dict[str, int] = {
    "preflight": 1,
    "bump": 2,
    "build": 3,
    "release-pr": 4,
    "tag": 5,
    "ci": 6,
    "github-release": 7,
    "pypi": 8,
    "post-release": 9,
    "propagate": 10,
    "verify": 11,
    # Aliases for muscle-memory from old phase names
    "release": 4,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_release(
    path: str,
    *,
    version: str | None = None,
    dry_run: bool = False,
    resume_from: str | None = None,
) -> None:
    """Execute the release workflow.

    Phases 1–8 handle the originating repo. Phase 9 does post-release
    cleanup (dev restore, README SHA). Phase 10 propagates to sibling
    repos via PRs. Phase 11 runs final verification checks.
    """
    root = Path(path).resolve()
    try:
        if not root.is_dir():
            _fail(f"{root} is not a directory")

        info = detect(root)

        if info.language is None and not info.is_plugin:
            _fail("Cannot detect project type — is this a Punt Labs project?")

        _interrupted.clear()

        if not dry_run:

            def _cleanup_handler(signum: int, frame: object) -> None:  # noqa: ARG001
                _info("\nInterrupted — finishing active operations before cleanup...")
                _interrupted.set()
                raise KeyboardInterrupt()

            signal.signal(signal.SIGINT, _cleanup_handler)
            signal.signal(signal.SIGTERM, _cleanup_handler)

        # Determine start phase
        start = 1
        if resume_from:
            if resume_from not in PHASE_NAMES:
                valid = ", ".join(sorted(PHASE_NAMES.keys()))
                _fail(f"Unknown phase '{resume_from}'. Valid: {valid}")
            start = PHASE_NAMES[resume_from]

        mode = "[bold yellow]DRY RUN[/bold yellow] — " if dry_run else ""
        resume = f" (resuming from phase {start})" if start > 1 else ""
        console.print(f"\n{mode}[bold]punt release[/bold] — {root.name}{resume}")

        # Run preflight before version detection (need clean tree for accurate reads)
        if start <= 1:
            _phase1_preflight(info, dry_run=dry_run)

        # Determine version
        if version is None:
            if start == 1:
                # Fresh release — detect from changelog
                if info.pyproject is None and info.language != "go":
                    _fail(
                        "Version required for plugin-only projects (no pyproject.toml)"
                    )
                current = _get_project_version(info)
                changelog = _read_changelog(root)
                version = _suggest_version(changelog, current)
                console.print(
                    f"\n  [bold]Suggested version:[/bold]"
                    f" {version} (current: {current})"
                )
                if not dry_run:
                    _info(f"Using suggested version {version}")
            else:
                # Resuming — read current version
                version = _get_project_version(info)
                source = "git tags" if info.language == "go" else "pyproject.toml"
                _info(f"Detected version {version} from {source}")

        try:
            if start <= 2:
                _phase2_version_bump(info, version, dry_run=dry_run)
            if start <= 3:
                _phase3_build(info, dry_run=dry_run)
            if start <= 4:
                _phase4_release_pr(info, version, dry_run=dry_run)
            if start <= 5:
                _phase5_tag(info, version, dry_run=dry_run)
            if start <= 6:
                _phase6_ci_wait(info, version, dry_run=dry_run)
            if start <= 7:
                _phase7_github_release(info, version, dry_run=dry_run)
            if start <= 8:
                _phase8_verify_pypi(info, version, dry_run=dry_run)
            # P9 and P10 are independent — run concurrently when both are in scope
            _run_phases_9_10(info, version, dry_run=dry_run, start=start)
            if start <= 11:
                _phase11_verify(info, version, dry_run=dry_run)

            _phase_summary(info, version, dry_run=dry_run)
        finally:
            if _interrupted.is_set():
                _info("Cleaning up after interrupt...")
                _reset_propagation_siblings(info, fail_on_error=False)
                sys.exit(1)
    except ReleaseError:
        raise SystemExit(1) from None
