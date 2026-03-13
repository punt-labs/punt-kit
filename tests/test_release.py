"""Tests for release command."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from punt_kit.release import (
    PHASE_NAMES,
    _bump_readme_install_sha,  # pyright: ignore[reportPrivateUsage]
    _extract_version_notes,  # pyright: ignore[reportPrivateUsage]
    _get_latest_tag_version,  # pyright: ignore[reportPrivateUsage]
    _phase1_preflight,  # pyright: ignore[reportPrivateUsage]
    _phase2_version_bump,  # pyright: ignore[reportPrivateUsage]
    _propagate_install_all,  # pyright: ignore[reportPrivateUsage]
    _propagate_marketplace,  # pyright: ignore[reportPrivateUsage]
    _propagate_profile,  # pyright: ignore[reportPrivateUsage]
    _propagate_website,  # pyright: ignore[reportPrivateUsage]
    _resolve_sibling,  # pyright: ignore[reportPrivateUsage]
    _suggest_version,  # pyright: ignore[reportPrivateUsage]
    _validate_sibling,  # pyright: ignore[reportPrivateUsage]
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

    with pytest.raises(SystemExit):
        _phase1_preflight(info, dry_run=False)


def test_preflight_fails_untracked_file(tmp_path: Path) -> None:
    """Pre-flight fails when there is an untracked file."""
    root = _make_release_project(tmp_path)
    (root / "untracked.txt").write_text("untracked")

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(SystemExit):
        _phase1_preflight(info, dry_run=False)


def test_preflight_fails_wrong_branch(tmp_path: Path) -> None:
    """Pre-flight fails when not on main branch."""
    root = _make_release_project(tmp_path)
    _git(["checkout", "-b", "feature"], cwd=str(root))

    from punt_kit.detect import detect

    info = detect(root)

    with pytest.raises(SystemExit):
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

    with pytest.raises(SystemExit):
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

    with pytest.raises(SystemExit):
        _validate_sibling(sibling, "sib")


def test_validate_sibling_fails_dirty(tmp_path: Path) -> None:
    """Fails when sibling has uncommitted changes."""
    sibling = _make_sibling(tmp_path, "sib", {})
    (sibling / "dirty.txt").write_text("dirty")
    _git(["add", "dirty.txt"], cwd=str(sibling))

    with pytest.raises(SystemExit):
        _validate_sibling(sibling, "sib")


# --- Phase 10a: install-all.sh ---


def test_propagate_install_all_updates_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Updates project SHA in install-all.sh."""
    root = _make_release_project(tmp_path)
    d = str(root)

    # Create tag
    _git(["tag", "v0.2.0"], cwd=d)

    # Create punt-kit sibling with install-all.sh referencing this project
    _make_sibling(
        tmp_path,
        "punt-kit",
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

    calls: list[tuple[str, str]] = []

    def mock_sibling_pr_merge(
        path: Path,
        branch: str,
        files: list[str],
        message: str,
        name: str,
        *,
        dry_run: bool,
    ) -> bool:
        calls.append((name, message))
        return True

    monkeypatch.setattr(release_mod, "_sibling_pr_merge", mock_sibling_pr_merge)

    from punt_kit.detect import detect

    info = detect(root)
    _propagate_install_all(info, "0.2.0", dry_run=False)

    # Verify install-all.sh was updated (file content, before PR merge)
    content = (tmp_path / "punt-kit" / "install-all.sh").read_text()
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
    assert calls[0][0] == "punt-kit"


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

    # Create sibling with the SHA already set
    _make_sibling(
        tmp_path,
        "punt-kit",
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


# --- Phase 10c: profile ---


def test_propagate_profile_updates_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Updates profile README with punt-kit HEAD SHA."""
    root = _make_release_project(tmp_path)
    d = str(root)
    _git(
        [
            "remote",
            "set-url",
            "origin",
            "git@github.com:punt-labs/punt-kit.git",
        ],
        cwd=d,
    )

    _make_sibling(
        tmp_path,
        ".github",
        {
            "profile/README.md": (
                "# Punt Labs\n\n"
                "```bash\n"
                "curl -fsSL https://raw.githubusercontent.com/"
                "punt-labs/punt-kit/aabb001/install-all.sh | sh\n"
                "```\n"
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
    _propagate_profile(info, "0.2.0", dry_run=False)

    readme = (tmp_path / ".github" / "profile" / "README.md").read_text()
    assert "aabb001" not in readme
    head_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=d,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert f"punt-kit/{head_sha}/install-all.sh" in readme
    assert len(calls) == 1


def test_propagate_profile_skipped_for_non_punt_kit(tmp_path: Path) -> None:
    """No-op when releasing a project other than punt-kit."""
    root = _make_release_project(tmp_path)
    _git(
        ["remote", "set-url", "origin", "git@github.com:punt-labs/biff.git"],
        cwd=str(root),
    )

    from punt_kit.detect import detect

    info = detect(root)

    # Should not raise even without .github sibling
    _propagate_profile(info, "0.2.0", dry_run=False)


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


def test_phase_names_cover_all_phases() -> None:
    """All 11 phases are mapped (plus aliases)."""
    phase_numbers = set(PHASE_NAMES.values())
    assert phase_numbers == set(range(1, 12))


def test_phase_names_aliases() -> None:
    """Old name aliases resolve to correct phase numbers."""
    assert PHASE_NAMES["release"] == 4  # alias for release-pr
