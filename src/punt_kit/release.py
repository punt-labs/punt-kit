"""punt release — deterministic release workflow for Punt Labs projects."""

from __future__ import annotations

import signal
import subprocess
import sys
import threading

# Unused directly in this module since the polling loops moved to
# phases/shared/gh.py and ci_run.py, but several tests monkeypatch
# "punt_kit.release.time.sleep" — that dotted path resolves through this
# module's own `time` attribute, so removing the import breaks the patch
# with an ImportError before the test body even runs.
import time  # noqa: F401  # pyright: ignore[reportUnusedImport]
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast, final

from rich.console import Console

from punt_kit.detect import ProjectInfo, detect
from punt_kit.phases.phase01_preflight import Phase1Preflight
from punt_kit.phases.phase02_version_bump import Phase2VersionBump
from punt_kit.phases.phase03_build import Phase3Build
from punt_kit.phases.phase04_release_pr import Phase4ReleasePr
from punt_kit.phases.phase05_tag import Phase5Tag
from punt_kit.phases.phase06_ci_wait import Phase6CiWait
from punt_kit.phases.phase07_github_release import Phase7GithubRelease
from punt_kit.phases.phase08_verify_pypi import Phase8VerifyPypi
from punt_kit.phases.phase09_post_release import Phase9PostRelease
from punt_kit.phases.phase10_propagate import (
    InstallAllPropagator,
    MarketplacePropagator,
    Phase10Propagate,
    WebsitePropagator,
)
from punt_kit.phases.phase11_verify import Phase11Verify
from punt_kit.phases.shared import changelog as changelog_mod
from punt_kit.phases.shared import project_info as project_info_mod
from punt_kit.phases.shared import siblings as siblings_mod
from punt_kit.phases.shared import timeouts
from punt_kit.phases.shared.changelog import Changelog
from punt_kit.phases.shared.ci_run import TagRunSelector
from punt_kit.phases.shared.errors import ReleaseError as ReleaseError
from punt_kit.phases.shared.gh import GithubRepo, PrThreadResolver, RequiredChecksWaiter
from punt_kit.phases.shared.pipeline import PhaseStep, ReleasePipeline, ThreadedStep
from punt_kit.phases.shared.pr_merge import PrMerger
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.readme_sha import ReadmeShaPin
from punt_kit.phases.shared.reporter import reporter
from punt_kit.phases.shared.siblings import SiblingRegistry, SiblingRepo, SkipRecorder

if TYPE_CHECKING:
    from collections.abc import Sequence

console = Console()

# Set by the signal handler so threads can drain before cleanup runs.
_interrupted = threading.Event()

# Aliases — see phases/shared/siblings.py for the source of truth.
PROPAGATION_SIBLINGS = siblings_mod.PROPAGATION_SIBLINGS
_GITHUB_ABSENT_SKIP = siblings_mod.GITHUB_ABSENT_SKIP
_PROPAGATION_OWNED_PATHS = siblings_mod.PROPAGATION_OWNED_PATHS

# ---------------------------------------------------------------------------
# Timeout budgets — see phases/shared/timeouts.py for the source of truth and
# the rationale behind each budget. Aliased here (not just imported) because
# _CI_RUN_POLL_ATTEMPTS/_CI_RUN_POLL_INTERVAL are monkeypatched directly on
# this module by tests/test_release.py; every other name is a plain re-export.
_DEFAULT_RUN_TIMEOUT = timeouts.DEFAULT_RUN
_UV_TIMEOUT = timeouts.UV
_GIT_NETWORK_TIMEOUT = timeouts.GIT_NETWORK
_GIT_HOOK_TIMEOUT = timeouts.GIT_HOOK
_QUALITY_GATE_TIMEOUT = timeouts.QUALITY_GATE
_CI_RUN_POLL_INTERVAL = timeouts.CI_RUN_POLL_INTERVAL
_CI_RUN_POLL_ATTEMPTS = timeouts.CI_RUN_POLL_ATTEMPTS
_CI_ADVERSE_CONCLUSIONS = timeouts.CI_ADVERSE_CONCLUSIONS
_CI_WATCH_TIMEOUT = timeouts.CI_WATCH
_CI_RUN_LIST_TIMEOUT = timeouts.CI_RUN_LIST

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    timeout: int = _DEFAULT_RUN_TIMEOUT,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with standard options.

    ``timeout`` defaults to a short metadata budget. Call sites that
    legitimately need longer — package installs, quality gates, network git,
    ``gh run watch`` — must pass one of the named budgets defined above.
    """
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
    )


# Static aliases — release.py's own module-level names for Reporter's bound
# methods. No test monkeypatches these names, so a plain assignment is safe:
# nothing downstream expects to observe a later reassignment of the target.
_fail = reporter.fail
_ok = reporter.ok
_info = reporter.info
_dry = reporter.dry
_warn = reporter.warn


@final
class _ReleaseOpsAdapter:
    """Implements ``ReleaseOps`` by forwarding into this module's own globals.

    Every ``phases/*`` class receives this adapter at construction and calls
    ``self._ops.run(...)`` instead of a bare ``_run``. Because these methods
    are *defined in* ``release.py``, the bare names ``_run``, ``_ok``, etc.
    inside them resolve against ``release.py``'s ``__dict__`` at call time —
    exactly like every other function already in this file. That is what
    lets ``monkeypatch.setattr(release_mod, "_run", fake_run)`` reach a
    ``RequiredChecksWaiter`` or a ``Phase6CiWait`` that was constructed with
    this adapter, with zero changes to ``tests/test_release.py``.

    Legitimate PY-OO-7 exception: a stateless Adapter whose entire purpose is
    to forward to module globals for this testability reason, not a data
    holder that should have methods added to it.
    """

    __slots__ = ()

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)

    def ok(self, msg: str) -> None:
        _ok(msg)

    def info(self, msg: str) -> None:
        _info(msg)

    def dry(self, msg: str) -> None:
        _dry(msg)

    def warn(self, msg: str) -> None:
        _warn(msg)

    def fail(self, msg: str) -> NoReturn:
        _fail(msg)


# Shared instance handed to every phase and shared-collaborator constructor.
_ops = _ReleaseOpsAdapter()


# Module-scoped so any phase can record a skip and the end-of-run summary can
# recap them. Cleared at the start of every ``run_release`` so one release's
# skips never leak into the next in a long-lived process.
_skips = SkipRecorder(ops=_ops)


def _get_install_sh_sha(  # pyright: ignore[reportUnusedFunction]
    root: Path,
) -> str:
    """Get the short SHA of the commit that last modified install.sh.

    No caller remains in this module — every former call site now
    constructs ReleaseProject directly. Kept importable for public API
    preservation.
    """
    return ReleaseProject(ProjectInfo(root), ops=_ops).install_sh_sha()


def _get_project_version(info: ProjectInfo) -> str:
    """Extract current version from pyproject.toml, plugin.json, or git tags (Go)."""
    if info.language == "go":
        return _get_latest_tag_version(info.root)
    return ReleaseProject(info, ops=_ops).version()


def _get_latest_tag_version(root: Path) -> str:
    """Get the latest semantic version from git tags."""
    return ReleaseProject(ProjectInfo(root), ops=_ops).latest_tag_version()


def _get_package_name(  # pyright: ignore[reportUnusedFunction]
    info: ProjectInfo,
) -> str:
    """Extract package name from pyproject.toml.

    No caller remains in this module — every former call site now
    constructs ReleaseProject directly. Kept importable for public API
    preservation.
    """
    return ReleaseProject(info, ops=_ops).package_name()


def _self_package_name(  # pyright: ignore[reportUnusedFunction]
    info: ProjectInfo,
) -> str | None:
    """Return the project's own PyPI package name for self-referential pins.

    No caller remains in this module — _rewrite_template_pins now delegates
    fully to ReleaseProject.rewrite_template_pins, which calls the class's
    own self_package_name() rather than this bare name. Kept importable for
    public API preservation (punt_kit.release.<name> stays reachable).
    """
    return ReleaseProject(info, ops=_ops).self_package_name()


def _find_package_dir(  # pyright: ignore[reportUnusedFunction]
    info: ProjectInfo,
) -> Path | None:
    """Find the Python package directory (src layout).

    No caller remains in this module — every former call site now
    constructs ReleaseProject directly. Kept importable for public API
    preservation.
    """
    return ReleaseProject(info, ops=_ops).package_dir()


def _get_github_repo(root: Path) -> str | None:
    """Extract GitHub owner/repo from git remote."""
    return GithubRepo(root, ops=_ops).resolve()


def _read_changelog(root: Path) -> str:
    """Read CHANGELOG.md content."""
    return Changelog(root, ops=_ops).text()


def _extract_version_notes(  # pyright: ignore[reportUnusedFunction]
    changelog: str, version: str
) -> str:
    """Extract release notes for a specific version from changelog.

    No caller remains in this module — Phase7GithubRelease calls
    changelog_mod.extract_version_notes directly. Kept importable for
    public API preservation (this name is also directly tested).
    """
    return changelog_mod.extract_version_notes(changelog, version)


def _resolve_pr_threads(gh: str, cwd: str, pr_number: int) -> None:
    """Resolve all unresolved review threads on a PR."""
    PrThreadResolver(GithubRepo(Path(cwd), ops=_ops), ops=_ops).resolve(
        gh, cwd, pr_number
    )


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------


def _phase1_preflight(info: ProjectInfo, *, dry_run: bool) -> None:
    """Phase 1: Pre-flight checks."""
    Phase1Preflight(info, dry_run=dry_run, ops=_ops).run()


def _suggest_version(changelog: str, current: str) -> str:
    """Suggest a version bump based on changelog content."""
    return changelog_mod.suggest_next_version(changelog, current)


def _branch_protection_exists(  # pyright: ignore[reportUnusedFunction]
    gh: str, cwd: str, owner: str, repo_name: str
) -> bool:
    """True if ``main`` has a branch protection rule; False only on a confirmed
    "branch not protected" response.

    No caller remains in this module — RequiredChecksWaiter.wait calls
    self._repo.has_branch_protection directly. Kept importable for public
    API preservation.
    """
    return GithubRepo(Path(cwd), ops=_ops).has_branch_protection(gh, owner, repo_name)


def _wait_for_required_checks(gh: str, cwd: str, pr_number: int) -> None:
    """Poll required CI checks until all pass or any fail."""
    RequiredChecksWaiter(GithubRepo(Path(cwd), ops=_ops), ops=_ops).wait(
        gh, cwd, pr_number, resolve_repo=_get_github_repo
    )


def _select_existing_pr(  # pyright: ignore[reportUnusedFunction]
    prs: list[dict[str, object]], local_head: str
) -> tuple[int | None, bool]:
    """Pick which same-named PR, if any, represents the current release.

    No caller remains in this module — PrMerger.merge calls
    PrMerger._select_existing directly. Kept importable for public API
    preservation.
    """
    return PrMerger._select_existing(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
        prs, local_head
    )


def _pr_is_merged(  # pyright: ignore[reportUnusedFunction]
    gh: str, cwd: str, pr_number: int
) -> bool:
    """Check whether a PR has reached the MERGED state.

    No caller remains in this module — PrMerger.merge calls
    PrMerger._is_merged directly. Kept importable for public API
    preservation.
    """
    return PrMerger(ops=_ops)._is_merged(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
        gh, cwd, pr_number
    )


def _pr_merge(
    *,
    cwd: Path,
    branch: str,
    title: str,
    body: str = "",
    dry_run: bool = False,
) -> str:
    """Push branch, create PR, wait for CI, squash-merge. Return merge SHA."""
    return PrMerger(ops=_ops).merge(
        cwd=cwd,
        branch=branch,
        title=title,
        body=body,
        dry_run=dry_run,
        wait_for_checks=_wait_for_required_checks,
        resolve_threads=_resolve_pr_threads,
    )


# Static alias — pure string transform, no test monkeypatches this name.
_normalize_package_name = project_info_mod.normalize_package_name


def _rewrite_template_pins(  # pyright: ignore[reportUnusedFunction]
    info: ProjectInfo, version: str, *, dry_run: bool
) -> list[Path]:
    """Rewrite self-referential ``uvx --from <own-pkg>==X.Y.Z`` template pins.

    No caller remains in this module — Phase2VersionBump calls
    ReleaseProject.rewrite_template_pins directly. Kept importable for
    public API preservation (this name is also directly tested).
    """
    return ReleaseProject(info, ops=_ops).rewrite_template_pins(
        version, dry_run=dry_run
    )


def _phase2_version_bump(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 2: Bump version on release branch."""
    Phase2VersionBump(info, version, dry_run=dry_run, ops=_ops).run()


def _phase3_build(info: ProjectInfo, *, dry_run: bool) -> None:
    """Phase 3: Build validation."""
    Phase3Build(info, dry_run=dry_run, ops=_ops).run()


def _phase4_release_pr(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 4: Plugin swap, push branch, create PR, merge."""
    Phase4ReleasePr(info, version, dry_run=dry_run, ops=_ops).run(
        merge=_pr_merge, land_readme_sha_pin=_land_readme_sha_pin
    )


def _phase5_tag(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 5: Tag main HEAD and push tag."""
    Phase5Tag(info, version, dry_run=dry_run, ops=_ops).run()


def _bump_readme_install_sha(  # pyright: ignore[reportUnusedFunction]
    info: ProjectInfo, version: str, *, dry_run: bool
) -> None:
    """Update SHA-pinned install.sh URLs in README to the install.sh commit.

    No caller remains in this module — ReadmeShaPin.land calls self.bump
    directly. Kept importable for public API preservation.
    """
    ReadmeShaPin(info, ops=_ops).bump(
        version, dry_run=dry_run, resolve_repo=_get_github_repo
    )


def _land_readme_sha_pin(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Pin README's install-URL SHA via its own PR, right after the squash-merge."""
    ReadmeShaPin(info, ops=_ops).land(
        version, dry_run=dry_run, merge=_pr_merge, resolve_repo=_get_github_repo
    )


# Static alias — re-export of the relocated class. No test's monkeypatch
# reassigns this name; every use is a direct call/import.
_TagRunSelector = TagRunSelector


def _phase6_ci_wait(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 6: Wait for CI."""
    Phase6CiWait(info, version, dry_run=dry_run, ops=_ops).run(
        poll_attempts=_CI_RUN_POLL_ATTEMPTS, poll_interval=_CI_RUN_POLL_INTERVAL
    )


def _phase7_github_release(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 7: Create GitHub release."""
    Phase7GithubRelease(info, version, dry_run=dry_run, ops=_ops).run()


def _phase8_verify_pypi(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 8: Verify PyPI install."""
    Phase8VerifyPypi(info, version, dry_run=dry_run, ops=_ops).run()


# ---------------------------------------------------------------------------
# Phase 9: Post-release (dev restore + README SHA bump via PR)
# ---------------------------------------------------------------------------


def _phase9_post_release(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 9: Dev plugin restore via PR."""
    Phase9PostRelease(info, version, dry_run=dry_run, ops=_ops).run(merge=_pr_merge)


# ---------------------------------------------------------------------------
# Sibling repo helpers
# ---------------------------------------------------------------------------


def _resolve_sibling(root: Path, name: str) -> Path | None:
    """Resolve a sibling repo directory."""
    repo = SiblingRepo.resolve(root, name, ops=_ops)
    return repo.path if repo is not None else None


def _validate_sibling(  # pyright: ignore[reportUnusedFunction]
    path: Path, name: str
) -> None:
    """Validate a sibling repo is ready for propagation.

    No caller remains in this module — every former call site now
    constructs SiblingRepo directly. Kept importable for public API
    preservation (this name is also directly tested).
    """
    SiblingRepo(path, name, ops=_ops).validate()


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
    return PrMerger(ops=_ops).merge_in_sibling(
        path, branch, files, message, name, dry_run=dry_run, merge=_pr_merge
    )


# ---------------------------------------------------------------------------
# Phase 10: Local propagation via PRs
# ---------------------------------------------------------------------------


def _propagate_install_all(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """10a. Update project's install.sh SHA in .github/install-all.sh."""
    InstallAllPropagator(info, ops=_ops, skips=_skips).run(
        version, dry_run=dry_run, merge_sibling=_sibling_pr_merge
    )


def _propagate_marketplace(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """10b. Update version and ref in claude-plugins marketplace.json."""
    MarketplacePropagator(info, ops=_ops).run(
        version, dry_run=dry_run, merge_sibling=_sibling_pr_merge
    )


def _propagate_website(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """10d. Update version in public-website projects.json."""
    WebsitePropagator(info, ops=_ops).run(
        version, dry_run=dry_run, merge_sibling=_sibling_pr_merge
    )


def _reset_sibling_owned_dirt(  # pyright: ignore[reportUnusedFunction]
    sib_path: Path, sib_name: str, *, fail_on_error: bool
) -> None:
    """Restore propagation-owned files if a sibling on main is dirty in them.

    No caller remains in this module — SiblingRegistry.reset_all constructs
    a SiblingRepo and calls its own reset_owned_dirt() directly. Kept
    importable for public API preservation.
    """
    SiblingRepo(sib_path, sib_name, ops=_ops).reset_owned_dirt(
        fail_on_error=fail_on_error
    )


def _reset_propagation_siblings(
    info: ProjectInfo, *, fail_on_error: bool = True
) -> None:
    """Return all propagation sibling repos to the main branch.

    Passes the bare ``_resolve_sibling`` name (not ``SiblingRepo.resolve``
    directly) as the resolver — tests monkeypatch ``_resolve_sibling`` on
    this module and expect ``_reset_propagation_siblings`` to observe it.
    """
    SiblingRegistry(ops=_ops).reset_all(
        info.root, resolve=_resolve_sibling, fail_on_error=fail_on_error
    )


def _collect_thread_results(
    futures: dict[Future[None], str],
) -> None:
    """Wait for all futures, collect errors, and fail if any occurred."""
    ThreadedStep(ops=_ops).collect(futures, interrupted=_interrupted)


def _phase10_propagate(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 10: Local cross-repo propagation via PRs."""
    Phase10Propagate(info, version, dry_run=dry_run, ops=_ops).run(
        reset_propagation_siblings=_reset_propagation_siblings,
        propagate_install_all=_propagate_install_all,
        propagate_marketplace=_propagate_marketplace,
        propagate_website=_propagate_website,
        interrupted=_interrupted,
    )


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
    Phase11Verify(info, version, dry_run=dry_run, ops=_ops, skips=_skips).run()


def _phase_summary(  # pyright: ignore[reportUnusedFunction]
    info: ProjectInfo, version: str, *, dry_run: bool
) -> None:
    """Print release summary.

    No caller remains in this module — run_release calls
    ReleasePipeline.summarize directly on the pipeline it already built.
    Kept importable for public API preservation (this name is also
    directly tested).
    """
    ReleasePipeline((), ops=_ops).summarize(
        info,
        version,
        dry_run=dry_run,
        project=ReleaseProject(info, ops=_ops),
        skips=_skips,
    )


# ---------------------------------------------------------------------------
# Phase name → number mapping for --resume-from
# ---------------------------------------------------------------------------

# Canonical phase order. Index + 1 is the phase number; the name at that index
# is the string the operator passes to --resume-from. Kept as the single source
# of truth so PHASE_NAMES and _phase_name cannot drift out of sync.
_PHASE_ORDER: tuple[str, ...] = (
    "preflight",
    "bump",
    "build",
    "release-pr",
    "tag",
    "ci",
    "github-release",
    "pypi",
    "post-release",
    "propagate",
    "verify",
)

PHASE_NAMES: dict[str, int] = {name: i + 1 for i, name in enumerate(_PHASE_ORDER)}
# Aliases for muscle-memory from old phase names.
PHASE_NAMES["release"] = PHASE_NAMES["release-pr"]


def _phase_name(number: int) -> str:
    """Return the --resume-from name for a phase number, or 'unknown'.

    Only in-range phase numbers map to a name; 0 (nothing running yet) and
    anything outside 1..len(_PHASE_ORDER) fall through to 'unknown' so the
    diagnosis path never fabricates a phase that would not round-trip
    through --resume-from.
    """
    if 1 <= number <= len(_PHASE_ORDER):
        return _PHASE_ORDER[number - 1]
    return "unknown"


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
    # Updated inside every `if start <= N:` guard below so the TimeoutExpired
    # handler can name the phase that was running and hand the operator the
    # exact --resume-from string, not a placeholder they have to figure out.
    current_phase_num = 0
    try:
        if not root.is_dir():
            _fail(f"{root} is not a directory")

        info = detect(root)

        if info.language is None and not info.is_plugin:
            _fail("Cannot detect project type — is this a Punt Labs project?")

        _interrupted.clear()
        # Drop any skips retained from a prior release in this process so this
        # run's summary recaps only its own outstanding manual actions.
        _skips.clear()

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
            current_phase_num = 1
            _phase1_preflight(info, dry_run=dry_run)

        # Determine version
        if version is None:
            if start == 1:
                # Fresh release — detect from changelog
                if (
                    info.pyproject is None
                    and info.language != "go"
                    and not info.is_plugin
                ):
                    _fail(
                        "Version required — project has no pyproject.toml, "
                        "is not a Go project, and is not a plugin"
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

            def _step2() -> None:
                nonlocal current_phase_num
                current_phase_num = 2
                _phase2_version_bump(info, version, dry_run=dry_run)

            def _step3() -> None:
                nonlocal current_phase_num
                current_phase_num = 3
                _phase3_build(info, dry_run=dry_run)

            def _step4() -> None:
                nonlocal current_phase_num
                current_phase_num = 4
                _phase4_release_pr(info, version, dry_run=dry_run)

            def _step5() -> None:
                nonlocal current_phase_num
                current_phase_num = 5
                _phase5_tag(info, version, dry_run=dry_run)

            def _step6() -> None:
                nonlocal current_phase_num
                current_phase_num = 6
                _phase6_ci_wait(info, version, dry_run=dry_run)

            def _step7() -> None:
                nonlocal current_phase_num
                current_phase_num = 7
                _phase7_github_release(info, version, dry_run=dry_run)

            def _step8() -> None:
                nonlocal current_phase_num
                current_phase_num = 8
                _phase8_verify_pypi(info, version, dry_run=dry_run)

            def _step9_10() -> None:
                # P9 and P10. When both are in scope they run concurrently
                # and any in-thread TimeoutExpired crosses the boundary as
                # a ReleaseError via _collect_thread_results, so crediting
                # the pair's entry point (9) is honest for the concurrent
                # path. When start == 10, P9 is already done and
                # _run_phases_9_10 runs P10 alone on the main thread — a
                # TimeoutExpired there is a propagate hang, and telling the
                # operator `--resume-from post-release` would re-run phase
                # 9. Credit the phase that is actually executing.
                nonlocal current_phase_num
                current_phase_num = 9 if start <= 9 else 10
                _run_phases_9_10(info, version, dry_run=dry_run, start=start)

            def _step11() -> None:
                nonlocal current_phase_num
                current_phase_num = 11
                _phase11_verify(info, version, dry_run=dry_run)

            # The combined P9+P10 step is numbered 10 (not 9) so the
            # generic `step.number < start` skip only excludes it once
            # resuming past phase 10 — it must still run (P10 alone) when
            # start == 10.
            pipeline = ReleasePipeline(
                (
                    PhaseStep(2, "bump", _step2),
                    PhaseStep(3, "build", _step3),
                    PhaseStep(4, "release-pr", _step4),
                    PhaseStep(5, "tag", _step5),
                    PhaseStep(6, "ci", _step6),
                    PhaseStep(7, "github-release", _step7),
                    PhaseStep(8, "pypi", _step8),
                    PhaseStep(10, "post-release", _step9_10),
                    PhaseStep(11, "verify", _step11),
                ),
                ops=_ops,
            )
            pipeline.run(start=start)

            pipeline.summarize(
                info,
                version,
                dry_run=dry_run,
                project=ReleaseProject(info, ops=_ops),
                skips=_skips,
            )
        finally:
            if _interrupted.is_set():
                _info("Cleaning up after interrupt...")
                _reset_propagation_siblings(info, fail_on_error=False)
                sys.exit(1)
    except ReleaseError:
        raise SystemExit(1) from None
    except subprocess.TimeoutExpired as exc:
        # A call site that forgets to opt into a longer budget — or a genuine
        # subprocess wedge — must not exit the release in a traceback. Convert
        # it to the same diagnosed failure path ReleaseError takes and hand
        # the operator the exact --resume-from string; a placeholder here is
        # advice that is not actionable, and resuming from the wrong phase
        # skips a gate.
        raw_cmd = cast("object", exc.cmd)
        if isinstance(raw_cmd, list | tuple):
            parts = cast("Sequence[object]", raw_cmd)
            cmd_str = " ".join(str(part) for part in parts)
        else:
            cmd_str = str(raw_cmd)
        phase_label = _phase_name(current_phase_num)
        if phase_label == "unknown":
            resume_hint = (
                "Investigate the command; a phase could not be identified, "
                "so pick the earliest --resume-from that covers the failure."
            )
            location = "before the first phase started"
        else:
            resume_hint = (
                f"Investigate the command, then resume with "
                f"--resume-from {phase_label}."
            )
            location = f"in phase {current_phase_num} ({phase_label})"
        console.print(
            f"[red]Error:[/red] release aborted {location} — "
            f"`{cmd_str}` did not return within {exc.timeout}s. "
            f"{resume_hint}"
        )
        raise SystemExit(1) from None
