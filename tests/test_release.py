"""Tests for release command."""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path as _Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from punt_kit import release
from punt_kit.detect import detect
from punt_kit.release import (
    _DEFAULT_RUN_TIMEOUT,  # pyright: ignore[reportPrivateUsage]
    _GIT_HOOK_TIMEOUT,  # pyright: ignore[reportPrivateUsage]
    _QUALITY_GATE_TIMEOUT,  # pyright: ignore[reportPrivateUsage]
    PHASE_NAMES,
    ReleaseError,
    _bump_readme_install_sha,  # pyright: ignore[reportPrivateUsage]
    _extract_version_notes,  # pyright: ignore[reportPrivateUsage]
    _get_latest_tag_version,  # pyright: ignore[reportPrivateUsage]
    _get_project_version,  # pyright: ignore[reportPrivateUsage]
    _phase1_preflight,  # pyright: ignore[reportPrivateUsage]
    _phase2_version_bump,  # pyright: ignore[reportPrivateUsage]
    _phase6_ci_wait,  # pyright: ignore[reportPrivateUsage]
    _phase9_post_release,  # pyright: ignore[reportPrivateUsage]
    _phase10_propagate,  # pyright: ignore[reportPrivateUsage]
    _phase11_verify,  # pyright: ignore[reportPrivateUsage]
    _phase_name,  # pyright: ignore[reportPrivateUsage]
    _phase_summary,  # pyright: ignore[reportPrivateUsage]
    _pr_merge,  # pyright: ignore[reportPrivateUsage]
    _propagate_install_all,  # pyright: ignore[reportPrivateUsage]
    _propagate_marketplace,  # pyright: ignore[reportPrivateUsage]
    _propagate_website,  # pyright: ignore[reportPrivateUsage]
    _reset_propagation_siblings,  # pyright: ignore[reportPrivateUsage]
    _resolve_sibling,  # pyright: ignore[reportPrivateUsage]
    _rewrite_template_pins,  # pyright: ignore[reportPrivateUsage]
    _run,  # pyright: ignore[reportPrivateUsage]
    _run_phases_9_10,  # pyright: ignore[reportPrivateUsage]
    _select_existing_pr,  # pyright: ignore[reportPrivateUsage]
    _suggest_version,  # pyright: ignore[reportPrivateUsage]
    _TagRunSelector,  # pyright: ignore[reportPrivateUsage]
    _validate_sibling,  # pyright: ignore[reportPrivateUsage]
    _wait_for_required_checks,  # pyright: ignore[reportPrivateUsage]
    run_release,
)
from tests.harness.fault_ops import CompletedProcessSpec, FaultInjectingOps, FaultRule

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from punt_kit.detect import ProjectInfo


@pytest.fixture(autouse=True)
def isolate_skip_recorder() -> Iterator[None]:
    """Clear the module-scoped skip recorder around every test.

    ``release._skips`` persists for the process; a test that records a skip
    would otherwise leak the notice into the next test's summary recap.
    """
    release._skips.clear()  # pyright: ignore[reportPrivateUsage]
    yield
    release._skips.clear()  # pyright: ignore[reportPrivateUsage]


@pytest.fixture(autouse=True)
def isolate_interrupted_event() -> Iterator[None]:
    """Clear the module-scoped interrupt event around every test.

    ``release._interrupted`` persists for the process; a test that sets it
    to exercise the interrupt path (directly, or via a mocked phase raising
    ``KeyboardInterrupt``) would otherwise leak it into every later test —
    including unrelated ``_wait_for_required_checks`` tests, which now check
    this same event on every poll iteration (pkit-d7mz/pkit-plxh) and would
    fail immediately with "Interrupted" on a leaked, already-set event.
    """
    release._interrupted.clear()  # pyright: ignore[reportPrivateUsage]
    yield
    release._interrupted.clear()  # pyright: ignore[reportPrivateUsage]


def _git(args: list[str], cwd: str) -> None:
    """Run a git command with standard options."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(args: list[str], cwd: str) -> str:
    """Run a git command and return its stripped stdout."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_git_repo_with_bare_remote(path: Path, remote: Path) -> None:
    """Initialize a git repo whose ``origin`` is a separate bare remote.

    ``_init_git_repo`` points ``origin`` at the same directory as the
    working copy — a local ref is then visible via ``git ls-remote``
    without any push actually happening, which makes it unsuitable for
    testing push-failure/resume behavior. A genuinely separate remote is
    required so ``ls-remote`` reflects only what was actually pushed.
    """
    d = str(path)
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    _git(["init", "-b", "main"], cwd=d)
    _git(["config", "user.email", "test@test.com"], cwd=d)
    _git(["config", "user.name", "Test"], cwd=d)
    (path / ".gitkeep").write_text("")
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "init"], cwd=d)
    _git(["remote", "add", "origin", str(remote)], cwd=d)
    _git(["push", "-u", "origin", "main"], cwd=d)


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit and fake remote."""
    d = str(path)
    _git(["init", "-b", "main"], cwd=d)
    _git(["config", "user.email", "test@test.com"], cwd=d)
    _git(["config", "user.name", "Test"], cwd=d)
    # Create initial commit so HEAD exists
    (path / ".gitkeep").write_text("")
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "init"], cwd=d)
    # Set origin to self so fetch/diff work
    _git(["remote", "add", "origin", d], cwd=d)
    _git(["fetch", "origin"], cwd=d)


def _make_release_project(tmp_path: Path, *, subdir: bool = False) -> Path:
    """Create a minimal Python project ready for release testing.

    ``subdir`` selects the DES-025 layout, where the plugin surface lives
    under ``plugin/``.
    """
    root = tmp_path / "proj"
    root.mkdir()

    # Init git first with bare commit
    _init_git_repo(root)

    # Now write project files
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test-pkg"\nversion = "0.1.0"\n\n'
        "[project.scripts]\ntest-cli = 'test_pkg:main'\n"
    )

    src = root / "src" / "test_pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (src / "py.typed").write_text("")

    plugin_dir = (root / "plugin" if subdir else root) / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {"name": "test-dev", "version": "0.1.0"},
            indent=2,
        )
        + "\n"
    )

    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "release-plugin.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "git commit --allow-empty"
        ' -m "chore: prepare plugin for release"\n'
    )
    (scripts_dir / "restore-dev-plugin.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "git commit --allow-empty"
        ' -m "chore: restore dev plugin state"\n'
    )

    # Placeholder so info.workflow_files includes "release.yml" — Phase 6
    # (_phase6_ci_wait) fails fast when it's absent for a hybrid/non-plugin
    # project (see f85t.2). Content is irrelevant; only the filename matters
    # to detect().
    workflows_dir = root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "release.yml").write_text("")

    (root / "install.sh").write_text(
        '#!/bin/sh\nPACKAGE="test-pkg"\nVERSION="0.1.0"\n'
        'uv tool install --force "$PACKAGE==$VERSION"\n'
    )

    install_url = (
        "https://raw.githubusercontent.com/punt-labs/test-pkg/v0.1.0/install.sh"
    )
    (root / "README.md").write_text(
        f"# test-pkg\n\n```bash\ncurl -fsSL {install_url} | sh\n```\n"
    )

    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n\n"
        "- New feature\n\n"
        "## [0.1.0] - 2026-01-01\n\n"
        "### Added\n\n"
        "- Initial release\n"
    )

    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    return root


# --- suggest_version ---


def test_suggest_version_minor_bump() -> None:
    """Suggests minor bump when [Unreleased] has ### Added."""
    cl = "## [Unreleased]\n\n### Added\n\n- Feature\n\n## [1.2.3]\n"
    assert _suggest_version(cl, "1.2.3") == "1.3.0"


def test_suggest_version_patch_bump() -> None:
    """Suggests patch bump when [Unreleased] has only ### Fixed."""
    cl = "## [Unreleased]\n\n### Fixed\n\n- Bug fix\n\n## [1.2.3]\n"
    assert _suggest_version(cl, "1.2.3") == "1.2.4"


def test_suggest_version_major_bump() -> None:
    """Suggests major bump for breaking changes."""
    cl = "## [Unreleased]\n\n### Changed\n\n- BREAKING: removed old API\n\n## [1.2.3]\n"
    assert _suggest_version(cl, "1.2.3") == "2.0.0"


def test_suggest_version_breaking_in_fixed_not_major() -> None:
    """'breaking' in Fixed section does not trigger major bump."""
    cl = "## [Unreleased]\n\n### Fixed\n\n- Fixed breaking regression\n\n## [1.2.3]\n"
    assert _suggest_version(cl, "1.2.3") == "1.2.4"


# --- extract_version_notes ---


def test_extract_version_notes() -> None:
    """Extracts notes for a specific version."""
    changelog = (
        "## [Unreleased]\n\n"
        "## [0.2.0] - 2026-03-01\n\n"
        "### Added\n\n- New feature\n\n"
        "## [0.1.0] - 2026-01-01\n\n"
        "### Added\n\n- Initial\n"
    )
    notes = _extract_version_notes(changelog, "0.2.0")
    assert "New feature" in notes
    assert "Initial" not in notes


def test_extract_version_notes_missing() -> None:
    """Returns default when version not found."""
    notes = _extract_version_notes("## [Unreleased]\n", "9.9.9")
    assert "v9.9.9" in notes


# --- phase 1 preflight ---


def test_preflight_fails_dirty_tree(tmp_path: Path) -> None:
    """Pre-flight fails with uncommitted changes."""
    root = _make_release_project(tmp_path)
    (root / "dirty.txt").write_text("dirty")
    _git(["add", "dirty.txt"], cwd=str(root))

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase1_preflight(info, dry_run=False)


def test_preflight_daemon_mutable_only_dirt_names_stash_command(
    tmp_path: Path,
) -> None:
    """Only a daemon-rewritten settings file dirty → actionable stash hint.

    ``.punt-labs/vox/vox.md`` is the one file standards/punt-labs-dir.md § 7
    names as continuously rewritten by a running daemon. When it is the
    *only* dirty path, the failure names the exact stash-push command and
    the post-release pop step instead of the generic dirty-tree dump.
    """
    root = _make_release_project(tmp_path)
    vox_dir = root / ".punt-labs" / "vox"
    vox_dir.mkdir(parents=True)
    (vox_dir / "vox.md").write_text("voice: alloy\n")
    d = str(root)
    _git(["add", ".punt-labs"], cwd=d)
    _git(["commit", "-m", "add vox settings"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    (vox_dir / "vox.md").write_text("voice: nova\n")

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(ReleaseError) as exc_info:
        _phase1_preflight(info, dry_run=False)

    msg = str(exc_info.value)
    assert "git stash push -- .punt-labs/vox/vox.md" in msg
    assert "git stash pop --index" in msg
    assert "commit it instead" in msg
    assert "running vox session can rewrite this file again" in msg


def test_preflight_daemon_only_dirt_with_untracked_reports_both(
    tmp_path: Path,
) -> None:
    """Daemon-only dirt plus an untracked file reports both in one failure.

    ``ops.fail`` raises immediately — a daemon-only-dirty message that
    omitted the untracked file would send the operator through a stash
    only to hit a second, previously invisible failure on the very next
    run. Both problems must be visible from the first failure.
    """
    root = _make_release_project(tmp_path)
    vox_dir = root / ".punt-labs" / "vox"
    vox_dir.mkdir(parents=True)
    (vox_dir / "vox.md").write_text("voice: alloy\n")
    d = str(root)
    _git(["add", ".punt-labs"], cwd=d)
    _git(["commit", "-m", "add vox settings"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    (vox_dir / "vox.md").write_text("voice: nova\n")
    (root / "stray.txt").write_text("stray")

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(ReleaseError) as exc_info:
        _phase1_preflight(info, dry_run=False)

    msg = str(exc_info.value)
    assert "git stash push -- .punt-labs/vox/vox.md" in msg
    assert "Untracked files are also present" in msg
    assert "stray.txt" in msg


def test_preflight_daemon_stash_pop_index_preserves_staged_state(
    tmp_path: Path,
) -> None:
    """The advised stash/pop commands round-trip a *staged* settings change.

    A bare ``git stash pop`` restores file content but not staged status —
    silently turning a staged settings change into an unstaged one. This
    drives the exact commands the message recommends and asserts the file
    comes back staged, proving ``--index`` does what it's there for.
    """
    root = _make_release_project(tmp_path)
    vox_dir = root / ".punt-labs" / "vox"
    vox_dir.mkdir(parents=True)
    (vox_dir / "vox.md").write_text("voice: alloy\n")
    d = str(root)
    _git(["add", ".punt-labs"], cwd=d)
    _git(["commit", "-m", "add vox settings"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    (vox_dir / "vox.md").write_text("voice: nova\n")
    _git(["add", ".punt-labs/vox/vox.md"], cwd=d)

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(ReleaseError) as exc_info:
        _phase1_preflight(info, dry_run=False)

    msg = str(exc_info.value)
    assert "git stash pop --index" in msg

    _git(["stash", "push", "--", ".punt-labs/vox/vox.md"], cwd=d)
    assert _git_out(["status", "--porcelain"], cwd=d) == ""

    _git(["stash", "pop", "--index"], cwd=d)
    status = _git_out(["status", "--porcelain", "--", ".punt-labs/vox/vox.md"], cwd=d)
    assert status == "M  .punt-labs/vox/vox.md"


def test_preflight_mixed_daemon_and_other_dirt_keeps_generic_shape(
    tmp_path: Path,
) -> None:
    """Daemon-mutable dirt mixed with unrelated dirt keeps the generic message.

    The operator still has real cleanup to do beyond stashing vox.md, so the
    failure keeps the original "Working tree is not clean" shape — but it
    still names which paths are daemon-mutable so the stash step isn't
    rediscovered by hand once the rest is cleaned up.
    """
    root = _make_release_project(tmp_path)
    vox_dir = root / ".punt-labs" / "vox"
    vox_dir.mkdir(parents=True)
    (vox_dir / "vox.md").write_text("voice: alloy\n")
    d = str(root)
    _git(["add", ".punt-labs"], cwd=d)
    _git(["commit", "-m", "add vox settings"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    (vox_dir / "vox.md").write_text("voice: nova\n")
    (root / "README.md").write_text("# test-pkg\n\nunrelated edit\n")

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(ReleaseError) as exc_info:
        _phase1_preflight(info, dry_run=False)

    msg = str(exc_info.value)
    assert "Working tree is not clean:" in msg
    assert "README.md" in msg
    assert ".punt-labs/vox/vox.md" in msg
    assert "git stash push -- .punt-labs/vox/vox.md" in msg
    assert "git stash pop --index" in msg
    assert "commit it" in msg
    assert "running vox session can rewrite this file again" in msg


def test_preflight_clean_tree_with_daemon_file_unmodified_passes(
    tmp_path: Path,
) -> None:
    """A committed, unmodified vox.md does not trip the dirty-tree gate.

    The daemon-mutable allowance only changes the *message* on failure — a
    clean tree (vox.md present but not currently dirty) must still pass
    exactly as before.
    """
    root = _make_release_project(tmp_path)
    vox_dir = root / ".punt-labs" / "vox"
    vox_dir.mkdir(parents=True)
    (vox_dir / "vox.md").write_text("voice: alloy\n")
    d = str(root)
    _git(["add", ".punt-labs"], cwd=d)
    _git(["commit", "-m", "add vox settings"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    from punt_kit.detect import detect

    info = detect(root)

    # Should not raise — dry_run skips quality gates.
    _phase1_preflight(info, dry_run=True)


def test_preflight_fails_untracked_file(tmp_path: Path) -> None:
    """Pre-flight fails when there is an untracked file.

    dry_run=True skips the quality gates so the failure is attributable
    to the untracked-file check itself, not to gates failing in the
    scratch project.
    """
    root = _make_release_project(tmp_path)
    (root / "untracked.txt").write_text("untracked")

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(ReleaseError, match="[Uu]ntracked"):
        _phase1_preflight(info, dry_run=True)


def test_preflight_ignores_untracked_beads(tmp_path: Path) -> None:
    """Untracked .beads/ content does not block a release."""
    root = _make_release_project(tmp_path)
    beads = root / ".beads"
    beads.mkdir()
    (beads / "state.json").write_text("{}")

    from punt_kit.detect import detect

    info = detect(root)

    # Should not raise
    _phase1_preflight(info, dry_run=True)


def test_preflight_fails_wrong_branch(tmp_path: Path) -> None:
    """Pre-flight fails when not on main branch."""
    root = _make_release_project(tmp_path)
    _git(["checkout", "-b", "feature"], cwd=str(root))

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase1_preflight(info, dry_run=False)


def test_preflight_fails_empty_unreleased(tmp_path: Path) -> None:
    """Pre-flight fails when [Unreleased] is empty."""
    root = _make_release_project(tmp_path)
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n"
    )
    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "empty changelog"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase1_preflight(info, dry_run=False)


def test_preflight_passes_clean(tmp_path: Path) -> None:
    """Pre-flight passes for clean project on main."""
    root = _make_release_project(tmp_path)

    from punt_kit.detect import detect

    info = detect(root)

    # Should not raise — dry_run skips quality gates
    _phase1_preflight(info, dry_run=True)


def test_preflight_python_prefers_make_check_when_makefile_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Python quality gate runs `make check` when the project has a Makefile.

    Mirrors the Go branch's behavior (pkit-mjcb): a project with optional
    heavy extras (e.g. a `[display]` extra) knows how to gate itself via its
    own Makefile, so the bare `uv run mypy`/`pyright` sequence — which reports
    false errors against the base wheel env — must not run.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    (root / "Makefile").write_text("check:\n\techo ok\n")
    d = str(root)
    _git(["add", "Makefile"], cwd=d)
    _git(["commit", "-m", "add makefile"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)

    gate_calls: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd and cmd[0] in ("make", "uv"):
            gate_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)

    monkeypatch.setattr(release_mod, "_run", fake_run)

    _phase1_preflight(info, dry_run=False)

    assert gate_calls == [["make", "check"]]


def test_preflight_python_falls_back_to_hardcoded_gates_without_makefile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a Makefile, the Python branch keeps running the hardcoded gates."""
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    assert not (root / "Makefile").exists()

    info = detect(root)

    gate_calls: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd and cmd[0] in ("make", "uv"):
            gate_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)

    monkeypatch.setattr(release_mod, "_run", fake_run)

    _phase1_preflight(info, dry_run=False)

    assert gate_calls == [
        ["uv", "run", "ruff", "check", "src/", "tests/"],
        ["uv", "run", "ruff", "format", "--check", "src/", "tests/"],
        ["uv", "run", "mypy", "src/", "tests/"],
        ["uv", "run", "pyright", "src/", "tests/"],
        ["uv", "run", "pytest", "tests/", "-v"],
    ]


def test_preflight_python_make_check_failure_aborts_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A non-zero `make check` aborts the phase instead of reporting success."""
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    (root / "Makefile").write_text("check:\n\techo ok\n")
    d = str(root)
    _git(["add", "Makefile"], cwd=d)
    _git(["commit", "-m", "add makefile"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)

    def fake_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd and cmd[0] in ("make", "uv"):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="lint failed")
        return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="Quality gate failed: make check"):
        _phase1_preflight(info, dry_run=False)

    assert "All quality gates passed" not in capsys.readouterr().out


def test_preflight_fails_actionably_when_git_fetch_origin_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero `git fetch origin` (network failure) must abort with a diagnosis.

    ``fetch.returncode != 0`` is already handled in code (phase01_preflight.py)
    but nothing forced that branch before this test (matrix row 3).
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)

    def fake_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["git", "fetch", "origin"]:
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="fatal: unable to access origin"
            )
        return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="git fetch origin failed"):
        _phase1_preflight(info, dry_run=False)


def test_preflight_quality_gate_timeout_surfaces_as_diagnosed_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A hung `make check` (a wedge, not a failure) must diagnose, not traceback.

    Phase 1's quality gate already opts into the QUALITY_GATE budget
    (matrix row 5 covers a non-zero exit); nothing forced the TimeoutExpired
    path at this specific call site before this test (matrix row 6).
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    (root / "Makefile").write_text("check:\n\techo ok\n")
    d = str(root)
    _git(["add", "Makefile"], cwd=d)
    _git(["commit", "-m", "add makefile"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    hung_cmd = ["make", "check"]

    def fake_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd == hung_cmd:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", dry_run=False)

    assert exc_info.value.code == 1
    normalized = " ".join(capsys.readouterr().out.split())
    assert "make check" in normalized
    assert f"{_QUALITY_GATE_TIMEOUT}s" in normalized
    assert "phase 1 (preflight)" in normalized
    assert "--resume-from preflight" in normalized


def test_preflight_go_quality_gate_failure_aborts_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-zero `go test -race` aborts the phase, parallel to the Python case.

    Row 5's Python `make check` failure test has no Go-language sibling —
    the Go branch (phase01_preflight.py) is unexercised on the failure path
    (matrix row 55).
    """
    from punt_kit import release as release_mod

    root = tmp_path / "go-proj"
    root.mkdir()
    _init_git_repo(root)
    (root / "go.mod").write_text("module github.com/punt-labs/test-go\n\ngo 1.25.0\n")
    (root / "main.go").write_text("package main\n\nfunc main() {}\n")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- New feature\n"
    )
    workflows_dir = root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "release.yml").write_text("")
    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)
    _git(["tag", "v0.1.0"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)
    assert not (root / "Makefile").exists()

    def fake_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["go", "test"]:
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="race detected"
            )
        if cmd[:2] == ["go", "vet"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(
        ReleaseError, match=r"Quality gate failed: go test -race \./\.\.\."
    ):
        _phase1_preflight(info, dry_run=False)

    assert "All quality gates passed" not in capsys.readouterr().out


# --- phase 2 version bump ---


@pytest.mark.parametrize("subdir", [False, True])
def test_version_bump_updates_all_files(tmp_path: Path, *, subdir: bool) -> None:
    """Version bump updates all version locations.

    Run against both layouts: the plugin.json bump is the one place where a
    stale repo-root path silently skips a file rather than failing, and a
    release that ships a plugin.json one version behind is invisible until a
    user's /plugin reports the wrong number.
    """
    root = _make_release_project(tmp_path, subdir=subdir)

    from punt_kit.detect import detect

    info = detect(root)

    _phase2_version_bump(info, "0.2.0", dry_run=False)

    # Check pyproject.toml
    content = (root / "pyproject.toml").read_text()
    assert 'version = "0.2.0"' in content

    # Check __init__.py
    init_path = root / "src" / "test_pkg" / "__init__.py"
    init_content = init_path.read_text()
    assert '__version__ = "0.2.0"' in init_content

    # Check plugin.json
    plugin_data = json.loads(info.plugin_manifest.read_text())
    assert plugin_data["version"] == "0.2.0"

    # Check install.sh VERSION pin
    install_content = (root / "install.sh").read_text()
    assert 'VERSION="0.2.0"' in install_content

    # README install URLs are NOT updated in Phase 2 — they are updated
    # in Phase 9 (_bump_readme_install_sha) after tagging, when the SHA
    # is known.

    # Check CHANGELOG.md
    cl = (root / "CHANGELOG.md").read_text()
    assert "## [0.2.0] - " in cl
    assert "## [Unreleased]" in cl


def test_version_bump_install_sh_no_version_pin(tmp_path: Path) -> None:
    """Version bump is a no-op for install.sh without VERSION pin."""
    root = _make_release_project(tmp_path)

    # Replace install.sh with an unpinned version
    (root / "install.sh").write_text(
        '#!/bin/sh\nPACKAGE="test-pkg"\nuv tool install --force "$PACKAGE"\n'
    )
    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "unpin install.sh"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    from punt_kit.detect import detect

    info = detect(root)

    _phase2_version_bump(info, "0.2.0", dry_run=False)

    # install.sh should be unchanged (no VERSION to bump)
    install_content = (root / "install.sh").read_text()
    assert "VERSION" not in install_content


def test_version_bump_dry_run_no_changes(tmp_path: Path) -> None:
    """Dry run does not modify any files."""
    root = _make_release_project(tmp_path)

    from punt_kit.detect import detect

    info = detect(root)

    _phase2_version_bump(info, "0.2.0", dry_run=True)

    # Files should be unchanged
    content = (root / "pyproject.toml").read_text()
    assert 'version = "0.1.0"' in content


def _commit_files(root: Path, ref: str = "HEAD") -> list[str]:
    """Return the files changed by a commit."""
    result = subprocess.run(
        ["git", "show", "--name-only", "--format=", ref],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    )
    return [ln for ln in result.stdout.strip().splitlines() if ln]


def test_version_bump_commit_excludes_untracked(tmp_path: Path) -> None:
    """The release commit stages only the files the bump edits.

    An untracked file present at bump time must not be swept into the
    release commit (git add -A would capture it).
    """
    root = _make_release_project(tmp_path)
    (root / "stray-transcript.jsonl").write_text("{}\n")

    from punt_kit.detect import detect

    info = detect(root)
    _phase2_version_bump(info, "0.2.0", dry_run=False)

    committed = _commit_files(root)
    assert "stray-transcript.jsonl" not in committed
    assert "pyproject.toml" in committed
    assert "CHANGELOG.md" in committed

    # The stray file is still present and still untracked
    assert (root / "stray-transcript.jsonl").exists()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "stray-transcript.jsonl"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status.startswith("??")


def test_version_bump_uv_lock_failure_diagnoses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing `uv lock` (network resolver op) must diagnose, not leak a
    raw CalledProcessError — the same risk class as `uv build` (Phase 3,
    already diagnosed), missed by round 1's sweep (pkit-f85t.7 round 2)."""
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    (root / "uv.lock").write_text("# lock\n")
    d = str(root)
    _git(["add", "uv.lock"], cwd=d)
    _git(["commit", "-m", "add lock file"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)

    def fake_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd == ["uv", "lock"]:
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="error: failed to resolve dependencies"
            )
        return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="uv lock failed"):
        _phase2_version_bump(info, "0.2.0", dry_run=False)


def test_version_bump_uv_lock_failure_streams_real_output_to_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """The resolver's own error output must actually reach the terminal,
    not just get diagnosed — `capture=False` streams the child process's
    stdout/stderr directly, which the fake-`_run` version of this test
    above cannot prove (it never invokes a real subprocess at all).

    Cursor and Copilot both flagged the same gap on PR #359: the `uv lock`
    call defaulted to `capture=True` while its fail message said "see
    output above," pointing at output that was silently captured and
    never shown anywhere — fixed by adding `capture=False`, matching
    `uv build` (Phase 3) and the Phase 1 quality gates. This test drives
    a real subprocess (a fake `uv` script on `PATH` that fails `uv lock`
    specifically) so `capfd` — which captures at the OS file-descriptor
    level, unlike `capsys` — can observe what the terminal actually
    would.
    """
    from punt_kit.phases.phase02_version_bump import Phase2VersionBump

    root = _make_release_project(tmp_path)
    (root / "uv.lock").write_text("# lock\n")
    d = str(root)
    _git(["add", "uv.lock"], cwd=d)
    _git(["commit", "-m", "add lock file"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "lock" ]; then\n'
        '  echo "error: failed to resolve dependencies for punt-kit" >&2\n'
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    fake_uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    info = detect(root)
    ops = FaultInjectingOps(real_run=_run, rules=[], passthrough=[["uv", "lock"]])

    with pytest.raises(ReleaseError, match="uv lock failed"):
        Phase2VersionBump(info, "0.2.0", dry_run=False, ops=ops).run()

    captured = capfd.readouterr()
    assert "failed to resolve dependencies for punt-kit" in captured.err


# --- phase 2 template pin rewrite (pkit-3zu8) ---

# The pin regex only captures ``punt-*`` names (PL-PL-2: every PyPI package in
# the fleet is punt-prefixed) — the shared fixture's "test-pkg" name predates
# that convention, so these tests rename it before writing any pins.
_OWN_PKG = "punt-test-pkg"


def _use_punt_prefixed_name(root: Path) -> None:
    """Rename the fixture project's pyproject.toml package to ``_OWN_PKG``."""
    pyproject_path = root / "pyproject.toml"
    content = pyproject_path.read_text()
    new_content = content.replace('name = "test-pkg"', f'name = "{_OWN_PKG}"', 1)
    pyproject_path.write_text(new_content)


def _write_template_pin(root: Path, rel_path: str, lines: str) -> Path:
    """Write a bundled-template YAML fixture at ``rel_path`` under ``root``."""
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(lines)
    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", f"add {rel_path}"], cwd=d)
    _git(["fetch", "origin"], cwd=d)
    return path


def test_template_pin_rewritten(tmp_path: Path) -> None:
    """A self-referential 'uvx --from <own-pkg>==X.Y.Z' pin is bumped."""
    root = _make_release_project(tmp_path)
    _use_punt_prefixed_name(root)
    template = _write_template_pin(
        root,
        "src/test_pkg/data/notify.yml",
        f"steps:\n  - run: uvx --from {_OWN_PKG}==0.1.0 test-cli --user wall\n",
    )

    from punt_kit.detect import detect

    info = detect(root)
    _phase2_version_bump(info, "0.2.0", dry_run=False)

    assert f"uvx --from {_OWN_PKG}==0.2.0" in template.read_text()

    # Same commit as the rest of the version bump.
    committed = _commit_files(root)
    assert "src/test_pkg/data/notify.yml" in committed
    assert "pyproject.toml" in committed


def test_template_pin_idempotent(tmp_path: Path) -> None:
    """Re-running the bump with the same version is a no-op."""
    root = _make_release_project(tmp_path)
    _use_punt_prefixed_name(root)
    template = _write_template_pin(
        root,
        "src/test_pkg/data/notify.yml",
        f"steps:\n  - run: uvx --from {_OWN_PKG}==0.1.0 test-cli --user wall\n",
    )

    from punt_kit.detect import detect

    info = detect(root)
    _phase2_version_bump(info, "0.2.0", dry_run=False)
    after_first = template.read_text()

    changed = _rewrite_template_pins(info, "0.2.0", dry_run=False)

    assert changed == []
    assert template.read_text() == after_first


def test_template_pin_dry_run_no_changes(tmp_path: Path) -> None:
    """Dry run reports the rewrite but does not modify the file."""
    root = _make_release_project(tmp_path)
    _use_punt_prefixed_name(root)
    template = _write_template_pin(
        root,
        "src/test_pkg/data/notify.yml",
        f"steps:\n  - run: uvx --from {_OWN_PKG}==0.1.0 test-cli --user wall\n",
    )

    from punt_kit.detect import detect

    info = detect(root)
    changed = _rewrite_template_pins(info, "0.2.0", dry_run=True)

    assert changed == [template]
    assert f"uvx --from {_OWN_PKG}==0.1.0" in template.read_text()


def test_template_pin_unrelated_package_untouched(tmp_path: Path) -> None:
    """Pins for other punt-* packages are never rewritten — supply-chain guarantee."""
    root = _make_release_project(tmp_path)
    _use_punt_prefixed_name(root)
    template = _write_template_pin(
        root,
        "src/test_pkg/data/notify.yml",
        f"steps:\n"
        f"  - run: uvx --from {_OWN_PKG}==0.1.0 test-cli --user wall\n"
        "  - run: uvx --from punt-other==9.9.9 other --do-thing\n",
    )

    from punt_kit.detect import detect

    info = detect(root)
    _phase2_version_bump(info, "0.2.0", dry_run=False)

    content = template.read_text()
    assert f"uvx --from {_OWN_PKG}==0.2.0" in content
    assert "uvx --from punt-other==9.9.9" in content


def test_template_pin_multiple_files_rewritten(tmp_path: Path) -> None:
    """Every matching template file is rewritten in one pass."""
    root = _make_release_project(tmp_path)
    _use_punt_prefixed_name(root)
    first = _write_template_pin(
        root,
        "src/test_pkg/data/notify.yml",
        f"steps:\n  - run: uvx --from {_OWN_PKG}==0.1.0 test-cli --user wall\n",
    )
    second = _write_template_pin(
        root,
        "plugin/workflows/deploy.yaml",
        f"steps:\n  - run: uvx --from {_OWN_PKG}==0.1.0 test-cli --deploy\n",
    )

    from punt_kit.detect import detect

    info = detect(root)
    _phase2_version_bump(info, "0.2.0", dry_run=False)

    assert f"uvx --from {_OWN_PKG}==0.2.0" in first.read_text()
    assert f"uvx --from {_OWN_PKG}==0.2.0" in second.read_text()


def test_template_pin_normalizes_separator_and_case(tmp_path: Path) -> None:
    """A pin spelled with underscores/case still matches the hyphenated name.

    PyPI treats ``-``, ``_``, and ``.`` as equivalent separators and names as
    case-insensitive (PEP 503) — a template pin written as ``punt_test_pkg``
    must still be recognized as the same package as ``punt-test-pkg``.
    """
    root = _make_release_project(tmp_path)
    _use_punt_prefixed_name(root)
    underscored = _OWN_PKG.replace("-", "_")
    template = _write_template_pin(
        root,
        "src/test_pkg/data/notify.yml",
        f"steps:\n  - run: uvx --from {underscored}==0.1.0 test-cli --user wall\n",
    )

    from punt_kit.detect import detect

    info = detect(root)
    _phase2_version_bump(info, "0.2.0", dry_run=False)

    assert f"uvx --from {_OWN_PKG}==0.2.0" in template.read_text()


def test_template_pin_plugin_only_strips_dev_suffix(tmp_path: Path) -> None:
    """The plugin-only fallback name still matches once the dev suffix is gone.

    Phase 2 runs before phase 4's dev-to-prod plugin swap, so a plugin-only
    project's manifest ``name`` on disk at phase 2 time is still the dev
    shell (e.g. ``punt-widget-dev``), not the production name a bundled
    template pins against (``punt-widget``). Without stripping the ``-dev``
    suffix, the equality check would never match and the pin would stay
    stale forever.
    """
    root = _make_language_none_plugin_project(tmp_path)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "punt-widget-dev", "version": "0.1.0"}, indent=2) + "\n"
    )
    template = _write_template_pin(
        root,
        "plugin/workflows/notify.yml",
        "steps:\n  - run: uvx --from punt-widget==0.1.0 widget --user wall\n",
    )

    from punt_kit.detect import detect

    info = detect(root)
    _phase2_version_bump(info, "0.2.0", dry_run=False)

    assert "uvx --from punt-widget==0.2.0" in template.read_text()


def test_template_pin_missing_template_dir_not_an_error(tmp_path: Path) -> None:
    """No src/**/data or plugin/**/*.yml files present is not an error."""
    root = _make_release_project(tmp_path)

    from punt_kit.detect import detect

    info = detect(root)

    changed = _rewrite_template_pins(info, "0.2.0", dry_run=False)

    assert changed == []


def test_phase9_post_release_no_longer_bumps_readme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 9 no longer touches README — that job moved to phase 4 (fwql).

    Regression guard: phase 4 now guarantees the README is already current
    by the time phase 9 runs, so phase 9's job shrinks to dev-restore only.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    d = str(root)

    # A stale SHA that _bump_readme_install_sha would have rewritten under
    # the old phase-9 behavior this fix removes.
    stale_readme = (
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/deadbeef/install.sh | sh\n"
        "```\n"
    )
    (root / "README.md").write_text(stale_readme)
    # Plugin already at "just-released" HEAD state: dev name, released
    # version. Phase 9's restore_done precondition requires both — see
    # release.py:_phase9_post_release.
    plugin_json = root / ".claude-plugin" / "plugin.json"
    plugin_json.write_text(
        json.dumps({"name": "test-dev", "version": "0.2.0"}, indent=2) + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "stale readme, dev/released HEAD"], cwd=d)

    def _unreachable(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("phase 9 must not call _bump_readme_install_sha")

    monkeypatch.setattr(release_mod, "_bump_readme_install_sha", _unreachable)

    def fake_pr_merge(**_kwargs: object) -> str:
        raise AssertionError("phase 9 has nothing to land — _pr_merge must not run")

    monkeypatch.setattr(release_mod, "_pr_merge", fake_pr_merge)

    from punt_kit.detect import detect

    info = detect(root)
    _phase9_post_release(info, "0.2.0", dry_run=False)

    assert (root / "README.md").read_text() == stale_readme


def test_land_readme_sha_pin_commit_excludes_untracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The README-SHA-pin commit stages only README.md, not stray files.

    Ports the untracked-file-exclusion invariant that used to guard phase 9's
    README commit (removed by fwql) to its new home.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    d = str(root)

    # README with a URL matching the repo directory name so the SHA bump fires
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/abc1234/install.sh | sh\n"
        "```\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "matching readme"], cwd=d)

    (root / "stray-transcript.jsonl").write_text("{}\n")

    def fake_pr_merge(**_kwargs: object) -> str:
        return "abc1234"

    monkeypatch.setattr(release_mod, "_pr_merge", fake_pr_merge)

    from punt_kit.detect import detect

    info = detect(root)
    release_mod._land_readme_sha_pin(  # pyright: ignore[reportPrivateUsage]
        info, "0.2.0", dry_run=False
    )

    committed = _commit_files(root)
    assert committed == ["README.md"]
    assert (root / "stray-transcript.jsonl").exists()


# --- README install SHA bump (used in Phase 9: post-release) ---


def test_bump_readme_install_sha_replaces_sha(tmp_path: Path) -> None:
    """SHA-pinned install URLs in README are updated to the tag SHA."""
    root = _make_release_project(tmp_path)
    d = str(root)

    # Rewrite README with SHA-pinned URL using the directory name (proj)
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/abc1234/install.sh | sh\n"
        "```\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "sha-pinned readme"], cwd=d)

    # Create a tag so git rev-parse works
    _git(["tag", "v0.2.0"], cwd=d)

    from punt_kit.detect import detect

    info = detect(root)
    _bump_readme_install_sha(info, "0.2.0", dry_run=False)

    readme_content = (root / "README.md").read_text()
    # Old SHA should be gone
    assert "abc1234" not in readme_content
    # New SHA should be the commit that last touched install.sh
    result = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "install.sh"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    )
    expected_sha = result.stdout.strip()
    assert f"{expected_sha}/install.sh" in readme_content


def test_bump_readme_install_sha_replaces_version_tag(tmp_path: Path) -> None:
    """Version-tagged install URLs in README are replaced with SHA."""
    root = _make_release_project(tmp_path)
    d = str(root)

    # Rewrite README with version-tag URL using directory name (proj)
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/v0.1.0/install.sh | sh\n"
        "```\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "version-tag readme"], cwd=d)
    _git(["tag", "v0.2.0"], cwd=d)

    from punt_kit.detect import detect

    info = detect(root)
    _bump_readme_install_sha(info, "0.2.0", dry_run=False)

    readme_content = (root / "README.md").read_text()
    assert "v0.1.0" not in readme_content
    # New SHA should be the commit that last touched install.sh
    result = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "install.sh"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    )
    expected_sha = result.stdout.strip()
    assert f"{expected_sha}/install.sh" in readme_content


def test_bump_readme_install_sha_dry_run_no_changes(tmp_path: Path) -> None:
    """Dry run does not modify README."""
    root = _make_release_project(tmp_path)
    d = str(root)

    # Use a URL that matches the repo name (proj) so dry-run is exercised
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/abc1234/install.sh | sh\n"
        "```\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "matching readme"], cwd=d)

    original = (root / "README.md").read_text()

    from punt_kit.detect import detect

    info = detect(root)
    _bump_readme_install_sha(info, "0.2.0", dry_run=True)

    assert (root / "README.md").read_text() == original


def test_bump_readme_install_sha_tag_on_different_commit(tmp_path: Path) -> None:
    """Tag on later commit: SHA pins to install.sh commit, not tag."""
    root = _make_release_project(tmp_path)
    d = str(root)

    # Rewrite README with SHA-pinned URL
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/abc1234/install.sh | sh\n"
        "```\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "sha-pinned readme"], cwd=d)

    # Record the SHA of the commit that last touched install.sh
    result = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "install.sh"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    )
    install_sh_sha = result.stdout.strip()

    # Create a "prepare plugin" commit that does NOT touch install.sh,
    # then tag it — simulates hybrid release flow where tag != install.sh commit
    (root / "plugin.json").write_text('{"name": "proj", "version": "0.2.0"}')
    _git(["add", "plugin.json"], cwd=d)
    _git(["commit", "-m", "prepare plugin for release"], cwd=d)
    _git(["tag", "v0.2.0"], cwd=d)

    # Verify tag SHA differs from install.sh SHA
    tag_result = subprocess.run(
        ["git", "rev-parse", "--short", "v0.2.0"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    )
    tag_sha = tag_result.stdout.strip()
    assert tag_sha != install_sh_sha, "test setup: tag and install.sh SHAs must differ"

    from punt_kit.detect import detect

    info = detect(root)
    _bump_readme_install_sha(info, "0.2.0", dry_run=False)

    readme_content = (root / "README.md").read_text()
    assert f"{install_sh_sha}/install.sh" in readme_content
    assert f"{tag_sha}/install.sh" not in readme_content


# --- dry run integration ---


def test_dry_run_no_side_effects(tmp_path: Path) -> None:
    """Full dry run completes without modifying the project."""
    root = _make_release_project(tmp_path)

    original_pyproject = (root / "pyproject.toml").read_text()
    original_changelog = (root / "CHANGELOG.md").read_text()
    original_install = (root / "install.sh").read_text()

    run_release(str(root), version="0.2.0", dry_run=True)

    assert (root / "pyproject.toml").read_text() == original_pyproject
    assert (root / "CHANGELOG.md").read_text() == original_changelog
    assert (root / "install.sh").read_text() == original_install


# --- Go project support ---


def test_get_latest_tag_version(tmp_path: Path) -> None:
    """Reads latest semver tag from git."""
    root = tmp_path / "go-proj"
    root.mkdir()
    _init_git_repo(root)
    d = str(root)
    _git(["tag", "v0.1.0"], cwd=d)
    _git(["commit", "--allow-empty", "-m", "bump"], cwd=d)
    _git(["tag", "v0.2.0"], cwd=d)

    assert _get_latest_tag_version(root) == "0.2.0"


def test_get_latest_tag_version_no_tags(tmp_path: Path) -> None:
    """Returns 0.0.0 when no tags exist."""
    root = tmp_path / "go-proj"
    root.mkdir()
    _init_git_repo(root)

    assert _get_latest_tag_version(root) == "0.0.0"


# --- _get_project_version ---


def test_get_project_version_plugin_only_reads_plugin_json(tmp_path: Path) -> None:
    """A marketplace-only plugin (no pyproject.toml) reads plugin.json's version."""
    root = _make_language_none_plugin_project(tmp_path)
    info = detect(root)
    assert _get_project_version(info) == "0.1.0"


def test_get_project_version_plugin_only_missing_version_fails(tmp_path: Path) -> None:
    """A plugin.json with no version key still fails loudly, not silently."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)
    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps({"name": "test-dev"}) + "\n")
    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "release-plugin.sh").write_text("#!/usr/bin/env bash\n")
    (scripts_dir / "restore-dev-plugin.sh").write_text("#!/usr/bin/env bash\n")
    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)

    info = detect(root)
    with pytest.raises(ReleaseError, match="No version in"):
        _get_project_version(info)


def test_get_project_version_python_unaffected(tmp_path: Path) -> None:
    """The pyproject.toml path is unchanged by the new plugin-only branch."""
    root = _make_release_project(tmp_path)
    info = detect(root)
    assert _get_project_version(info) == "0.1.0"


def test_get_project_version_go_unaffected(tmp_path: Path) -> None:
    """The Go tag path is unchanged by the new plugin-only branch."""
    from punt_kit.detect import ProjectInfo

    root = tmp_path / "go-proj"
    root.mkdir()
    _init_git_repo(root)
    _git(["tag", "v1.2.3"], cwd=str(root))

    info = ProjectInfo(root=root, language="go")
    assert _get_project_version(info) == "1.2.3"


def test_run_release_resume_plugin_only_no_version_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming a plugin-only release without --version must not hard-fail.

    Regresses the bug this bead reports verbatim: "Error: No pyproject.toml
    found" when resuming a marketplace-only plugin release past phase 1.
    """
    from punt_kit import release as release_mod

    root = _make_language_none_plugin_project(tmp_path)

    class _StopAfterVersion(Exception):
        """Sentinel raised once version resolution has succeeded."""

    def _stop(*_args: object, **_kwargs: object) -> None:
        raise _StopAfterVersion

    monkeypatch.setattr(release_mod, "_phase3_build", _stop)

    with pytest.raises(_StopAfterVersion):
        run_release(str(root), resume_from="build")


def test_run_release_fresh_plugin_only_no_version_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh (non-resume) plugin-only release without --version auto-detects.

    Regresses the fresh-path asymmetry: before this fix, a plugin-only
    project failed here even though the resume path (once fixed) could
    already resolve the same version from plugin.json.
    """
    from punt_kit import release as release_mod

    root = _make_language_none_plugin_project(tmp_path)

    class _StopAfterVersion(Exception):
        """Sentinel raised once version resolution has succeeded."""

    def _stop(*_args: object, **_kwargs: object) -> None:
        raise _StopAfterVersion

    monkeypatch.setattr(release_mod, "_phase2_version_bump", _stop)

    with pytest.raises(_StopAfterVersion):
        run_release(str(root))


def test_go_dry_run_no_side_effects(tmp_path: Path) -> None:
    """Dry run for a Go project completes without errors."""
    root = tmp_path / "go-proj"
    root.mkdir()
    _init_git_repo(root)

    (root / "go.mod").write_text("module github.com/punt-labs/test-go\n\ngo 1.25.0\n")
    (root / "main.go").write_text("package main\n\nfunc main() {}\n")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- New feature\n"
    )
    workflows_dir = root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "release.yml").write_text("")

    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)
    _git(["tag", "v0.1.0"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    original_changelog = (root / "CHANGELOG.md").read_text()

    run_release(str(root), version="0.2.0", dry_run=True)

    assert (root / "CHANGELOG.md").read_text() == original_changelog


# --- GitWorkspace (pkit-f85t.7 round 2: sites the round-1 sweep missed) ---


def test_git_workspace_ensure_on_main_diagnoses_checkout_failure(
    tmp_path: Path,
) -> None:
    """A failing `git checkout main` (when not already on main) must
    diagnose, not leak a raw CalledProcessError.

    `GitWorkspace.ensure_on_main` is called unconditionally from Phase 2,
    5, and 9's `run()` — a hook-firing checkout that defaulted to
    check=True was missed by round 1's sweep (pkit-f85t.7 round 2).
    """
    from punt_kit.phases.shared.git import GitWorkspace

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)
    _git(["checkout", "-b", "feature"], cwd=str(root))

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "checkout", "main"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="error: pathspec 'main' did not match"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git checkout main failed"):
        GitWorkspace(root, ops=ops).ensure_on_main()


def test_git_workspace_ensure_on_main_diagnoses_pull_failure(tmp_path: Path) -> None:
    """A failing `git pull --ff-only origin main` must diagnose — a network
    call, structurally identical in risk to `git fetch origin` (Phase 1,
    already diagnosed) and `GitWorkspace.push` (Phase 5, already
    diagnosed), but missed for `ensure_on_main` by round 1's sweep."""
    from punt_kit.phases.shared.git import GitWorkspace

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "pull", "--ff-only", "origin", "main"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="fatal: unable to access origin"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git pull --ff-only origin main failed"):
        GitWorkspace(root, ops=ops).ensure_on_main()


def test_git_workspace_checkout_or_create_diagnoses_existing_branch_failure(
    tmp_path: Path,
) -> None:
    """A failing `git checkout <branch>` for an already-existing branch must
    diagnose, not leak a raw CalledProcessError (pkit-f85t.7 round 2)."""
    from punt_kit.phases.shared.git import GitWorkspace

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)
    _git(["branch", "release/v1.0.0"], cwd=str(root))

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "checkout", "release/v1.0.0"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="error: pre-checkout hook rejected"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git checkout release/v1.0.0 failed"):
        GitWorkspace(root, ops=ops).checkout_or_create("release/v1.0.0")


def test_git_workspace_checkout_or_create_diagnoses_new_branch_failure(
    tmp_path: Path,
) -> None:
    """A failing `git checkout -b <branch>` for a genuinely new branch must
    diagnose, not leak a raw CalledProcessError (pkit-f85t.7 round 2)."""
    from punt_kit.phases.shared.git import GitWorkspace

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "checkout", "-b", "release/v1.0.0"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="fatal: a branch named ... already exists"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git checkout -b release/v1.0.0 failed"):
        GitWorkspace(root, ops=ops).checkout_or_create("release/v1.0.0")


def test_git_workspace_commit_if_staged_diagnoses_commit_failure(
    tmp_path: Path,
) -> None:
    """A rejected `git commit` (pre-commit hook) must diagnose — the same
    hook-firing-mutation class as the Phase 4 swap commit and Phase 9
    restore commit, but this one backs *every* phase's own commit,
    including Phase 2's release-version-bump commit, and was missed by
    round 1's sweep (pkit-f85t.7 round 2)."""
    from punt_kit.phases.shared.git import GitWorkspace

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)
    (root / "release-marker.txt").write_text("v1.0.0\n")

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "commit", "-m", "chore: release v1.0.0"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="pre-commit hook rejected"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git commit failed"):
        GitWorkspace(root, ops=ops).commit_if_staged(
            ["release-marker.txt"], "chore: release v1.0.0"
        )


# --- Phase 3: build ---


def test_phase3_build_uv_build_failure_diagnoses_instead_of_leaking(
    tmp_path: Path,
) -> None:
    """A non-zero `uv build` must diagnose as a ReleaseError, not leak a raw
    CalledProcessError.

    Phase 3 had no isolated failure-path test at all before this (matrix row
    12, design doc defect #5) — `uv build` also defaulted to check=True
    (pkit-f85t.7), so a failure here previously escaped run_release's own
    exception handling and surfaced as a bare traceback, not just a
    lower-quality diagnosis.
    """
    from punt_kit.phases.phase03_build import Phase3Build

    root = _make_release_project(tmp_path)
    info = detect(root)

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["uv", "build"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="error: build backend failed"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="uv build failed"):
        Phase3Build(info, dry_run=False, ops=ops).run()


# --- Phase 5: tag ---


def test_phase5_tag_creation_failure_diagnoses(tmp_path: Path) -> None:
    """A failing `git tag {tag}` (disk full, permission, a lock held by a
    concurrent git process) must diagnose, not leak a raw
    CalledProcessError — kept in the same diagnosed convention as the push
    two lines below in the source, rather than left as the odd one out
    (pkit-f85t.7 round 2)."""
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)
    head_sha = _git_out(["rev-parse", "HEAD"], cwd=str(root))

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "tag", "v1.0.0"],
                response=CompletedProcessSpec(
                    returncode=128, stderr="fatal: cannot lock ref"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git tag v1.0.0 failed"):
        Phase5Tag(info, "1.0.0", dry_run=False, ops=ops).run(release_sha=head_sha)

    assert _git_out(["tag", "--list", "v1.0.0"], cwd=str(root)) == ""


def test_phase5_tag_initial_push_failure_diagnoses_and_leaves_tag_unpushed(
    tmp_path: Path,
) -> None:
    """The very first `git push origin <tag>` failing must diagnose loudly.

    Isolated from the resume scenario below (which forces the same failure
    mode but goes on to test retry-on-resume): this test covers the failure
    moment itself (matrix row 20) — the tag lands locally at HEAD, the
    remote gets nothing, and the phase raises a diagnosed ReleaseError
    rather than a raw CalledProcessError. `GitWorkspace.push` defaulted to
    check=True (pkit-f85t.7); a non-threaded phase like this one had no
    handler that would catch a raw CalledProcessError, so it would have
    escaped run_release's diagnosis path entirely and surfaced as a bare
    traceback.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)
    head_sha = _git_out(["rev-parse", "HEAD"], cwd=str(root))

    failing_ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "push", "origin", "v1.0.0"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="fatal: unable to access remote"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git push origin v1.0.0 failed"):
        Phase5Tag(info, "1.0.0", dry_run=False, ops=failing_ops).run(
            release_sha=head_sha
        )

    assert _git_out(["tag", "--list", "v1.0.0"], cwd=str(root)) == "v1.0.0"
    assert _git_out(["ls-remote", "--tags", "origin", "v1.0.0"], cwd=str(root)) == ""


def test_phase5_tag_resume_repushes_a_locally_created_but_unpushed_tag(
    tmp_path: Path,
) -> None:
    """A push failure after the local tag is created must retry on resume.

    ``Phase5Tag.run`` creates the tag locally before pushing it. If the push
    fails, the tag is left at HEAD locally with nothing on the remote. A
    naive resume that only checks "does the tag exist locally, at HEAD"
    would treat that as success and never re-push — this is the exact
    defect the fix closes.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)
    head_sha = _git_out(["rev-parse", "HEAD"], cwd=str(root))

    failing_ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "push", "origin", "v1.0.0"],
                raises=subprocess.CalledProcessError(1, ["git", "push"]),
            )
        ],
    )
    with pytest.raises(subprocess.CalledProcessError):
        Phase5Tag(info, "1.0.0", dry_run=False, ops=failing_ops).run(
            release_sha=head_sha
        )

    # Local tag exists at HEAD; the remote never received it.
    assert _git_out(["tag", "--list", "v1.0.0"], cwd=str(root)) == "v1.0.0"
    assert _git_out(["ls-remote", "--tags", "origin", "v1.0.0"], cwd=str(root)) == ""

    # Resume with a clean ops double — the push must be retried, not skipped.
    resumed_ops = FaultInjectingOps(real_run=_run, rules=[])
    Phase5Tag(info, "1.0.0", dry_run=False, ops=resumed_ops).run(release_sha=head_sha)

    assert "v1.0.0" in _git_out(
        ["ls-remote", "--tags", "origin", "v1.0.0"], cwd=str(root)
    )


def test_phase5_tag_resume_noops_when_tag_already_reached_remote(
    tmp_path: Path,
) -> None:
    """Resuming after a fully successful tag+push must not push again."""
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)
    head_sha = _git_out(["rev-parse", "HEAD"], cwd=str(root))

    Phase5Tag(
        info, "1.0.0", dry_run=False, ops=FaultInjectingOps(real_run=_run, rules=[])
    ).run(release_sha=head_sha)
    assert "v1.0.0" in _git_out(
        ["ls-remote", "--tags", "origin", "v1.0.0"], cwd=str(root)
    )

    push_calls: list[list[str]] = []

    def spying_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "push"]:
            push_calls.append(cmd)
        return _run(cmd, **kwargs)  # type: ignore[arg-type]

    Phase5Tag(
        info,
        "1.0.0",
        dry_run=False,
        ops=FaultInjectingOps(real_run=spying_run, rules=[]),
    ).run(release_sha=head_sha)

    assert push_calls == [], "tag genuinely on the remote must not be re-pushed"


def test_phase5_tag_resume_fails_loud_when_remote_tag_is_a_stale_different_sha(
    tmp_path: Path,
) -> None:
    """A remote tag's mere presence is not proof it is the right commit.

    Regression test for the SHA-mismatch gap flagged in round-2 review: an
    operator recovering from a botched release by recreating the local tag
    at a corrected commit, while an older, wrong-commit tag of the same
    name still sits on the remote, must get a loud diagnosed failure — not
    a silent "already exists" that leaves the wrong commit tagged upstream.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)

    # Remote gets v1.0.0 at the original commit — the "stale earlier
    # attempt" this scenario recovers from.
    _git(["tag", "v1.0.0"], cwd=str(root))
    _git(["push", "origin", "v1.0.0"], cwd=str(root))
    stale_sha = _git_out(["rev-parse", "v1.0.0"], cwd=str(root))

    # Operator recovery: delete the local tag, advance HEAD, recreate the
    # local tag at the corrected commit — without re-pushing it yet.
    _git(["tag", "-d", "v1.0.0"], cwd=str(root))
    (root / "corrected.txt").write_text("corrected\n")
    _git(["add", "."], cwd=str(root))
    _git(["commit", "-m", "corrected release commit"], cwd=str(root))
    _git(["tag", "v1.0.0"], cwd=str(root))
    corrected_sha = _git_out(["rev-parse", "v1.0.0"], cwd=str(root))
    assert corrected_sha != stale_sha

    push_calls: list[list[str]] = []

    def spying_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "push"]:
            push_calls.append(cmd)
        return _run(cmd, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(ReleaseError, match="exists on the remote but points to"):
        Phase5Tag(
            info,
            "1.0.0",
            dry_run=False,
            ops=FaultInjectingOps(real_run=spying_run, rules=[]),
        ).run(release_sha=corrected_sha)

    assert push_calls == [], "must fail loud, not silently push over the mismatch"
    # The remote still has the stale tag — the failure did not corrupt
    # anything, it only refused to proceed silently.
    assert (
        _git_out(["ls-remote", "--tags", "origin", "v1.0.0"], cwd=str(root)).split()[0]
        == stale_sha
    )


def test_phase5_tag_resume_diagnoses_ls_remote_failure(tmp_path: Path) -> None:
    """A failing `git ls-remote --tags origin` (network) in the existing-tag
    resume path must diagnose, not leak a raw CalledProcessError — same
    network risk class as `git fetch origin` (Phase 1) and this phase's own
    tag push, both already diagnosed. Missed in earlier sweep passes
    (pkit-f85t.7 round 2)."""
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)

    # Tag already exists locally at HEAD (the resume case) — reaches the
    # ls-remote call this test targets.
    _git(["tag", "v1.0.0"], cwd=str(root))
    head_sha = _git_out(["rev-parse", "HEAD"], cwd=str(root))

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "ls-remote", "--tags", "origin"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="fatal: unable to access origin"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git ls-remote --tags origin failed"):
        Phase5Tag(info, "1.0.0", dry_run=False, ops=ops).run(release_sha=head_sha)


def test_phase5_tag_resume_noops_when_remote_tag_is_annotated_at_the_same_commit(
    tmp_path: Path,
) -> None:
    """An annotated remote tag at the right commit must not read as a mismatch.

    Phase5Tag only ever creates lightweight tags itself, but the remote's
    copy of a tag can be annotated (other tooling, a manual `git tag -a`).
    `git ls-remote --tags origin <exact-tag>` (an explicit ref argument)
    never emits the peeled `^{}` line at all, and for an annotated tag its
    one line reports the tag OBJECT's own SHA — not the commit it points
    at — so comparing that directly against a local lightweight tag's
    commit SHA would treat every annotated remote tag as a mismatch, even
    one at the exact right commit.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)

    # Remote gets an ANNOTATED v1.0.0 at the current commit.
    _git(["tag", "-a", "v1.0.0", "-m", "annotated by other tooling"], cwd=str(root))
    _git(["push", "origin", "v1.0.0"], cwd=str(root))
    # Phase5Tag's own local tag is always lightweight, at the same commit —
    # simulate its creation directly (Phase5Tag.run only pushes here since
    # `existing` will be truthy).
    _git(["tag", "-d", "v1.0.0"], cwd=str(root))
    _git(["tag", "v1.0.0"], cwd=str(root))
    head_sha = _git_out(["rev-parse", "HEAD"], cwd=str(root))

    push_calls: list[list[str]] = []

    def spying_run(
        cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "push"]:
            push_calls.append(cmd)
        return _run(cmd, **kwargs)  # type: ignore[arg-type]

    Phase5Tag(
        info,
        "1.0.0",
        dry_run=False,
        ops=FaultInjectingOps(real_run=spying_run, rules=[]),
    ).run(release_sha=head_sha)

    assert push_calls == [], "an annotated tag at the right commit must be a no-op"


def test_phase5_tag_resume_fails_loud_when_remote_tag_is_annotated_at_a_diff_commit(
    tmp_path: Path,
) -> None:
    """An annotated remote tag at the WRONG commit must still fail loud.

    Companion to the same-commit no-op test above — proves the peeled-SHA
    resolution is being compared, not merely tolerated as "present."
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)

    # Remote gets an ANNOTATED v1.0.0 at the original commit.
    _git(["tag", "-a", "v1.0.0", "-m", "annotated by other tooling"], cwd=str(root))
    _git(["push", "origin", "v1.0.0"], cwd=str(root))

    # Operator recovery, as in the lightweight-mismatch test above.
    _git(["tag", "-d", "v1.0.0"], cwd=str(root))
    (root / "corrected.txt").write_text("corrected\n")
    _git(["add", "."], cwd=str(root))
    _git(["commit", "-m", "corrected release commit"], cwd=str(root))
    _git(["tag", "v1.0.0"], cwd=str(root))
    corrected_sha = _git_out(["rev-parse", "v1.0.0"], cwd=str(root))

    with pytest.raises(ReleaseError, match="exists on the remote but points to"):
        Phase5Tag(
            info,
            "1.0.0",
            dry_run=False,
            ops=FaultInjectingOps(real_run=_run, rules=[]),
        ).run(release_sha=corrected_sha)


def test_phase5_tag_tags_the_captured_release_sha_not_advanced_main_head(
    tmp_path: Path,
) -> None:
    """Phase 4c lands a further commit on main (the README install-SHA pin)
    right after the squash-merge Phase 4 itself returns — by the time
    Phase 5 runs, main HEAD is one commit ahead of the actual release.
    Passing the captured ``release_sha`` through must tag that commit, not
    whatever HEAD has since become.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)

    # The release squash-merge commit — this is the SHA Phase 4 would have
    # returned and threaded through to Phase 5.
    release_sha = _git_out(["rev-parse", "HEAD"], cwd=str(root))

    # A further commit lands on main afterward, exactly like Phase 4c's
    # README-SHA-pin commit — main HEAD is now one commit past the release.
    (root / "readme-pin.txt").write_text("pinned\n")
    _git(["add", "."], cwd=str(root))
    _git(["commit", "-m", "chore: update README install SHA to v1.0.0"], cwd=str(root))
    advanced_head = _git_out(["rev-parse", "HEAD"], cwd=str(root))
    assert advanced_head != release_sha

    Phase5Tag(
        info,
        "1.0.0",
        dry_run=False,
        ops=FaultInjectingOps(real_run=_run, rules=[]),
    ).run(release_sha=release_sha)

    assert _git_out(["rev-parse", "v1.0.0"], cwd=str(root)) == release_sha
    assert (
        _git_out(["ls-remote", "--tags", "origin", "v1.0.0"], cwd=str(root)).split()[0]
        == release_sha
    )


def test_phase5_tag_resume_fallback_finds_the_release_commit_past_an_advanced_head(
    tmp_path: Path,
) -> None:
    """``--resume-from tag`` with no captured SHA must resolve the release
    commit from git history, not tag whatever main HEAD currently is.

    Simulates the exact drift scenario from the bead: the release
    squash-merge commit (``chore: release vX.Y.Z``) lands, then a further
    commit (the README-SHA-pin) advances main HEAD past it, and only then
    does Phase 5 run with no ``release_sha`` in hand (a resume that skipped
    Phase 4 in this process).
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)

    (root / "release.txt").write_text("released\n")
    _git(["add", "."], cwd=str(root))
    _git(["commit", "-m", "chore: release v1.0.0"], cwd=str(root))
    release_sha = _git_out(["rev-parse", "HEAD"], cwd=str(root))

    (root / "readme-pin.txt").write_text("pinned\n")
    _git(["add", "."], cwd=str(root))
    _git(["commit", "-m", "chore: update README install SHA to v1.0.0"], cwd=str(root))
    advanced_head = _git_out(["rev-parse", "HEAD"], cwd=str(root))
    assert advanced_head != release_sha

    Phase5Tag(
        info,
        "1.0.0",
        dry_run=False,
        ops=FaultInjectingOps(real_run=_run, rules=[]),
    ).run()

    assert _git_out(["rev-parse", "v1.0.0"], cwd=str(root)) == release_sha


def test_phase5_tag_resume_fallback_matches_squash_commit_with_pr_number_suffix(
    tmp_path: Path,
) -> None:
    """The fallback must match GitHub's real default squash-commit subject.

    ``gh pr merge --squash`` (no ``--subject`` override, as ``PrMerger``
    calls it) appends `` (#<pr-number>)`` to the PR title by default — the
    fallback search must match that shape, not only a bare, hand-committed
    ``chore: release vX.Y.Z`` message.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)

    (root / "release.txt").write_text("released\n")
    _git(["add", "."], cwd=str(root))
    _git(["commit", "-m", "chore: release v1.0.0 (#429)"], cwd=str(root))
    release_sha = _git_out(["rev-parse", "HEAD"], cwd=str(root))

    (root / "readme-pin.txt").write_text("pinned\n")
    _git(["add", "."], cwd=str(root))
    _git(
        ["commit", "-m", "chore: update README install SHA to v1.0.0 (#430)"],
        cwd=str(root),
    )

    Phase5Tag(
        info,
        "1.0.0",
        dry_run=False,
        ops=FaultInjectingOps(real_run=_run, rules=[]),
    ).run()

    assert _git_out(["rev-parse", "v1.0.0"], cwd=str(root)) == release_sha


def test_phase5_tag_resume_fallback_fails_loud_when_no_release_commit_found(
    tmp_path: Path,
) -> None:
    """No matching ``chore: release`` commit on main must raise, not
    silently fall back to tagging HEAD.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)

    with pytest.raises(ReleaseError, match="Could not resolve the release commit"):
        Phase5Tag(
            info,
            "1.0.0",
            dry_run=False,
            ops=FaultInjectingOps(real_run=_run, rules=[]),
        ).run()

    assert _git_out(["tag", "--list", "v1.0.0"], cwd=str(root)) == ""


def test_phase5_tag_resume_fallback_rejects_a_manual_fix_suffix(
    tmp_path: Path,
) -> None:
    """A commit like ``chore: release v1.0.0 (manual fix)`` must NOT match —
    only a bare subject or the real GitHub squash suffix `` (#<number>)``
    does. A loose prefix check would accept any parenthesized suffix,
    including an unrelated commit that merely starts the same way.
    """
    from punt_kit.detect import ProjectInfo
    from punt_kit.phases.phase05_tag import Phase5Tag

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo_with_bare_remote(root, tmp_path / "remote.git")
    info = ProjectInfo(root=root)

    (root / "manual.txt").write_text("manual\n")
    _git(["add", "."], cwd=str(root))
    _git(["commit", "-m", "chore: release v1.0.0 (manual fix)"], cwd=str(root))

    with pytest.raises(ReleaseError, match="Could not resolve the release commit"):
        Phase5Tag(
            info,
            "1.0.0",
            dry_run=False,
            ops=FaultInjectingOps(real_run=_run, rules=[]),
        ).run()

    assert _git_out(["tag", "--list", "v1.0.0"], cwd=str(root)) == ""


# --- sibling helpers ---


def _make_sibling(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    """Create a sibling git repo with given files."""
    sibling = tmp_path / name
    sibling.mkdir(parents=True, exist_ok=True)
    _init_git_repo(sibling)
    for filepath, content in files.items():
        (sibling / filepath).parent.mkdir(parents=True, exist_ok=True)
        (sibling / filepath).write_text(content)
    if files:
        _git(["add", "."], cwd=str(sibling))
        _git(["commit", "-m", f"init {name}"], cwd=str(sibling))
    _git(["fetch", "origin"], cwd=str(sibling))
    return sibling


def test_resolve_sibling_finds_existing(tmp_path: Path) -> None:
    """Resolves a sibling repo that exists."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)

    sibling = _make_sibling(tmp_path, "punt-kit", {})

    result = _resolve_sibling(root, "punt-kit")
    assert result is not None
    assert result == sibling


def test_resolve_sibling_returns_none_missing(tmp_path: Path) -> None:
    """Returns None when sibling does not exist."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)

    result = _resolve_sibling(root, "nonexistent")
    assert result is None


def test_validate_sibling_fails_wrong_branch(tmp_path: Path) -> None:
    """Fails when sibling is on wrong branch."""
    sibling = _make_sibling(tmp_path, "sib", {})
    _git(["checkout", "-b", "feature"], cwd=str(sibling))

    with pytest.raises(ReleaseError):
        _validate_sibling(sibling, "sib")


def test_validate_sibling_fails_dirty(tmp_path: Path) -> None:
    """Fails when sibling has uncommitted changes."""
    sibling = _make_sibling(tmp_path, "sib", {})
    (sibling / "dirty.txt").write_text("dirty")
    _git(["add", "dirty.txt"], cwd=str(sibling))

    with pytest.raises(ReleaseError):
        _validate_sibling(sibling, "sib")


def test_validate_sibling_diagnoses_branch_read_command_failure(
    tmp_path: Path,
) -> None:
    """A `git branch --show-current` command failure on a sibling checkout
    must diagnose, not leak a raw CalledProcessError.

    Sibling checkouts are far less controlled than the project's own repo
    (pkit-f85t.7) — this call defaulted to check=True, inconsistent with
    the `git pull --ff-only` a few lines later in the same method, which
    already diagnosed its own failures.
    """
    from punt_kit.phases.shared.siblings import SiblingRepo

    sibling = _make_sibling(tmp_path, "sib", {})

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "branch", "--show-current"],
                response=CompletedProcessSpec(
                    returncode=128, stderr="fatal: not a git repository"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git branch --show-current failed"):
        SiblingRepo(sibling, "sib", ops=ops).validate()


def test_validate_sibling_diagnoses_status_read_command_failure(
    tmp_path: Path,
) -> None:
    """A `git status --porcelain` command failure on a sibling checkout must
    diagnose, not leak a raw CalledProcessError (pkit-f85t.7)."""
    from punt_kit.phases.shared.siblings import SiblingRepo

    sibling = _make_sibling(tmp_path, "sib", {})

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "status", "--porcelain"],
                response=CompletedProcessSpec(
                    returncode=128, stderr="fatal: index file corrupt"
                ),
            )
        ],
    )

    with pytest.raises(ReleaseError, match="git status --porcelain failed"):
        SiblingRepo(sibling, "sib", ops=ops).validate()


# --- Phase 10a: install-all.sh ---


def test_propagate_install_all_updates_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Updates project SHA in .github/install-all.sh."""
    root = _make_release_project(tmp_path)
    d = str(root)

    # Create tag
    _git(["tag", "v0.2.0"], cwd=d)

    # Create .github sibling with install-all.sh referencing this project
    _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                'curl -fsSL "$GH/proj/aabb001/install.sh" | sh\n'
            )
        },
    )

    # Set remote to include the project name for _get_github_repo
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    # Mock _sibling_pr_merge to avoid needing gh CLI
    from punt_kit import release as release_mod

    calls: list[tuple[str, str, list[str]]] = []

    def mock_sibling_pr_merge(
        path: Path,
        branch: str,
        files: list[str],
        message: str,
        name: str,
        *,
        dry_run: bool,
    ) -> bool:
        calls.append((name, message, files))
        return True

    monkeypatch.setattr(release_mod, "_sibling_pr_merge", mock_sibling_pr_merge)

    from punt_kit.detect import detect

    info = detect(root)
    _propagate_install_all(info, "0.2.0", dry_run=False)

    # Verify install-all.sh was updated (file content, before PR merge)
    content = (tmp_path / ".github" / "install-all.sh").read_text()
    assert "aabb001" not in content
    tag_sha = subprocess.run(
        ["git", "rev-parse", "--short", "v0.2.0"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert f"$GH/proj/{tag_sha}/install.sh" in content
    assert len(calls) == 1
    assert calls[0][0] == ".github"


def test_propagate_install_all_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No-op when SHA is already current."""
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    # SHA already matches — install.sh's last-modifying commit is used
    install_sha = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "install.sh"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Create .github sibling with the SHA already set
    _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                f'curl -fsSL "$GH/proj/{install_sha}/install.sh" | sh\n'
            )
        },
    )

    # Mock _sibling_pr_merge
    from punt_kit import release as release_mod

    calls: list[str] = []

    def mock_sibling_pr_merge(
        path: Path,
        branch: str,
        files: list[str],
        message: str,
        name: str,
        *,
        dry_run: bool,
    ) -> bool:
        calls.append(name)
        return True

    monkeypatch.setattr(release_mod, "_sibling_pr_merge", mock_sibling_pr_merge)

    from punt_kit.detect import detect

    info = detect(root)
    _propagate_install_all(info, "0.2.0", dry_run=False)

    # Should not have called _sibling_pr_merge (SHA already current)
    assert len(calls) == 0


def test_propagate_install_all_skips_when_github_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Absent .github sibling → skip loudly, do not abort the release.

    Phase 10a runs after the tag, PyPI publish, and GitHub release have
    already landed. In the workspace meta-repo layout the ``.github`` path
    is occupied by the meta-repo's own (non-git-root) folder, so it can
    never resolve as a propagation sibling. A ``ReleaseError`` here would
    report failure on an already-published release. The skip must return
    cleanly and tell the operator what did not happen.
    """
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    # No .github sibling created — _resolve_sibling returns None.
    info = detect(root)

    # Must not raise.
    _propagate_install_all(info, "0.2.0", dry_run=False)

    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert "manual" in out.lower()
    assert "install-all.sh" in out
    # Names the repo and version so the operator knows what to fix.
    assert "proj" in out
    assert "v0.2.0" in out


def test_propagate_install_all_fails_when_install_all_missing(
    tmp_path: Path,
) -> None:
    """Present .github sibling but no install-all.sh → still a hard failure.

    A resolvable ``.github`` sibling that lacks ``install-all.sh`` is a
    genuine misconfiguration, distinct from the absent-sibling case, and
    must still abort loudly.
    """
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    # .github sibling exists but has no install-all.sh inside it.
    _make_sibling(tmp_path, ".github", {"README.md": "# org profile\n"})

    info = detect(root)

    with pytest.raises(ReleaseError):
        _propagate_install_all(info, "0.2.0", dry_run=False)


# --- Phase 10b: marketplace ---


def test_propagate_marketplace_updates_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Updates version and ref in marketplace.json."""
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    marketplace_data = {
        "plugins": [
            {
                "name": "proj",
                "version": "0.1.0",
                "source": {
                    "url": "https://github.com/punt-labs/proj.git",
                    "ref": "v0.1.0",
                },
            }
        ]
    }
    _make_sibling(
        tmp_path,
        "claude-plugins",
        {
            ".claude-plugin/marketplace.json": json.dumps(marketplace_data, indent=2)
            + "\n"
        },
    )

    # Mock _sibling_pr_merge
    from punt_kit import release as release_mod

    calls: list[str] = []

    def mock_sibling_pr_merge(
        path: Path,
        branch: str,
        files: list[str],
        message: str,
        name: str,
        *,
        dry_run: bool,
    ) -> bool:
        calls.append(name)
        return True

    monkeypatch.setattr(release_mod, "_sibling_pr_merge", mock_sibling_pr_merge)

    from punt_kit.detect import detect

    info = detect(root)
    _propagate_marketplace(info, "0.2.0", dry_run=False)

    # Verify marketplace.json was updated
    mp = tmp_path / "claude-plugins" / ".claude-plugin" / "marketplace.json"
    data = json.loads(mp.read_text())
    assert data["plugins"][0]["version"] == "0.2.0"
    assert data["plugins"][0]["source"]["ref"] == "v0.2.0"
    assert len(calls) == 1


def _always_merges_sibling(
    path: Path,
    branch: str,
    files: list[str],
    message: str,
    name: str,
    *,
    dry_run: bool,
) -> bool:
    """A ``_sibling_pr_merge`` stand-in that reports every sibling PR merged.

    Used by tests that only care whether ``MarketplacePropagator`` found and
    rewrote the right entry, not whether the (separately tested) sibling-PR
    machinery ran.
    """
    return True


def test_propagate_marketplace_matches_by_marketplace_short_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matches by the plugin's marketplace short name even when the entry's
    ``source.url`` points somewhere that does not end in the project's repo
    name — e.g. a renamed or forked upstream URL that predates a rename.

    Regression coverage for pkit-p328/pkit-d8ij: marketplace entries key on
    the plugin's short name (``punt``), not the PyPI distribution name
    (``punt-kit``) or a URL that happens to match the repo. ``proj``'s
    manifest name (``test-dev`` in the base fixture) is overridden here so
    the marketplace short name ("punt") diverges from both the git remote's
    repo name ("punt-kit") and the entry's (deliberately non-matching) URL.
    """
    root = _make_release_project(tmp_path)
    d = str(root)

    plugin_json = root / ".claude-plugin" / "plugin.json"
    plugin_json.write_text(
        json.dumps({"name": "punt-dev", "version": "0.1.0"}, indent=2) + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "rename plugin manifest"], cwd=d)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/punt-kit.git"],
        cwd=d,
    )

    marketplace_data = {
        "plugins": [
            {
                "name": "punt",
                "version": "0.1.0",
                "source": {
                    # Deliberately does not end in "/punt-kit" — the name
                    # candidate must carry the match on its own.
                    "url": "https://github.com/some-other-org/renamed-repo.git",
                    "ref": "v0.1.0",
                },
            }
        ]
    }
    _make_sibling(
        tmp_path,
        "claude-plugins",
        {
            ".claude-plugin/marketplace.json": json.dumps(marketplace_data, indent=2)
            + "\n"
        },
    )

    from punt_kit import release as release_mod

    monkeypatch.setattr(release_mod, "_sibling_pr_merge", _always_merges_sibling)

    info = detect(root)
    _propagate_marketplace(info, "0.2.0", dry_run=False)

    mp = tmp_path / "claude-plugins" / ".claude-plugin" / "marketplace.json"
    data = json.loads(mp.read_text())
    assert data["plugins"][0]["name"] == "punt"
    assert data["plugins"][0]["version"] == "0.2.0"
    assert data["plugins"][0]["source"]["ref"] == "v0.2.0"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/punt-labs/proj.git",
        "https://github.com/punt-labs/proj",
    ],
)
def test_propagate_marketplace_matches_url_with_and_without_git_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """The trailing ``.git`` on the source URL is optional."""
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    marketplace_data = {
        "plugins": [
            {
                "name": "something-else",
                "version": "0.1.0",
                "source": {"url": url, "ref": "v0.1.0"},
            }
        ]
    }
    _make_sibling(
        tmp_path,
        "claude-plugins",
        {
            ".claude-plugin/marketplace.json": json.dumps(marketplace_data, indent=2)
            + "\n"
        },
    )

    from punt_kit import release as release_mod

    monkeypatch.setattr(release_mod, "_sibling_pr_merge", _always_merges_sibling)

    info = detect(root)
    _propagate_marketplace(info, "0.2.0", dry_run=False)

    mp = tmp_path / "claude-plugins" / ".claude-plugin" / "marketplace.json"
    data = json.loads(mp.read_text())
    assert data["plugins"][0]["version"] == "0.2.0"


def test_propagate_marketplace_fails_when_no_entry_matches_any_candidate(
    tmp_path: Path,
) -> None:
    """No matching name or url in marketplace.json — a hard failure.

    Plugin/hybrid releases require a marketplace entry; a silent no-op here
    is exactly the pkit-d8ij failure mode (propagation runs, nothing lands).
    """
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    marketplace_data = {
        "plugins": [
            {
                "name": "unrelated",
                "version": "0.1.0",
                "source": {
                    "url": "https://github.com/punt-labs/unrelated.git",
                    "ref": "v0.1.0",
                },
            }
        ]
    }
    _make_sibling(
        tmp_path,
        "claude-plugins",
        {
            ".claude-plugin/marketplace.json": json.dumps(marketplace_data, indent=2)
            + "\n"
        },
    )

    info = detect(root)
    with pytest.raises(ReleaseError, match="No marketplace entry for proj"):
        _propagate_marketplace(info, "0.2.0", dry_run=False)


def test_propagate_marketplace_skipped_for_cli_only(tmp_path: Path) -> None:
    """No-op for non-plugin projects."""
    root = tmp_path / "cli-proj"
    root.mkdir()
    _init_git_repo(root)

    (root / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.1.0"\n'
    )
    (root / "CHANGELOG.md").write_text("## [Unreleased]\n\n### Added\n\n- x\n")
    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "init"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    from punt_kit.detect import detect

    info = detect(root)
    assert not info.is_plugin

    # Should not raise even without claude-plugins sibling
    _propagate_marketplace(info, "0.2.0", dry_run=False)


def _merging_sibling_pr_merge(
    calls: list[tuple[str, list[str]]],
) -> object:
    """Build a _sibling_pr_merge mock that lands the change on sibling main.

    Committing the staged files mimics the squash merge so a later
    ``git log -1 -- install-all.sh`` sees the propagated commit.
    """

    def mock_sibling_pr_merge(
        path: Path,
        branch: str,
        files: list[str],
        message: str,
        name: str,
        *,
        dry_run: bool,
    ) -> bool:
        calls.append((name, list(files)))
        for f in files:
            _git(["add", f], cwd=str(path))
        _git(["commit", "-m", message], cwd=str(path))
        return True

    return mock_sibling_pr_merge


def test_propagate_install_all_pins_profile_to_merged_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile README pins the SHA of the merged install-all.sh commit.

    The SHA must be captured after the install-all.sh PR merges — a pin
    captured before points one commit behind and serves the previous
    installer on every release.
    """
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    # Create .github sibling with install-all.sh AND profile/README.md
    sibling = _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                'curl -fsSL "$GH/proj/aabb001/install.sh" | sh\n'
            ),
            "profile/README.md": (
                "# Punt Labs\n\n"
                "```bash\n"
                "curl -fsSL https://raw.githubusercontent.com/"
                "punt-labs/.github/aabb002/install-all.sh | sh\n"
                "```\n"
            ),
        },
    )

    # SHA of the last install-all.sh commit BEFORE propagation
    pre_merge_sha = _get_install_all_short_sha(sibling)

    from punt_kit import release as release_mod

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        release_mod, "_sibling_pr_merge", _merging_sibling_pr_merge(calls)
    )

    from punt_kit.detect import detect

    info = detect(root)
    _propagate_install_all(info, "0.2.0", dry_run=False)

    # The profile pins the merged commit, not the pre-merge one
    merged_sha = _get_install_all_short_sha(sibling)
    assert merged_sha != pre_merge_sha
    readme = (tmp_path / ".github" / "profile" / "README.md").read_text()
    assert "aabb002" not in readme
    assert f".github/{merged_sha}/install-all.sh" in readme

    # Two sequential PRs: install-all.sh first, then the profile pin
    assert calls == [
        (".github", ["install-all.sh"]),
        (".github", ["profile/README.md"]),
    ]


def test_propagate_install_all_repairs_stale_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale profile pin is repaired even when install-all.sh is current."""
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    install_sha = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "install.sh"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # install-all.sh already current; profile pinned to a stale SHA
    sibling = _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                f'curl -fsSL "$GH/proj/{install_sha}/install.sh" | sh\n'
            ),
            "profile/README.md": (
                "# Punt Labs\n\n"
                "curl -fsSL https://raw.githubusercontent.com/"
                "punt-labs/.github/aabb002/install-all.sh | sh\n"
            ),
        },
    )

    from punt_kit import release as release_mod

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        release_mod, "_sibling_pr_merge", _merging_sibling_pr_merge(calls)
    )

    from punt_kit.detect import detect

    info = detect(root)
    _propagate_install_all(info, "0.2.0", dry_run=False)

    # Only the profile PR is needed
    assert calls == [(".github", ["profile/README.md"])]
    current_sha = _get_install_all_short_sha(sibling)
    readme = (tmp_path / ".github" / "profile" / "README.md").read_text()
    assert f".github/{current_sha}/install-all.sh" in readme


def test_propagate_install_all_sync_profile_readme_git_log_failure_diagnoses(
    tmp_path: Path,
) -> None:
    """A failing `git log` against the sibling checkout (install-all.sh's
    last-touch commit) must diagnose, not leak a raw CalledProcessError.

    `_sync_profile_readme`'s git log call is design doc defect #3's named
    example — it defaulted to check=True with no surrounding message
    (pkit-f85t.7), unlike a genuinely empty result (no commit has ever
    touched install-all.sh), which is a distinct, already-handled case.
    """
    from punt_kit.phases.phase10_propagate import InstallAllPropagator
    from punt_kit.phases.shared.siblings import SkipRecorder

    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"], cwd=d)

    install_sha = _git_out(["log", "-1", "--format=%h", "--", "install.sh"], cwd=d)

    # install-all.sh already current — the propagator falls straight through
    # to _sync_profile_readme, which is where the fault below fires.
    _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                f'curl -fsSL "$GH/proj/{install_sha}/install.sh" | sh\n'
            ),
            "profile/README.md": "# Punt Labs\n\nno pin yet\n",
        },
    )

    info = detect(root)

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "log", "-1", "--format=%h", "--", "install-all.sh"],
                response=CompletedProcessSpec(
                    returncode=128, stderr="fatal: bad revision 'HEAD'"
                ),
            )
        ],
    )

    def _unreachable_merge(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError(
            "merge_sibling must not run — the git log call fails first"
        )

    with pytest.raises(
        ReleaseError, match="git log on sibling .* \\(install-all.sh\\) failed"
    ):
        InstallAllPropagator(info, ops=ops, skips=SkipRecorder(ops=ops)).run(
            "0.2.0", dry_run=False, merge_sibling=_unreachable_merge
        )


def _get_install_all_short_sha(sibling: Path) -> str:
    """Return the short SHA of the last commit touching install-all.sh."""
    return subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "install-all.sh"],
        cwd=str(sibling),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


# --- Phase 10d: website ---


def test_propagate_website_updates_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Updates version in projects.json."""
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.2.0"], cwd=d)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    projects_data = [
        {"id": "proj", "version": "0.1.0", "githubUrl": ""},
        {"id": "other", "version": "1.0.0", "githubUrl": ""},
    ]
    _make_sibling(
        tmp_path,
        "public-website",
        {"src/data/projects.json": json.dumps(projects_data, indent=2) + "\n"},
    )

    # Mock _sibling_pr_merge
    from punt_kit import release as release_mod

    calls: list[str] = []

    def mock_sibling_pr_merge(
        path: Path,
        branch: str,
        files: list[str],
        message: str,
        name: str,
        *,
        dry_run: bool,
    ) -> bool:
        calls.append(name)
        return True

    monkeypatch.setattr(release_mod, "_sibling_pr_merge", mock_sibling_pr_merge)

    from punt_kit.detect import detect

    info = detect(root)
    _propagate_website(info, "0.2.0", dry_run=False)

    pj = tmp_path / "public-website" / "src" / "data" / "projects.json"
    data = json.loads(pj.read_text())
    assert data[0]["version"] == "0.2.0"
    assert data[1]["version"] == "1.0.0"  # unchanged
    assert len(calls) == 1


def test_propagate_website_skipped_when_missing(tmp_path: Path) -> None:
    """Graceful skip when public-website not present."""
    root = _make_release_project(tmp_path)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=str(root),
    )

    from punt_kit.detect import detect

    info = detect(root)
    # Should not raise
    _propagate_website(info, "0.2.0", dry_run=False)


# --- PHASE_NAMES ---


# --- Propagation bug fixes (punt-kit-91t, punt-kit-5b4, punt-kit-zay) ---


def test_validate_sibling_called_during_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Preflight validates sibling repos that would be used in propagation (91t).

    We use dry_run=True to skip quality gates, but sibling checks should still
    run because dirty siblings won't magically become clean by release time.
    """
    root = _make_release_project(tmp_path)

    # Create .github sibling with staged (dirty) changes
    sibling = _make_sibling(tmp_path, ".github", {"install-all.sh": "#!/bin/sh\n"})
    (sibling / "dirty.txt").write_text("dirty")
    _git(["add", "dirty.txt"], cwd=str(sibling))

    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase1_preflight(info, dry_run=True)


def test_validate_sibling_wrong_branch_during_preflight(
    tmp_path: Path,
) -> None:
    """Preflight fails if sibling is on stale propagation branch (5b4/zay)."""
    root = _make_release_project(tmp_path)

    sibling = _make_sibling(tmp_path, ".github", {"install-all.sh": "#!/bin/sh\n"})
    _git(["checkout", "-b", "propagate/v1.0.0-proj-github"], cwd=str(sibling))

    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase1_preflight(info, dry_run=True)


def test_preflight_passes_with_clean_siblings(tmp_path: Path) -> None:
    """Preflight passes when siblings are clean and on main."""
    root = _make_release_project(tmp_path)

    # Create clean sibling on main
    _make_sibling(tmp_path, ".github", {"install-all.sh": "#!/bin/sh\n"})

    info = detect(root)
    # Should not raise
    _phase1_preflight(info, dry_run=True)


def test_sibling_pr_merge_returns_to_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After _sibling_pr_merge, sibling is back on main (5b4/zay fix)."""
    from punt_kit import release as release_mod

    sibling = _make_sibling(tmp_path, "sib", {"file.txt": "v1"})

    # Modify a tracked file to create a diff
    (sibling / "file.txt").write_text("v2")

    # Mock _pr_merge to avoid real GitHub operations
    def fake_pr_merge(
        *,
        cwd: Path,
        branch: str,
        title: str,
        body: str = "",
        dry_run: bool = False,
    ) -> str:
        # Real _pr_merge checks out main after merge — simulate that
        _git(["checkout", "main"], cwd=str(cwd))
        return "abc1234"

    monkeypatch.setattr(release_mod, "_pr_merge", fake_pr_merge)

    release_mod._sibling_pr_merge(  # pyright: ignore[reportPrivateUsage]
        sibling, "test-branch", ["file.txt"], "test commit", "sib", dry_run=False
    )

    # Verify we're back on main
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(sibling),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "main"


def test_sibling_pr_merge_returns_to_main_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sibling returns to main even when _pr_merge fails (5b4/zay)."""
    from punt_kit import release as release_mod

    sibling = _make_sibling(tmp_path, "sib", {"file.txt": "v1"})
    (sibling / "file.txt").write_text("v2")

    def failing_pr_merge(**kwargs: object) -> str:  # noqa: ARG001
        raise SystemExit(1)

    monkeypatch.setattr(release_mod, "_pr_merge", failing_pr_merge)

    with pytest.raises(SystemExit):
        release_mod._sibling_pr_merge(  # pyright: ignore[reportPrivateUsage]
            sibling,
            "test-branch",
            ["file.txt"],
            "test commit",
            "sib",
            dry_run=False,
        )

    # The critical assertion: sibling is back on main despite the failure
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(sibling),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "main"


def test_sibling_pr_merge_wrapper_wires_skips_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real ``_sibling_pr_merge`` wrapper threads ``_skips`` through.

    Every other SkipRecorder test constructs ``PrMerger(ops=ops,
    skips=skips)`` directly — none drives a secondary cleanup failure
    through the actual production wiring
    (``PrMerger(ops=_ops, skips=_skips)`` at ``_sibling_pr_merge``'s one
    call site). A future change that dropped or misdirected that one
    argument would not be caught by anything else in the suite.
    """
    from punt_kit import release as release_mod

    sibling = _make_sibling(tmp_path, "sib", {"file.txt": "v1"})
    (sibling / "file.txt").write_text("v2")

    def failing_pr_merge(**kwargs: object) -> str:  # noqa: ARG001
        raise ReleaseError("required checks never passed")

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        # Only the merge_in_sibling finally block's cleanup checkout uses
        # this exact argv — checkout_or_create checks out the feature
        # branch, not "main" — so this can't accidentally intercept an
        # earlier, unrelated checkout in the same flow.
        if cmd == ["git", "checkout", "main"]:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout="",
                stderr="local changes would be overwritten",
            )
        return _run(cmd, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(release_mod, "_pr_merge", failing_pr_merge)
    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="required checks never passed"):
        release_mod._sibling_pr_merge(  # pyright: ignore[reportPrivateUsage]
            sibling,
            "test-branch",
            ["file.txt"],
            "test commit",
            "sib",
            dry_run=False,
        )

    (notice,) = release_mod._skips.drain()  # pyright: ignore[reportPrivateUsage]
    assert "required checks never passed" in notice
    assert "local changes would be overwritten" in notice


def test_phase_names_cover_all_phases() -> None:
    """All 11 phases are mapped (plus aliases)."""
    phase_numbers = set(PHASE_NAMES.values())
    assert phase_numbers == set(range(1, 12))


def test_phase_names_aliases() -> None:
    """Old name aliases resolve to correct phase numbers."""
    assert PHASE_NAMES["release"] == 4  # alias for release-pr


# --- wy5: plugin script checks for pure plugin projects ---


def _make_pure_plugin_project(tmp_path: Path) -> Path:
    """Create a pure plugin project (no CLI commands, so not hybrid)."""
    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)

    # pyproject.toml WITHOUT [project.scripts] → cli_commands=[]
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test-pkg"\nversion = "0.1.0"\n'
    )

    src = root / "src" / "test_pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('__version__ = "0.1.0"\n')

    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test-dev", "version": "0.1.0"}, indent=2) + "\n"
    )

    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "release-plugin.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'git commit --allow-empty -m "chore: prepare plugin for release"\n'
    )
    (scripts_dir / "restore-dev-plugin.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'git commit --allow-empty -m "chore: restore dev plugin state"\n'
    )

    # No install.sh — pure plugins are installed via the `for plugin in` loop
    # in install-all.sh, not via curl of a standalone installer.

    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n\n"
        "- New feature\n\n"
        "## [0.1.0] - 2026-01-01\n\n"
        "### Added\n\n"
        "- Initial release\n"
    )

    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    return root


def _make_language_none_plugin_project(tmp_path: Path) -> Path:
    """Create a marketplace-only plugin with no pyproject.toml at all.

    Unlike ``_make_pure_plugin_project`` (which still writes a
    ``pyproject.toml`` without ``[project.scripts]``, so ``info.language ==
    "python"`` and ``info.pyproject is not None``), this fixture leaves
    ``language`` and ``pyproject`` both unset — the precondition f85t.1's
    plugin-only branch of ``_get_project_version`` actually guards on.
    """
    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)

    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test-dev", "version": "0.1.0"}, indent=2) + "\n"
    )

    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "release-plugin.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'git commit --allow-empty -m "chore: prepare plugin for release"\n'
    )
    (scripts_dir / "restore-dev-plugin.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'git commit --allow-empty -m "chore: restore dev plugin state"\n'
    )

    # No pyproject.toml, no package.json, no go.mod — detect() leaves
    # language=None. No install.sh — marketplace-only, same as
    # _make_pure_plugin_project.

    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n\n"
        "- New feature\n\n"
        "## [0.1.0] - 2026-01-01\n\n"
        "### Added\n\n"
        "- Initial release\n"
    )

    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    return root


def test_pure_plugin_detected_correctly(tmp_path: Path) -> None:
    """Pure plugin has is_plugin=True but is_hybrid=False."""
    root = _make_pure_plugin_project(tmp_path)
    info = detect(root)
    assert info.is_plugin is True
    assert info.is_hybrid is False


def test_language_none_plugin_project_detected_correctly(tmp_path: Path) -> None:
    """Marketplace-only plugin has no pyproject.toml and no detected language."""
    root = _make_language_none_plugin_project(tmp_path)
    info = detect(root)
    assert info.is_plugin is True
    assert info.language is None
    assert info.pyproject is None


def test_preflight_checks_scripts_for_pure_plugin(tmp_path: Path) -> None:
    """Preflight validates release/restore scripts exist for pure plugins."""
    root = _make_pure_plugin_project(tmp_path)
    info = detect(root)

    # Should pass — scripts exist
    _phase1_preflight(info, dry_run=True)


def test_preflight_fails_missing_scripts_for_pure_plugin(tmp_path: Path) -> None:
    """Preflight fails for pure plugin with missing release scripts."""
    root = _make_pure_plugin_project(tmp_path)

    # Remove the release script
    (root / "scripts" / "release-plugin.sh").unlink()
    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "remove script"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase1_preflight(info, dry_run=False)


# --- pkit-dlv6: preflight out-of-band tag detection ---


def test_preflight_silent_with_no_prior_tags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No tags at all — nothing to compare, nothing to warn about."""
    root = _make_pure_plugin_project(tmp_path)
    info = detect(root)

    _phase1_preflight(info, dry_run=True)

    assert "WARNING" not in capsys.readouterr().out


def test_preflight_silent_when_prior_tag_is_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A prior tag whose manifest is already prod-shaped is silent."""
    root = _make_pure_plugin_project(tmp_path)
    d = str(root)
    plugin_json = root / ".claude-plugin" / "plugin.json"
    plugin_json.write_text(
        json.dumps({"name": "test-pkg", "version": "0.1.0"}, indent=2) + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "swap to prod"], cwd=d)
    _git(["tag", "v0.1.0"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)
    _phase1_preflight(info, dry_run=True)

    assert "WARNING" not in capsys.readouterr().out


def test_preflight_warns_when_prior_tag_still_carries_dev_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A prior tag whose manifest never got swapped to prod warns loudly.

    ``_make_pure_plugin_project`` scaffolds ``plugin.json`` with the ``-dev``
    name and never swaps it, so tagging straight off that scaffold models a
    release cut outside the normal Phase 4 plugin-swap flow.
    """
    root = _make_pure_plugin_project(tmp_path)
    d = str(root)
    _git(["tag", "v0.1.0"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)
    _phase1_preflight(info, dry_run=True)

    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "v0.1.0" in out
    assert "test-dev" in out


def test_preflight_warns_when_prior_tag_version_mismatches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A prior tag whose manifest version does not match the tag warns."""
    root = _make_pure_plugin_project(tmp_path)
    d = str(root)
    plugin_json = root / ".claude-plugin" / "plugin.json"
    plugin_json.write_text(
        json.dumps({"name": "test-pkg", "version": "0.0.9"}, indent=2) + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "swap to prod at wrong version"], cwd=d)
    _git(["tag", "v0.1.0"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)
    _phase1_preflight(info, dry_run=True)

    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "v0.1.0" in out
    assert "0.0.9" in out


# --- pvb: verify finds pure-plugin entries in install-all.sh ---


def test_verify_finds_pure_plugin_in_install_all(tmp_path: Path) -> None:
    """Verify phase finds projects in the 'for plugin in ...' loop."""
    import re

    root = _make_release_project(tmp_path)
    d = str(root)

    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    # Create .github sibling with pure-plugin loop containing this project
    sibling = _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                "for plugin in prfaq proj z-spec; do\n"
                '  claude plugin install "$plugin@punt-labs"\n'
                "done\n"
            )
        },
    )

    # Verify the regex matches the pure-plugin loop
    iac = (sibling / "install-all.sh").read_text()
    project_name = "proj"

    # The curl-entry regex should NOT match
    curl_match = re.search(
        rf"\$GH/{re.escape(project_name)}/"
        r"([0-9a-fA-F]{7,40})/install\.sh",
        iac,
    )
    assert curl_match is None

    # The pure-plugin loop regex SHOULD match
    plugin_match = re.search(
        rf"for plugin in [^;]*\b{re.escape(project_name)}\b",
        iac,
    )
    assert plugin_match is not None


# --- _wait_for_required_checks ---


def _fake_get_github_repo(_p: Path) -> str:
    return "punt-labs/punt-kit"


def _graphql_checks_response(
    check_nodes: list[dict[str, object]],
) -> dict[str, object]:
    """Build a GraphQL response matching the nested structure used by
    ``_wait_for_required_checks``."""
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "commits": {
                        "nodes": [
                            {
                                "commit": {
                                    "statusCheckRollup": {
                                        "contexts": {
                                            "nodes": check_nodes,
                                        },
                                    },
                                },
                            },
                        ],
                    },
                },
            },
        },
    }


def _graphql_no_required_checks_response() -> dict[str, object]:
    """A GraphQL response whose contexts list is empty.

    Distinct from ``_graphql_checks_response([])`` only in intent — used by
    the "no branch protection" tests where the empty context list represents
    the repo genuinely having no checks configured yet, not a malformed poll.
    """
    return _graphql_checks_response([])


def _protection_response(*, protected: bool) -> MagicMock:
    """Build the ``MagicMock`` for a ``gh api .../branches/main/protection`` call."""
    result = MagicMock()
    if protected:
        result.returncode = 0
        result.stdout = json.dumps({"required_status_checks": {"contexts": []}})
        result.stderr = ""
    else:
        result.returncode = 1
        result.stdout = ""
        result.stderr = "gh: Branch not protected (HTTP 404)"
    return result


def _ruleset_response(*, governed: bool) -> MagicMock:
    """Build the ``MagicMock`` for a ``gh api .../rules/branches/main`` call.

    The endpoint returns a JSON array of active rules — non-empty when a
    ruleset governs the branch, empty (never a non-zero exit) when none do.
    """
    result = MagicMock()
    result.returncode = 0
    result.stderr = ""
    result.stdout = json.dumps([{"type": "required_status_checks"}] if governed else [])
    return result


def _is_protection_call(cmd: list[str]) -> bool:
    """True if ``cmd`` is the legacy branch-protection ``gh api`` call."""
    return cmd[:2] == ["gh", "api"] and cmd[2].endswith("/protection")


def _is_ruleset_call(cmd: list[str]) -> bool:
    """True if ``cmd`` is the ruleset ``gh api`` call."""
    return cmd[:2] == ["gh", "api"] and cmd[2].endswith("/rules/branches/main")


def _make_fake_clock(*, step: float = 60.0) -> Callable[[], float]:
    """A monotonically increasing fake clock for grace-window tests.

    Each call advances by ``step`` seconds, so a bounded wall-clock window
    (e.g. ``NO_CHECKS_GRACE``) can be crossed in a handful of calls instead
    of the test actually sleeping in real time. Paired with a no-op
    ``time.sleep`` patch, since ``_wait_for_required_checks`` sleeps between
    polls but the fake clock — not real elapsed time — is what the deadline
    checks read.
    """
    state = {"now": 1_000_000.0}

    def _clock() -> float:
        state["now"] += step
        return state["now"]

    return _clock


def test_graphql_no_required_checks_response_shape() -> None:
    """The empty-contexts fixture nests under the same path as a real poll."""
    response = _graphql_no_required_checks_response()
    data = cast("dict[str, object]", response["data"])
    repository = cast("dict[str, object]", data["repository"])
    pull_request = cast("dict[str, object]", repository["pullRequest"])
    commits = cast("dict[str, object]", pull_request["commits"])
    nodes = cast("list[dict[str, object]]", commits["nodes"])
    commit = cast("dict[str, object]", nodes[0]["commit"])
    rollup = cast("dict[str, object]", commit["statusCheckRollup"])
    contexts = cast("dict[str, object]", rollup["contexts"])
    assert contexts["nodes"] == []


def test_protection_response_protected_true() -> None:
    """A protected-repo response reports success with no stderr."""
    result = _protection_response(protected=True)
    assert result.returncode == 0
    assert result.stderr == ""


def test_protection_response_protected_false() -> None:
    """An unprotected-repo response reports the 404 gh emits."""
    result = _protection_response(protected=False)
    assert result.returncode == 1
    assert "404" in result.stderr


def test_wait_for_required_checks_passes_when_all_required_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns immediately when all required checks succeed."""
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "lint",
            "isRequired": True,
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
        {
            "name": "Claude Code Review",
            "isRequired": False,
            "conclusion": None,
            "status": "IN_PROGRESS",
        },
    ]

    call_count = 0

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        nonlocal call_count
        if _is_protection_call(cmd):
            return _protection_response(protected=True)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        call_count += 1
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    _wait_for_required_checks("gh", "/tmp", 42)
    # One graphql poll — the pre-loop branch-protection and ruleset checks
    # are intercepted separately and are not counted here.
    assert call_count == 1


def test_wait_for_required_checks_fails_on_required_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calls _fail when a required check fails."""
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "test",
            "isRequired": True,
            "conclusion": "FAILURE",
            "status": "COMPLETED",
        },
    ]

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    with pytest.raises(ReleaseError):
        _wait_for_required_checks("gh", "/tmp", 42)


def test_wait_for_required_checks_ignores_non_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Does not fail when only non-required checks fail."""
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "lint",
            "isRequired": True,
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
        {
            "name": "optional",
            "isRequired": False,
            "conclusion": "FAILURE",
            "status": "COMPLETED",
        },
    ]

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    # Should not raise
    _wait_for_required_checks("gh", "/tmp", 42)


def test_wait_for_required_checks_status_context_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """StatusContext nodes with state=SUCCESS are treated as passed."""
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "context": "deploy/preview",
            "isRequired": True,
            "state": "SUCCESS",
        },
    ]

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    # Should not raise — SUCCESS StatusContext is a pass
    _wait_for_required_checks("gh", "/tmp", 42)


def test_wait_for_required_checks_status_context_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """StatusContext nodes with state=ERROR are treated as failures."""
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "context": "deploy/preview",
            "isRequired": True,
            "state": "ERROR",
        },
    ]

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    with pytest.raises(ReleaseError):
        _wait_for_required_checks("gh", "/tmp", 42)


def test_wait_for_required_checks_survives_a_slow_graphql_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TimeoutExpired from one gh api graphql must not abort the poll.

    The loop has a two-hour deadline and models a failed query with a
    five-strikes counter. One slow GitHub response must route into that
    counter — the release still has most of its polling window left —
    rather than escape as a traceback and abort the whole run.
    """
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "lint",
            "isRequired": True,
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
    ]

    def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("punt_kit.release.time.sleep", _noop_sleep)

    call_count = 0

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        nonlocal call_count
        if _is_protection_call(cmd):
            return _protection_response(protected=True)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        call_count += 1
        if call_count == 1:
            raise subprocess.TimeoutExpired(cmd, 60)
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    _wait_for_required_checks("gh", "/tmp", 42)
    assert call_count == 2


def test_wait_for_required_checks_fails_after_five_consecutive_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Five consecutive timeouts trip the same failure path as five errors.

    The timeout route must not launder a permanently-broken GitHub into an
    infinite retry — routing into consecutive_errors means the existing
    five-strikes ceiling still trips.
    """
    from punt_kit import release as release_mod

    def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("punt_kit.release.time.sleep", _noop_sleep)

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    with pytest.raises(ReleaseError, match="5 consecutive times"):
        _wait_for_required_checks("gh", "/tmp", 42)


# --- f85t.4: branch-protection fallback ---


def test_branch_protection_exists_true_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 from the protection endpoint means the branch is protected."""
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        return _protection_response(protected=True)

    monkeypatch.setattr(release_mod, "_run", fake_run)
    assert (
        release_mod._branch_protection_exists(  # pyright: ignore[reportPrivateUsage]
            "gh", "/tmp", "punt-labs", "punt-kit"
        )
        is True
    )


def test_branch_protection_exists_false_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """A confirmed 404 means the branch has no protection configured."""
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        return _protection_response(protected=False)

    monkeypatch.setattr(release_mod, "_run", fake_run)
    assert (
        release_mod._branch_protection_exists(  # pyright: ignore[reportPrivateUsage]
            "gh", "/tmp", "punt-labs", "punt-kit"
        )
        is False
    )


def test_branch_protection_exists_true_on_unrelated_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrelated failure (rate limit, auth) does not widen the check set."""
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "gh: API rate limit exceeded"
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    assert (
        release_mod._branch_protection_exists(  # pyright: ignore[reportPrivateUsage]
            "gh", "/tmp", "punt-labs", "punt-kit"
        )
        is True
    )


def test_branch_protection_exists_true_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung protection check fails open rather than aborting the release."""
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(release_mod, "_run", fake_run)
    assert (
        release_mod._branch_protection_exists(  # pyright: ignore[reportPrivateUsage]
            "gh", "/tmp", "punt-labs", "punt-kit"
        )
        is True
    )


def test_branch_protection_exists_true_on_permission_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 404 without the "branch not protected" marker is treated as protected.

    GitHub's branch-protection REST endpoint 404s when the token lacks
    ``admin:repo`` even for a repo that DOES have protection. Fail-safe
    to protected=True in that case rather than silently widening the
    check set to include informational-only checks the repo excluded.
    """
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "gh: Not Found (HTTP 404)"
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    assert (
        release_mod._branch_protection_exists(  # pyright: ignore[reportPrivateUsage]
            "gh", "/tmp", "punt-labs", "punt-kit"
        )
        is True
    )


def test_wait_for_required_checks_falls_back_to_all_checks_when_unprotected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No branch protection means every check is waited on, not just isRequired."""
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "lint",
            "isRequired": False,
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
    ]

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        if cmd[:2] == ["gh", "api"] and cmd[2].endswith("/protection"):
            return _protection_response(protected=False)
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    # Should not raise — the non-required "lint" check is treated as the
    # pass condition because the repo has no branch protection configured.
    _wait_for_required_checks("gh", "/tmp", 42)


def test_wait_for_required_checks_still_requires_only_required_when_protected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: branch protection still narrows to isRequired checks.

    The commit never registers a required check (every poll returns the
    empty-contexts fixture), so the no-checks grace window trips — the fake
    clock crosses it in a handful of iterations instead of the test
    sleeping for ``NO_CHECKS_GRACE`` real seconds.
    """
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        if _is_protection_call(cmd):
            return _protection_response(protected=True)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_no_required_checks_response())
        result.stderr = ""
        return result

    def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    monkeypatch.setattr("punt_kit.release.time.sleep", _noop_sleep)
    monkeypatch.setattr("punt_kit.release.time.time", _make_fake_clock())
    with pytest.raises(ReleaseError, match="No CI checks registered"):
        _wait_for_required_checks("gh", "/tmp", 42)


def test_wait_for_required_checks_warns_once_on_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The unprotected-branch warning prints once, not once per poll.

    Branch protection is resolved once before the loop starts, so this is a
    proof of function structure rather than a distinct behavior.
    """
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "lint",
            "isRequired": False,
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
    ]

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        if _is_protection_call(cmd):
            return _protection_response(protected=False)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    _wait_for_required_checks("gh", "/tmp", 42)

    printed = capsys.readouterr().out
    assert printed.count("No branch protection or ruleset configured") == 1


def test_gh_module_has_no_hardcoded_7200_literal() -> None:
    """gh.py's CI-check deadline must derive from timeouts.CI_WATCH.

    A hardcoded 7200 that happens to equal CI_WATCH today would silently
    drift the moment CI_WATCH changes — this asserts the import, not just
    the current numeric coincidence.
    """
    from punt_kit.phases.shared import gh as gh_mod

    source = inspect.getsource(gh_mod)
    assert "7200" not in source
    assert "CI_WATCH" in source


def test_wait_for_required_checks_deadline_tracks_ci_watch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shrinking ``gh``'s own ``CI_WATCH`` binding actually shortens the wait.

    Proves the deadline is read from the module attribute at call time
    (patchable), not baked in as a literal at import time.
    """
    from punt_kit import release as release_mod
    from punt_kit.phases.shared import gh as gh_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        if _is_protection_call(cmd):
            return _protection_response(protected=False)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        raise AssertionError("should time out before ever polling checks")

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    monkeypatch.setattr(gh_mod, "CI_WATCH", -1)

    with pytest.raises(ReleaseError, match="Timed out waiting for"):
        _wait_for_required_checks("gh", "/tmp", 42)


# --- pkit-plxh: ruleset awareness + no-checks grace window ---


def test_has_ruleset_true_when_rules_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-empty rules array means the branch is ruleset-governed."""
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        return _ruleset_response(governed=True)

    monkeypatch.setattr(release_mod, "_run", fake_run)
    assert (
        release_mod._has_ruleset(  # pyright: ignore[reportPrivateUsage]
            "gh", "/tmp", "punt-labs", "ethos"
        )
        is True
    )


def test_has_ruleset_false_when_rules_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty rules array means no ruleset governs the branch."""
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        return _ruleset_response(governed=False)

    monkeypatch.setattr(release_mod, "_run", fake_run)
    assert (
        release_mod._has_ruleset(  # pyright: ignore[reportPrivateUsage]
            "gh", "/tmp", "punt-labs", "punt-kit"
        )
        is False
    )


def test_has_ruleset_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero exit fails safe to "no ruleset", same direction as a timeout."""
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "gh: API rate limit exceeded"
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    assert (
        release_mod._has_ruleset(  # pyright: ignore[reportPrivateUsage]
            "gh", "/tmp", "punt-labs", "punt-kit"
        )
        is False
    )


def test_wait_for_required_checks_ruleset_governed_no_legacy_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ruleset-governed repo with no legacy branch protection is not warned
    about, and required checks are still honored (the ethos main shape).
    """
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "lint",
            "isRequired": True,
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
        {
            "name": "Claude Code Review",
            "isRequired": False,
            "conclusion": None,
            "status": "IN_PROGRESS",
        },
    ]

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        if _is_protection_call(cmd):
            return _protection_response(protected=False)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=True)
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    # Should not raise — the ruleset governs, so isRequired narrows to
    # "lint" alone, and the in-progress non-required review is ignored.
    _wait_for_required_checks("gh", "/tmp", 42)

    out = capsys.readouterr().out
    assert "No branch protection or ruleset configured" not in out
    assert "Required CI checks passed: lint" in out


def test_wait_for_required_checks_null_rollup_grace_expiry_names_likely_causes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit that never registers a check fails loudly, not after 2 hours.

    Models the ethos #496 shape: a post-release commit carrying [skip ci],
    so ``statusCheckRollup`` stays null on every poll. The fake clock
    crosses ``NO_CHECKS_GRACE`` in a few iterations; the failure names the
    likely causes an operator needs to check.
    """
    from punt_kit import release as release_mod

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        if _is_protection_call(cmd):
            return _protection_response(protected=True)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_null_rollup_response())
        result.stderr = ""
        return result

    def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    monkeypatch.setattr("punt_kit.release.time.sleep", _noop_sleep)
    monkeypatch.setattr("punt_kit.release.time.time", _make_fake_clock())

    with pytest.raises(ReleaseError, match="No CI checks registered") as exc_info:
        _wait_for_required_checks("gh", "/tmp", 42)

    message = str(exc_info.value)
    assert "skip ci" in message
    assert "paths" in message


def test_wait_for_required_checks_governed_no_required_checks_grace_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checks registered but none required must not read as "nothing at all".

    Distinct from the null-rollup case: the commit has a real, non-empty
    ``statusCheckRollup`` — a check genuinely ran — but the repo is governed
    and none of the registered checks are marked ``isRequired``. The
    grace-expiry failure must say so, not repeat the "no CI checks
    registered at all" wording that fits the null-rollup case.
    """
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "Claude Code Review",
            "isRequired": False,
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
    ]

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        if _is_protection_call(cmd):
            return _protection_response(protected=True)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    monkeypatch.setattr("punt_kit.release.time.sleep", _noop_sleep)
    monkeypatch.setattr("punt_kit.release.time.time", _make_fake_clock())

    with pytest.raises(ReleaseError) as exc_info:
        _wait_for_required_checks("gh", "/tmp", 42)

    message = str(exc_info.value)
    assert "registered" in message
    assert "none are required" in message
    assert "no CI checks registered at all" not in message.lower()


def test_wait_for_required_checks_late_arriving_checks_still_proceed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checks that register partway through the grace window still pass.

    Several no-checks polls elapse (well inside ``NO_CHECKS_GRACE``) before
    the check appears — the grace window must not trip on a commit whose
    checks are merely slow to attach, only on one that never gets any.
    """
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "lint",
            "isRequired": True,
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
    ]

    calls = 0

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        nonlocal calls
        if _is_protection_call(cmd):
            return _protection_response(protected=True)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        calls += 1
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        if calls < 3:
            result.stdout = json.dumps(_graphql_null_rollup_response())
        else:
            result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        return result

    def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    monkeypatch.setattr("punt_kit.release.time.sleep", _noop_sleep)
    # A small step keeps every poll well inside NO_CHECKS_GRACE (300s) even
    # across several no-checks iterations, unlike the expiry test's clock.
    monkeypatch.setattr("punt_kit.release.time.time", _make_fake_clock(step=5.0))

    # Should not raise — checks arrive on the third poll, inside the window.
    _wait_for_required_checks("gh", "/tmp", 42)
    assert calls == 3


def test_wait_for_required_checks_stops_promptly_when_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt raised while a worker thread is blocked in the poll loop
    is observed within one iteration, not only after the two-hour deadline.

    This is the direct regression guard for pkit-d7mz: without checking
    ``interrupted`` inside the loop, a worker thread polling here has no way
    to learn that the main thread's signal handler fired — only the main
    thread receives SIGINT — so it would keep polling for up to two hours,
    blocking ``ThreadPoolExecutor.__exit__``'s join for the same span.
    """
    from punt_kit import release as release_mod

    check_nodes: list[dict[str, object]] = [
        {
            "name": "lint",
            "isRequired": True,
            "conclusion": "SUCCESS",
            "status": "COMPLETED",
        },
    ]

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        if _is_protection_call(cmd):
            return _protection_response(protected=True)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    release_mod._interrupted.set()  # pyright: ignore[reportPrivateUsage]
    try:
        with pytest.raises(ReleaseError, match="Interrupted while waiting"):
            _wait_for_required_checks("gh", "/tmp", 42)
    finally:
        release_mod._interrupted.clear()  # pyright: ignore[reportPrivateUsage]


# --- _reset_propagation_siblings ---


def test_reset_propagation_siblings_resets_propagation_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resets siblings on propagate/v* branches to main."""
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)

    checkout_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        if cmd[1:3] == ["branch", "--show-current"]:
            result.stdout = "propagate/v1.0.0-punt-kit-claude-plugins\n"
        elif len(cmd) > 1 and cmd[1] == "checkout":
            checkout_calls.append(list(cmd))
            result.stdout = ""
        else:
            result.stdout = ""
        result.stderr = ""
        return result

    def fake_resolve(r: object, name: str) -> object:  # noqa: ARG001
        return tmp_path / name

    monkeypatch.setattr(release_mod, "_resolve_sibling", fake_resolve)
    monkeypatch.setattr(release_mod, "_run", fake_run)
    _reset_propagation_siblings(info)
    assert any("main" in c for c in checkout_calls)


def test_reset_propagation_siblings_skips_feature_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Does not touch siblings on non-propagation branches."""
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)

    checkout_calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        if cmd[1:3] == ["branch", "--show-current"]:
            result.stdout = "fix/some-other-work\n"
        elif len(cmd) > 1 and cmd[1] == "checkout":
            checkout_calls.append(list(cmd))
        result.stderr = ""
        return result

    def fake_resolve(r: object, name: str) -> object:  # noqa: ARG001
        return tmp_path / name

    monkeypatch.setattr(release_mod, "_resolve_sibling", fake_resolve)
    monkeypatch.setattr(release_mod, "_run", fake_run)
    _reset_propagation_siblings(info)
    assert not checkout_calls  # Should not have attempted any checkout


def test_reset_propagation_siblings_continues_on_error_when_fail_on_error_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With fail_on_error=False, a checkout failure does not abort remaining ones."""
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)

    siblings_seen: list[str] = []
    call_num = 0

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        nonlocal call_num
        call_num += 1
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        if cmd[1:3] == ["branch", "--show-current"]:
            result.stdout = "propagate/v1.0.0\n"
        elif len(cmd) > 1 and cmd[1] == "checkout":
            # Fail checkout for first sibling, succeed for rest
            cwd = str(kwargs.get("cwd", ""))
            siblings_seen.append(cwd)
            if len(siblings_seen) == 1:
                result.returncode = 1
                result.stderr = "checkout failed"
            else:
                result.stdout = ""
        else:
            result.stdout = ""
        return result

    sibling_names = ["punt-kit", "claude-plugins", ".github", "public-website"]

    def fake_resolve(r: object, name: str) -> object:  # noqa: ARG001
        return tmp_path / name if name in sibling_names else None

    monkeypatch.setattr(release_mod, "_resolve_sibling", fake_resolve)
    monkeypatch.setattr(release_mod, "_run", fake_run)

    # Should not raise even though first checkout fails
    _reset_propagation_siblings(info, fail_on_error=False)
    # At least 2 checkout attempts: one failed, one succeeded
    assert len(siblings_seen) >= 2


def test_reset_propagation_siblings_fails_on_error_when_fail_on_error_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With fail_on_error=True (default), a checkout failure raises ReleaseError."""
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        if cmd[1:3] == ["branch", "--show-current"]:
            result.stdout = "propagate/v1.0.0\n"
        elif len(cmd) > 1 and cmd[1] == "checkout":
            result.returncode = 1
            result.stderr = "checkout failed"
            result.stdout = ""
        else:
            result.stdout = ""
        return result

    def fake_resolve(r: object, name: str) -> object:  # noqa: ARG001
        return tmp_path / name

    monkeypatch.setattr(release_mod, "_resolve_sibling", fake_resolve)
    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError):
        _reset_propagation_siblings(info, fail_on_error=True)


def _make_dirty_sibling(parent: Path, name: str, tracked_files: dict[str, str]) -> Path:
    """Create a sibling repo committed with ``tracked_files`` at HEAD.

    Returns the sibling path. Caller mutates any tracked file after the
    initial commit to produce the dirty-on-main state phase 10's mid-write
    interruption leaves behind.
    """
    sib = parent / name
    sib.mkdir(parents=True)
    d = str(sib)
    _git(["init", "-b", "main"], cwd=d)
    _git(["config", "user.email", "test@test.com"], cwd=d)
    _git(["config", "user.name", "Test"], cwd=d)
    for rel, content in tracked_files.items():
        target = sib / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "seed"], cwd=d)
    return sib


def test_reset_propagation_siblings_restores_dirty_owned_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sibling on main with only propagation-owned file dirty is reconciled.

    This is the v0.14.0 residue: phase 10 wrote projects.json, then the
    subsequent `git checkout -b propagate/...` timed out. The sibling
    was left on main with the write on disk, and the guarded retry
    refused to run. _reset_propagation_siblings must restore that file
    so --resume-from propagate can retry the same idempotent write.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)

    original = '[{"id": "punt-kit", "version": "0.1.0"}]\n'
    sib = _make_dirty_sibling(
        tmp_path, "public-website", {"src/data/projects.json": original}
    )
    # Simulate the mid-phase-10 interruption: the propagation write landed
    # before _sibling_pr_merge's checkout hung.
    (sib / "src" / "data" / "projects.json").write_text(
        '[{"id": "punt-kit", "version": "0.2.0"}]\n'
    )

    def fake_resolve(_root: object, name: str) -> Path | None:
        return sib if name == "public-website" else None

    monkeypatch.setattr(release_mod, "_resolve_sibling", fake_resolve)

    _reset_propagation_siblings(info)

    restored = (sib / "src" / "data" / "projects.json").read_text()
    assert restored == original, "propagation-owned file should be restored to HEAD"

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(sib),
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout.strip() == "", "sibling should be clean after reset"


def test_reset_propagation_siblings_leaves_unrelated_dirty_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Modifications outside _PROPAGATION_OWNED_PATHS survive the reset.

    The guarantee is scoped to paths, not to intent: a change to a file
    the release owns IS discarded, including one an operator made by
    hand, because the reset cannot tell the two apart. What it can
    promise is that nothing outside the owned set is touched — a sibling
    with only unrelated modifications is left entirely alone for the
    existing _validate_sibling guard to trip on, as it does today.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)

    original_unrelated = "operator was here\n"
    sib = _make_dirty_sibling(
        tmp_path,
        "public-website",
        {
            "src/data/projects.json": '[{"id": "punt-kit", "version": "0.1.0"}]\n',
            "docs/notes.md": original_unrelated,
        },
    )
    # Operator work — not owned by punt release.
    (sib / "docs" / "notes.md").write_text("operator edited this\n")

    def fake_resolve(_root: object, name: str) -> Path | None:
        return sib if name == "public-website" else None

    monkeypatch.setattr(release_mod, "_resolve_sibling", fake_resolve)

    _reset_propagation_siblings(info)

    assert (sib / "docs" / "notes.md").read_text() == "operator edited this\n"
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(sib),
        capture_output=True,
        text=True,
        check=True,
    )
    # Modification survives — the guard is expected to trip on it next.
    assert "docs/notes.md" in status.stdout


def test_reset_propagation_siblings_mixed_dirt_preserves_unrelated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When both owned and unrelated files are dirty, unrelated survives.

    This is the sharp edge: an interrupted propagation left the owned
    file dirty AND the operator has a modification of their own in the
    same sibling. The reset must not destroy the operator's file, even
    at the cost of leaving the owned file dirty for the guard to trip
    on — losing operator work is unrecoverable, letting the guard fail
    once is not.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)

    owned_original = '[{"id": "punt-kit", "version": "0.1.0"}]\n'
    unrelated_original = "operator was here\n"
    sib = _make_dirty_sibling(
        tmp_path,
        "public-website",
        {
            "src/data/projects.json": owned_original,
            "docs/notes.md": unrelated_original,
        },
    )
    (sib / "src" / "data" / "projects.json").write_text(
        '[{"id": "punt-kit", "version": "0.2.0"}]\n'
    )
    (sib / "docs" / "notes.md").write_text("operator edited this\n")

    def fake_resolve(_root: object, name: str) -> Path | None:
        return sib if name == "public-website" else None

    monkeypatch.setattr(release_mod, "_resolve_sibling", fake_resolve)

    _reset_propagation_siblings(info)

    # The one that MUST survive.
    assert (sib / "docs" / "notes.md").read_text() == "operator edited this\n"


# --- _select_existing_pr / _pr_merge: stale same-named PRs ---

_LOCAL_HEAD = "a" * 40
_STALE_HEAD = "b" * 40
_MERGE_OID = "c" * 40


def test_select_existing_pr_prefers_open() -> None:
    """An OPEN PR is always the current release."""
    prs: list[dict[str, object]] = [
        {"number": 5, "state": "MERGED", "headRefOid": _LOCAL_HEAD},
        {"number": 7, "state": "OPEN", "headRefOid": _LOCAL_HEAD},
    ]
    assert _select_existing_pr(prs, _LOCAL_HEAD) == (7, False)


def test_select_existing_pr_ignores_closed() -> None:
    """A CLOSED PR is never reused — its CI is dead."""
    prs: list[dict[str, object]] = [
        {"number": 7, "state": "CLOSED", "headRefOid": _LOCAL_HEAD},
    ]
    assert _select_existing_pr(prs, _LOCAL_HEAD) == (None, False)


def test_select_existing_pr_ignores_stale_merged() -> None:
    """A MERGED PR at a different head is a stale earlier attempt."""
    prs: list[dict[str, object]] = [
        {"number": 5, "state": "MERGED", "headRefOid": _STALE_HEAD},
    ]
    assert _select_existing_pr(prs, _LOCAL_HEAD) == (None, False)


def test_select_existing_pr_accepts_matching_merged() -> None:
    """A MERGED PR at the local branch head is the completed release."""
    prs: list[dict[str, object]] = [
        {"number": 5, "state": "MERGED", "headRefOid": _LOCAL_HEAD},
    ]
    assert _select_existing_pr(prs, _LOCAL_HEAD) == (5, True)


def test_select_existing_pr_empty() -> None:
    """No PRs means create a fresh one."""
    assert _select_existing_pr([], _LOCAL_HEAD) == (None, False)


def _fake_gh_run(
    pr_list: list[dict[str, object]],
    *,
    merge_rc: int = 0,
    merge_stderr: str = "",
    view_states: list[str] | None = None,
) -> tuple[object, list[list[str]]]:
    """Build a fake ``_run`` covering the git/gh commands _pr_merge issues.

    ``view_states`` is consumed one state per ``gh pr view`` call; the last
    entry repeats once exhausted.
    """
    issued: list[list[str]] = []
    states = list(view_states or ["OPEN"])

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        issued.append(list(cmd))
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        if cmd[:2] == ["git", "rev-parse"]:
            r.stdout = "abc1234\n" if "--short" in cmd else _LOCAL_HEAD + "\n"
        elif cmd[:3] == ["gh", "pr", "list"]:
            r.stdout = json.dumps(pr_list)
        elif cmd[:3] == ["gh", "pr", "create"]:
            r.stdout = "https://github.com/punt-labs/proj/pull/99\n"
        elif cmd[:3] == ["gh", "pr", "view"] and "mergeCommit" in cmd:
            # `--jq .mergeCommit.oid` — raw oid, no JSON envelope.
            r.stdout = f"{_MERGE_OID}\n"
        elif cmd[:3] == ["gh", "pr", "view"]:
            state = states.pop(0) if len(states) > 1 else states[0]
            r.stdout = json.dumps({"state": state})
        elif cmd[:3] == ["gh", "pr", "merge"]:
            r.returncode = merge_rc
            r.stderr = merge_stderr
        return r

    return fake_run, issued


def _patch_pr_merge_env(
    monkeypatch: pytest.MonkeyPatch,
    fake_run: object,
    waited_prs: list[int],
) -> None:
    """Wire _pr_merge to the fake gh environment."""
    import shutil

    from punt_kit import release as release_mod

    def fake_which(_name: str) -> str:
        return "gh"

    def fake_wait(_gh: str, _cwd: str, pr: int) -> None:
        waited_prs.append(pr)

    def fake_resolve_threads(_gh: str, _cwd: str, _pr: int) -> None:
        return None

    monkeypatch.setattr(shutil, "which", fake_which)
    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_wait_for_required_checks", fake_wait)
    monkeypatch.setattr(release_mod, "_resolve_pr_threads", fake_resolve_threads)


def test_pr_merge_ignores_closed_pr_creates_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CLOSED same-named PR is not resumed; a fresh PR is created.

    Resuming a closed PR waits forever on CI that will never run again.
    """
    fake_run, issued = _fake_gh_run(
        [{"number": 7, "state": "CLOSED", "headRefOid": _LOCAL_HEAD}],
        view_states=["MERGED"],
    )
    waited: list[int] = []
    _patch_pr_merge_env(monkeypatch, fake_run, waited)

    _pr_merge(cwd=tmp_path, branch="release/v0.2.0", title="chore: release v0.2.0")

    created = [c for c in issued if c[:3] == ["gh", "pr", "create"]]
    assert created, "expected a fresh PR instead of reusing the closed one"
    assert waited == [99]


def test_pr_merge_stale_merged_pr_not_treated_as_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A MERGED PR at a different head does not short-circuit the release.

    Treating it as current skips the version bump and tags an unbumped
    commit (build/tag version mismatch).
    """
    fake_run, issued = _fake_gh_run(
        [{"number": 5, "state": "MERGED", "headRefOid": _STALE_HEAD}],
        view_states=["MERGED"],
    )
    waited: list[int] = []
    _patch_pr_merge_env(monkeypatch, fake_run, waited)

    _pr_merge(cwd=tmp_path, branch="release/v0.2.0", title="chore: release v0.2.0")

    created = [c for c in issued if c[:3] == ["gh", "pr", "create"]]
    assert created, "expected a fresh PR instead of reusing the stale merged one"
    assert waited == [99]


def test_pr_merge_matching_merged_pr_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A MERGED PR at the local branch head is the completed release."""
    fake_run, issued = _fake_gh_run(
        [{"number": 5, "state": "MERGED", "headRefOid": _LOCAL_HEAD}],
    )
    waited: list[int] = []
    _patch_pr_merge_env(monkeypatch, fake_run, waited)

    sha = _pr_merge(
        cwd=tmp_path, branch="release/v0.2.0", title="chore: release v0.2.0"
    )

    assert sha == _MERGE_OID
    created = [c for c in issued if c[:3] == ["gh", "pr", "create"]]
    assert not created
    assert waited == []


def test_pr_merge_sync_local_main_diagnoses_checkout_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing `git checkout main` while fast-forwarding local main after
    an already-merged PR must diagnose, not leak a raw CalledProcessError.

    One of three near-identical inline blocks `PrMerger.merge` hand-rolled
    with an unqualified check=True default, missed by round 1's sweep and
    now centralized into `_sync_local_main` (pkit-f85t.7 round 2)."""
    base_fake_run, _issued = _fake_gh_run(
        [{"number": 5, "state": "MERGED", "headRefOid": _LOCAL_HEAD}],
    )
    base_run = cast("Callable[..., object]", base_fake_run)

    def fake_run(cmd: list[str], **kwargs: object) -> object:
        if cmd == ["git", "checkout", "main"]:
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            r.stderr = "error: pre-checkout hook rejected"
            return r
        return base_run(cmd, **kwargs)

    waited: list[int] = []
    _patch_pr_merge_env(monkeypatch, fake_run, waited)

    with pytest.raises(ReleaseError, match="git checkout main failed"):
        _pr_merge(cwd=tmp_path, branch="release/v0.2.0", title="chore: release v0.2.0")


def test_pr_merge_sync_local_main_diagnoses_pull_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing `git pull --ff-only` while fast-forwarding local main — a
    network call, structurally identical in risk to `git fetch origin`
    (Phase 1) and `GitWorkspace.push` (Phase 5), both already diagnosed —
    must diagnose too (pkit-f85t.7 round 2)."""
    base_fake_run, _issued = _fake_gh_run(
        [{"number": 5, "state": "MERGED", "headRefOid": _LOCAL_HEAD}],
    )
    base_run = cast("Callable[..., object]", base_fake_run)

    def fake_run(cmd: list[str], **kwargs: object) -> object:
        if cmd == ["git", "pull", "--ff-only"]:
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            r.stderr = "fatal: unable to access origin"
            return r
        return base_run(cmd, **kwargs)

    waited: list[int] = []
    _patch_pr_merge_env(monkeypatch, fake_run, waited)

    with pytest.raises(ReleaseError, match="git pull --ff-only failed"):
        _pr_merge(cwd=tmp_path, branch="release/v0.2.0", title="chore: release v0.2.0")


def test_pr_merge_branch_deletion_404_is_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed post-merge branch deletion does not fail a merged PR.

    Repos with "automatically delete head branches" remove the branch
    during the merge; gh's own DELETE then gets a 404 and exits non-zero
    even though the merge succeeded.
    """
    fake_run, issued = _fake_gh_run(
        [{"number": 42, "state": "OPEN", "headRefOid": _LOCAL_HEAD}],
        merge_rc=1,
        merge_stderr=(
            "failed to delete remote branch release/v0.2.0: "
            "HTTP 404: Reference does not exist"
        ),
        view_states=["OPEN", "MERGED"],
    )
    waited: list[int] = []
    _patch_pr_merge_env(monkeypatch, fake_run, waited)

    sha = _pr_merge(
        cwd=tmp_path, branch="release/v0.2.0", title="chore: release v0.2.0"
    )

    assert sha == _MERGE_OID
    merges = [c for c in issued if c[:3] == ["gh", "pr", "merge"]]
    assert len(merges) == 1, "merge must not be retried once the PR is MERGED"


def test_pr_merge_real_merge_failure_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A merge failure on a PR that is genuinely not merged still fails."""
    fake_run, _issued = _fake_gh_run(
        [{"number": 42, "state": "OPEN", "headRefOid": _LOCAL_HEAD}],
        merge_rc=1,
        merge_stderr="GraphQL: Merge conflict detected",
        view_states=["OPEN"],
    )
    waited: list[int] = []
    _patch_pr_merge_env(monkeypatch, fake_run, waited)

    with pytest.raises(ReleaseError):
        _pr_merge(cwd=tmp_path, branch="release/v0.2.0", title="chore: release v0.2.0")


# --- PrMerger.merge: squash-merge retry loop past attempt 1 ---
#
# The loop's ``time.sleep(wait)`` call lives in pr_merge.py, which shares
# the process's one ``time`` module object with release.py (only one
# ``import time`` per module, no ``from time import sleep`` anywhere in
# either) — so patching ``punt_kit.phases.shared.pr_merge.time.sleep``
# reaches the same attribute every other module's ``time.sleep(...)`` call
# reads, with no real wall-clock spent on any of these tests.


def _fake_which_gh(_name: str) -> str:
    """Patched in for ``shutil.which`` so ``PrMerger.merge``'s own
    ``shutil.which("gh")`` lookup resolves without a real ``gh`` binary on
    ``PATH`` — matches ``tests/test_gh_fixture_contracts.py``'s convention.
    """
    return "gh"


# --- Phase 7: github release ---


def test_phase7_github_release_create_failure_diagnoses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `gh release create` failure (network/permission) must diagnose loudly.

    Phase 7 had no isolated failure-path test at all before this (matrix
    row 29).
    """
    from punt_kit.phases.phase07_github_release import Phase7GithubRelease

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which_gh)

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["gh", "release", "view", "v0.2.0"],
                response=CompletedProcessSpec(returncode=1),
            ),
            FaultRule(
                match=["gh", "release", "create", "v0.2.0"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="HTTP 403: Forbidden"
                ),
            ),
        ],
    )

    with pytest.raises(ReleaseError, match="Failed to create release"):
        Phase7GithubRelease(info, "0.2.0", dry_run=False, ops=ops).run()


# --- Phase 8: verify PyPI ---


def test_phase8_verify_pypi_install_timeout_mid_retry_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hang (not just a failure) at any retry attempt must not be
    swallowed — including an attempt *after* the loop has already retried
    once, not only the very first call.

    Phase 8's 10-attempt retry loop (`uv tool install --force --refresh`)
    only special-cases a non-zero exit; nothing forced a genuine
    `TimeoutExpired` at this call site before this test (matrix row 31,
    design doc defect #6) — distinct from Phase 11's own, differently-
    shaped PyPI resolve check. The loop's own `time.sleep(30)` between
    attempts is real wall-clock the harness has no seam for at the
    `ops.run` level, so `phase08_verify_pypi`'s own `time.sleep` is
    patched to a no-op here — the retry bookkeeping and the second
    attempt still run for real, just without the real 30s wait between
    them (qodo round-1 review: the single-attempt version of this test
    could not distinguish "nothing catches TimeoutExpired" from "nothing
    catches TimeoutExpired on the first attempt specifically").
    """
    from punt_kit.phases.phase08_verify_pypi import Phase8VerifyPypi

    def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("punt_kit.phases.phase08_verify_pypi.time.sleep", _noop_sleep)

    root = _make_release_project(tmp_path)
    info = detect(root)

    install_cmd = ["uv", "tool", "install", "--force", "--refresh"]
    first_attempt = FaultRule(
        match=install_cmd,
        response=CompletedProcessSpec(returncode=1, stderr="index unreachable"),
    )
    second_attempt = FaultRule(
        match=install_cmd,
        raises=subprocess.TimeoutExpired(install_cmd, 600),
    )
    ops = FaultInjectingOps(real_run=_run, rules=[first_attempt, second_attempt])

    with pytest.raises(subprocess.TimeoutExpired):
        Phase8VerifyPypi(info, "0.1.0", dry_run=False, ops=ops).run()

    # Both rules were actually consumed — the failure happened on attempt
    # 2, not attempt 1 (a regression that made the loop stop retrying
    # after a non-zero exit would leave second_attempt unconsumed and the
    # TimeoutExpired assertion above would still pass for the wrong
    # reason).
    assert first_attempt._consumed == 1  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert second_attempt._consumed == 1  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_phase8_verify_pypi_editable_restore_failure_diagnoses(
    tmp_path: Path,
) -> None:
    """A failing `uv tool install --force --editable .` (restoring the dev
    install after the PyPI verify succeeds) must diagnose, not leak a raw
    CalledProcessError — same external-tool risk class as the install
    retry loop above, missed in earlier sweep passes (pkit-f85t.7 round 2).
    """
    from punt_kit.phases.phase08_verify_pypi import Phase8VerifyPypi

    root = _make_release_project(tmp_path)
    info = detect(root)

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["uv", "tool", "install", "--force", "--refresh"],
                response=CompletedProcessSpec(returncode=0),
            ),
            FaultRule(
                match=["uv", "tool", "install", "--force", "--editable", "."],
                response=CompletedProcessSpec(
                    returncode=1, stderr="error: no pyproject.toml found"
                ),
            ),
        ],
    )

    with pytest.raises(ReleaseError, match="uv tool install --editable . failed"):
        Phase8VerifyPypi(info, "0.1.0", dry_run=False, ops=ops).run()


def _merge_env(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, pr_number: int = 42
) -> tuple[FaultInjectingOps, str]:
    """A real git repo on a release branch plus a scripted gh double.

    Wires the ``gh pr list``/``gh pr create``/``gh pr view`` calls every
    ``PrMerger.merge`` invocation needs before it ever reaches the
    squash-merge loop, leaving the caller to add only the merge-loop
    ``FaultRule`` its scenario needs. Also patches ``shutil.which`` so
    these scenarios run on a machine with no real ``gh`` binary installed.
    """
    monkeypatch.setattr("shutil.which", _fake_which_gh)
    branch = "release/v1.0.0"
    _init_git_repo(root)
    # PrMerger.merge's post-merge step runs a bare `git pull --ff-only`
    # (no explicit remote/branch), which needs main's upstream configured —
    # unlike Phase5Tag's `ensure_on_main`, which always names `origin main`
    # explicitly and needs no tracking branch at all.
    _git(["push", "-u", "origin", "main"], cwd=str(root))
    _git(["checkout", "-b", branch], cwd=str(root))
    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["gh", "pr", "list"], response=CompletedProcessSpec(stdout="[]")
            ),
            FaultRule(
                match=["gh", "pr", "create"],
                response=CompletedProcessSpec(
                    stdout=f"https://github.com/punt-labs/proj/pull/{pr_number}\n"
                ),
            ),
            FaultRule(
                match=["gh", "pr", "view", str(pr_number), "--json", "state"],
                times=None,
                response=CompletedProcessSpec(stdout=json.dumps({"state": "OPEN"})),
            ),
            FaultRule(
                match=[
                    "gh",
                    "pr",
                    "view",
                    str(pr_number),
                    "--json",
                    "mergeCommit",
                    "--jq",
                    ".mergeCommit.oid",
                ],
                times=None,
                response=CompletedProcessSpec(stdout=f"{_MERGE_OID}\n"),
            ),
        ],
    )
    return ops, branch


def test_pr_merge_retries_transient_block_and_succeeds_before_exhaustion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The squash-merge retry loop must actually retry, not stop at attempt 1.

    Attempts 1 and 2 are blocked by a transient policy check; attempt 3
    succeeds. Before this test, nothing drove ``merge_attempt`` past 0.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger

    def _noop_sleep(_seconds: float) -> None:
        return None

    def _noop_wait_for_checks(_gh: str, _cwd: str, _pr: int) -> None:
        return None

    monkeypatch.setattr("punt_kit.phases.shared.pr_merge.time.sleep", _noop_sleep)

    root = tmp_path / "proj"
    root.mkdir()
    ops, branch = _merge_env(root, monkeypatch)
    transient = CompletedProcessSpec(
        returncode=1, stderr="required status check has not passed"
    )
    ops._rules.append(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
        FaultRule(
            match=["gh", "pr", "merge", "42", "--squash", "--delete-branch"],
            responses=[transient, transient, CompletedProcessSpec()],
        )
    )
    resolve_calls: list[int] = []

    def _record_resolve_threads(_gh: str, _cwd: str, pr: int) -> None:
        resolve_calls.append(pr)

    sha = PrMerger(ops=ops).merge(
        cwd=root,
        branch=branch,
        title="chore: release v1.0.0",
        wait_for_checks=_noop_wait_for_checks,
        resolve_threads=_record_resolve_threads,
    )

    assert sha
    # Once before the merge loop, then once per retry (attempts 1 and 2).
    assert resolve_calls == [42, 42, 42]


def test_pr_merge_retry_exhausts_all_six_attempts_then_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A merge that stays transiently blocked for all 6 attempts really fails.

    Regression guard for the exhaustion path: nothing before this test
    proved the loop gives up after attempt 6 instead of retrying forever
    or silently succeeding.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger

    def _noop_sleep(_seconds: float) -> None:
        return None

    def _noop_wait_for_checks(_gh: str, _cwd: str, _pr: int) -> None:
        return None

    def _noop_resolve_threads(_gh: str, _cwd: str, _pr: int) -> None:
        return None

    monkeypatch.setattr("punt_kit.phases.shared.pr_merge.time.sleep", _noop_sleep)

    root = tmp_path / "proj"
    root.mkdir()
    ops, branch = _merge_env(root, monkeypatch)
    merge_rule = FaultRule(
        match=["gh", "pr", "merge", "42", "--squash", "--delete-branch"],
        response=CompletedProcessSpec(
            returncode=1, stderr="required status check has not passed"
        ),
        times=6,
    )
    ops._rules.append(merge_rule)  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001

    with pytest.raises(ReleaseError, match="Failed to merge PR #42"):
        PrMerger(ops=ops).merge(
            cwd=root,
            branch=branch,
            title="chore: release v1.0.0",
            wait_for_checks=_noop_wait_for_checks,
            resolve_threads=_noop_resolve_threads,
        )

    # Pin the count directly — with only `times=6` + the fixed-transient
    # response, a future off-by-one in the `merge_attempt < 5` guard that
    # gave up after 5 or tried a 7th time would raise the same
    # ReleaseError/message either way (5 attempts: exhausted at the
    # `is_transient` check without a 6th `time.sleep`; 7 attempts: the
    # rule's own exhaustion makes call 7 an unmatched `gh` command, a
    # deny-by-default `AssertionError` instead of `ReleaseError` — so an
    # *unbounded* runaway is already caught, but an off-by-one that stops
    # one attempt early would not be, without this explicit count).
    assert merge_rule._consumed == 6  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001


def test_pr_merge_retry_swallows_a_failed_thread_re_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A best-effort re-resolve failure mid-retry does not abort the retry.

    Exercises the ``except (ReleaseError, SystemExit,
    subprocess.CalledProcessError)`` swallow: attempt 1 is transiently
    blocked, the subsequent re-resolve raises, and the loop must still
    proceed to attempt 2 instead of propagating that exception.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger

    def _noop_sleep(_seconds: float) -> None:
        return None

    def _noop_wait_for_checks(_gh: str, _cwd: str, _pr: int) -> None:
        return None

    monkeypatch.setattr("punt_kit.phases.shared.pr_merge.time.sleep", _noop_sleep)

    root = tmp_path / "proj"
    root.mkdir()
    ops, branch = _merge_env(root, monkeypatch)
    ops._rules.append(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
        FaultRule(
            match=["gh", "pr", "merge", "42", "--squash", "--delete-branch"],
            responses=[
                CompletedProcessSpec(
                    returncode=1, stderr="required status check has not passed"
                ),
                CompletedProcessSpec(),
            ],
        )
    )
    resolve_calls = 0

    def flaky_resolve_threads(_gh: str, _cwd: str, _pr: int) -> None:
        nonlocal resolve_calls
        resolve_calls += 1
        if resolve_calls == 2:  # the retry's re-resolve, not the first call
            raise ReleaseError("threads API is down")

    sha = PrMerger(ops=ops).merge(
        cwd=root,
        branch=branch,
        title="chore: release v1.0.0",
        wait_for_checks=_noop_wait_for_checks,
        resolve_threads=flaky_resolve_threads,
    )

    assert sha
    printed = capsys.readouterr().out
    assert "Could not re-resolve threads, proceeding with retry" in printed


# --- PrMerger.merge: return value survives a concurrent commit ---


def test_pr_merge_returns_merge_commit_oid_not_a_later_concurrent_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``merge()`` must return the PR's authoritative mergeCommit oid from
    GitHub, not local main HEAD after ``_sync_local_main``'s pull.

    If another commit lands on main between the squash-merge and that
    pull — a concurrent release, a hotfix — local HEAD becomes the LATER
    commit. The old `git rev-parse --short HEAD` return would have handed
    that back silently instead of the actual merge commit; Phase 5 would
    then tag the wrong commit even with the SHA-threading fix in place,
    since it trusts whatever ``merge()`` returns.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger

    monkeypatch.setattr("shutil.which", _fake_which_gh)
    root = tmp_path / "proj"
    root.mkdir()
    branch = "release/v1.0.0"
    _init_git_repo(root)
    _git(["push", "-u", "origin", "main"], cwd=str(root))
    _git(["checkout", "-b", branch], cwd=str(root))
    (root / "release.txt").write_text("v1.0.0\n")
    _git(["add", "."], cwd=str(root))
    _git(["commit", "-m", "bump version"], cwd=str(root))

    merge_sha: dict[str, str] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["gh", "pr", "list"]:
            return CompletedProcessSpec(stdout="[]").to_completed_process(cmd)
        if cmd[:3] == ["gh", "pr", "create"]:
            return CompletedProcessSpec(
                stdout="https://github.com/punt-labs/proj/pull/42\n"
            ).to_completed_process(cmd)
        if cmd[:3] == ["gh", "pr", "view"] and "mergeCommit" in cmd:
            return CompletedProcessSpec(
                stdout=f"{merge_sha['oid']}\n"
            ).to_completed_process(cmd)
        if cmd[:3] == ["gh", "pr", "view"]:
            return CompletedProcessSpec(
                stdout=json.dumps({"state": "OPEN"})
            ).to_completed_process(cmd)
        if cmd[:3] == ["gh", "pr", "merge"]:
            # The real squash-merge GitHub performs.
            _git(["checkout", "main"], cwd=str(root))
            _git(["merge", "--squash", branch], cwd=str(root))
            _git(["commit", "-m", "chore: release v1.0.0"], cwd=str(root))
            merge_sha["oid"] = _git_out(["rev-parse", "HEAD"], cwd=str(root))
            # Then, before this process's own sync-back pull runs, a
            # CONCURRENT commit lands on main too — a second release or a
            # hotfix landing independently of this PR.
            _git(["commit", "--allow-empty", "-m", "concurrent release"], cwd=str(root))
            return CompletedProcessSpec().to_completed_process(cmd)
        return cast("Callable[..., subprocess.CompletedProcess[str]]", _run)(
            cmd, **kwargs
        )

    def _noop_wait_for_checks(_gh: str, _cwd: str, _pr: int) -> None:
        return None

    def _noop_resolve_threads(_gh: str, _cwd: str, _pr: int) -> None:
        return None

    ops = FaultInjectingOps(
        real_run=fake_run,
        rules=[],
        passthrough=[
            ("gh", "pr", "list"),
            ("gh", "pr", "create"),
            ("gh", "pr", "view"),
            ("gh", "pr", "merge"),
        ],
    )

    sha = PrMerger(ops=ops).merge(
        cwd=root,
        branch=branch,
        title="chore: release v1.0.0",
        wait_for_checks=_noop_wait_for_checks,
        resolve_threads=_noop_resolve_threads,
    )

    concurrent_head = _git_out(["rev-parse", "main"], cwd=str(root))
    assert merge_sha["oid"] != concurrent_head, (
        "test setup bug — the concurrent commit must actually advance main "
        "past the merge commit for this regression to mean anything"
    )
    assert sha == merge_sha["oid"]


# --- PrMerger.merge_in_sibling: secondary cleanup failure -> SkipRecorder ---


def test_merge_in_sibling_secondary_cleanup_failure_reaches_skip_recorder(
    tmp_path: Path,
) -> None:
    """A primary merge failure whose own cleanup also fails must recap both.

    Before this fix, a failed "return sibling to main" checkout inside the
    ``finally`` block only reached ``ops.info`` — invisible in the
    end-of-run "Manual action required" recap that ``SkipRecorder`` drives.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger
    from punt_kit.phases.shared.siblings import SkipRecorder

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _init_git_repo(sibling)
    (sibling / ".gitkeep").write_text("changed\n")

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "checkout", "main"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="local changes would be overwritten"
                ),
            ),
        ],
    )
    skips = SkipRecorder(ops=ops)

    def failing_merge(**_kwargs: object) -> str:
        raise ReleaseError("required checks never passed")

    merger = PrMerger(ops=ops, skips=skips)
    with pytest.raises(ReleaseError, match="required checks never passed"):
        merger.merge_in_sibling(
            sibling,
            "propagate/v1.0.0",
            [".gitkeep"],
            "chore: propagate v1.0.0",
            "install-all-github",
            dry_run=False,
            merge=failing_merge,
        )

    (notice,) = skips.drain()
    assert "required checks never passed" in notice
    assert "local changes would be overwritten" in notice


def test_merge_in_sibling_solo_cleanup_failure_still_only_infos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No SkipRecorder threaded through (Phase 4's own merge) keeps the
    original info-only behavior — the routing is additive, not a
    replacement for every caller.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _init_git_repo(sibling)
    (sibling / ".gitkeep").write_text("changed\n")

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "checkout", "main"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="local changes would be overwritten"
                ),
            ),
        ],
    )

    def failing_merge(**_kwargs: object) -> str:
        raise ReleaseError("required checks never passed")

    merger = PrMerger(ops=ops)  # no skips= — the _pr_merge/Phase 4 shape
    with pytest.raises(ReleaseError, match="required checks never passed"):
        merger.merge_in_sibling(
            sibling,
            "propagate/v1.0.0",
            [".gitkeep"],
            "chore: propagate v1.0.0",
            "install-all-github",
            dry_run=False,
            merge=failing_merge,
        )

    printed = capsys.readouterr().out
    assert "Warning: could not return sibling install-all-github to main" in printed


def test_merge_in_sibling_cleanup_timeout_does_not_mask_the_primary_failure(
    tmp_path: Path,
) -> None:
    """A hung cleanup checkout must not replace the primary merge failure.

    Regression test for a review finding on pkit-f85t.6: the cleanup
    checkout's ``ops.run(..., check=False)`` can still raise
    ``TimeoutExpired`` (a hung git hook) even though ``check=False``
    suppresses non-zero-exit errors. An uncaught ``TimeoutExpired`` inside
    the ``finally`` block would replace the propagating primary exception
    instead of merely accompanying it in the recap.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger
    from punt_kit.phases.shared.siblings import SkipRecorder

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _init_git_repo(sibling)
    (sibling / ".gitkeep").write_text("changed\n")

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "checkout", "main"],
                raises=subprocess.TimeoutExpired(
                    cmd=["git", "checkout", "main"], timeout=600
                ),
            ),
        ],
    )
    skips = SkipRecorder(ops=ops)

    def failing_merge(**_kwargs: object) -> str:
        raise ReleaseError("required checks never passed")

    merger = PrMerger(ops=ops, skips=skips)
    # The ORIGINAL exception must propagate, not the cleanup TimeoutExpired.
    with pytest.raises(ReleaseError, match="required checks never passed"):
        merger.merge_in_sibling(
            sibling,
            "propagate/v1.0.0",
            [".gitkeep"],
            "chore: propagate v1.0.0",
            "install-all-github",
            dry_run=False,
            merge=failing_merge,
        )

    (notice,) = skips.drain()
    assert "required checks never passed" in notice
    assert "checkout" in notice


def test_merge_in_sibling_cleanup_timeout_alone_still_propagates(
    tmp_path: Path,
) -> None:
    """A cleanup timeout with no primary failure behaves as it always did.

    When the merge itself succeeds and only the "return to main" cleanup
    hangs, that timeout is the only failure — it must still surface (not
    be swallowed into a quiet info line), matching pre-fix behavior where
    nothing caught this exception at all.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _init_git_repo(sibling)
    (sibling / ".gitkeep").write_text("changed\n")

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "checkout", "main"],
                raises=subprocess.TimeoutExpired(
                    cmd=["git", "checkout", "main"], timeout=600
                ),
            ),
        ],
    )

    def successful_merge(**_kwargs: object) -> str:
        return "abc1234"

    merger = PrMerger(ops=ops)
    with pytest.raises(subprocess.TimeoutExpired):
        merger.merge_in_sibling(
            sibling,
            "propagate/v1.0.0",
            [".gitkeep"],
            "chore: propagate v1.0.0",
            "install-all-github",
            dry_run=False,
            merge=successful_merge,
        )


def test_merge_in_sibling_branch_lookup_failure_also_reaches_skip_recorder(
    tmp_path: Path,
) -> None:
    """A failed ``git branch --show-current`` is a secondary failure too.

    Regression test for a review finding: when the primary merge fails
    AND the cleanup's own branch lookup returns non-zero, ``current``
    becomes ``None`` — that path used to fall straight to an info-only
    message, unlike the checkout-failure path below it, leaving it out
    of the ``SkipRecorder`` recap.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger
    from punt_kit.phases.shared.siblings import SkipRecorder

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _init_git_repo(sibling)
    (sibling / ".gitkeep").write_text("changed\n")

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "branch", "--show-current"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="fatal: not a git repository"
                ),
            ),
        ],
    )
    skips = SkipRecorder(ops=ops)

    def failing_merge(**_kwargs: object) -> str:
        raise ReleaseError("required checks never passed")

    merger = PrMerger(ops=ops, skips=skips)
    with pytest.raises(ReleaseError, match="required checks never passed"):
        merger.merge_in_sibling(
            sibling,
            "propagate/v1.0.0",
            [".gitkeep"],
            "chore: propagate v1.0.0",
            "install-all-github",
            dry_run=False,
            merge=failing_merge,
        )

    (notice,) = skips.drain()
    assert "required checks never passed" in notice
    assert "could not read current branch" in notice


def test_merge_in_sibling_branch_lookup_failure_alone_still_only_infos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No primary exception: a failed branch lookup stays info-only.

    Mirrors ``test_merge_in_sibling_solo_cleanup_failure_still_only_infos``
    for the branch-lookup path specifically — the routing only escalates
    when there is a primary failure for the secondary one to accompany.
    """
    from punt_kit.phases.shared.pr_merge import PrMerger
    from punt_kit.phases.shared.siblings import SkipRecorder

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _init_git_repo(sibling)
    (sibling / ".gitkeep").write_text("changed\n")

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "branch", "--show-current"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="fatal: not a git repository"
                ),
            ),
        ],
    )
    skips = SkipRecorder(ops=ops)

    def successful_merge(**_kwargs: object) -> str:
        return "abc1234"

    merger = PrMerger(ops=ops, skips=skips)
    merger.merge_in_sibling(
        sibling,
        "propagate/v1.0.0",
        [".gitkeep"],
        "chore: propagate v1.0.0",
        "install-all-github",
        dry_run=False,
        merge=successful_merge,
    )

    assert skips.drain() == ()
    printed = capsys.readouterr().out.replace("\n", " ")
    assert "could not read current branch" in printed


def test_merge_in_sibling_status_read_failure_diagnoses(tmp_path: Path) -> None:
    """A failing `git status --porcelain` on the sibling checkout must
    diagnose, not leak a raw CalledProcessError — a cross-repo read, same
    risk class as `SiblingRepo.validate`'s reads and `_sync_profile_readme`'s
    git log, both already diagnosed. Missed in earlier sweep passes
    (pkit-f85t.7 round 2)."""
    from punt_kit.phases.shared.pr_merge import PrMerger

    sibling = tmp_path / "sibling"
    sibling.mkdir()
    _init_git_repo(sibling)

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "status", "--porcelain", "--", ".gitkeep"],
                response=CompletedProcessSpec(
                    returncode=128, stderr="fatal: index file corrupt"
                ),
            )
        ],
    )

    def _unreachable_merge(**_kwargs: object) -> str:
        raise AssertionError("merge must not run — status read fails first")

    merger = PrMerger(ops=ops)
    with pytest.raises(ReleaseError, match="git status on sibling"):
        merger.merge_in_sibling(
            sibling,
            "propagate/v1.0.0",
            [".gitkeep"],
            "chore: propagate v1.0.0",
            "install-all-github",
            dry_run=False,
            merge=_unreachable_merge,
        )


# --- fwql: README SHA pin lands after the release PR's squash-merge ---


def test_phase4_release_pr_pins_readme_after_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 4 lands a second, README-only PR right after the release PR merges."""
    from punt_kit import release as release_mod
    from punt_kit.detect import ProjectInfo

    root = tmp_path / "proj"
    root.mkdir()
    (root / "install.sh").write_text(
        "#!/bin/sh\n"
        "curl -fsSL https://raw.githubusercontent.com/punt-labs/proj/"
        "deadbee/install.sh | sh\n"
    )
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/punt-labs/proj/"
        "deadbee/install.sh | sh\n"
        "```\n"
    )

    info = ProjectInfo(root=root, language="python")

    issued: list[list[str]] = []
    pr_number = {"n": 100}
    # Distinguishable per call: `gh pr view --json mergeCommit` runs once
    # after each of the two squash-merges below (the release PR, then the
    # README-pin PR) — giving each a different oid proves
    # _phase4_release_pr returns the FIRST (the release commit), not
    # whatever HEAD became after the second.
    merge_oids = iter(["aaa1111", "bbb2222"])

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        issued.append(list(cmd))
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        if cmd[:2] == ["git", "log"] and "--format=%h" in cmd:
            r.stdout = "newsha1\n"
        elif cmd[:2] == ["git", "log"]:
            r.stdout = ""
        elif cmd[:2] == ["git", "rev-parse"]:
            r.stdout = "deadbeefcafe\n"
        elif cmd[:2] == ["git", "status"]:
            r.stdout = " M README.md\n" if cmd[-1] == "README.md" else ""
        elif cmd[:2] == ["git", "branch"] and "--show-current" in cmd:
            r.stdout = "main\n"
        elif cmd[:2] == ["git", "branch"] and "--list" in cmd:
            r.stdout = ""
        elif cmd[:3] == ["gh", "pr", "list"]:
            r.stdout = "[]"
        elif cmd[:3] == ["gh", "pr", "create"]:
            pr_number["n"] += 1
            r.stdout = f"https://github.com/punt-labs/proj/pull/{pr_number['n']}\n"
        elif cmd[:3] == ["gh", "pr", "view"] and "mergeCommit" in cmd:
            r.stdout = f"{next(merge_oids)}\n"
        elif cmd[:3] == ["gh", "pr", "view"]:
            r.stdout = json.dumps({"state": "OPEN"})
        elif cmd[:3] == ["gh", "pr", "merge"]:
            r.returncode = 0
        return r

    def _which_gh(_n: str) -> str:
        return "gh"

    def _no_wait(*_a: object, **_k: object) -> None:
        return None

    def _no_threads(*_a: object, **_k: object) -> None:
        return None

    def _repo_slug(_root: Path) -> str:
        return "punt-labs/proj"

    monkeypatch.setattr(shutil, "which", _which_gh)
    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_wait_for_required_checks", _no_wait)
    monkeypatch.setattr(release_mod, "_resolve_pr_threads", _no_threads)
    monkeypatch.setattr(release_mod, "_get_github_repo", _repo_slug)

    release_sha = release_mod._phase4_release_pr(  # pyright: ignore[reportPrivateUsage]
        info, "0.2.0", dry_run=False
    )

    # The squash-merge sha, not whatever HEAD became after the README-pin
    # PR's own squash-merge landed on top of it.
    assert release_sha == "aaa1111"

    pushed_branches = [c[4] for c in issued if c[:3] == ["git", "push", "-u"]]
    assert "release/v0.2.0" in pushed_branches
    assert "release-readme-pin/v0.2.0" in pushed_branches

    created = [c for c in issued if c[:3] == ["gh", "pr", "create"]]
    assert len(created) == 2

    merges = [c for c in issued if c[:3] == ["gh", "pr", "merge"]]
    assert len(merges) == 2

    assert "newsha1" in (root / "README.md").read_text()


def test_land_readme_sha_pin_noop_when_readme_already_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No PR is created when the README already pins the current install SHA."""
    from punt_kit import release as release_mod
    from punt_kit.detect import ProjectInfo

    root = tmp_path / "proj"
    root.mkdir()
    (root / "install.sh").write_text("#!/bin/sh\necho hi\n")
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/punt-labs/proj/"
        "currentsha/install.sh | sh\n"
        "```\n"
    )

    info = ProjectInfo(root=root, language="python")
    issued: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        issued.append(list(cmd))
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        if cmd[:2] == ["git", "log"] and "--format=%h" in cmd:
            r.stdout = "currentsha\n"
        elif cmd[:2] == ["git", "log"]:
            r.stdout = ""
        elif cmd[:2] == ["git", "branch"] and "--show-current" in cmd:
            r.stdout = "main\n"
        elif (cmd[:2] == ["git", "branch"] and "--list" in cmd) or cmd[:2] == [
            "git",
            "status",
        ]:
            r.stdout = ""
        return r

    def _repo_slug(_root: Path) -> str:
        return "punt-labs/proj"

    monkeypatch.setattr(release_mod, "_get_github_repo", _repo_slug)
    monkeypatch.setattr(release_mod, "_run", fake_run)

    release_mod._land_readme_sha_pin(  # pyright: ignore[reportPrivateUsage]
        info, "0.2.0", dry_run=False
    )

    assert not any(c[:3] == ["gh", "pr", "create"] for c in issued)


def test_land_readme_sha_pin_cleanup_diagnoses_checkout_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing `git checkout main` in the no-changes-needed cleanup path
    (README already pins the current SHA) must diagnose, not leak a raw
    CalledProcessError — the same cleanup pattern Phase 9 already
    diagnoses, missed here in earlier sweep passes (pkit-f85t.7 round 2)."""
    from punt_kit import release as release_mod
    from punt_kit.detect import ProjectInfo

    root = tmp_path / "proj"
    root.mkdir()
    (root / "install.sh").write_text("#!/bin/sh\necho hi\n")
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/punt-labs/proj/"
        "currentsha/install.sh | sh\n"
        "```\n"
    )

    info = ProjectInfo(root=root, language="python")

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        if cmd == ["git", "checkout", "main"]:
            r.returncode = 1
            r.stderr = "error: pre-checkout hook rejected"
        elif cmd[:2] == ["git", "log"] and "--format=%h" in cmd:
            r.stdout = "currentsha\n"
        elif cmd[:2] == ["git", "log"]:
            r.stdout = ""
        elif cmd[:2] == ["git", "branch"] and "--show-current" in cmd:
            r.stdout = "main\n"
        elif (cmd[:2] == ["git", "branch"] and "--list" in cmd) or cmd[:2] == [
            "git",
            "status",
        ]:
            r.stdout = ""
        return r

    def _repo_slug(_root: Path) -> str:
        return "punt-labs/proj"

    monkeypatch.setattr(release_mod, "_get_github_repo", _repo_slug)
    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="git checkout main failed"):
        release_mod._land_readme_sha_pin(  # pyright: ignore[reportPrivateUsage]
            info, "0.2.0", dry_run=False
        )


def test_land_readme_sha_pin_cleanup_diagnoses_branch_delete_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing `git branch -D` in the no-changes-needed cleanup path must
    diagnose, not leak a raw CalledProcessError (pkit-f85t.7 round 2)."""
    from punt_kit import release as release_mod
    from punt_kit.detect import ProjectInfo

    root = tmp_path / "proj"
    root.mkdir()
    (root / "install.sh").write_text("#!/bin/sh\necho hi\n")
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/punt-labs/proj/"
        "currentsha/install.sh | sh\n"
        "```\n"
    )

    info = ProjectInfo(root=root, language="python")

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        r = MagicMock()
        r.returncode = 0
        r.stdout = ""
        r.stderr = ""
        if cmd[:3] == ["git", "branch", "-D"]:
            r.returncode = 1
            r.stderr = "error: branch is checked out"
        elif cmd[:2] == ["git", "log"] and "--format=%h" in cmd:
            r.stdout = "currentsha\n"
        elif cmd[:2] == ["git", "log"]:
            r.stdout = ""
        elif cmd[:2] == ["git", "branch"] and "--show-current" in cmd:
            r.stdout = "main\n"
        elif (cmd[:2] == ["git", "branch"] and "--list" in cmd) or cmd[:2] == [
            "git",
            "status",
        ]:
            r.stdout = ""
        return r

    def _repo_slug(_root: Path) -> str:
        return "punt-labs/proj"

    monkeypatch.setattr(release_mod, "_get_github_repo", _repo_slug)
    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="git branch -D .* failed"):
        release_mod._land_readme_sha_pin(  # pyright: ignore[reportPrivateUsage]
            info, "0.2.0", dry_run=False
        )


def test_readme_sha_pin_survives_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The README-pinned install.sh SHA is reachable from main after squash-merge.

    Written to catch the reachability defect Option A (pinning inside
    _phase2_version_bump, before the squash-merge) has: that pins a commit
    that lives only on the release branch, which the merge deletes.
    Byte-equality alone would not catch this — a dangling commit still
    resolves via ``git show`` for a while after deletion. Reachability from
    main is the property that matters once CI checks out the release tag.
    """
    from punt_kit import release as release_mod
    from punt_kit.detect import detect

    root = _make_release_project(tmp_path)
    d = str(root)

    release_branch = "release/v0.2.0"
    _git(["checkout", "-b", release_branch], cwd=d)
    (root / "install.sh").write_text(
        '#!/bin/sh\nPACKAGE="test-pkg"\nVERSION="0.2.0"\n'
        'uv tool install --force "$PACKAGE==$VERSION"\n'
    )
    _git(["add", "install.sh"], cwd=d)
    _git(["commit", "-m", "chore: release v0.2.0"], cwd=d)

    def fake_pr_merge(
        *,
        cwd: Path,
        branch: str,
        title: str,
        body: str = "",
        dry_run: bool = False,
    ) -> str:
        """Simulate `gh pr merge --squash --delete-branch`, entirely locally."""
        r = str(cwd)
        _git(["checkout", "main"], cwd=r)
        _git(["merge", "--squash", branch], cwd=r)
        _git(["commit", "-m", title], cwd=r)
        _git(["branch", "-D", branch], cwd=r)
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=r,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    monkeypatch.setattr(release_mod, "_pr_merge", fake_pr_merge)

    # The reachability guard runs against the working tree's install.sh
    # SHA and the README's install URL. Pin the URL owner/repo to what
    # _make_release_project wrote ("test-pkg") — otherwise the real
    # _get_github_repo (no remote configured in tmp) falls back to
    # root.name ("proj"), the regex misses, and _bump_readme_install_sha
    # returns silently. That would make this whole test a no-op.
    def _repo_slug(_root: Path) -> str:
        return "punt-labs/test-pkg"

    monkeypatch.setattr(release_mod, "_get_github_repo", _repo_slug)

    # Step 1: the release PR's own squash-merge (mirrors _phase4_release_pr's
    # first _pr_merge call, for the release branch itself).
    release_mod._pr_merge(  # pyright: ignore[reportPrivateUsage]
        cwd=root, branch=release_branch, title="chore: release v0.2.0"
    )

    # Step 2: land the README pin — the fix under test.
    info = detect(root)
    release_mod._land_readme_sha_pin(  # pyright: ignore[reportPrivateUsage]
        info, "0.2.0", dry_run=False
    )

    # Read the SHA out of README.md itself — not out of git log — so the
    # test would fail if _land_readme_sha_pin were a no-op that left the
    # stale pre-release SHA in place. The install URL uses a 7-40 hex
    # placeholder segment between "punt-labs/proj/" and "/install.sh"
    # (or the org name we happen to have here); grab whichever hex SHA
    # appears after the last "/" before "install.sh".
    readme = (root / "README.md").read_text()
    match = re.search(r"/([0-9a-fA-F]{7,40})/install\.sh", readme)
    assert match is not None, f"README.md has no SHA-pinned install URL: {readme!r}"
    pinned_sha = match.group(1)

    # (a) The SHA must resolve in the local object DB. Option A's failure
    # mode is exactly this — a dangling object that survives briefly and
    # then gets pruned; the resolve here is a proxy for "the release tag's
    # CI checkout will actually see this commit."
    show = subprocess.run(
        ["git", "show", f"{pinned_sha}:install.sh"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert show == (root / "install.sh").read_text()

    # (b) The SHA must be reachable from main (not a dangling commit).
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", pinned_sha, "main"], cwd=d
    )
    assert ancestor.returncode == 0, (
        f"pinned SHA {pinned_sha} is not reachable from main — Option A's "
        "reachability defect. It resolves via git show only because the "
        "object hasn't been pruned yet."
    )


# --- _phase11_verify: profile SHA ---


def _get_install_all_sha(sibling: Path) -> str:
    """Return the git commit SHA that last touched install-all.sh in sibling."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", "install-all.sh"],
        cwd=str(sibling),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _setup_verify_project(
    tmp_path: Path,
    version: str = "0.1.0",
) -> tuple[Path, Path]:
    """Set up a project with all Phase 11 verify checks passing except profile SHA.

    Returns (root, github_sibling).
    """
    root = _make_release_project(tmp_path)
    d = str(root)

    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=d,
    )

    # Stamp changelog
    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        f"# Changelog\n\n## [{version}] - 2026-03-28\n\n### Added\n\n- Init\n"
    )
    _git(["add", "CHANGELOG.md"], cwd=d)
    _git(["commit", "-m", "stamp changelog"], cwd=d)

    # Tag after all commits so HEAD matches
    _git(["tag", f"v{version}"], cwd=d)

    # Get the install.sh SHA from the project repo
    install_sha = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", "install.sh"],
        cwd=d,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # Create .github sibling with install-all.sh referencing valid project SHA
    sibling = _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                f'curl -fsSL "$GH/proj/{install_sha}/install.sh" | sh\n'
            ),
        },
    )

    # Create claude-plugins sibling with marketplace entry
    _make_sibling(
        tmp_path,
        "claude-plugins",
        {
            ".claude-plugin/marketplace.json": json.dumps(
                {
                    "plugins": [
                        {
                            "name": "proj",
                            "version": version,
                            "source": {
                                "url": "https://github.com/punt-labs/proj.git",
                                "ref": f"v{version}",
                            },
                        }
                    ]
                }
            ),
        },
    )

    return root, sibling


# Exact argv prefix of the Phase 11 PyPI probe (everything but the trailing
# ``<pkg>==<ver>``). Single source of truth: the mock predicate and the
# regression test both match against this, so a change to the probe's shape
# fails loudly here rather than silently falling through to a real command.
_PYPI_PROBE_CMD: tuple[str, ...] = (
    "uv",
    "pip",
    "install",
    "--dry-run",
    "--no-deps",
    "--no-cache",
    "--reinstall",
)


def _patch_pypi_probe(
    monkeypatch: pytest.MonkeyPatch, *, present: bool = True
) -> list[tuple[list[str], dict[str, object]]]:
    """Fake the Phase 11 PyPI probe so verify runs offline.

    Phase 11 checks a published version with the exact ``_PYPI_PROBE_CMD`` argv
    plus a trailing ``<pkg>==<ver>`` and reads only the exit code: 0 means the
    version resolves from the index, non-zero means it is absent. This intercepts
    only that exact command, returns the requested outcome, and leaves every
    other ``_run`` call to the real implementation. No ``pip`` binary is
    involved. Returns the list of intercepted ``(cmd, kwargs)`` pairs so callers
    can assert the probe ran exactly once and inspect its ``cwd``.
    """
    from punt_kit import release as release_mod

    original_run = release_mod._run  # pyright: ignore[reportPrivateUsage]
    calls: list[tuple[list[str], dict[str, object]]] = []

    def patched_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if len(cmd) == len(_PYPI_PROBE_CMD) + 1 and tuple(cmd[:-1]) == _PYPI_PROBE_CMD:
            calls.append((list(cmd), dict(kwargs)))
            result = MagicMock()
            result.returncode = 0 if present else 1
            result.stdout = ""
            result.stderr = "" if present else "unsatisfiable"
            return result
        return original_run(cmd, **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(release_mod, "_run", patched_run)
    return calls


def _setup_fully_passing_verify(tmp_path: Path, version: str) -> Path:
    """Build a project where every Phase 11 check passes but the PyPI probe.

    Extends _setup_verify_project by pinning the profile README to the real
    install-all.sh commit, so the only remaining variable is the PyPI probe's
    exit code — flip it with ``_patch_pypi_probe(present=...)``.
    """
    root, sibling = _setup_verify_project(tmp_path, version)
    sha = _get_install_all_sha(sibling)
    profile_dir = sibling / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "README.md").write_text(
        "# Punt Labs\n\n"
        f"curl -fsSL https://raw.githubusercontent.com/punt-labs/.github/{sha}"
        "/install-all.sh | sh\n"
    )
    _git(["add", "profile/README.md"], cwd=str(sibling))
    _git(["commit", "-m", "add profile"], cwd=str(sibling))
    return root


def test_phase11_verify_cli_only_project_runs_all_applicable_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 11 must run cleanly against a CLI-only project — install.sh
    present, no plugin.json at all — exercising every applicable check
    without assuming the plugin/marketplace shape every other Phase 11
    fixture carries (matrix row 52).
    """
    version = "0.1.0"
    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)

    (root / "pyproject.toml").write_text(
        f'[project]\nname = "test-pkg"\nversion = "{version}"\n\n'
        "[project.scripts]\ntest-cli = 'test_pkg:main'\n"
    )
    src = root / "src" / "test_pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (src / "py.typed").write_text("")

    (root / "install.sh").write_text(
        f'#!/bin/sh\nPACKAGE="test-pkg"\nVERSION="{version}"\n'
        'uv tool install --force "$PACKAGE==$VERSION"\n'
    )
    (root / "README.md").write_text(
        "# test-pkg\n\n```bash\ncurl -fsSL "
        f"https://raw.githubusercontent.com/punt-labs/proj/v{version}/install.sh"
        " | sh\n```\n"
    )
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [{version}] - 2026-03-28\n\n### Added\n\n- Init\n"
    )

    workflows_dir = root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "release.yml").write_text("")

    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)
    _git(["fetch", "origin"], cwd=d)
    _git(["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"], cwd=d)
    _git(["tag", f"v{version}"], cwd=d)

    install_sha = _git_out(["log", "-1", "--format=%H", "--", "install.sh"], cwd=d)

    github_sibling = _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                f'curl -fsSL "$GH/proj/{install_sha}/install.sh" | sh\n'
            ),
        },
    )
    sha = _get_install_all_sha(github_sibling)
    profile_dir = github_sibling / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "README.md").write_text(
        "# Punt Labs\n\n"
        f"curl -fsSL https://raw.githubusercontent.com/punt-labs/.github/{sha}"
        "/install-all.sh | sh\n"
    )
    _git(["add", "profile/README.md"], cwd=str(github_sibling))
    _git(["commit", "-m", "add profile"], cwd=str(github_sibling))

    _patch_pypi_probe(monkeypatch)

    info = detect(root)
    assert info.is_plugin is False
    assert info.is_hybrid is False

    # Should not raise — every applicable check (tag, pyproject, __init__.py,
    # changelog, install-all.sh, profile SHA, PyPI) passes; the plugin.json
    # and marketplace checks correctly do not run at all for this shape.
    _phase11_verify(info, version, dry_run=False)


def test_phase11_verify_profile_sha_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile SHA check passes when README contains a resolvable SHA."""
    version = "0.1.0"
    root = _setup_fully_passing_verify(tmp_path, version)

    _patch_pypi_probe(monkeypatch)

    info = detect(root)

    # Should NOT raise — all checks pass including profile SHA
    _phase11_verify(info, version, dry_run=False)


def test_phase11_verify_profile_sha_fails_bad_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile SHA check fails when README contains a non-resolvable SHA."""
    version = "0.1.0"
    root, sibling = _setup_verify_project(tmp_path, version)

    # Add profile/README.md with a bogus SHA that won't resolve
    bogus_sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    profile_dir = sibling / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "README.md").write_text(
        "# Punt Labs\n\n"
        f"curl -fsSL https://raw.githubusercontent.com/punt-labs/.github/{bogus_sha}"
        "/install-all.sh | sh\n"
    )
    _git(["add", "profile/README.md"], cwd=str(sibling))
    _git(["commit", "-m", "add profile with bad SHA"], cwd=str(sibling))

    _patch_pypi_probe(monkeypatch)

    info = detect(root)

    # Should raise ReleaseError — profile SHA does not resolve
    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)


def test_phase11_verify_profile_sha_fails_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile SHA check fails when the pin resolves but predates the merge.

    A resolvable pin whose content lacks the project's current install SHA
    serves the previous installer — the exact one-commit-behind failure the
    propagation phase exists to prevent.
    """
    version = "0.1.0"
    root, sibling = _setup_verify_project(tmp_path, version)
    sd = str(sibling)

    # Create an OLDER commit whose install-all.sh carries a stale project
    # SHA, then restore the current content on top of it.
    current_content = (sibling / "install-all.sh").read_text()
    stale_content = (
        '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
        'curl -fsSL "$GH/proj/aabb001/install.sh" | sh\n'
    )
    (sibling / "install-all.sh").write_text(stale_content)
    _git(["add", "install-all.sh"], cwd=sd)
    _git(["commit", "-m", "stale entry"], cwd=sd)
    stale_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=sd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (sibling / "install-all.sh").write_text(current_content)
    _git(["add", "install-all.sh"], cwd=sd)
    _git(["commit", "-m", "current entry"], cwd=sd)

    # Profile pins the stale commit — it resolves, but its content is old
    profile_dir = sibling / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "README.md").write_text(
        "# Punt Labs\n\n"
        f"curl -fsSL https://raw.githubusercontent.com/punt-labs/.github/"
        f"{stale_commit}/install-all.sh | sh\n"
    )
    _git(["add", "profile/README.md"], cwd=sd)
    _git(["commit", "-m", "add stale profile pin"], cwd=sd)

    _patch_pypi_probe(monkeypatch)

    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)


def test_phase11_verify_skips_when_github_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Absent .github sibling → Phase 11 skips its two checks, does not fail.

    Phase 11 runs after tag/PyPI/GitHub-release have published. A False check on
    an absent .github sibling would exit non-zero on an already-published release
    and read identically to a real defect — the exact ambiguity the Phase 10 fix
    removed. The install-all.sh and profile-SHA checks must skip (not fail) and
    surface the skip, consistent with Phase 10a and Phase 1d.
    """
    version = "0.1.0"
    root, sibling = _setup_verify_project(tmp_path, version)

    # Remove the .github sibling so _resolve_sibling(".github") returns None.
    shutil.rmtree(sibling)

    _patch_pypi_probe(monkeypatch)
    info = detect(root)

    # Must NOT raise — the two .github checks are skipped, all others pass.
    _phase11_verify(info, version, dry_run=False)

    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert "manual" in out.lower()
    # The skip must not be rendered as a failed check.
    assert "✗ install-all.sh" not in out
    assert "✗ profile SHA" not in out
    # Recorded (once, deduplicated) for the end-of-run recap.
    assert len(release._skips.drain()) == 1  # pyright: ignore[reportPrivateUsage]


def test_phase11_verify_fails_when_install_all_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Present .github sibling but no install-all.sh → still a hard failure.

    Only the absent-sibling case is tolerated. A resolvable .github sibling that
    lacks install-all.sh is a genuine misconfiguration and must still fail.
    """
    version = "0.1.0"
    root, sibling = _setup_verify_project(tmp_path, version)

    # Sibling resolves, but its install-all.sh is gone.
    (sibling / "install-all.sh").unlink()

    _patch_pypi_probe(monkeypatch)
    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)


# --- pkit-9n6q: install SHA pins must be ancestors of the release, not just
# resolvable objects with matching content ---


def test_phase11_verify_install_all_sha_passes_when_ancestor_of_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The install-all.sh SHA passes when it is on the tag's history."""
    version = "0.1.0"
    root = _setup_fully_passing_verify(tmp_path, version)

    _patch_pypi_probe(monkeypatch)
    info = detect(root)

    _phase11_verify(info, version, dry_run=False)  # must not raise

    out = capsys.readouterr().out
    assert "install-all.sh" in out
    assert "✗ install-all.sh" not in out


def test_phase11_verify_install_all_sha_fails_when_not_ancestor_of_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A resolvable install-all.sh SHA that isn't on the tag's history fails.

    Regression for the silent-rot gap: before this check, a SHA on an
    abandoned or superseded branch could carry a byte-identical VERSION
    string and pass a content-only comparison while never having been part
    of the tagged release — install-all.sh would "work" by pointing at the
    wrong commit.
    """
    version = "0.1.0"
    root, sibling = _setup_verify_project(tmp_path, version)
    d = str(root)

    # A commit that resolves via `git show` and still matches VERSION, but
    # lives on a branch that never merges into main — unreachable from the
    # tag even though the object is present in the local database.
    _git(["checkout", "-b", "stale-branch"], cwd=d)
    (root / "install.sh").write_text(
        '#!/bin/sh\nPACKAGE="test-pkg"\nVERSION="0.1.0"\n'
        "# unrelated edit on an unmerged branch\n"
        'uv tool install --force "$PACKAGE==$VERSION"\n'
    )
    _git(["add", "install.sh"], cwd=d)
    _git(["commit", "-m", "stale branch edit"], cwd=d)
    stale_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=d,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(["checkout", "main"], cwd=d)

    # Pin install-all.sh to the stale, unreachable commit instead of the
    # real one _setup_verify_project wrote.
    content = (sibling / "install-all.sh").read_text()
    new_content = re.sub(
        r"/proj/[0-9a-fA-F]{7,40}/install\.sh",
        f"/proj/{stale_sha}/install.sh",
        content,
    )
    assert new_content != content, "fixture regex did not match the pinned SHA"
    (sibling / "install-all.sh").write_text(new_content)
    _git(["add", "install-all.sh"], cwd=str(sibling))
    _git(["commit", "-m", "pin stale sha"], cwd=str(sibling))

    _patch_pypi_probe(monkeypatch)
    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)

    # "ancestor" alone — Rich word-wraps the detail message at console width,
    # so a multi-word phrase like "not an ancestor of ..." can be split across
    # a line break by the renderer even though the underlying string is one
    # contiguous sentence.
    out = capsys.readouterr().out
    assert "✗ install-all.sh" in out
    assert "ancestor" in out


def test_phase11_verify_profile_sha_passes_when_ancestor_of_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The profile pin passes when it is reachable from .github's main."""
    version = "0.1.0"
    root = _setup_fully_passing_verify(tmp_path, version)

    _patch_pypi_probe(monkeypatch)
    info = detect(root)

    _phase11_verify(info, version, dry_run=False)  # must not raise

    out = capsys.readouterr().out
    assert "✗ profile SHA" not in out


def test_phase11_verify_profile_sha_fails_when_not_ancestor_of_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A resolvable profile pin that never merged into .github main fails.

    An empty commit on an unmerged branch carries byte-identical
    install-all.sh content to the real, merged commit — the pre-existing
    content-based staleness check alone would have passed this. Only
    reachability from main catches it: ``git show`` resolves any object
    still in the local database, merged or not, for as long as it survives
    garbage collection.
    """
    version = "0.1.0"
    root, sibling = _setup_verify_project(tmp_path, version)
    sd = str(sibling)

    _git(["checkout", "-b", "dangling-branch"], cwd=sd)
    _git(["commit", "--allow-empty", "-m", "dangling"], cwd=sd)
    dangling_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=sd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(["checkout", "main"], cwd=sd)

    profile_dir = sibling / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "README.md").write_text(
        "# Punt Labs\n\n"
        f"curl -fsSL https://raw.githubusercontent.com/punt-labs/.github/"
        f"{dangling_sha}/install-all.sh | sh\n"
    )
    _git(["add", "profile/README.md"], cwd=sd)
    _git(["commit", "-m", "add dangling profile pin"], cwd=sd)

    _patch_pypi_probe(monkeypatch)
    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)

    # See the analogous comment above — check for the single word rather
    # than the full phrase, which Rich may word-wrap across a line break.
    out = capsys.readouterr().out
    assert "✗ profile SHA" in out
    assert "ancestor" in out


# --- f85t.3: profile SHA marketplace-pin chain for marketplace-only plugins ---


def _marketplace_json(project_version: str) -> str:
    return json.dumps(
        {
            "plugins": [
                {
                    "name": "proj",
                    "version": project_version,
                    "source": {
                        "url": "https://github.com/punt-labs/proj.git",
                        "ref": f"v{project_version}",
                    },
                }
            ]
        }
    )


def _setup_marketplace_only_verify_project(
    tmp_path: Path, version: str, *, pinned_marketplace_version: str
) -> tuple[Path, Path, Path]:
    """Build a marketplace-only plugin project for f85t.3 profile-SHA tests.

    Returns ``(root, github_sibling, claude_plugins_sibling)``. The
    claude-plugins sibling's HEAD always carries ``version`` (so check 5,
    Marketplace, always passes against the working tree); the ``.github``
    commit the profile pins carries ``pinned_marketplace_version`` in its
    own historical marketplace.json instead — set the two equal for a
    passing chain, or different to model a stale pin.
    """
    root = _make_language_none_plugin_project(tmp_path)
    d = str(root)
    _git(["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"], cwd=d)

    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        f"# Changelog\n\n## [{version}] - 2026-03-28\n\n### Added\n\n- Init\n"
    )
    _git(["add", "CHANGELOG.md"], cwd=d)
    _git(["commit", "-m", "stamp changelog"], cwd=d)
    _git(["tag", f"v{version}"], cwd=d)

    cp_sibling = _make_sibling(
        tmp_path,
        "claude-plugins",
        {
            ".claude-plugin/marketplace.json": _marketplace_json(
                pinned_marketplace_version
            )
        },
    )
    pinned_cp_sha = subprocess.run(
        ["git", "log", "-1", "--format=%H"],
        cwd=str(cp_sibling),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    if pinned_marketplace_version != version:
        (cp_sibling / ".claude-plugin" / "marketplace.json").write_text(
            _marketplace_json(version)
        )
        _git(["add", "."], cwd=str(cp_sibling))
        _git(["commit", "-m", "bump to current version"], cwd=str(cp_sibling))

    github_sibling = _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                f'curl -fsSL "$GH/claude-plugins/{pinned_cp_sha}/install.sh" | sh\n'
                "for plugin in prfaq proj z-spec; do\n"
                '  claude plugin install "$plugin@punt-labs"\n'
                "done\n"
            )
        },
    )
    github_sha = _get_install_all_sha(github_sibling)
    profile_dir = github_sibling / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "README.md").write_text(
        "# Punt Labs\n\n"
        f"curl -fsSL https://raw.githubusercontent.com/punt-labs/.github/{github_sha}"
        "/install-all.sh | sh\n"
    )
    _git(["add", "profile/README.md"], cwd=str(github_sibling))
    _git(["commit", "-m", "add profile"], cwd=str(github_sibling))

    return root, github_sibling, cp_sibling


def test_phase11_verify_profile_sha_marketplace_chain_passes(tmp_path: Path) -> None:
    """A marketplace-only plugin's profile SHA verifies via the pin chain."""
    version = "0.1.0"
    root, _github, _cp = _setup_marketplace_only_verify_project(
        tmp_path, version, pinned_marketplace_version=version
    )
    info = detect(root)

    # Should NOT raise — the pinned claude-plugins commit's marketplace.json
    # already carries the current version/ref.
    _phase11_verify(info, version, dry_run=False)


def test_phase11_verify_profile_sha_marketplace_chain_stale_version(
    tmp_path: Path,
) -> None:
    """A stale claude-plugins pin behind the current version fails loud."""
    version = "0.1.0"
    root, _github, _cp = _setup_marketplace_only_verify_project(
        tmp_path, version, pinned_marketplace_version="0.0.9"
    )
    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)


def test_phase11_verify_profile_sha_marketplace_chain_no_claude_plugins_pin(
    tmp_path: Path,
) -> None:
    """No claude-plugins pin in install-all.sh at all is a genuine failure."""
    version = "0.1.0"
    root = _make_language_none_plugin_project(tmp_path)
    d = str(root)
    _git(["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"], cwd=d)
    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        f"# Changelog\n\n## [{version}] - 2026-03-28\n\n### Added\n\n- Init\n"
    )
    _git(["add", "CHANGELOG.md"], cwd=d)
    _git(["commit", "-m", "stamp changelog"], cwd=d)
    _git(["tag", f"v{version}"], cwd=d)

    _make_sibling(
        tmp_path,
        "claude-plugins",
        {".claude-plugin/marketplace.json": _marketplace_json(version)},
    )

    github_sibling = _make_sibling(
        tmp_path,
        ".github",
        {
            "install-all.sh": (
                '#!/bin/sh\nGH="https://raw.githubusercontent.com/punt-labs"\n'
                "for plugin in prfaq proj z-spec; do\n"
                '  claude plugin install "$plugin@punt-labs"\n'
                "done\n"
            )
        },
    )
    github_sha = _get_install_all_sha(github_sibling)
    profile_dir = github_sibling / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "README.md").write_text(
        "# Punt Labs\n\n"
        f"curl -fsSL https://raw.githubusercontent.com/punt-labs/.github/{github_sha}"
        "/install-all.sh | sh\n"
    )
    _git(["add", "profile/README.md"], cwd=str(github_sibling))
    _git(["commit", "-m", "add profile"], cwd=str(github_sibling))

    info = detect(root)
    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)


def test_phase11_verify_profile_sha_marketplace_chain_missing_sibling(
    tmp_path: Path,
) -> None:
    """A claude-plugins pin that cannot be checked (sibling absent) fails.

    Unlike the tolerated ``.github``-absent case, a marketplace-only plugin
    with no resolvable claude-plugins sibling genuinely cannot be verified —
    this is a real defect, not a meta-repo shape to skip.
    """
    version = "0.1.0"
    root, _github, cp_sibling = _setup_marketplace_only_verify_project(
        tmp_path, version, pinned_marketplace_version=version
    )
    shutil.rmtree(cp_sibling)

    info = detect(root)
    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)


def test_phase11_verify_profile_sha_direct_url_path_unaffected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: a CLI/hybrid project (has install.sh) is unaffected.

    Proves ``install_sh.exists()`` — not merely ``info.is_plugin`` — is the
    discriminator that routes into the marketplace-pin chain, so a hybrid
    project (is_plugin=True, has install.sh) still takes the direct-URL path.
    """
    version = "0.1.0"
    root = _setup_fully_passing_verify(tmp_path, version)
    _patch_pypi_probe(monkeypatch)
    info = detect(root)
    assert info.is_plugin is True
    assert (root / "install.sh").exists()

    # Should NOT raise — unchanged direct-URL behavior.
    _phase11_verify(info, version, dry_run=False)


def test_phase_summary_recaps_skipped_propagation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-of-run summary recaps recorded skips and drains them.

    With Phase 11 no longer the backstop, a skip recorded mid-run must be
    re-surfaced at the end so a scrolled-past warning is never the only notice.
    """
    root = _make_release_project(tmp_path)
    info = detect(root)

    release._skips.record(  # pyright: ignore[reportPrivateUsage]
        "SKIPPED — manual action required: verify ../.github by hand"
    )
    capsys.readouterr()  # discard the inline warning emitted by record()

    _phase_summary(info, "0.2.0", dry_run=False)

    out = capsys.readouterr().out
    assert "Manual action required" in out
    assert "verify ../.github by hand" in out
    # drain() inside the summary consumed the notice — nothing left to recap.
    assert release._skips.drain() == ()  # pyright: ignore[reportPrivateUsage]


def test_absent_github_dedups_to_single_recap_across_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.github` absent for a whole run → exactly ONE recap bullet.

    Phase 10a (propagation) and both Phase 11 checks (install-all.sh, profile
    SHA) all skip for the same reason and describe the same manual remediation.
    They record through one shared template so _skips collapses them to a single
    notice, rather than flooding the operator with duplicate warnings for one
    root cause — the common meta-repo case where .github never resolves.
    """
    version = "0.1.0"
    root, sibling = _setup_verify_project(tmp_path, version)

    # .github absent for the entire run.
    shutil.rmtree(sibling)

    _patch_pypi_probe(monkeypatch)
    info = detect(root)

    # Phase 10a records its propagation skip; Phase 11 records two verify skips.
    _propagate_install_all(info, version, dry_run=False)
    _phase11_verify(info, version, dry_run=False)

    # All three collapse to a single deduplicated recap line.
    notices = release._skips.drain()  # pyright: ignore[reportPrivateUsage]
    assert len(notices) == 1


# --- Phase 11: PyPI check ---


def test_phase11_verify_pypi_present_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Published version resolves → PyPI check passes, verify does not raise."""
    version = "0.1.0"
    root = _setup_fully_passing_verify(tmp_path, version)

    calls = _patch_pypi_probe(monkeypatch, present=True)
    info = detect(root)

    _phase11_verify(info, version, dry_run=False)

    assert "✓ PyPI" in capsys.readouterr().out
    assert len(calls) == 1


def test_phase11_verify_pypi_absent_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Unresolvable version → PyPI check fails, verify raises.

    With every other check passing, flipping only the PyPI probe's exit code to
    non-zero must flip verify to failure — so a genuinely missing publish is
    still caught, not masked.
    """
    version = "0.1.0"
    root = _setup_fully_passing_verify(tmp_path, version)

    calls = _patch_pypi_probe(monkeypatch, present=False)
    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)

    assert "✗ PyPI" in capsys.readouterr().out
    assert len(calls) == 1


def test_phase11_pypi_probe_shape_index_authoritative_and_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PyPI probe must be index-authoritative, uv-native, and run in-project.

    Guards three regressions at once:
    - uv-managed venvs ship no `pip`, so `uv run pip …` fails to spawn — the
      probe must be `uv pip …` (uv's own resolver), never `uv run pip …`.
    - a cached/installed copy must not satisfy the check (`--no-cache` +
      `--reinstall` force a fresh index query), else a locally-built-but-never-
      published version would false-positive.
    - the probe must run in the project dir (`cwd=info.root`).
    """
    version = "0.1.0"
    root = _setup_fully_passing_verify(tmp_path, version)

    calls = _patch_pypi_probe(monkeypatch, present=True)
    info = detect(root)

    _phase11_verify(info, version, dry_run=False)

    # Exactly one probe call, matching the exact uv-native argv shape.
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert tuple(cmd[:-1]) == _PYPI_PROBE_CMD
    # Not `uv run pip …` — that path spawns the absent pip binary.
    assert "run" not in cmd
    # Cache/env bypass so the check asserts index presence, not local resolvability.
    assert "--no-cache" in cmd
    assert "--reinstall" in cmd
    # The target is pinned to the exact published version.
    assert cmd[-1].endswith(f"=={version}")
    # The probe runs in the project dir.
    assert kwargs["cwd"] == str(info.root)


# --- restore-dev-plugin.sh ---

# Path to the real restore-dev-plugin.sh script
_RESTORE_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir,
    "scripts",
    "restore-dev-plugin.sh",
)

# Path to the real release-plugin.sh script
_RELEASE_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir,
    "scripts",
    "release-plugin.sh",
)


def test_release_path_never_bypasses_git_hooks() -> None:
    """No release-path file may pass ``--no-verify`` to git.

    The org CLAUDE.md bans ``--no-verify`` outright; the release path is
    the historical repeat offender (Phases 4 and 9 previously carried
    three uses across ``release.py``, ``release-plugin.sh``, and
    ``restore-dev-plugin.sh``). This test greps the files themselves so
    a reintroduction fails immediately, not on the next release. Comments
    describing the ban are stripped before scanning so this file's own
    prose does not trigger it.
    """
    root = _Path(__file__).parent.parent
    targets = [
        root / "src" / "punt_kit" / "release.py",
        root / "scripts" / "release-plugin.sh",
        root / "scripts" / "restore-dev-plugin.sh",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        code_only_lines: list[str] = []
        for raw in text.splitlines():
            stripped = raw.lstrip()
            if stripped.startswith("#"):
                continue
            code, sep, _ = raw.partition("#")
            code_only_lines.append(code if sep else raw)
        code_only = "\n".join(code_only_lines)
        assert "--no-verify" not in code_only, (
            f"{path.name} reintroduced --no-verify — org CLAUDE.md bans "
            "the flag; let the hooks run or surface a real hook failure."
        )


def _install_script(root: Path, source: str) -> Path:
    """Copy one of the real release scripts into a test repo."""
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    dest = scripts_dir / os.path.basename(source)
    with open(source) as f:
        dest.write_text(f.read())
    dest.chmod(0o755)
    return dest


def _install_restore_script(root: Path) -> None:
    """Copy the real restore-dev-plugin.sh into a test repo."""
    _install_script(root, _RESTORE_SCRIPT)


@pytest.mark.parametrize("subdir", [False, True])
def test_release_plugin_swaps_both_layouts(tmp_path: Path, *, subdir: bool) -> None:
    """release-plugin.sh finds the manifest under plugin/ and at the root.

    The script is copied verbatim into nine plugin repos that migrate to the
    plugin/ layout one at a time. A hardcoded repo-root path would abort the
    release on a migrated repo; a hardcoded plugin/ path would abort it on an
    unmigrated one.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    d = str(root)

    plugin_root = root / "plugin" if subdir else root
    plugin_dir = plugin_root / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test-dev", "version": "0.1.0"}, indent=2) + "\n"
    )
    commands_dir = plugin_root / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "hello.md").write_text("# Hello\n")
    (commands_dir / "hello-dev.md").write_text("# Hello dev\n")
    script = _install_script(root, _RELEASE_SCRIPT)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add dev plugin state"], cwd=d)

    subprocess.run(["bash", str(script)], cwd=d, check=True, capture_output=True)

    swapped = json.loads((plugin_dir / "plugin.json").read_text())
    assert swapped["name"] == "test", "the -dev suffix must be gone from the tag"
    assert not (commands_dir / "hello-dev.md").exists()
    assert (commands_dir / "hello.md").exists()

    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert subject == "chore: prepare plugin for release"


def test_release_plugin_swaps_a_plugin_with_no_commands(tmp_path: Path) -> None:
    """A skills-only plugin releases on the name swap alone.

    plugins.md allows a plugin that ships only skills, agents, or hooks, and
    `punt audit` reports a missing commands/ as informational. Aborting the
    release preparation here would block such a plugin from ever tagging.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    d = str(root)

    plugin_dir = root / "plugin" / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test-dev", "version": "0.1.0"}, indent=2) + "\n"
    )
    skill_dir = root / "plugin" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\n---\n")
    script = _install_script(root, _RELEASE_SCRIPT)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add dev plugin state"], cwd=d)

    result = subprocess.run(
        ["bash", str(script)], cwd=d, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert json.loads((plugin_dir / "plugin.json").read_text())["name"] == "test"
    assert "swapping the name only" in result.stdout


def test_release_plugin_errors_when_commands_vanished_from_the_tree(
    tmp_path: Path,
) -> None:
    """commands/ tracked at HEAD but gone from disk aborts the preparation.

    This is the case a `[ -d ]` test cannot see. `find` inside a process
    substitution discards its exit status, so a directory that vanished yields
    an empty match and reads exactly like a plugin that never had commands —
    and the release would tag a "prod" commit still carrying every -dev file.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    d = str(root)

    plugin_dir = root / "plugin" / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test-dev", "version": "0.1.0"}, indent=2) + "\n"
    )
    commands_dir = root / "plugin" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "hello.md").write_text("# Hello\n")
    (commands_dir / "hello-dev.md").write_text("# Hello dev\n")
    script = _install_script(root, _RELEASE_SCRIPT)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add dev plugin state"], cwd=d)

    # Vanish the directory without committing the deletion.
    shutil.rmtree(commands_dir)

    result = subprocess.run(
        ["bash", str(script)], cwd=d, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "tracked at HEAD but missing from the working tree" in result.stderr
    # The name swap must not have been committed either.
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert subject == "add dev plugin state", "no release commit may land"


def test_release_plugin_errors_when_commands_exist_without_dev_variants(
    tmp_path: Path,
) -> None:
    """A commands/ directory with no -dev variants still aborts.

    Distinct from having no commands/ at all: either the dev variants were
    never written or a prior run already swapped, and both need a human.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    d = str(root)

    plugin_dir = root / "plugin" / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test-dev", "version": "0.1.0"}, indent=2) + "\n"
    )
    commands_dir = root / "plugin" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "hello.md").write_text("# Hello\n")
    script = _install_script(root, _RELEASE_SCRIPT)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add plugin without dev variants"], cwd=d)

    result = subprocess.run(
        ["bash", str(script)], cwd=d, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "No -dev commands found" in result.stderr


def test_restore_dev_plugin_restores_a_plugin_with_no_commands(tmp_path: Path) -> None:
    """The restore names commands/ only when the dev commit has it.

    git checkout aborts on a pathspec matching nothing, and this runs under
    `set -e` inside phase 9 — so an unconditional commands/ would kill the
    post-release run for a plugin that never had one.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    d = str(root)

    plugin_dir = root / "plugin" / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    plugin_json = plugin_dir / "plugin.json"
    plugin_json.write_text(
        json.dumps({"name": "test-dev", "version": "0.1.0"}, indent=2) + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add dev plugin state"], cwd=d)

    plugin_json.write_text(
        json.dumps({"name": "test", "version": "0.1.0"}, indent=2) + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "chore: prepare plugin for release"], cwd=d)

    script = _install_script(root, _RESTORE_SCRIPT)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add restore script"], cwd=d)

    result = subprocess.run(
        ["bash", str(script)], cwd=d, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(plugin_json.read_text())["name"] == "test-dev"
    assert "restoring the manifest only" in result.stdout


def test_release_plugin_errors_when_no_manifest(tmp_path: Path) -> None:
    """No manifest in either location is a hard error, not a silent no-op.

    Exiting 0 here would let phase 4 tag a release whose plugin was never
    swapped to its prod name — the failure the idempotency check exists for.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    script = _install_script(root, _RELEASE_SCRIPT)

    result = subprocess.run(
        ["bash", str(script)], cwd=str(root), capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "no .claude-plugin/plugin.json" in result.stderr


def test_restore_dev_plugin_errors_when_no_manifest(tmp_path: Path) -> None:
    """Same contract for the restore side: refuse rather than restore nothing.

    A silent exit would leave main advertising the prod plugin name, so every
    developer's --plugin-dir session would collide with the marketplace copy.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    script = _install_script(root, _RESTORE_SCRIPT)

    result = subprocess.run(
        ["bash", str(script)], cwd=str(root), capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "no .claude-plugin/plugin.json" in result.stderr


@pytest.mark.parametrize("subdir", [False, True])
def test_restore_dev_plugin_finds_dev_commit_past_head1(
    tmp_path: Path, *, subdir: bool
) -> None:
    """restore-dev-plugin.sh finds dev state even when HEAD~1 is unrelated.

    Simulates the scenario where multiple PRs merge between the release swap
    and Phase 9 (post-release), so HEAD~1 no longer has the dev plugin state.
    Run against both layouts: the script walks plugin.json's history by path,
    so naming the wrong path yields an empty log and an early exit.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    d = str(root)

    # Create dev plugin state
    plugin_root = root / "plugin" if subdir else root
    plugin_dir = plugin_root / ".claude-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test-dev", "version": "0.1.0"}, indent=2) + "\n"
    )
    commands_dir = plugin_root / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "hello.md").write_text("# Hello\nDev command\n")
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add dev plugin state"], cwd=d)

    # Release swap: remove -dev from name (simulates release-plugin.sh)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test", "version": "0.1.0"}, indent=2) + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "chore: prepare plugin for release"], cwd=d)

    # Simulate 2 unrelated PRs merging after release tag
    (root / "unrelated1.txt").write_text("pr 1\n")
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "feat: unrelated PR 1"], cwd=d)

    (root / "unrelated2.txt").write_text("pr 2\n")
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "feat: unrelated PR 2"], cwd=d)

    # Copy the real restore-dev-plugin.sh into the test repo
    _install_restore_script(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add restore script"], cwd=d)

    # Capture HEAD before running the script so the "no commit" contract
    # can be asserted against a concrete baseline rather than by absence.
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Run the script
    subprocess.run(
        ["bash", str(root / "scripts" / "restore-dev-plugin.sh")],
        cwd=d,
        check=True,
        capture_output=True,
    )

    # Verify plugin.json now has the dev name
    restored = json.loads((plugin_dir / "plugin.json").read_text())
    assert restored["name"] == "test-dev"

    # Verify the dev command was restored
    assert (commands_dir / "hello.md").read_text() == "# Hello\nDev command\n"

    # Contract: the script stages but does NOT commit — HEAD is unchanged
    # and the restored files are in the index, waiting for the caller
    # (Phase 9) to re-stamp the version and commit once.
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert head_after == head_before, "restore-dev-plugin.sh must not commit"

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    # Only plugin.json differs from the dev commit — commands/hello.md
    # was never removed by the simulated release swap so `git add
    # commands/` finds nothing new to stage. What matters for the
    # contract is that the name-flip landed in the index.
    expected = (plugin_dir / "plugin.json").relative_to(root).as_posix()
    assert expected in staged


def test_restore_dev_plugin_errors_when_no_dev_commit(tmp_path: Path) -> None:
    """restore-dev-plugin.sh exits non-zero when no dev commit exists."""
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    d = str(root)

    # Create plugin state that never had -dev in the name
    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test", "version": "0.1.0"}, indent=2) + "\n"
    )
    commands_dir = root / "commands"
    commands_dir.mkdir()
    (commands_dir / "hello.md").write_text("# Hello\n")
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add plugin without dev name"], cwd=d)

    # Copy the real restore-dev-plugin.sh
    _install_restore_script(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add restore script"], cwd=d)

    # Run the script — should fail
    result = subprocess.run(
        ["bash", str(root / "scripts" / "restore-dev-plugin.sh")],
        cwd=d,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "No commit found with dev plugin name" in result.stderr


@pytest.mark.parametrize("subdir", [False, True])
def test_phase9_dev_restore_single_commit_with_restamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, subdir: bool
) -> None:
    """Phase 9 lands the dev restore and version re-stamp in one commit.

    The previous shape ran restore-dev-plugin.sh (which committed on its
    own with --no-verify), noticed the version had been reverted along
    with the name, and then --amend --no-edit --no-verify'd to correct
    it. Both --no-verify uses are banned. The new shape has the script
    stage but not commit; this phase re-stamps and commits once with
    hooks running. The observable evidence of the new shape is: HEAD is
    a single new commit (not an amend of one, not a commit-plus-amend
    pair), and it carries both the name flip and the correct version.
    """
    from punt_kit import release as release_mod
    from punt_kit.release import (
        _phase9_post_release,  # pyright: ignore[reportPrivateUsage]
    )

    root = _make_release_project(tmp_path, subdir=subdir)
    d = str(root)
    plugin_root = root / "plugin" if subdir else root

    # Establish a dev-state commit that also carries a -dev command
    # file, so restore-dev-plugin.sh's `git checkout ... commands/` has
    # something to walk back to. The commit must touch plugin.json —
    # the script walks plugin.json history, so a commit that only adds
    # commands/ would be invisible to it and it would keep walking back
    # to the initial scaffold commit (which has no commands/).
    plugin_json = plugin_root / ".claude-plugin" / "plugin.json"
    commands_dir = plugin_root / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    (commands_dir / "hello-dev.md").write_text("# hello-dev\n")
    # Force plugin.json to differ from the scaffold — the restore
    # script walks plugin.json history and picks the newest commit
    # whose JSON has a -dev name. A no-op write leaves plugin.json out
    # of this commit and the script walks back past it to the scaffold
    # (which has no commands/) and errors on the checkout.
    plugin_json.write_text(
        json.dumps(
            {"name": "test-dev", "version": "0.1.0", "description": "d"},
            indent=2,
        )
        + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add dev command"], cwd=d)

    # Simulate the release-branch merge: on main plugin.json is already in
    # prod state at the just-released version and the -dev command has
    # been removed. The dev-named commit that restore-dev-plugin.sh
    # walks back to still has the previous version and the dev command.
    plugin_json.write_text(
        json.dumps({"name": "test", "version": "0.2.0"}, indent=2) + "\n"
    )
    (commands_dir / "hello-dev.md").unlink()
    _git(["add", "-A"], cwd=d)
    _git(["commit", "-m", "chore: release v0.2.0 (post-merge)"], cwd=d)

    # Swap in the real restore script (the fake in _make_release_project
    # only does `git commit --allow-empty`, which does not exercise the
    # stage-only contract this test is asserting).
    scripts_dir = root / "scripts"
    real_script = _Path(__file__).parent.parent / "scripts" / "restore-dev-plugin.sh"
    (scripts_dir / "restore-dev-plugin.sh").write_text(real_script.read_text())
    (scripts_dir / "restore-dev-plugin.sh").chmod(0o755)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "install real restore script"], cwd=d)

    # README pointing at the project so the SHA bump has something to
    # rewrite — this exercises the second Phase 9 commit as well and
    # lets us assert the exact commit sequence.
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/abc1234/install.sh | sh\n"
        "```\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "sha-pinned readme"], cwd=d)

    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    def fake_pr_merge(
        *,
        cwd: Path,
        branch: str,
        title: str,
        body: str = "",
        dry_run: bool = False,
    ) -> str:
        return "abc1234"

    monkeypatch.setattr(release_mod, "_pr_merge", fake_pr_merge)

    info = detect(root)
    _phase9_post_release(info, "0.2.0", dry_run=False)

    # Post-release branch has the restore commit and the README-SHA
    # commit — exactly two commits ahead of the base. The restore
    # commit is a single new commit, not a commit-plus-amend pair, so
    # the count is the primary evidence that the amend is gone.
    log = (
        subprocess.run(
            ["git", "log", "--format=%s", f"{base_head}..HEAD"],
            cwd=d,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    assert log == [
        "chore: restore dev plugin state",
    ], log

    # The restore commit — HEAD — must contain both the plugin.json
    # revert and the version re-stamp. If the script had committed
    # first, the re-stamp would either be in HEAD (a second commit) or
    # would have required the --amend path this refactor deleted.
    restore_files = _commit_files(root, ref="HEAD")
    assert plugin_json.relative_to(root).as_posix() in restore_files

    restored = json.loads(plugin_json.read_text())
    assert restored["name"] == "test-dev"
    assert restored["version"] == "0.2.0"


def test_phase09_post_release_commit_never_marks_skip_ci() -> None:
    """The dev-restore commit message must not carry [skip ci].

    GitHub Actions honors [skip ci] on ``pull_request`` triggers, so a
    marked commit skips the branch-protected lint/test/docs workflows —
    and the PR becomes unmergeable because the required checks never
    ran. Guard against reintroduction by scanning the phase 9 module.
    See pkit-x5j8.
    """
    phase9 = (
        _Path(__file__).parent.parent
        / "src"
        / "punt_kit"
        / "phases"
        / "phase09_post_release.py"
    )
    text = phase9.read_text(encoding="utf-8")
    # Strip full-line comments so the explanatory comment about the
    # marker does not trigger the scan.
    code_lines = [
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert "[skip ci]" not in code, (
        "phase 9 post-release commit message must not carry [skip ci] — "
        "branch protection requires lint/test/docs to run on the PR."
    )


def test_phase4_release_pr_swap_script_failure_retries_cleanly(
    tmp_path: Path,
) -> None:
    """A rejected plugin-swap commit (a real pre-commit hook, exactly the
    failure mode the module docstring documents) must diagnose, and a
    clean retry from the same starting state must still land a
    production-shaped commit and reach merge.

    Uses the *real* release-plugin.sh with a real rejecting pre-commit
    hook — not fault injection at the `ops.run` boundary — so the first
    attempt genuinely leaves the tree mutated and staged but uncommitted
    (the partial state this phase's HEAD-consult retry exists to recover
    from), and the second attempt proves the retry produces the actual
    production-shaped result: name swapped, dev command removed, merge
    reached (qodo round-1 review: the fault-injection version of this
    test intercepted the whole script call and so never reached that
    partial state at all — this replaces it). `bash
    scripts/release-plugin.sh` also defaulted to check=True
    (pkit-f85t.7), so a rejected commit here previously leaked a raw
    CalledProcessError instead of a diagnosed message (matrix row 13).
    """
    from punt_kit.phases.phase04_release_pr import Phase4ReleasePr

    root = _make_release_project(tmp_path)
    d = str(root)

    # Install the real release-plugin.sh — the _make_release_project fake
    # is `git commit --allow-empty` and would not exercise the
    # tree-mutation-and-stage path a real hook rejection leaves behind.
    real_script = _Path(__file__).parent.parent / "scripts" / "release-plugin.sh"
    release_script = root / "scripts" / "release-plugin.sh"
    release_script.write_text(real_script.read_text())
    release_script.chmod(0o755)

    # release-plugin.sh removes commands/*-dev.md as part of the swap; the
    # fixture ships no commands/ directory, so add one -dev command so the
    # script has something to `git rm`.
    commands_dir = root / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    (commands_dir / "hello-dev.md").write_text("# hello-dev\n")
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "install real release script"], cwd=d)

    info = detect(root)
    pre_head = _git_out(["rev-parse", "HEAD"], cwd=d)

    hooks_dir = root / ".git" / "hooks"
    pre_commit_hook = hooks_dir / "pre-commit"
    pre_commit_hook.write_text("#!/bin/sh\nexit 1\n")
    pre_commit_hook.chmod(0o755)

    ops = FaultInjectingOps(
        real_run=_run, rules=[], passthrough=[["bash", str(release_script)]]
    )

    def _unreachable_merge(**_kwargs: object) -> str:
        raise AssertionError("merge must not run when the swap script fails")

    def _unreachable_pin(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("readme pin must not run when the swap script fails")

    with pytest.raises(ReleaseError, match=re.escape(str(release_script))):
        Phase4ReleasePr(info, "0.2.0", dry_run=False, ops=ops).run(
            merge=_unreachable_merge, land_readme_sha_pin=_unreachable_pin
        )

    # HEAD is untouched (the script's own commit was rejected by the
    # hook), but the swap itself genuinely happened — plugin.json and the
    # -dev command removal are staged, uncommitted. This IS the partial
    # state the module docstring describes and the pre-existing
    # hand-simulated test (test_phase4_resumes_when_prior_swap_staged_
    # but_uncommitted) also covers; here it is produced by a real hook
    # rejection instead of hand-written.
    assert _git_out(["rev-parse", "HEAD"], cwd=d) == pre_head
    staged_pj = json.loads(_git_out(["show", ":.claude-plugin/plugin.json"], cwd=d))
    assert staged_pj["name"] == "test"
    assert "hello-dev.md" in _git_out(["status", "--porcelain"], cwd=d)

    pre_commit_hook.unlink()

    merged: dict[str, object] = {}

    def _capture_merge(**kwargs: object) -> str:
        merged.update(kwargs)
        return "abc1234"

    def _capture_pin(*_args: object, **_kwargs: object) -> None:
        return None

    resumed_ops = FaultInjectingOps(
        real_run=_run, rules=[], passthrough=[["bash", str(release_script)]]
    )
    Phase4ReleasePr(info, "0.2.0", dry_run=False, ops=resumed_ops).run(
        merge=_capture_merge, land_readme_sha_pin=_capture_pin
    )

    assert _git_out(["rev-parse", "HEAD"], cwd=d) != pre_head
    head_pj = json.loads(_git_out(["show", "HEAD:.claude-plugin/plugin.json"], cwd=d))
    assert head_pj["name"] == "test"
    assert not (commands_dir / "hello-dev.md").exists()
    assert merged.get("branch") == "release/v0.2.0"


@pytest.mark.parametrize("subdir", [False, True])
def test_phase4_resumes_when_prior_swap_staged_but_uncommitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, subdir: bool
) -> None:
    """Phase 4 must NOT skip the swap when a prior run failed mid-commit.

    Removing --no-verify (pkit-sliw) let pre-commit hooks abort
    release-plugin.sh AFTER it mutated the working tree and staged the
    changes. A working-tree read of plugin.json then reports the swap
    complete, phase 4 falls through to _pr_merge, and the release tag
    lands on a commit still carrying the -dev plugin name. The correct
    predicate is whether the swap is committed AT HEAD.

    This test simulates the failed-hook state by staging a prod-shaped
    plugin.json without committing, then runs the phase and asserts
    the swap commit lands. Mutation-checked by reverting the predicate
    to read the working tree — the assertion that HEAD advanced fails
    because the buggy code takes the "already in prod state" branch
    and _pr_merge sees an unchanged HEAD.

    Run against both layouts, because the predicate is a ``git show
    HEAD:<path>`` and a path that does not exist at HEAD makes the phase
    raise rather than answer.
    """
    from punt_kit import release as release_mod
    from punt_kit.release import (
        _phase4_release_pr,  # pyright: ignore[reportPrivateUsage]
    )

    root = _make_release_project(tmp_path, subdir=subdir)
    d = str(root)
    plugin_root = root / "plugin" if subdir else root
    pj_rel = (plugin_root / ".claude-plugin" / "plugin.json").relative_to(root)
    pj_spec = pj_rel.as_posix()
    commands_rel = (plugin_root / "commands").relative_to(root).as_posix()

    # Install the real release-plugin.sh — the _make_release_project
    # fake is `git commit --allow-empty` and would not exercise the
    # tree-mutation-and-stage path this test asserts against.
    real_script = _Path(__file__).parent.parent / "scripts" / "release-plugin.sh"
    (root / "scripts" / "release-plugin.sh").write_text(real_script.read_text())
    (root / "scripts" / "release-plugin.sh").chmod(0o755)

    # release-plugin.sh removes commands/*-dev.md as part of the swap;
    # the fixture ships no commands/ directory, so add one -dev command
    # so the script has something to `git rm`.
    commands_dir = plugin_root / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    (commands_dir / "hello-dev.md").write_text("# hello-dev\n")

    # Switch to the release branch phase 2 would have created and
    # commit the fixture into that branch's HEAD. HEAD's plugin.json
    # name is dev at this point — the correct starting state for the
    # phase 4 swap.
    _git(["checkout", "-b", "release/v0.2.0"], cwd=d)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "chore: bump versions to 0.2.0"], cwd=d)

    pre_phase_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Simulate the failed-hook state: release-plugin.sh mutated the
    # working tree and staged, but the commit did not land. Do exactly
    # what the script does short of the commit itself.
    plugin_json = root / pj_rel
    prod_pj = json.loads(plugin_json.read_text())
    prod_pj["name"] = "test"
    plugin_json.write_text(json.dumps(prod_pj, indent=2) + "\n")
    _git(["rm", f"{commands_rel}/hello-dev.md"], cwd=d)
    _git(["add", pj_spec], cwd=d)

    # Confirm the setup matches the defect scenario: disk reports prod
    # but HEAD still carries dev.
    assert json.loads(plugin_json.read_text())["name"] == "test"
    head_pj = subprocess.run(
        ["git", "show", f"HEAD:{pj_spec}"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert json.loads(head_pj)["name"] == "test-dev"

    # Capture what _pr_merge sees. If the swap was skipped, the SHA
    # captured here equals pre_phase_head — the release branch that
    # would be pushed does not contain the swap.
    captured: dict[str, str] = {}

    def fake_pr_merge(
        *,
        cwd: Path,
        branch: str,
        title: str,
        body: str = "",
        dry_run: bool = False,
    ) -> str:
        captured["head_at_push"] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        captured["head_name_at_push"] = json.loads(
            subprocess.run(
                ["git", "show", f"HEAD:{pj_spec}"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )["name"]
        return "abc1234"

    monkeypatch.setattr(release_mod, "_pr_merge", fake_pr_merge)

    # The fwql pin step runs against a real remote in production; this
    # test has none. Stub it out — the assertions here are about the
    # swap behavior, not the pin.
    def _skip_pin(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(release_mod, "_land_readme_sha_pin", _skip_pin)

    info = detect(root)
    _phase4_release_pr(info, "0.2.0", dry_run=False)

    assert captured["head_at_push"] != pre_phase_head, (
        "phase 4 skipped the swap and pushed an unchanged branch — the "
        "release tag would land on a commit still carrying the -dev name"
    )
    assert captured["head_name_at_push"] == "test"


def test_phase9_post_release_restore_commit_failure_retries_cleanly(
    tmp_path: Path,
) -> None:
    """A rejected restore commit must diagnose, and a clean retry from the
    same starting state must still land the restore and reach merge.

    The restore script only stages (never commits — see restore-dev-
    plugin.sh's CONTRACT); Phase 9's own explicit `git commit` is where a
    hook rejection actually lands. That call defaulted to check=True
    (pkit-f85t.7), so the failure previously leaked a raw
    CalledProcessError instead of the diagnosed message this phase's
    HEAD-consult idempotency check exists to recover from (matrix row 32).
    """
    from punt_kit.phases.phase09_post_release import Phase9PostRelease

    root = _make_release_project(tmp_path)
    d = str(root)

    # Same dev-history scaffold the resume test below builds: a prior dev
    # commit for restore-dev-plugin.sh to walk back to, then the
    # release-branch merge landing prod on main.
    plugin_json = root / ".claude-plugin" / "plugin.json"
    commands_dir = root / "commands"
    commands_dir.mkdir(exist_ok=True)
    (commands_dir / "hello-dev.md").write_text("# hello-dev\n")
    plugin_json.write_text(
        json.dumps(
            {"name": "test-dev", "version": "0.1.0", "description": "d"},
            indent=2,
        )
        + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add dev command"], cwd=d)

    plugin_json.write_text(
        json.dumps({"name": "test", "version": "0.2.0"}, indent=2) + "\n"
    )
    (commands_dir / "hello-dev.md").unlink()
    _git(["add", "-A"], cwd=d)
    _git(["commit", "-m", "chore: release v0.2.0 (post-merge)"], cwd=d)

    real_script = _Path(__file__).parent.parent / "scripts" / "restore-dev-plugin.sh"
    (root / "scripts" / "restore-dev-plugin.sh").write_text(real_script.read_text())
    (root / "scripts" / "restore-dev-plugin.sh").chmod(0o755)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "install real restore script"], cwd=d)

    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/abc1234/install.sh | sh\n"
        "```\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add readme"], cwd=d)

    info = detect(root)
    pre_head = _git_out(["rev-parse", "HEAD"], cwd=d)
    restore_script = root / "scripts" / "restore-dev-plugin.sh"

    failing_ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "commit", "-m", "chore: restore dev plugin state"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="pre-commit hook rejected"
                ),
            )
        ],
        passthrough=[["bash", str(restore_script)]],
    )

    def _unreachable_merge(**_kwargs: object) -> str:
        raise AssertionError("merge must not run when the restore commit fails")

    with pytest.raises(ReleaseError, match="restore dev plugin state"):
        Phase9PostRelease(info, "0.2.0", dry_run=False, ops=failing_ops).run(
            merge=_unreachable_merge
        )

    # The restore script legitimately staged its revert (that IS its
    # contract) — only the follow-up commit failed. HEAD must be
    # unchanged; the staged, uncommitted dev-shaped plugin.json is exactly
    # the partial state the HEAD-consult check exists to recover from.
    assert _git_out(["rev-parse", "HEAD"], cwd=d) == pre_head

    merged: dict[str, object] = {}

    def _capture_merge(**kwargs: object) -> str:
        merged.update(kwargs)
        return "abc1234"

    resumed_ops = FaultInjectingOps(
        real_run=_run, rules=[], passthrough=[["bash", str(restore_script)]]
    )
    Phase9PostRelease(info, "0.2.0", dry_run=False, ops=resumed_ops).run(
        merge=_capture_merge
    )

    assert _git_out(["rev-parse", "HEAD"], cwd=d) != pre_head
    assert merged.get("branch") == "post-release/v0.2.0"


def test_phase9_post_release_restore_script_itself_failing_diagnoses(
    tmp_path: Path,
) -> None:
    """A failing `bash scripts/restore-dev-plugin.sh` itself — distinct
    from the follow-up commit failing, already covered above — must
    diagnose too. Flagged by Copilot's round-1 PR review as an uncovered
    branch of the same converted call site."""
    from punt_kit.phases.phase09_post_release import Phase9PostRelease

    root = _make_release_project(tmp_path)
    info = detect(root)
    restore_script = root / "scripts" / "restore-dev-plugin.sh"

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["bash", str(restore_script)],
                response=CompletedProcessSpec(
                    returncode=1,
                    stderr="ERROR: No commit found with dev plugin name",
                ),
            )
        ],
    )

    def _unreachable_merge(**_kwargs: object) -> str:
        raise AssertionError("merge must not run — restore script fails first")

    with pytest.raises(ReleaseError, match=re.escape(str(restore_script))):
        Phase9PostRelease(info, "0.2.0", dry_run=False, ops=ops).run(
            merge=_unreachable_merge
        )


def test_phase9_post_release_cleanup_diagnoses_checkout_failure(
    tmp_path: Path,
) -> None:
    """A failing `git checkout main` in the no-changes-needed cleanup path
    must diagnose, not leak a raw CalledProcessError — missed by round 1's
    sweep (pkit-f85t.7 round 2)."""
    from punt_kit.phases.phase09_post_release import Phase9PostRelease

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test-pkg"\nversion = "0.1.0"\n'
    )
    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)
    assert not info.is_plugin

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "checkout", "main"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="error: pre-checkout hook rejected"
                ),
            )
        ],
    )

    def _unreachable_merge(**_kwargs: object) -> str:
        raise AssertionError("merge must not run — cleanup checkout fails first")

    with pytest.raises(ReleaseError, match="git checkout main failed"):
        Phase9PostRelease(info, "0.2.0", dry_run=False, ops=ops).run(
            merge=_unreachable_merge
        )


def test_phase9_post_release_cleanup_diagnoses_branch_delete_failure(
    tmp_path: Path,
) -> None:
    """A failing `git branch -D` in the no-changes-needed cleanup path must
    diagnose, not leak a raw CalledProcessError (pkit-f85t.7 round 2)."""
    from punt_kit.phases.phase09_post_release import Phase9PostRelease

    root = tmp_path / "proj"
    root.mkdir()
    _init_git_repo(root)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "test-pkg"\nversion = "0.1.0"\n'
    )
    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    info = detect(root)

    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            FaultRule(
                match=["git", "branch", "-D", "post-release/v0.2.0"],
                response=CompletedProcessSpec(
                    returncode=1, stderr="error: branch is checked out"
                ),
            )
        ],
    )

    def _unreachable_merge(**_kwargs: object) -> str:
        raise AssertionError("merge must not run — cleanup branch delete fails first")

    with pytest.raises(ReleaseError, match="git branch -D post-release/v0.2.0 failed"):
        Phase9PostRelease(info, "0.2.0", dry_run=False, ops=ops).run(
            merge=_unreachable_merge
        )


def test_phase9_resumes_when_prior_restore_staged_but_uncommitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 9 must NOT skip the restore when a prior commit failed on a hook.

    Mirror of the phase 4 defect: the restore script stages but does
    not commit, so if the following ``git commit`` fails on a hook the
    working tree already shows the dev name with no commit backing it.
    A working-tree read would then treat the restore as done and fall
    through to the README-SHA bump, whose ``git commit`` would sweep
    the still-staged plugin.json into itself under the wrong message —
    a silent fusion with no restore commit and a mislabelled second
    commit. Consulting HEAD (name AND version) forces the retry to
    complete and land a properly-labelled restore commit.
    """
    from punt_kit import release as release_mod
    from punt_kit.release import (
        _phase9_post_release,  # pyright: ignore[reportPrivateUsage]
    )

    root = _make_release_project(tmp_path)
    d = str(root)

    # Build the same dev-history scaffold the single-commit test uses:
    # a prior dev commit for restore-dev-plugin.sh to walk back to,
    # then the release-branch merge landing prod on main.
    plugin_json = root / ".claude-plugin" / "plugin.json"
    commands_dir = root / "commands"
    commands_dir.mkdir(exist_ok=True)
    (commands_dir / "hello-dev.md").write_text("# hello-dev\n")
    plugin_json.write_text(
        json.dumps(
            {"name": "test-dev", "version": "0.1.0", "description": "d"},
            indent=2,
        )
        + "\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "add dev command"], cwd=d)

    plugin_json.write_text(
        json.dumps({"name": "test", "version": "0.2.0"}, indent=2) + "\n"
    )
    (commands_dir / "hello-dev.md").unlink()
    _git(["add", "-A"], cwd=d)
    _git(["commit", "-m", "chore: release v0.2.0 (post-merge)"], cwd=d)

    real_script = _Path(__file__).parent.parent / "scripts" / "restore-dev-plugin.sh"
    (root / "scripts" / "restore-dev-plugin.sh").write_text(real_script.read_text())
    (root / "scripts" / "restore-dev-plugin.sh").chmod(0o755)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "install real restore script"], cwd=d)

    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/abc1234/install.sh | sh\n"
        "```\n"
    )
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "sha-pinned readme"], cwd=d)

    # Enter phase 9 as if a prior run had staged the restore and the
    # commit hook failed. Create the post-release branch by hand (phase
    # 9 will find it and reuse it), then run the script (which stages
    # plugin.json into the dev shape) without following it with a
    # commit.
    _git(["checkout", "-b", "post-release/v0.2.0"], cwd=d)
    subprocess.run(
        ["bash", str(root / "scripts" / "restore-dev-plugin.sh")],
        cwd=d,
        check=True,
        capture_output=True,
    )
    assert json.loads(plugin_json.read_text())["name"] == "test-dev"
    head_pj = subprocess.run(
        ["git", "show", "HEAD:.claude-plugin/plugin.json"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert json.loads(head_pj)["name"] == "test"
    # Return to main so phase 9's branch-management code re-enters
    # post-release/v0.2.0 through its own path, matching the real
    # resume shape.
    _git(["checkout", "main"], cwd=d)

    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    def fake_pr_merge(
        *,
        cwd: Path,
        branch: str,
        title: str,
        body: str = "",
        dry_run: bool = False,
    ) -> str:
        return "abc1234"

    monkeypatch.setattr(release_mod, "_pr_merge", fake_pr_merge)

    info = detect(root)
    _phase9_post_release(info, "0.2.0", dry_run=False)

    log = (
        subprocess.run(
            ["git", "log", "--format=%s", f"{base_head}..HEAD"],
            cwd=d,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()
    )
    # One commit — dev restore only. Phase 9 no longer bumps README;
    # that moved to phase 4 (fwql). The restore commit must land
    # cleanly regardless of the prior mid-hook stage.
    assert log == [
        "chore: restore dev plugin state",
    ], log

    # The restore commit — HEAD — must carry plugin.json. A skipped
    # restore would leave a stray staged plugin.json rather than a
    # proper commit.
    restore_files = _commit_files(root, ref="HEAD")
    assert ".claude-plugin/plugin.json" in restore_files

    restored = json.loads(plugin_json.read_text())
    assert restored["name"] == "test-dev"
    assert restored["version"] == "0.2.0"


# --- Phase 10 concurrent propagation ---


def test_phase10_propagate_runs_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All three propagation functions are called even when running concurrently."""
    root = _make_release_project(tmp_path)
    info = detect(root)

    calls: list[str] = []
    barrier = threading.Barrier(3, timeout=5)

    def mock_install_all(*args: object, **kwargs: object) -> None:
        calls.append("install_all")
        barrier.wait()

    def mock_marketplace(*args: object, **kwargs: object) -> None:
        calls.append("marketplace")
        barrier.wait()

    def mock_website(*args: object, **kwargs: object) -> None:
        calls.append("website")
        barrier.wait()

    from punt_kit import release as release_mod

    monkeypatch.setattr(release_mod, "_propagate_install_all", mock_install_all)
    monkeypatch.setattr(release_mod, "_propagate_marketplace", mock_marketplace)
    monkeypatch.setattr(release_mod, "_propagate_website", mock_website)

    def _noop_reset(*args: object, **kwargs: object) -> None:
        pass

    monkeypatch.setattr(release_mod, "_reset_propagation_siblings", _noop_reset)

    _phase10_propagate(info, "0.2.0", dry_run=False)

    assert sorted(calls) == ["install_all", "marketplace", "website"]


def test_phase10_propagate_collects_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One propagation failing does not prevent the others from running."""
    root = _make_release_project(tmp_path)
    info = detect(root)

    calls: list[str] = []

    def mock_install_all(*args: object, **kwargs: object) -> None:
        calls.append("install_all")
        raise SystemExit(1)

    def mock_marketplace(*args: object, **kwargs: object) -> None:
        calls.append("marketplace")

    def mock_website(*args: object, **kwargs: object) -> None:
        calls.append("website")

    from punt_kit import release as release_mod

    monkeypatch.setattr(release_mod, "_propagate_install_all", mock_install_all)
    monkeypatch.setattr(release_mod, "_propagate_marketplace", mock_marketplace)
    monkeypatch.setattr(release_mod, "_propagate_website", mock_website)

    def _noop_reset(*args: object, **kwargs: object) -> None:
        pass

    monkeypatch.setattr(release_mod, "_reset_propagation_siblings", _noop_reset)

    with pytest.raises(ReleaseError):
        _phase10_propagate(info, "0.2.0", dry_run=False)

    # All three should have been called despite the failure in install_all
    assert sorted(calls) == ["install_all", "marketplace", "website"]


def test_phase10_propagate_records_leg_failure_in_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leg failure lands in the shared SkipRecorder, not only the raised error.

    pkit-d7mz: the end-of-run recap drains ``_skips`` even when the pipeline
    stops before a successful ``pipeline.summarize()`` — so a Phase 10 leg
    failure must be recorded there, not only surfaced as the exception that
    ``ThreadedStep.collect`` raises and the caller sees.
    """
    root = _make_release_project(tmp_path)
    info = detect(root)

    def mock_install_all(*args: object, **kwargs: object) -> None:
        raise ReleaseError("install-all.sh: boom")

    def mock_marketplace(*args: object, **kwargs: object) -> None:
        return None

    def mock_website(*args: object, **kwargs: object) -> None:
        return None

    from punt_kit import release as release_mod

    monkeypatch.setattr(release_mod, "_propagate_install_all", mock_install_all)
    monkeypatch.setattr(release_mod, "_propagate_marketplace", mock_marketplace)
    monkeypatch.setattr(release_mod, "_propagate_website", mock_website)

    def _noop_reset(*args: object, **kwargs: object) -> None:
        pass

    monkeypatch.setattr(release_mod, "_reset_propagation_siblings", _noop_reset)

    with pytest.raises(ReleaseError):
        _phase10_propagate(info, "0.2.0", dry_run=False)

    notices = release_mod._skips.drain()  # pyright: ignore[reportPrivateUsage]
    assert len(notices) == 1
    assert "FAILED" in notices[0]
    assert "Phase 10 propagation" in notices[0]
    # Names the failing leg (.github), not just "something failed".
    assert ".github" in notices[0]


# --- Phases 9+10 concurrent ---


def test_phases_9_10_run_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both P9 and P10 are called when start <= 9."""
    root = _make_release_project(tmp_path)
    info = detect(root)

    calls: list[str] = []

    from punt_kit import release as release_mod

    def mock_p9(*args: object, **kwargs: object) -> None:
        calls.append("p9")

    def mock_p10(*args: object, **kwargs: object) -> None:
        calls.append("p10")

    monkeypatch.setattr(release_mod, "_phase9_post_release", mock_p9)
    monkeypatch.setattr(release_mod, "_phase10_propagate", mock_p10)

    _run_phases_9_10(info, "0.2.0", dry_run=False, start=9)
    assert sorted(calls) == ["p10", "p9"]


def test_phases_9_10_only_p10_when_start_10(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only P10 runs when start == 10."""
    root = _make_release_project(tmp_path)
    info = detect(root)

    calls: list[str] = []

    from punt_kit import release as release_mod

    def mock_p9(*args: object, **kwargs: object) -> None:
        calls.append("p9")

    def mock_p10(*args: object, **kwargs: object) -> None:
        calls.append("p10")

    monkeypatch.setattr(release_mod, "_phase9_post_release", mock_p9)
    monkeypatch.setattr(release_mod, "_phase10_propagate", mock_p10)

    _run_phases_9_10(info, "0.2.0", dry_run=False, start=10)
    assert calls == ["p10"]


def test_phases_9_10_exception_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exception from P10 propagates even when P9 succeeds."""
    root = _make_release_project(tmp_path)
    info = detect(root)

    from punt_kit import release as release_mod

    def noop_p9(*args: object, **kwargs: object) -> None:
        pass

    monkeypatch.setattr(release_mod, "_phase9_post_release", noop_p9)

    def failing_p10(*args: object, **kwargs: object) -> None:
        raise RuntimeError("P10 exploded")

    monkeypatch.setattr(release_mod, "_phase10_propagate", failing_p10)

    with pytest.raises(ReleaseError):
        _run_phases_9_10(info, "0.2.0", dry_run=False, start=9)


def test_phases_9_10_p9_systemexit_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SystemExit from P9 is collected and re-raised as ReleaseError."""
    root = _make_release_project(tmp_path)
    info = detect(root)

    from punt_kit import release as release_mod

    def failing_p9(*args: object, **kwargs: object) -> None:
        raise SystemExit(1)

    monkeypatch.setattr(release_mod, "_phase9_post_release", failing_p9)

    def noop_p10(*args: object, **kwargs: object) -> None:
        pass

    monkeypatch.setattr(release_mod, "_phase10_propagate", noop_p10)

    with pytest.raises(ReleaseError):
        _run_phases_9_10(info, "0.2.0", dry_run=False, start=9)


def test_phases_9_10_both_fail_reports_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When both P9 and P10 fail, both errors are collected."""
    root = _make_release_project(tmp_path)
    info = detect(root)

    from punt_kit import release as release_mod

    def failing_p9(*args: object, **kwargs: object) -> None:
        raise RuntimeError("P9 exploded")

    monkeypatch.setattr(release_mod, "_phase9_post_release", failing_p9)

    def failing_p10(*args: object, **kwargs: object) -> None:
        raise RuntimeError("P10 exploded")

    monkeypatch.setattr(release_mod, "_phase10_propagate", failing_p10)

    with pytest.raises(ReleaseError):
        _run_phases_9_10(info, "0.2.0", dry_run=False, start=9)


# ---------------------------------------------------------------------------
# Phase 6 run selection
#
# The failure this guards against is a false green: phase 6 attaching to a
# successful run that predates the tag and reporting "CI passed" for a release
# that was never tested. It cannot be reproduced by running a release, because
# the trigger is GitHub being slow to register a run. So the selection logic is
# driven directly against synthesised `gh run list` payloads instead.
#
# Payload shapes are copied from real `gh run list --workflow release.yml
# --json databaseId,headBranch,event,headSha` output on punt-labs/punt-kit.
# ---------------------------------------------------------------------------

TAG = "v0.13.0"
COMMIT = "d613f08eb7deedbcdf78f550a88201ca5541ad26"

# The run this tag actually triggered.
MATCHING_RUN: dict[str, object] = {
    "databaseId": 31806710142,
    "headBranch": TAG,
    "event": "push",
    "headSha": COMMIT,
    "name": "Release",
}

# The previous release's run — succeeded, and sits at runs[0] until the new
# run registers. This is the one the old code would have watched.
STALE_SUCCESS_RUN: dict[str, object] = {
    "databaseId": 31761285776,
    "headBranch": "v0.12.0",
    "event": "push",
    "headSha": "4265f57b75d733211227917e10e07bc739575584",
    "name": "Release",
}


def _selector() -> _TagRunSelector:
    return _TagRunSelector(TAG, COMMIT)


def _never_sleep(_seconds: float) -> None:
    """Collapse the poll interval so tests do not actually wait."""


def test_phase6_fails_on_stale_success_with_no_matching_run() -> None:
    """A previous release's green run must not be accepted for this tag.

    This is the false green the fix exists for: without the tag filter, the
    old code took runs[0] — the stale success — and reported CI passed.
    """
    selector = _selector()

    with pytest.raises(ReleaseError, match="no release.yml run found"):
        selector.poll(
            lambda: [STALE_SUCCESS_RUN], attempts=2, interval=0, sleep=_never_sleep
        )


def test_phase6_selects_the_matching_run_among_stale_ones() -> None:
    """The tag's own run is picked even when stale runs are listed first."""
    selector = _selector()

    run_id = selector.poll(
        lambda: [STALE_SUCCESS_RUN, MATCHING_RUN],
        attempts=2,
        interval=0,
        sleep=_never_sleep,
    )

    assert run_id == 31806710142


def test_phase6_waits_for_a_run_that_registers_late() -> None:
    """A slow registration extends the wait instead of selecting the wrong run."""
    selector = _selector()
    calls: list[int] = []
    slept: list[float] = []

    def list_runs() -> list[dict[str, object]]:
        calls.append(1)
        # The tag's run only shows up on the third poll.
        if len(calls) < 3:
            return [STALE_SUCCESS_RUN]
        return [MATCHING_RUN, STALE_SUCCESS_RUN]

    run_id = selector.poll(list_runs, attempts=5, interval=5.0, sleep=slept.append)

    assert run_id == 31806710142
    assert len(calls) == 3
    assert slept == [5.0, 5.0], "should sleep between polls, not after the match"


def test_phase6_fails_when_no_runs_exist_at_all() -> None:
    """An empty run list must fail after the attempts, not hang."""
    selector = _selector()
    attempts_made: list[int] = []

    def list_runs() -> list[dict[str, object]]:
        attempts_made.append(1)
        return []

    with pytest.raises(ReleaseError, match="no release.yml run found"):
        selector.poll(list_runs, attempts=3, interval=0, sleep=_never_sleep)

    assert len(attempts_made) == 3, "must stop after the configured attempts"


def test_phase6_rejects_a_retagged_run_at_a_different_commit() -> None:
    """Same tag name, different commit — a delete-and-recreate leftover.

    Real case: v0.12.0 had two push runs at different headShas. Matching on
    the tag name alone would accept the older one.
    """
    selector = _selector()
    leftover = {**MATCHING_RUN, "headSha": "70111ff62936f5cbb64f8c6235bbe106258088a2"}

    with pytest.raises(ReleaseError, match="no release.yml run found"):
        selector.poll([leftover].copy, attempts=2, interval=0, sleep=_never_sleep)


def test_phase6_rejects_a_branch_run_at_the_same_commit() -> None:
    """A run at the right commit but the wrong ref is still the wrong run.

    The tag points at main's HEAD, so a main-branch run shares the tag run's
    headSha exactly. Only headBranch separates them — without that check the
    wait can attach to the branch run and never watch the tag's release at all.
    """
    selector = _selector()
    branch_run = {**MATCHING_RUN, "databaseId": 31806700000, "headBranch": "main"}

    with pytest.raises(ReleaseError, match="no release.yml run found"):
        selector.poll([branch_run].copy, attempts=2, interval=0, sleep=_never_sleep)


def test_phase6_rejects_a_manual_dispatch_of_the_same_tag() -> None:
    """workflow_dispatch is not the tag push, even at the right commit."""
    selector = _selector()
    dispatched = {**MATCHING_RUN, "event": "workflow_dispatch"}

    with pytest.raises(ReleaseError, match="no release.yml run found"):
        selector.poll([dispatched].copy, attempts=2, interval=0, sleep=_never_sleep)


def test_phase6_rejects_a_run_without_a_usable_id() -> None:
    """A malformed payload fails loudly rather than watching run 'None'."""
    selector = _selector()
    malformed = {**MATCHING_RUN, "databaseId": None}

    with pytest.raises(ReleaseError, match="no usable databaseId"):
        selector.poll([malformed].copy, attempts=1, interval=0, sleep=_never_sleep)


def test_phase6_error_names_the_tag_and_commit() -> None:
    """The failure message must say what was looked for, not just that it failed."""
    selector = _selector()

    with pytest.raises(ReleaseError) as caught:
        selector.poll(list, attempts=1, interval=0, sleep=_never_sleep)

    message = str(caught.value)
    assert TAG in message
    assert COMMIT[:8] in message


def _fake_which(_name: str) -> str:
    """Stand in for a gh binary so phase 6 gets past its tool check."""
    return "/usr/bin/gh"


def test_phase6_fails_when_the_tag_cannot_be_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tag missing locally fails cleanly instead of raising CalledProcessError."""
    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)

    with pytest.raises(ReleaseError, match="Cannot resolve"):
        _phase6_ci_wait(info, "9.9.9", dry_run=False)


def test_phase6_reports_gh_failure_rather_than_a_missing_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken gh must not be reported as 'the tag did not trigger CI'.

    Both produce an empty run list, but the operator's next action is
    completely different, so the two must not share a message.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 2)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc1234\n", stderr="")
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="gh: not authenticated"
        )

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="not authenticated"):
        _phase6_ci_wait(info, "9.9.9", dry_run=False)


def test_phase6_blames_the_missing_run_when_gh_worked_at_least_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late transient gh blip must not be blamed for a run that never existed.

    The interleaved case: gh answers cleanly for most polls (no matching run,
    because the tag genuinely never triggered CI) and then fails once at the
    end. Reporting that blip as "gh never succeeded" points the operator at
    their network when the real story is that no run was ever created.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 3)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    gh_calls: list[int] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc1234\n", stderr="")
        gh_calls.append(1)
        # Clean empty answers, then one transient failure on the last poll.
        if len(gh_calls) < 3:
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="gh: connection reset"
        )

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="no release.yml run found"):
        _phase6_ci_wait(info, "9.9.9", dry_run=False)


def test_phase6_lists_runs_filtered_to_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run list is filtered by ref server-side, not truncated client-side.

    Without --branch, a busy release.yml history can push the target run past
    the limit, which reads identically to "the tag never triggered CI".
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 1)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc1234\n", stderr="")
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError):
        _phase6_ci_wait(info, "9.9.9", dry_run=False)

    assert seen, "gh run list should have been invoked"
    assert "--branch" in seen[0]
    assert seen[0][seen[0].index("--branch") + 1] == "v9.9.9"


def test_phase6_reports_the_time_it_actually_waited() -> None:
    """The failure message must not claim an interval it never slept.

    poll sleeps between attempts, not after the last one, so N attempts wait
    (N-1) intervals.
    """
    selector = _selector()
    slept: list[float] = []

    with pytest.raises(ReleaseError, match="after 15s"):
        selector.poll(list, attempts=4, interval=5.0, sleep=slept.append)

    assert sum(slept) == 15.0, "reported wait must match the wait performed"


def test_phase6_survives_unparseable_gh_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Garbage on stdout with a zero exit must diagnose, not traceback.

    A JSONDecodeError escaping list_runs would bypass both _fail sites and
    end the release in a stack trace instead of a message.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 2)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc1234\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="not json at all", stderr="")

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="unparseable JSON"):
        _phase6_ci_wait(info, "9.9.9", dry_run=False)


def test_phase6_dry_run_prints_the_command_it_would_execute(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The dry run must show the real invocation, not a paraphrase.

    A dry run that prints an approximation of the command is worse than
    useless for debugging: it diverges silently from what actually runs.
    """
    root = _make_release_project(tmp_path)
    info = detect(root)

    _phase6_ci_wait(info, "9.9.9", dry_run=True)

    printed = capsys.readouterr().out
    executed = " ".join(_TagRunSelector.list_command("gh", "v9.9.9"))
    # Rich wraps long lines, so compare on the argument tokens.
    for token in executed.split():
        assert token in printed, f"dry run omitted {token!r}"


def test_phase6_survives_wrong_shaped_gh_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid JSON of the wrong shape must diagnose, not raise TypeError.

    gh reports some errors as a JSON object rather than a run array. Casting
    one to a run sequence surfaces as a TypeError from inside poll, which
    escapes both _fail sites the same way a decode error would.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 2)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc1234\n", stderr="")
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"message":"Not Found"}', stderr=""
        )

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="unexpected JSON shape"):
        _phase6_ci_wait(info, "9.9.9", dry_run=False)


def test_phase6_reports_a_sub_second_interval_without_truncating() -> None:
    """A fractional interval must not be rounded down in the message.

    int() on (attempts - 1) * interval would report 2s for a 2.5s wait,
    understating how long the release actually blocked.
    """
    selector = _selector()

    with pytest.raises(ReleaseError, match="after 2.5s"):
        selector.poll(list, attempts=3, interval=1.25, sleep=_never_sleep)


def _run_stub(
    responses: dict[str, subprocess.CompletedProcess[str]],
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Route fake _run calls by the gh subcommand (or git) they invoke."""

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{COMMIT}\n", stderr="")
        key = cmd[2] if len(cmd) > 2 else ""
        return responses[key]

    return fake_run


def test_phase6_reports_failed_lookups_alongside_the_missing_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lookups that never happened must not vanish from the account.

    One success latches "gh worked"; without a count, 23 subsequent failures
    read as 24 clean looks that found nothing, and the operator concludes the
    tag never triggered CI when most of the search never ran.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 3)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    calls: list[int] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{COMMIT}\n", stderr="")
        calls.append(1)
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="gh: API rate limit exceeded"
        )

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError) as caught:
        _phase6_ci_wait(info, "9.9.9", dry_run=False)

    message = str(caught.value)
    assert "2 of 3 lookups failed" in message
    assert "rate limit" in message


def test_phase6_names_the_near_miss_run_it_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run for this tag at another commit is the fact the operator needs.

    The list is filtered by ref, so a rejected run cannot mean "the tag never
    triggered CI" — saying that while holding evidence to the contrary is the
    worst message this phase can print.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 1)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    stale = json.dumps(
        [
            {
                "databaseId": 31760774397,
                "headBranch": TAG,
                "event": "push",
                "headSha": "70111ff62936f5cbb64f8c6235bbe106258088a2",
                "conclusion": "failure",
            }
        ]
    )
    monkeypatch.setattr(
        release_mod,
        "_run",
        _run_stub(
            {"list": subprocess.CompletedProcess([], 0, stdout=stale, stderr="")}
        ),
    )

    with pytest.raises(ReleaseError) as caught:
        _phase6_ci_wait(info, TAG.removeprefix("v"), dry_run=False)

    message = str(caught.value)
    assert "70111ff6" in message, "must name the commit it saw"
    assert "failure" in message, "must name that run's conclusion"
    assert COMMIT[:8] in message, "must name the commit it wanted"


def test_phase6_does_not_call_an_unreachable_run_a_ci_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 404 or 401 from gh run watch is not a verdict from CI.

    Both exit non-zero exactly like a real failure. Reporting them as "CI
    failed" sends the operator to a green run, and the natural recovery from
    there is to resume past this phase — publishing with no verdict at all.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 1)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    listed = json.dumps([MATCHING_RUN | {"conclusion": "success"}])
    monkeypatch.setattr(
        release_mod,
        "_run",
        _run_stub(
            {
                "list": subprocess.CompletedProcess([], 0, stdout=listed, stderr=""),
                "watch": subprocess.CompletedProcess(
                    [], 1, stdout="", stderr="HTTP 401: Bad credentials"
                ),
                "view": subprocess.CompletedProcess(
                    [],
                    0,
                    stdout='{"status":"completed","conclusion":"success"}',
                    stderr="",
                ),
            }
        ),
    )

    with pytest.raises(ReleaseError, match="could not confirm"):
        _phase6_ci_wait(info, TAG.removeprefix("v"), dry_run=False)


def test_phase6_still_reports_a_genuine_ci_failure_as_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unreachable-run handling must not soften a real red build."""
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 1)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    listed = json.dumps([MATCHING_RUN | {"conclusion": "failure"}])
    monkeypatch.setattr(
        release_mod,
        "_run",
        _run_stub(
            {
                "list": subprocess.CompletedProcess([], 0, stdout=listed, stderr=""),
                "watch": subprocess.CompletedProcess([], 1, stdout="", stderr=""),
                "view": subprocess.CompletedProcess(
                    [],
                    0,
                    stdout='{"status":"completed","conclusion":"failure"}',
                    stderr="",
                ),
            }
        ),
    )

    with pytest.raises(ReleaseError, match="concluded failure"):
        _phase6_ci_wait(info, TAG.removeprefix("v"), dry_run=False)


def test_phase6_timeout_explains_itself_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A watch timeout must diagnose, not exit in a traceback.

    run_release catches ReleaseError only, so TimeoutExpired escapes as a
    stack trace — and the release environment's manual approval gate makes
    outlasting the two-hour watch a routine occurrence, not an exotic one.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 1)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    listed = json.dumps([MATCHING_RUN | {"conclusion": None}])

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{COMMIT}\n", stderr="")
        if cmd[2] == "watch":
            raise subprocess.TimeoutExpired(cmd, 7200)
        return subprocess.CompletedProcess(cmd, 0, stdout=listed, stderr="")

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="release environment approval"):
        _phase6_ci_wait(info, TAG.removeprefix("v"), dry_run=False)


def test_phase6_treats_a_hung_run_list_as_a_failed_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung listing must be a failed lookup, not a traceback.

    The watch call was hardened against TimeoutExpired; the listing goes
    through the same _run and would escape poll the same way.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 2)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{COMMIT}\n", stderr="")
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="timed out"):
        _phase6_ci_wait(info, TAG.removeprefix("v"), dry_run=False)


def test_phase6_survives_a_hung_verdict_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure-reporting path must survive the failure it reports on.

    The broken connection that makes gh run watch exit non-zero is the
    likeliest reason the follow-up status query hangs, so a timeout there
    must produce the could-not-confirm message rather than a traceback.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_ATTEMPTS", 1)
    monkeypatch.setattr(release_mod, "_CI_RUN_POLL_INTERVAL", 0.0)

    listed = json.dumps([MATCHING_RUN | {"conclusion": None}])

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{COMMIT}\n", stderr="")
        if cmd[2] == "view":
            raise subprocess.TimeoutExpired(cmd, 60)
        if cmd[2] == "watch":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=listed, stderr="")

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(ReleaseError, match="could not confirm"):
        _phase6_ci_wait(info, TAG.removeprefix("v"), dry_run=False)


# --- f85t.2: phase 6 skip/fail on a missing release.yml workflow ---


def test_phase6_skips_for_pure_plugin_without_release_yml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pure (non-hybrid) plugin with no release.yml has nothing to wait for."""
    from punt_kit import release as release_mod
    from punt_kit.detect import ProjectInfo

    def _unreachable(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("_run must not be called on the pure-plugin skip path")

    monkeypatch.setattr(release_mod, "_run", _unreachable)

    info = ProjectInfo(
        root=_Path("/nonexistent"),
        is_plugin=True,
        workflow_files=["docs.yml", "biff-notify.yml"],
    )
    _phase6_ci_wait(info, "1.0.0", dry_run=False)


def test_phase6_fails_actionably_when_python_project_missing_release_yml() -> None:
    """A non-plugin project missing release.yml fails loud, not silent."""
    from punt_kit.detect import ProjectInfo

    info = ProjectInfo(
        root=_Path("/nonexistent"),
        language="python",
        workflow_files=["docs.yml"],
    )
    with pytest.raises(ReleaseError, match="misconfiguration"):
        _phase6_ci_wait(info, "1.0.0", dry_run=False)


def test_phase6_hybrid_missing_release_yml_still_fails() -> None:
    """A hybrid project (CLI + plugin) must have release.yml — no silent skip."""
    from punt_kit.detect import ProjectInfo

    info = ProjectInfo(
        root=_Path("/nonexistent"),
        is_plugin=True,
        cli_commands=["test-cli"],
        workflow_files=["docs.yml"],
    )
    assert info.is_hybrid is True
    with pytest.raises(ReleaseError, match="misconfiguration"):
        _phase6_ci_wait(info, "1.0.0", dry_run=False)


def test_phase6_proceeds_normally_when_release_yml_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard: the existing pass-through behavior is untouched.

    ``_make_release_project`` now includes a ``release.yml`` placeholder
    (added for this guard), so this exercises the unchanged code path after
    the new guard using the pre-existing ``_run_stub`` dict-dispatch mocks.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    info = detect(root)
    monkeypatch.setattr(shutil, "which", _fake_which)

    listed = json.dumps([MATCHING_RUN])
    fake_run = _run_stub(
        {
            "list": subprocess.CompletedProcess([], 0, stdout=listed, stderr=""),
            "watch": subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        }
    )
    monkeypatch.setattr(release_mod, "_run", fake_run)

    _phase6_ci_wait(info, TAG.removeprefix("v"), dry_run=False)


def test_run_default_timeout_is_short() -> None:
    """A hung subprocess must fail loud in seconds, not silently in hours.

    The default was 7200s so gh run watch could inherit it without arguing;
    every other of the ~90 _run call sites in release.py inherited that same
    two-hour hang budget silently. Pin the short default here — a regression
    to a long default puts the whole release one forgotten call site away
    from a two-hour stall.
    """
    sig = inspect.signature(_run)
    default = sig.parameters["timeout"].default
    assert default == _DEFAULT_RUN_TIMEOUT
    assert _DEFAULT_RUN_TIMEOUT <= 60


def test_git_hook_timeout_exceeds_beads_hook_ceiling() -> None:
    """The hook budget must live above BEADS_HOOK_TIMEOUT (300s), not equal to it.

    A git command that fires a bd hook spends time on git's own I/O
    (write index, resolve refs, network for push/pull) in addition to the
    hook. Setting the budget to 300s — the hook's own ceiling — leaves no
    headroom, and the release aborts the moment the hook uses its full
    tolerance. The v0.14.0 release lost two phases exactly this way.
    """
    assert _GIT_HOOK_TIMEOUT > 300


def test_hook_firing_git_calls_do_not_use_default_timeout() -> None:
    """Every _run call for a hook-firing git command must pass an explicit timeout.

    checkout, commit, merge, push, and pull all fire bd hooks against the
    networked Dolt server; the 60s metadata default is not enough. An
    audit-by-command-name that silently reclassified these back to the
    default is exactly how the v0.14.0 defect was introduced — this test
    pins the classification in code so the next audit cannot undo it
    without a test failure to answer for.
    """
    src = _Path(release.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    hook_firing = {"checkout", "commit", "merge", "push", "pull"}

    def _first_git_verb(call: ast.Call) -> str | None:
        if not call.args:
            return None
        first = call.args[0]
        if not isinstance(first, ast.List) or len(first.elts) < 2:
            return None
        head, verb = first.elts[0], first.elts[1]
        if not (isinstance(head, ast.Constant) and head.value == "git"):
            return None
        if not (isinstance(verb, ast.Constant) and isinstance(verb.value, str)):
            return None
        return verb.value

    def _run_name(call: ast.Call) -> str | None:
        f = call.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
        return None

    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _run_name(node) != "_run":
            continue
        verb = _first_git_verb(node)
        if verb not in hook_firing:
            continue
        # Presence of `timeout=` is not enough. _GIT_NETWORK_TIMEOUT is 300s,
        # exactly the beads hook ceiling with no headroom, so a call site set
        # to it would pass a presence check and still reintroduce the hang
        # this test exists to prevent. Pin the identifier, not the keyword.
        budget: str | None = None
        for kw in node.keywords:
            if kw.arg == "timeout" and isinstance(kw.value, ast.Name):
                budget = kw.value.id
            elif kw.arg == "timeout":
                budget = "<non-name expression>"
        if budget != "_GIT_HOOK_TIMEOUT":
            offenders.append((node.lineno, f"{verb} (timeout={budget})"))

    assert offenders == [], (
        "hook-firing git commands must use timeout=_GIT_HOOK_TIMEOUT — a bare "
        "`timeout=` or any other budget is not sufficient, because the hook's "
        f"own ceiling is 300s: {offenders}"
    )


def test_run_release_converts_timeout_expired_to_diagnosed_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A TimeoutExpired from any phase must exit cleanly, not traceback.

    The signature change prevents new call sites inheriting the wrong
    budget; this test pins the containment side of the fix — if some
    call site forgets to opt into a longer timeout, run_release still
    surfaces the hang as a diagnosis naming the command that timed out,
    the phase it was in, and the exact --resume-from string to retry with.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", _fake_which)

    hung_cmd = ["git", "fetch", "origin"]

    def fake_preflight(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(hung_cmd, 300)

    monkeypatch.setattr(release_mod, "_phase1_preflight", fake_preflight)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", dry_run=False)

    assert exc_info.value.code == 1
    # Rich wraps at the terminal width, so a bare "--resume-from preflight"
    # substring check would fail on the newline between the two tokens.
    # Collapse whitespace before asserting.
    normalized = " ".join(capsys.readouterr().out.split())
    assert "git fetch origin" in normalized
    assert "300s" in normalized
    assert "--resume-from" in normalized

    # The message must name the phase (not a <placeholder>) and hand the
    # operator the exact --resume-from value.  Advice with a placeholder is
    # advice that is not actionable, and resuming from the wrong phase
    # skips a gate.
    assert "phase 1 (preflight)" in normalized
    assert "--resume-from preflight" in normalized

    # And the suggested value must be a real member of PHASE_NAMES — this is
    # what stops the message drifting into naming a phase that does not
    # exist for --resume-from to accept.
    suggested = "preflight"
    assert suggested in PHASE_NAMES
    assert _phase_name(1) == suggested


def test_run_release_default_timeout_fallback_diagnoses_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A call site that forgot to opt into a named budget (falling through to
    DEFAULT_RUN) must still diagnose cleanly when it genuinely hangs.

    Unlike the fabricated-timeout test above (which forces a 300s
    GIT_NETWORK-budgeted timeout via a patched phase), this forces a
    TimeoutExpired at an actual call site that passes no ``timeout=`` at
    all — Phase 1's very first command, `git branch --show-current` — so
    the diagnosis is pinned to the genuine DEFAULT_RUN fallback value, not
    a named budget (matrix row 54).
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    hung_cmd = ["git", "branch", "--show-current"]

    def fake_run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = _DEFAULT_RUN_TIMEOUT,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cmd == hung_cmd and timeout == _DEFAULT_RUN_TIMEOUT:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return _run(cmd, cwd=cwd, timeout=timeout, check=check, capture=capture)

    monkeypatch.setattr(release_mod, "_run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", dry_run=False)

    assert exc_info.value.code == 1
    normalized = " ".join(capsys.readouterr().out.split())
    assert "git branch --show-current" in normalized
    assert f"{_DEFAULT_RUN_TIMEOUT}s" in normalized
    assert "phase 1 (preflight)" in normalized
    assert "--resume-from preflight" in normalized


def test_run_release_credits_propagate_when_resuming_from_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A P10 hang while resuming past P9 must diagnose as propagate.

    When ``start == 10``, ``_run_phases_9_10`` runs phase 10 alone on
    the main thread — the thread-boundary rationale for crediting phase
    9 does not apply. Naming this hang ``post-release`` and telling the
    operator ``--resume-from post-release`` would re-run phase 9,
    which is the exact contract failure the phase-in-diagnosis fix
    exists to close.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", _fake_which)

    hung_cmd = ["gh", "pr", "merge", "42", "--squash"]

    def fake_run_phases_9_10(
        _info: object, _version: str, *, dry_run: bool, start: int
    ) -> None:
        # Sanity: exercised only in the start == 10 path.
        assert start == 10
        assert dry_run is False
        raise subprocess.TimeoutExpired(hung_cmd, 300)

    monkeypatch.setattr(release_mod, "_run_phases_9_10", fake_run_phases_9_10)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", dry_run=False, resume_from="propagate")

    assert exc_info.value.code == 1
    normalized = " ".join(capsys.readouterr().out.split())
    assert "phase 10 (propagate)" in normalized
    assert "post-release" not in normalized
    assert "--resume-from propagate" in normalized
    assert "propagate" in PHASE_NAMES
    assert _phase_name(10) == "propagate"


def test_run_release_runs_verify_after_propagation_failure_then_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """pkit-d7mz: Phase 11 still runs and reports after a Phase 9/10 failure,
    and the release exits non-zero naming the phase to resume from.

    Reproduces the vox v5.0.4 shape at the orchestration level: P10 fails
    while running concurrently with P9. The pipeline must not silently stop
    there — Phase 11 verify has to run against the actual state, and the
    release has to fail loudly with --resume-from post-release (which
    re-enters both P9 and P10 concurrently, matching how they failed), not
    --resume-from verify, which would never retry the propagation that
    verify's own checks are reporting on.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", _fake_which)

    def fake_phase9(_info: object, _version: str, *, dry_run: bool) -> None:
        return None

    def fake_phase10(_info: object, _version: str, *, dry_run: bool) -> None:
        raise ReleaseError("marketplace: no entry for proj")

    verify_calls: list[str] = []

    def fake_phase11_verify(_info: object, version: str, *, dry_run: bool) -> None:
        verify_calls.append(version)

    monkeypatch.setattr(release_mod, "_phase9_post_release", fake_phase9)
    monkeypatch.setattr(release_mod, "_phase10_propagate", fake_phase10)
    monkeypatch.setattr(release_mod, "_phase11_verify", fake_phase11_verify)

    with pytest.raises(SystemExit) as exc_info:
        run_release(
            str(root), version="0.2.0", dry_run=False, resume_from="post-release"
        )

    assert exc_info.value.code == 1
    # Phase 11 ran despite the P9/P10 failure — this is the whole point.
    assert verify_calls == ["0.2.0"]

    normalized = " ".join(capsys.readouterr().out.split())
    assert "did not fully land" in normalized
    assert "Phase 9 reported" in normalized
    assert "marketplace: no entry for proj" in normalized
    assert "Not confirmed landed: post-release, propagate, verify" in normalized
    assert "--resume-from post-release" in normalized


def test_run_release_reports_incomplete_release_on_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """pkit-d7mz: an interrupted release exits non-zero naming exactly what
    was not confirmed landed and the --resume-from command to finish.

    Before this fix, the interrupt path in run_release's ``finally`` printed
    only "Cleaning up after interrupt..." — no phase, no unlanded list, no
    --resume-from hint. That silence is what let an operator's Ctrl-C during
    a Phase 4/10 check-wait hang go unresolved without anyone noticing the
    release was left mid-flight.
    """
    from punt_kit import release as release_mod

    root = _make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", _fake_which)

    def fake_ci_wait(_info: object, _version: str, *, dry_run: bool) -> None:
        release_mod._interrupted.set()  # pyright: ignore[reportPrivateUsage]
        raise KeyboardInterrupt()

    def _noop_reset(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(release_mod, "_phase6_ci_wait", fake_ci_wait)
    monkeypatch.setattr(release_mod, "_reset_propagation_siblings", _noop_reset)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", dry_run=False, resume_from="ci")

    assert exc_info.value.code == 1
    normalized = " ".join(capsys.readouterr().out.split())
    assert "Release incomplete" in normalized
    assert "phase 6 (ci)" in normalized
    assert "Not confirmed landed:" in normalized
    assert "--resume-from ci" in normalized


def test_phase_name_round_trips_through_phase_names() -> None:
    """Every phase number 1..N round-trips through PHASE_NAMES.

    The TimeoutExpired diagnosis hands the operator ``--resume-from
    <phase_name>``; if _phase_name ever produced a string that is not a
    key of PHASE_NAMES, that advice would fail at the very next command.
    Out-of-range numbers must fall through to 'unknown' rather than
    fabricating a name.
    """
    for phase_num in range(1, 12):
        name = _phase_name(phase_num)
        assert name != "unknown"
        assert name in PHASE_NAMES
        assert PHASE_NAMES[name] == phase_num

    # 0 (nothing started yet) and out-of-range numbers must not fabricate.
    assert _phase_name(0) == "unknown"
    assert _phase_name(12) == "unknown"
    assert _phase_name(-1) == "unknown"


def _graphql_null_rollup_response() -> dict[str, object]:
    """A real GitHub response for a PR whose commit has no checks yet.

    GitHub returns ``statusCheckRollup: null`` until the first check run is
    attached. This is what every freshly-opened PR returns for the first
    few seconds.
    """
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "commits": {"nodes": [{"commit": {"statusCheckRollup": None}}]}
                }
            }
        }
    }


def test_wait_for_required_checks_reports_no_checks_yet_not_a_malformed_response(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A null rollup is the normal pre-registration state, not an anomaly.

    This fired on every PR of every release — three propagation PRs plus
    the release and post-release PRs each logged it — because a null
    rollup was reaching a subscript and raising TypeError into the
    malformed-response handler. A warning that appears on every single
    run is not a warning; it teaches the operator to skim past the ones
    that matter.
    """
    from punt_kit import release as release_mod

    def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("punt_kit.release.time.sleep", _noop_sleep)

    calls = 0

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        nonlocal calls
        if _is_protection_call(cmd):
            return _protection_response(protected=True)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        calls += 1
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        # Checks appear only on the third poll, as they do in a real release.
        if calls < 3:
            result.stdout = json.dumps(_graphql_null_rollup_response())
        else:
            result.stdout = json.dumps(
                _graphql_checks_response(
                    [
                        {
                            "name": "lint",
                            "isRequired": True,
                            "conclusion": "SUCCESS",
                            "status": "COMPLETED",
                        }
                    ]
                )
            )
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)

    _wait_for_required_checks("gh", "/tmp", 42)

    out = " ".join(capsys.readouterr().out.split())
    assert "No checks registered on the commit yet" in out
    assert "Unexpected GraphQL response structure" not in out, (
        "a null rollup is the documented pre-registration state, not a "
        "malformed response"
    )
    assert calls == 3


def test_wait_for_required_checks_still_flags_a_genuinely_malformed_response(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Naming the null-rollup case must not silence real structure errors."""
    from punt_kit import release as release_mod

    def _noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("punt_kit.release.time.sleep", _noop_sleep)

    calls = 0

    def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
        nonlocal calls
        if _is_protection_call(cmd):
            return _protection_response(protected=True)
        if _is_ruleset_call(cmd):
            return _ruleset_response(governed=False)
        calls += 1
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        if calls < 2:
            # Shape GitHub never sends: pullRequest present, commits absent.
            result.stdout = json.dumps({"data": {"repository": {"pullRequest": {}}}})
        else:
            result.stdout = json.dumps(
                _graphql_checks_response(
                    [
                        {
                            "name": "lint",
                            "isRequired": True,
                            "conclusion": "SUCCESS",
                            "status": "COMPLETED",
                        }
                    ]
                )
            )
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)

    _wait_for_required_checks("gh", "/tmp", 42)

    out = " ".join(capsys.readouterr().out.split())
    assert "Unexpected GraphQL response structure" in out


def test_shell_scripts_that_fire_hooks_are_invoked_with_the_hook_budget() -> None:
    """A script that runs hook-firing git commands needs the hook budget too.

    The sibling audit inspects `_run(["git", ...])` calls directly, which
    makes a script invisible to it: `_run(["bash", script])` runs git one
    level down, so the call site inherits the 60s metadata default while
    the work behind it fires the bd pre-commit and post-checkout hooks
    that allow themselves 300s. That gap is how release-plugin.sh and
    restore-dev-plugin.sh kept the short budget after the commits inside
    them started running hooks.

    The rule is deliberately broad — every `_run(["bash", ...])` must
    carry the budget — because the script path arrives as a variable and
    cannot be resolved statically. Over-budgeting a fast script costs
    nothing: the timeout is a ceiling, not a wait. Under-budgeting one
    aborts a release.
    """
    src = _Path(release.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Every shell script the release path invokes lives here and is checked
    # for hook-firing git verbs, so the rule below is grounded in what the
    # scripts actually do rather than assumed.
    scripts_dir = _Path(release.__file__).parent.parent.parent / "scripts"
    # The scripts call `git -C "$REPO_ROOT" commit`, so a literal "git commit"
    # never matches — the verb is separated from `git` by the -C flag.
    hook_verb_re = re.compile(r"\bgit\b[^\n]*\b(commit|checkout|merge|push|pull)\b")
    hook_firing_scripts = sorted(
        p.name
        for p in scripts_dir.glob("*.sh")
        if hook_verb_re.search(p.read_text(encoding="utf-8"))
    )
    assert hook_firing_scripts, (
        "expected at least one release script to run hook-firing git commands; "
        "if that is no longer true this audit needs revisiting, not deleting"
    )

    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "_run" or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.List) or not first.elts:
            continue
        head = first.elts[0]
        if not (isinstance(head, ast.Constant) and head.value == "bash"):
            continue
        budget = None
        for kw in node.keywords:
            if kw.arg == "timeout":
                budget = kw.value.id if isinstance(kw.value, ast.Name) else "<expr>"
        if budget != "_GIT_HOOK_TIMEOUT":
            offenders.append((node.lineno, f"timeout={budget}"))

    assert offenders == [], (
        "shell scripts invoked by the release path run hook-firing git "
        f"commands ({', '.join(hook_firing_scripts)}) and must be given "
        f"timeout=_GIT_HOOK_TIMEOUT: {offenders}"
    )


# --- SIGINT during Phase 10 with a worker live inside the check-wait poll ---
#
# The DES-029 incident mechanism: a Phase 10 propagator worker sits in
# RequiredChecksWaiter.wait's poll loop when the operator interrupts. Only the
# main thread ever receives the signal, so the worker learns about it solely
# through the `interrupted.is_set()` check at the top of each poll iteration —
# and until it does, ThreadPoolExecutor.__exit__'s shutdown(wait=True) cannot
# return. These scenarios hold a worker genuinely mid-poll against a
# pending-forever GraphQL fake (never released early) and prove the interrupt
# check is what unblocks the join.


_POLL_BRANCH = "propagate/v0.2.0-proj-public-website"


def _interrupted_poll_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, FaultRule, FaultRule]:
    """A project + website sibling whose one live Phase 10 leg blocks mid-poll.

    The website propagator reaches ``RequiredChecksWaiter.wait`` against a
    pending-forever required-checks fake: three unarmed pending polls first
    (proving the loop is genuinely iterating, not started-and-idle), then a
    ``times=None`` pending rule armed with ``interrupt_after`` on
    ``release._interrupted`` — the rule-anchored stand-in for the signal
    handler's ``_interrupted.set()``, firing while the worker is mid-loop. The
    fake never leaves the pending state; the only exits from the loop are the
    interrupt check, or (regression) the deadline — shrunk from two hours to
    seconds here so a broken interrupt check fails the test instead of
    hanging it. Returns ``(project_root, warmup_rule, pending_forever_rule)``.
    """
    root = _make_release_project(tmp_path)
    # A python-only project: the marketplace leg no-ops, the .github leg
    # skips (no sibling), leaving the website leg as the one live worker.
    shutil.rmtree(root / ".claude-plugin")
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=str(root),
    )
    projects = [{"id": "proj", "version": "0.1.0", "githubUrl": ""}]
    _make_sibling(
        tmp_path,
        "public-website",
        {"src/data/projects.json": json.dumps(projects, indent=2) + "\n"},
    )

    monkeypatch.setattr(shutil, "which", _fake_which)
    monkeypatch.setattr(release, "_get_github_repo", _fake_get_github_repo)
    # Near-zero poll interval (the shared `time` singleton reaches gh.py), and
    # a seconds-scale deadline so a regressed interrupt check times the loop
    # out instead of spinning for the full two-hour CI_WATCH.
    real_sleep = time.sleep

    def _near_zero_sleep(_seconds: float) -> None:
        real_sleep(0.001)

    monkeypatch.setattr("punt_kit.release.time.sleep", _near_zero_sleep)
    monkeypatch.setattr("punt_kit.phases.shared.gh.CI_WATCH", 30)

    warmup = FaultRule(
        match=["gh", "api", "graphql"],
        times=3,
        response=FaultRule.from_fixture("gh_graphql_required_checks_pending.json"),
    )
    pending_forever = FaultRule(
        match=["gh", "api", "graphql"],
        times=None,
        response=FaultRule.from_fixture("gh_graphql_required_checks_pending.json"),
    )
    pending_forever.interrupt_after(
        release._interrupted  # pyright: ignore[reportPrivateUsage]
    )
    ops = FaultInjectingOps(
        real_run=_run,
        rules=[
            # The sibling's origin is itself (non-bare), which refuses a push
            # of its own checked-out branch — scripted success keeps the merge
            # flow moving toward the check wait.
            FaultRule(
                match=["git", "push", "-u", "origin", _POLL_BRANCH],
                response=CompletedProcessSpec(),
            ),
            FaultRule(
                match=["gh", "pr", "list"],
                response=FaultRule.from_fixture("gh_pr_list_empty.json"),
            ),
            FaultRule(
                match=["gh", "pr", "create"],
                response=FaultRule.from_fixture("gh_pr_create_success.json"),
            ),
            FaultRule(
                match=[
                    "gh",
                    "api",
                    "repos/punt-labs/punt-kit/branches/main/protection",
                ],
                response=FaultRule.from_fixture(
                    "gh_api_branch_protection_protected.json"
                ),
            ),
            FaultRule(
                match=["gh", "api", "repos/punt-labs/punt-kit/rules/branches/main"],
                response=FaultRule.from_fixture(
                    "gh_api_rules_branches_ungoverned.json"
                ),
            ),
            warmup,
            pending_forever,
        ],
    )
    monkeypatch.setattr(release, "_run", ops.run)
    return root, warmup, pending_forever


def test_phase10_interrupt_with_worker_mid_poll_join_returns_promptly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A worker held mid-poll observes the interrupt and unblocks the join.

    Reproduces the DES-029 mechanism directly: the website propagator worker
    inside Phase 10's own ThreadPoolExecutor is genuinely mid-iteration in
    ``RequiredChecksWaiter.wait`` when the interrupt event is set. Phase 10's
    executor ``__exit__`` can only return once that worker stops polling, and
    ``_phase10_propagate`` can only finish after that join — so the bounded
    ``future.result(timeout=...)`` below IS the join-promptness assertion: it
    passes within seconds only because the worker's ``interrupted.is_set()``
    check fired, while the fake it polls would have stayed pending for the
    entire deadline.
    """
    root, warmup, pending_forever = _interrupted_poll_scenario(tmp_path, monkeypatch)
    info = detect(root)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_phase10_propagate, info, "0.2.0", dry_run=False)
        # ThreadedStep.collect raises KeyboardInterrupt once the workers
        # drain with the interrupt event set. Bounded: a regressed interrupt
        # check fails here in 10s (and the scenario's shrunk deadline then
        # releases the pool worker) instead of hanging the suite.
        with pytest.raises(KeyboardInterrupt):
            future.result(timeout=10.0)

    out = " ".join(capsys.readouterr().out.split())
    # The loop exited through its interrupt check, not the deadline.
    assert "Interrupted while waiting for CI checks on PR #123" in out
    assert "Timed out waiting" not in out
    # The worker was genuinely mid-loop: three full pending iterations before
    # the armed rule fired, exactly one consumption after — the next
    # iteration's interrupt check stopped the loop before another poll, with
    # the fake still pending (it has no other state to serve).
    assert warmup._consumed == 3  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
    assert pending_forever._consumed == 1  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001


def test_run_release_interrupt_mid_poll_reports_incomplete_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An interrupt observed mid-poll ends in the incomplete-release report.

    The same live-worker scenario, driven through ``run_release`` exactly as
    the DES-029 incident ran: ``--resume-from propagate`` puts Phase 10 on
    the main thread with its propagators on pool workers. The
    KeyboardInterrupt that ``ThreadedStep.collect`` raises once the
    interrupted worker drains must reach ``run_release``'s cleanup, which
    resets propagation siblings and prints where the release stopped, what is
    not confirmed landed, and the exact resume command. The existing
    reporting test fakes the interrupting phase outright; this one earns the
    same report from a worker genuinely blocked in the poll loop.
    """
    root, warmup, pending_forever = _interrupted_poll_scenario(tmp_path, monkeypatch)

    started = time.monotonic()
    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", dry_run=False, resume_from="propagate")
    elapsed = time.monotonic() - started

    assert exc_info.value.code == 1
    # Prompt: the run ends within seconds of the interrupt, not after the
    # (shrunk) poll deadline — the join was released by the interrupt check.
    assert elapsed < 10.0
    out = " ".join(capsys.readouterr().out.split())
    assert "Interrupted while waiting for CI checks on PR #123" in out
    assert "Cleaning up after interrupt..." in out
    assert "Release incomplete" in out
    assert "phase 10 (propagate)" in out
    assert "Not confirmed landed: propagate, verify" in out
    assert "--resume-from propagate" in out
    assert warmup._consumed == 3  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
    assert pending_forever._consumed == 1  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001


def test_run_release_interrupt_mid_propagation_restores_owned_file_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The interrupt path itself restores a sibling's mid-write residue.

    Phase 10 writes its owned file *before* branching; an interrupt between
    the two leaves the sibling on main with the write on disk (the v0.14.0
    residue). Distinct from the next-run auto-recovery at Phase 10 entry:
    here the residue is created *after* that entry reset has already run, so
    only ``run_release``'s interrupt cleanup —
    ``_reset_propagation_siblings(..., fail_on_error=False)`` — can be what
    restores it, and the spy proves that call happened with the residue
    present and ``fail_on_error=False``.
    """
    root = _make_release_project(tmp_path)
    shutil.rmtree(root / ".claude-plugin")
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/proj.git"],
        cwd=str(root),
    )
    projects = [{"id": "proj", "version": "0.1.0", "githubUrl": ""}]
    sibling = _make_sibling(
        tmp_path,
        "public-website",
        {"src/data/projects.json": json.dumps(projects, indent=2) + "\n"},
    )
    projects_json = sibling / "src" / "data" / "projects.json"
    original = projects_json.read_text()

    real_reset = release._reset_propagation_siblings  # pyright: ignore[reportPrivateUsage]
    reset_calls: list[tuple[bool, bool]] = []

    def spying_reset(info: ProjectInfo, *, fail_on_error: bool = True) -> None:
        residue_present = "0.2.0" in projects_json.read_text()
        reset_calls.append((fail_on_error, residue_present))
        real_reset(info, fail_on_error=fail_on_error)

    monkeypatch.setattr(release, "_reset_propagation_siblings", spying_reset)

    # The interrupt arrives after the owned-file write: the propagator's
    # dirty-check returns (arming the interrupt event exactly as the signal
    # handler would set it), then the branch creation dies the way the
    # v0.14.0 incident's did — a checkout that never returns.
    status_rule = FaultRule(
        match=["git", "status", "--porcelain", "--", "src/data/projects.json"],
        response=CompletedProcessSpec(stdout=" M src/data/projects.json\n"),
    )
    status_rule.interrupt_after(
        release._interrupted  # pyright: ignore[reportPrivateUsage]
    )
    checkout_rule = FaultRule(
        match=["git", "checkout", "-b"],
        raises=subprocess.TimeoutExpired(cmd=["git", "checkout", "-b"], timeout=600),
    )
    ops = FaultInjectingOps(real_run=_run, rules=[status_rule, checkout_rule])
    monkeypatch.setattr(release, "_run", ops.run)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", dry_run=False, resume_from="propagate")

    assert exc_info.value.code == 1
    # First call: Phase 10's entry auto-recovery, before any residue exists.
    # Second: the interrupt path — fail_on_error=False, residue on disk.
    assert reset_calls == [(True, False), (False, True)]
    assert projects_json.read_text() == original
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(sibling),
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout.strip() == "", "sibling should be clean after the reset"
    out = " ".join(capsys.readouterr().out.split())
    assert "Cleaning up after interrupt..." in out
    assert "Restoring propagation-owned files in sibling public-website" in out
    assert "Release incomplete" in out
    assert "phase 10 (propagate)" in out
    assert "--resume-from propagate" in out
