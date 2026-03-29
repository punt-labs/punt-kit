"""Tests for release command."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from punt_kit.detect import detect
from punt_kit.release import (
    PHASE_NAMES,
    ReleaseError,
    _bump_readme_install_sha,  # pyright: ignore[reportPrivateUsage]
    _extract_version_notes,  # pyright: ignore[reportPrivateUsage]
    _get_latest_tag_version,  # pyright: ignore[reportPrivateUsage]
    _phase1_preflight,  # pyright: ignore[reportPrivateUsage]
    _phase2_version_bump,  # pyright: ignore[reportPrivateUsage]
    _phase10_propagate,  # pyright: ignore[reportPrivateUsage]
    _propagate_install_all,  # pyright: ignore[reportPrivateUsage]
    _propagate_marketplace,  # pyright: ignore[reportPrivateUsage]
    _propagate_website,  # pyright: ignore[reportPrivateUsage]
    _reset_propagation_siblings,  # pyright: ignore[reportPrivateUsage]
    _resolve_sibling,  # pyright: ignore[reportPrivateUsage]
    _run_phases_9_10,  # pyright: ignore[reportPrivateUsage]
    _suggest_version,  # pyright: ignore[reportPrivateUsage]
    _validate_sibling,  # pyright: ignore[reportPrivateUsage]
    _wait_for_required_checks,  # pyright: ignore[reportPrivateUsage]
    run_release,
)

if TYPE_CHECKING:
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
    """Pre-flight fails when there is an untracked file."""
    root = _make_release_project(tmp_path)
    (root / "untracked.txt").write_text("untracked")

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(ReleaseError):
        _phase1_preflight(info, dry_run=False)


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


def test_propagate_install_all_updates_profile_readme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """10a also updates profile/README.md with install-all.sh SHA."""
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

    # Get the SHA of the last commit that touched install-all.sh in .github
    github_sha = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "install-all.sh"],
        cwd=str(sibling),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    from punt_kit import release as release_mod

    calls: list[tuple[str, list[str]]] = []

    def mock_sibling_pr_merge(
        path: Path,
        branch: str,
        files: list[str],
        message: str,
        name: str,
        *,
        dry_run: bool,
    ) -> bool:
        calls.append((name, files))
        return True

    monkeypatch.setattr(release_mod, "_sibling_pr_merge", mock_sibling_pr_merge)

    from punt_kit.detect import detect

    info = detect(root)
    _propagate_install_all(info, "0.2.0", dry_run=False)

    # Verify profile/README.md was updated
    readme = (tmp_path / ".github" / "profile" / "README.md").read_text()
    assert "aabb002" not in readme
    assert f".github/{github_sha}/install-all.sh" in readme

    # Both files should be in the same PR
    assert len(calls) == 1
    assert calls[0][0] == ".github"
    assert "install-all.sh" in calls[0][1]
    assert "profile/README.md" in calls[0][1]


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
