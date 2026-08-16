"""Tests for release command."""

from __future__ import annotations

import ast
import inspect
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path as _Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from punt_kit import release
from punt_kit.detect import detect
from punt_kit.release import (
    _DEFAULT_RUN_TIMEOUT,  # pyright: ignore[reportPrivateUsage]
    _GIT_HOOK_TIMEOUT,  # pyright: ignore[reportPrivateUsage]
    PHASE_NAMES,
    ReleaseError,
    _bump_readme_install_sha,  # pyright: ignore[reportPrivateUsage]
    _extract_version_notes,  # pyright: ignore[reportPrivateUsage]
    _get_latest_tag_version,  # pyright: ignore[reportPrivateUsage]
    _phase1_preflight,  # pyright: ignore[reportPrivateUsage]
    _phase2_version_bump,  # pyright: ignore[reportPrivateUsage]
    _phase6_ci_wait,  # pyright: ignore[reportPrivateUsage]
    _phase10_propagate,  # pyright: ignore[reportPrivateUsage]
    _phase_name,  # pyright: ignore[reportPrivateUsage]
    _pr_merge,  # pyright: ignore[reportPrivateUsage]
    _propagate_install_all,  # pyright: ignore[reportPrivateUsage]
    _propagate_marketplace,  # pyright: ignore[reportPrivateUsage]
    _propagate_website,  # pyright: ignore[reportPrivateUsage]
    _reset_propagation_siblings,  # pyright: ignore[reportPrivateUsage]
    _resolve_sibling,  # pyright: ignore[reportPrivateUsage]
    _run,  # pyright: ignore[reportPrivateUsage]
    _run_phases_9_10,  # pyright: ignore[reportPrivateUsage]
    _select_existing_pr,  # pyright: ignore[reportPrivateUsage]
    _suggest_version,  # pyright: ignore[reportPrivateUsage]
    _TagRunSelector,  # pyright: ignore[reportPrivateUsage]
    _validate_sibling,  # pyright: ignore[reportPrivateUsage]
    _wait_for_required_checks,  # pyright: ignore[reportPrivateUsage]
    run_release,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _git(args: list[str], cwd: str) -> None:
    """Run a git command with standard options."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


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


def _make_release_project(tmp_path: Path) -> Path:
    """Create a minimal Python project ready for release testing."""
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

    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir()
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


# --- phase 2 version bump ---


def test_version_bump_updates_all_files(tmp_path: Path) -> None:
    """Version bump updates all version locations."""
    root = _make_release_project(tmp_path)

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
    pj = root / ".claude-plugin" / "plugin.json"
    plugin_data = json.loads(pj.read_text())
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


def test_phase9_commit_excludes_untracked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The post-release README commit stages only README.md."""
    from punt_kit import release as release_mod
    from punt_kit.release import (
        _phase9_post_release,  # pyright: ignore[reportPrivateUsage]
    )

    root = _make_release_project(tmp_path)
    d = str(root)

    # README with a URL matching the repo directory name so the SHA bump fires
    (root / "README.md").write_text(
        "# proj\n\n```bash\n"
        "curl -fsSL https://raw.githubusercontent.com/"
        "punt-labs/proj/abc1234/install.sh | sh\n"
        "```\n"
    )
    # Plugin already in dev state ("test-dev") so the dev restore is skipped
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "matching readme"], cwd=d)

    (root / "stray-transcript.jsonl").write_text("{}\n")

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

    from punt_kit.detect import detect

    info = detect(root)
    _phase9_post_release(info, "0.2.0", dry_run=False)

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

    d = str(root)
    _git(["add", "."], cwd=d)
    _git(["commit", "-m", "scaffold"], cwd=d)
    _git(["tag", "v0.1.0"], cwd=d)
    _git(["fetch", "origin"], cwd=d)

    original_changelog = (root / "CHANGELOG.md").read_text()

    run_release(str(root), version="0.2.0", dry_run=True)

    assert (root / "CHANGELOG.md").read_text() == original_changelog


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
                    "repo": "https://github.com/punt-labs/proj",
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


def test_pure_plugin_detected_correctly(tmp_path: Path) -> None:
    """Pure plugin has is_plugin=True but is_hybrid=False."""
    root = _make_pure_plugin_project(tmp_path)
    info = detect(root)
    assert info.is_plugin is True
    assert info.is_hybrid is False


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
        call_count += 1
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(_graphql_checks_response(check_nodes))
        result.stderr = ""
        return result

    monkeypatch.setattr(release_mod, "_run", fake_run)
    monkeypatch.setattr(release_mod, "_get_github_repo", _fake_get_github_repo)
    _wait_for_required_checks("gh", "/tmp", 42)
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

    assert sha == "abc1234"
    created = [c for c in issued if c[:3] == ["gh", "pr", "create"]]
    assert not created
    assert waited == []


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

    assert sha == "abc1234"
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
                                "repo": "punt-labs/proj",
                                "ref": f"v{version}",
                            },
                        }
                    ]
                }
            ),
        },
    )

    return root, sibling


def test_phase11_verify_profile_sha_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile SHA check passes when README contains a resolvable SHA."""
    from punt_kit import release as release_mod
    from punt_kit.release import (
        _phase11_verify,  # pyright: ignore[reportPrivateUsage]
    )

    version = "0.1.0"
    root, sibling = _setup_verify_project(tmp_path, version)

    # Get the real SHA of install-all.sh in the .github sibling
    sha = _get_install_all_sha(sibling)

    # Add profile/README.md with the real SHA
    profile_dir = sibling / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "README.md").write_text(
        "# Punt Labs\n\n"
        f"curl -fsSL https://raw.githubusercontent.com/punt-labs/.github/{sha}"
        "/install-all.sh | sh\n"
    )
    _git(["add", "profile/README.md"], cwd=str(sibling))
    _git(["commit", "-m", "add profile"], cwd=str(sibling))

    # Monkeypatch _run to intercept uv/pip calls that won't work in test
    original_run = release_mod._run  # pyright: ignore[reportPrivateUsage]

    def patched_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if "pip" in cmd and "index" in cmd:
            result = MagicMock()
            result.returncode = 0
            result.stdout = f"test-pkg ({version})"
            result.stderr = ""
            return result
        return original_run(cmd, **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(release_mod, "_run", patched_run)

    info = detect(root)

    # Should NOT raise — all checks pass including profile SHA
    _phase11_verify(info, version, dry_run=False)


def test_phase11_verify_profile_sha_fails_bad_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profile SHA check fails when README contains a non-resolvable SHA."""
    from punt_kit import release as release_mod
    from punt_kit.release import (
        _phase11_verify,  # pyright: ignore[reportPrivateUsage]
    )

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

    # Monkeypatch _run to intercept uv/pip calls
    original_run = release_mod._run  # pyright: ignore[reportPrivateUsage]

    def patched_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if "pip" in cmd and "index" in cmd:
            result = MagicMock()
            result.returncode = 0
            result.stdout = f"test-pkg ({version})"
            result.stderr = ""
            return result
        return original_run(cmd, **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(release_mod, "_run", patched_run)

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
    from punt_kit import release as release_mod
    from punt_kit.release import (
        _phase11_verify,  # pyright: ignore[reportPrivateUsage]
    )

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

    original_run = release_mod._run  # pyright: ignore[reportPrivateUsage]

    def patched_run(cmd: list[str], **kwargs: object) -> MagicMock:
        if "pip" in cmd and "index" in cmd:
            result = MagicMock()
            result.returncode = 0
            result.stdout = f"test-pkg ({version})"
            result.stderr = ""
            return result
        return original_run(cmd, **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(release_mod, "_run", patched_run)

    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase11_verify(info, version, dry_run=False)


# --- restore-dev-plugin.sh ---

# Path to the real restore-dev-plugin.sh script
_RESTORE_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir,
    "scripts",
    "restore-dev-plugin.sh",
)


def _install_restore_script(root: Path) -> None:
    """Copy the real restore-dev-plugin.sh into a test repo."""
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    dest = scripts_dir / "restore-dev-plugin.sh"
    with open(_RESTORE_SCRIPT) as f:
        dest.write_text(f.read())
    dest.chmod(0o755)


def test_restore_dev_plugin_finds_dev_commit_past_head1(tmp_path: Path) -> None:
    """restore-dev-plugin.sh finds dev state even when HEAD~1 is unrelated.

    Simulates the scenario where multiple PRs merge between the release swap
    and Phase 9 (post-release), so HEAD~1 no longer has the dev plugin state.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init_git_repo(root)
    d = str(root)

    # Create dev plugin state
    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "test-dev", "version": "0.1.0"}, indent=2) + "\n"
    )
    commands_dir = root / "commands"
    commands_dir.mkdir()
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

    def fake_run(_cmd: list[str], **_kwargs: object) -> MagicMock:
        nonlocal calls
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

    def fake_run(_cmd: list[str], **_kwargs: object) -> MagicMock:
        nonlocal calls
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
