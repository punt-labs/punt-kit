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


def _get_install_sh_sha(root: Path) -> str:
    """Get the short SHA of the commit that last modified install.sh."""
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


def _verify_marketplace_pin_chain(
    cp_sibling: Path | None,
    claude_plugins_sha: str,
    project_name: str,
    version: str,
    tag: str,
) -> tuple[bool, str]:
    """Check a pinned claude-plugins commit's marketplace.json for this project.

    Returns ``(passed, detail)``. Used only for marketplace-only plugins,
    where the profile-SHA check has no direct install URL to verify against
    — the pin chain (profile -> install-all.sh's claude-plugins SHA -> that
    commit's marketplace.json) is the equivalent invariant.
    """
    if cp_sibling is None:
        return False, "claude-plugins sibling not found"
    show = _run(
        ["git", "show", f"{claude_plugins_sha}:.claude-plugin/marketplace.json"],
        cwd=str(cp_sibling),
        check=False,
    )
    if show.returncode != 0:
        return False, f"claude-plugins@{claude_plugins_sha} does not resolve"
    data = cast("dict[str, object]", json.loads(show.stdout))
    plugins = cast("list[dict[str, object]]", data.get("plugins", []))
    for p in plugins:
        src = cast("dict[str, str]", p.get("source", {}))
        # Match by either the source.repo suffix (canonical) or the plugin
        # name field. Check 5 (marketplace) accepts both, and the historical
        # pin check must not be stricter — otherwise a genuinely-current
        # release fails the pin chain for entries whose top-level "name"
        # matches but whose "source.repo" points at a fork or a rename.
        if (
            str(src.get("repo", "")).endswith("/" + project_name)
            or str(p.get("name", "")) == project_name
        ):
            ok = str(p.get("version", "")) == version and str(src.get("ref", "")) == tag
            return (
                ok,
                f"claude-plugins@{claude_plugins_sha} version={p.get('version')}, "
                f"ref={src.get('ref')}",
            )
    return False, f"claude-plugins@{claude_plugins_sha} has no entry for {project_name}"


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
    """10a. Update project's install.sh SHA in .github/install-all.sh.

    Also updates the org profile README with the install-all.sh commit SHA
    so that both changes land in a single .github PR.

    When the ``.github`` sibling is absent (does not resolve as a git repo
    root), propagation is skipped with a loud warning and a clean return
    rather than a failure: this phase runs after the release has already
    published, and the workspace meta-repo layout legitimately has no
    resolvable ``.github`` sibling. A ``.github`` sibling that *is* present
    but is missing ``install-all.sh`` remains a hard failure — that is a
    genuine misconfiguration, not the expected meta-repo case.
    """
    if not (info.root / "install.sh").exists():
        return

    repo = _get_github_repo(info.root)
    if repo is None:
        return
    project_name = repo.split("/")[-1]

    sibling = _resolve_sibling(info.root, ".github")
    if sibling is None:
        # Phase 10a runs *after* the tag, PyPI publish, and GitHub release
        # (phases 5-7) have irreversibly landed, so aborting here would report
        # failure on an already-published release. The absent-sibling case is
        # also legitimate: in the workspace meta-repo layout the ``.github``
        # path is occupied by the meta-repo's own (non-git-root) folder and can
        # never resolve as a propagation sibling — Phase 1d already tolerates
        # this by skipping siblings that resolve to None. Mirror that here:
        # skip loudly and tell the operator exactly what to do by hand. Recorded
        # through the shared template so the end-of-run summary recaps it even if
        # this line scrolls past among the concurrent Phase 10 output — and so it
        # deduplicates against the identical Phase 11 verify-skip into one line.
        _skips.record(_GITHUB_ABSENT_SKIP.format(name=project_name, ver=version))
        return

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

    if info.is_plugin:
        pj_data = json.loads(info.plugin_manifest.read_text(encoding="utf-8"))
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
            # An absent .github sibling is not a verification failure: Phase 10a
            # already skipped propagation for the same reason (the workspace
            # meta-repo layout has no resolvable .github sibling), and this phase
            # runs after the release has published. Recording the skip surfaces
            # it without flipping all_pass — a False here would exit non-zero on
            # an already-published release and read identically to a real defect.
            _skips.record(_GITHUB_ABSENT_SKIP.format(name=project_name, ver=version))
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
    if repo and (install_sh.exists() or info.is_plugin):
        sibling = _resolve_sibling(info.root, ".github")
        if not sibling:
            # Absent sibling — same tolerated case as the install-all.sh check
            # above. The shared message deduplicates in _skips, so the two
            # checks collapse to one recap line rather than double-reporting.
            _skips.record(
                _GITHUB_ABSENT_SKIP.format(name=repo.split("/")[-1], ver=version)
            )
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
                    elif install_sh.exists():
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
                    else:
                        # Marketplace-only plugin: no install.sh, so there is
                        # no direct curl URL to verify. The equivalent
                        # invariant is the marketplace-pin chain — the
                        # profile-pinned install-all.sh names a claude-plugins
                        # SHA, and that commit's marketplace.json must carry
                        # this project's current version/ref.
                        project_name = repo.split("/")[-1]
                        mp_pin = re.search(
                            r"\$GH/claude-plugins/([0-9a-fA-F]{7,40})/install\.sh",
                            show_result.stdout,
                        )
                        if mp_pin is None:
                            checks.append(
                                (
                                    "profile SHA",
                                    False,
                                    f"SHA={profile_sha} "
                                    "(no claude-plugins pin in install-all.sh)",
                                )
                            )
                        else:
                            cp_sibling = _resolve_sibling(info.root, "claude-plugins")
                            ok, detail = _verify_marketplace_pin_chain(
                                cp_sibling,
                                mp_pin.group(1),
                                project_name,
                                version,
                                tag,
                            )
                            checks.append(
                                ("profile SHA", ok, f"SHA={profile_sha} ({detail})")
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

    # 8. PyPI — confirm the exact published version resolves from the INDEX.
    # `uv pip install --dry-run` uses uv's own resolver, so it needs no `pip`
    # binary (uv-managed project venvs do not ship one — `uv run pip` fails with
    # "Failed to spawn: pip"). This must assert index presence, not mere local
    # resolvability: by this phase the wheel was built locally (Phase 3) and
    # installed from PyPI (Phase 8), so `<pkg>==<version>` is almost certainly in
    # uv's cache and the environment. `--no-cache` forbids satisfying the resolve
    # from the download cache, and `--reinstall` forbids satisfying it from the
    # already-installed environment — together they force a fresh index query, so
    # a green result can only mean the version is actually published. `--no-deps`
    # isolates the signal to this one package==version, so a transiently
    # unresolvable transitive dependency cannot mask a successful publish.
    # `--dry-run` installs nothing. Resolvable → exit 0; absent → non-zero
    # ("unsatisfiable"). Run in the project dir so uv resolves against the
    # project's environment.
    if info.language == "python":
        package_name = _get_package_name(info)
        result = _run(
            [
                "uv",
                "pip",
                "install",
                "--dry-run",
                "--no-deps",
                "--no-cache",
                "--reinstall",
                f"{package_name}=={version}",
            ],
            cwd=str(info.root),
            check=False,
            timeout=_UV_TIMEOUT,
        )
        pypi_ok = result.returncode == 0
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
