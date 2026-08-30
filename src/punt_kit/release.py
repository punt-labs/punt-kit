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
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast, final

from rich.console import Console

from punt_kit.detect import ProjectInfo, detect
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
from punt_kit.phases.shared.ci_run import CiRunWatch, TagRunSelector
from punt_kit.phases.shared.errors import ReleaseError as ReleaseError
from punt_kit.phases.shared.gh import GithubRepo, PrThreadResolver, RequiredChecksWaiter
from punt_kit.phases.shared.git import GitWorkspace
from punt_kit.phases.shared.pipeline import ReleasePipeline, ThreadedStep
from punt_kit.phases.shared.plugin_swap import PluginSwap
from punt_kit.phases.shared.pr_merge import PrMerger
from punt_kit.phases.shared.project_info import ReleaseProject
from punt_kit.phases.shared.readme_sha import ReadmeShaPin
from punt_kit.phases.shared.reporter import reporter
from punt_kit.phases.shared.siblings import SiblingRegistry, SiblingRepo, SkipRecorder

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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


def _get_package_name(info: ProjectInfo) -> str:
    """Extract package name from pyproject.toml."""
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


def _find_package_dir(info: ProjectInfo) -> Path | None:
    """Find the Python package directory (src layout)."""
    return ReleaseProject(info, ops=_ops).package_dir()


def _get_github_repo(root: Path) -> str | None:
    """Extract GitHub owner/repo from git remote."""
    return GithubRepo(root, ops=_ops).resolve()


def _read_changelog(root: Path) -> str:
    """Read CHANGELOG.md content."""
    return Changelog(root, ops=_ops).text()


def _extract_version_notes(changelog: str, version: str) -> str:
    """Extract release notes for a specific version from changelog."""
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

    fetch = _run(
        ["git", "fetch", "origin"],
        cwd=str(info.root),
        check=False,
        timeout=_GIT_NETWORK_TIMEOUT,
    )
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
            result = _run(
                gate,
                cwd=str(info.root),
                check=False,
                capture=False,
                timeout=_QUALITY_GATE_TIMEOUT,
            )
            if result.returncode != 0:
                _fail(f"Quality gate failed: {' '.join(gate)}")
        _ok("All quality gates passed")
    elif not dry_run and info.language == "go":
        _info("Running quality gates...")
        makefile = info.root / "Makefile"
        if makefile.exists():
            result = _run(
                ["make", "check"],
                cwd=str(info.root),
                check=False,
                capture=False,
                timeout=_QUALITY_GATE_TIMEOUT,
            )
            if result.returncode != 0:
                _fail("Quality gate failed: make check")
        else:
            for gate in [["go", "vet", "./..."], ["go", "test", "-race", "./..."]]:
                result = _run(
                    gate,
                    cwd=str(info.root),
                    check=False,
                    capture=False,
                    timeout=_QUALITY_GATE_TIMEOUT,
                )
                if result.returncode != 0:
                    _fail(f"Quality gate failed: {' '.join(gate)}")
        _ok("All quality gates passed")
    elif dry_run:
        _dry("Would run quality gates")


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


def _rewrite_template_pins(
    info: ProjectInfo, version: str, *, dry_run: bool
) -> list[Path]:
    """Rewrite self-referential ``uvx --from <own-pkg>==X.Y.Z`` template pins."""
    return ReleaseProject(info, ops=_ops).rewrite_template_pins(
        version, dry_run=dry_run
    )


def _phase2_version_bump(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 2: Bump version on release branch."""
    console.print(f"\n[bold]Phase 2: Version bump → {version}[/bold]")

    root = info.root
    branch = f"release/v{version}"

    # Create release branch
    if dry_run:
        _dry(f"git checkout -b {branch}")
    else:
        if GitWorkspace(root, ops=_ops).checkout_or_create(branch):
            _info(f"Checked out existing branch {branch}")
        else:
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

    # Bump plugin.json version. None for a non-plugin project — absence is the
    # contract, and 2d below stages only the files that exist.
    plugin_json = info.plugin_manifest if info.is_plugin else None
    if plugin_json is not None:
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

    # 2d. Rewrite self-referential template pins
    template_pins = _rewrite_template_pins(info, version, dry_run=dry_run)

    # 2e. Refresh lock file and commit
    if dry_run:
        _dry("uv lock (refresh lock file)")
        _dry(f'git commit -m "chore: release v{version}"')
    else:
        lock_file = root / "uv.lock"
        if lock_file.exists():
            _run(["uv", "lock"], cwd=str(root), timeout=_UV_TIMEOUT)
            _ok("uv.lock refreshed")
        # Stage only the files this phase edits — `git add -A` would sweep
        # unrelated untracked files into the release commit.
        release_files = [
            pyproject_path,
            changelog_path,
            install_sh,
            lock_file,
        ]
        if plugin_json is not None:
            release_files.append(plugin_json)
        if pkg_dir is not None:
            release_files.append(pkg_dir / "__init__.py")
        release_files.extend(template_pins)
        to_stage = [str(p.relative_to(root)) for p in release_files if p.exists()]
        if GitWorkspace(root, ops=_ops).commit_if_staged(
            to_stage, f"chore: release v{version}"
        ):
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

    _run(["uv", "build"], cwd=str(info.root), capture=False, timeout=_UV_TIMEOUT)

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

    # 4a. Plugin swap (hybrid/plugin — idempotent: skip if already
    # committed at HEAD). The old shape read plugin.json from the
    # working tree, which is only correct while --no-verify guarantees
    # the commit cannot fail. With hooks live, a failed commit leaves
    # plugin.json prod-shaped on disk without a corresponding commit;
    # a working-tree read then reports the swap done and _pr_merge
    # pushes a release branch whose HEAD still carries the -dev name —
    # the release tag lands on it, silently. Consult HEAD, and reset
    # the swap paths so the script's fresh-run precondition (dev name
    # on disk) holds even on retry.
    if info.is_hybrid or info.is_plugin:
        release_script = root / "scripts" / "release-plugin.sh"
        if dry_run:
            _dry("bash scripts/release-plugin.sh")
        else:
            plugin_swap = PluginSwap(info, ops=_ops)
            head_data = plugin_swap.head_state()
            head_name = str(head_data.get("name", ""))
            if head_name.endswith("-dev"):
                plugin_swap.reset_to_head()
                _run(
                    ["bash", str(release_script)],
                    cwd=str(root),
                    capture=False,
                    # The script commits, and that commit now runs the repo
                    # hooks — the bd pre-commit hook alone allows itself 300s
                    # against a networked Dolt server. Budgeting the script at
                    # the 60s metadata default would abort a release for hook
                    # latency that is not a fault.
                    timeout=_GIT_HOOK_TIMEOUT,
                )
                _ok("Plugin swapped to prod")
            else:
                _ok("Plugin already swapped at HEAD (resume)")

    # 4b. Push branch, create PR, wait for CI, squash-merge
    _pr_merge(
        cwd=root,
        branch=branch,
        title=f"chore: release v{version}",
        dry_run=dry_run,
    )

    # 4c. Pin README's install-URL SHA now that the squash-merge has landed
    # on main — see _land_readme_sha_pin for why this must happen here and
    # not during phase 2's version bump on the (about to be deleted) branch.
    _land_readme_sha_pin(info, version, dry_run=dry_run)


def _phase5_tag(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 5: Tag main HEAD and push tag."""
    console.print(f"\n[bold]Phase 5: Tag v{version}[/bold]")

    root = info.root
    tag = f"v{version}"

    if dry_run:
        _dry(f"git tag {tag}")
        _dry(f"git push origin {tag}")
        return

    workspace = GitWorkspace(root, ops=_ops)
    workspace.ensure_on_main()

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

    # Push tag (not blocked by branch protection — targets refs/tags/*).
    # pre-push still fires bd hooks, so use the hook budget.
    workspace.push(tag)
    _ok(f"Pushed tag {tag}")


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
    console.print("\n[bold]Phase 6: Wait for CI[/bold]")

    if "release.yml" not in info.workflow_files:
        if info.is_plugin and not info.is_hybrid:
            _ok("No release.yml workflow — pure plugin, nothing to wait for")
            return
        _fail(
            "Expected .github/workflows/release.yml for this project but none "
            "was found — this is a misconfiguration, not a plugin-only skip "
            f"(workflows present: {info.workflow_files or 'none'})"
        )

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
        _fail(
            CiRunWatch(ops=_ops).failure_message(
                gh, info.root, run_id, result.returncode
            )
        )
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
            timeout=_UV_TIMEOUT,
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
        timeout=_UV_TIMEOUT,
    )
    _ok("Editable install restored")


# ---------------------------------------------------------------------------
# Phase 9: Post-release (dev restore + README SHA bump via PR)
# ---------------------------------------------------------------------------


def _phase9_post_release(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Phase 9: Dev plugin restore via PR."""
    console.print(f"\n[bold]Phase 9: Post-release v{version}[/bold]")

    root = info.root
    branch = f"post-release/v{version}"
    has_changes = False

    if dry_run:
        if info.is_hybrid or info.is_plugin:
            _dry("bash scripts/restore-dev-plugin.sh")
        _dry('git commit -m "chore: restore dev plugin state [skip ci]"')
        _dry(f'_pr_merge(branch={branch}, title="chore: post-release v{version}")')
        return

    # Create post-release branch — ensure we're on main first
    workspace = GitWorkspace(root, ops=_ops)
    workspace.ensure_on_main()

    if workspace.checkout_or_create(branch):
        _info(f"Checked out existing branch {branch}")
    else:
        _ok(f"Created branch {branch}")

    # Dev restore (hybrid/plugin — idempotent: skip only when the
    # restore commit is already at HEAD). Mirror of the phase 4 check.
    #
    # The restore script stages the reverted files but does not commit
    # (see scripts/restore-dev-plugin.sh CONTRACT). That lets this phase
    # re-stamp the version — the historical dev commit's plugin.json has
    # the old version — and land the restore + re-stamp as one commit
    # with hooks running. The previous shape committed inside the script
    # and then --amend --no-verify'd here to fix up the version; the
    # org bans --no-verify outright and the amend existed only because
    # the script committed too early.
    #
    # Consulting the working tree here has the same failure mode phase
    # 4 does: if the commit fails on a pre-commit hook, the restore is
    # already staged and the tree already shows the dev name — a disk
    # read would report "already in dev state (resume)" and fall
    # through to the README-SHA commit, which would then sweep the
    # staged plugin.json into itself under the wrong commit message.
    # Consult HEAD, and require BOTH the dev name AND the released
    # version at HEAD before treating the restore as done — a partial
    # historical commit with a mismatched version must still re-run.
    if info.is_hybrid or info.is_plugin:
        plugin_swap = PluginSwap(info, ops=_ops)
        head_data = plugin_swap.head_state()
        head_name = str(head_data.get("name", ""))
        head_version = str(head_data.get("version", ""))
        restore_done = head_name.endswith("-dev") and head_version == version
        if not restore_done:
            plugin_swap.reset_to_head()
            restore_script = root / "scripts" / "restore-dev-plugin.sh"
            _run(
                ["bash", str(restore_script)],
                cwd=str(root),
                capture=False,
                # git checkout inside the script fires the post-checkout hook;
                # same reasoning as the phase 4 swap above.
                timeout=_GIT_HOOK_TIMEOUT,
            )
            # The restore checks plugin.json out of the last dev commit,
            # which reverts the version field along with the name. Put
            # the just-released version back before committing so main
            # advertises the current release, not the previous one.
            plugin_json = info.plugin_manifest
            pj_data = json.loads(plugin_json.read_text(encoding="utf-8"))
            if pj_data.get("version") != version:
                pj_data["version"] = version
                plugin_json.write_text(
                    json.dumps(pj_data, indent=2) + "\n",
                    encoding="utf-8",
                )
                _run(["git", "add", str(plugin_json)], cwd=str(root))
            # The CI-skip marker spares a push-CI run on main once the
            # post-release PR squash-merges: this commit only restores dev
            # plugin state and re-stamps a version. It does NOT affect
            # release.yml, which triggers on tag push and whose tag was
            # placed back in phase 5 — the marker matters on phase 4's
            # release-plugin.sh commit, which the tag does land on, and
            # that is where the historical regression happened.
            _run(
                [
                    "git",
                    "commit",
                    "-m",
                    "chore: restore dev plugin state [skip ci]",
                ],
                cwd=str(root),
                timeout=_GIT_HOOK_TIMEOUT,
            )
            _ok("Dev plugin state restored")
            has_changes = True
        else:
            _ok("Dev restore already at HEAD (resume)")

    if not has_changes:
        # Check if branch has commits ahead of main (resume case)
        ahead = _run(
            ["git", "log", "main..HEAD", "--oneline"],
            cwd=str(root),
        ).stdout.strip()
        if ahead:
            has_changes = True
        else:
            _run(["git", "checkout", "main"], cwd=str(root), timeout=_GIT_HOOK_TIMEOUT)
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
    """Resolve a sibling repo directory."""
    repo = SiblingRepo.resolve(root, name, ops=_ops)
    return repo.path if repo is not None else None


def _validate_sibling(path: Path, name: str) -> None:
    """Validate a sibling repo is ready for propagation."""
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


def _phase_summary(info: ProjectInfo, version: str, *, dry_run: bool) -> None:
    """Print release summary."""
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
            if start <= 2:
                current_phase_num = 2
                _phase2_version_bump(info, version, dry_run=dry_run)
            if start <= 3:
                current_phase_num = 3
                _phase3_build(info, dry_run=dry_run)
            if start <= 4:
                current_phase_num = 4
                _phase4_release_pr(info, version, dry_run=dry_run)
            if start <= 5:
                current_phase_num = 5
                _phase5_tag(info, version, dry_run=dry_run)
            if start <= 6:
                current_phase_num = 6
                _phase6_ci_wait(info, version, dry_run=dry_run)
            if start <= 7:
                current_phase_num = 7
                _phase7_github_release(info, version, dry_run=dry_run)
            if start <= 8:
                current_phase_num = 8
                _phase8_verify_pypi(info, version, dry_run=dry_run)
            # P9 and P10. When both are in scope they run concurrently and
            # any in-thread TimeoutExpired crosses the boundary as a
            # ReleaseError via _collect_thread_results, so crediting the
            # pair's entry point (9) is honest for the concurrent path.
            # When start == 10, P9 is already done and _run_phases_9_10
            # runs P10 alone on the main thread — a TimeoutExpired there
            # is a propagate hang, and telling the operator
            # `--resume-from post-release` would re-run phase 9. Credit
            # the phase that is actually executing.
            current_phase_num = 9 if start <= 9 else 10
            _run_phases_9_10(info, version, dry_run=dry_run, start=start)
            if start <= 11:
                current_phase_num = 11
                _phase11_verify(info, version, dry_run=dry_run)

            _phase_summary(info, version, dry_run=dry_run)
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
