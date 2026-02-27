"""Tests for pii command."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from punt_kit.pii import PiiConfig, load_config, run_pii, scan_file

if TYPE_CHECKING:
    from pathlib import Path


def _init_git(tmp_path: Path) -> None:
    """Initialize a git repo so get_files works."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(tmp_path),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        capture_output=True,
    )


def _add_and_commit(tmp_path: Path) -> None:
    """Stage all files and commit."""
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--allow-empty"],
        cwd=str(tmp_path),
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Email detection
# ---------------------------------------------------------------------------


def test_detects_email(tmp_path: Path) -> None:
    """Emails in file content are detected."""
    (tmp_path / "config.py").write_text('AUTHOR = "someone@personal.com"\n')
    config = PiiConfig()
    findings = scan_file("config.py", tmp_path, config)
    assert len(findings) == 1
    assert findings[0].category == "email"
    assert findings[0].match == "someone@personal.com"


def test_allows_noreply_emails(tmp_path: Path) -> None:
    """Built-in noreply emails are not flagged."""
    (tmp_path / "config.py").write_text(
        'CO_AUTHOR = "noreply@github.com"\n'
        'BOT = "user@users.noreply.github.com"\n'
        'EXAMPLE = "test@example.com"\n'
    )
    config = PiiConfig()
    findings = scan_file("config.py", tmp_path, config)
    assert len(findings) == 0


def test_allows_configured_emails(tmp_path: Path) -> None:
    """User-configured allow_emails suppresses matches."""
    (tmp_path / "config.py").write_text('ORG = "hello@punt-labs.com"\n')
    config = PiiConfig(allow_emails=["hello@punt-labs.com"])
    findings = scan_file("config.py", tmp_path, config)
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Home path detection
# ---------------------------------------------------------------------------


def test_detects_home_paths(tmp_path: Path) -> None:
    """Local home directory paths are detected."""
    (tmp_path / "script.sh").write_text("cd /Users/jfreeman/projects\n")
    config = PiiConfig()
    findings = scan_file("script.sh", tmp_path, config)
    assert len(findings) == 1
    assert findings[0].category == "path"
    assert "/Users/jfreeman/" in findings[0].match


def test_detects_linux_home_paths(tmp_path: Path) -> None:
    """Linux home directory paths are detected."""
    (tmp_path / "script.sh").write_text("cd /home/jfreeman/projects\n")
    config = PiiConfig()
    findings = scan_file("script.sh", tmp_path, config)
    assert len(findings) == 1
    assert findings[0].category == "path"


def test_allows_runner_paths(tmp_path: Path) -> None:
    """CI runner paths are not flagged."""
    (tmp_path / "ci.yml").write_text("workdir: /home/runner/work\n")
    config = PiiConfig()
    findings = scan_file("ci.yml", tmp_path, config)
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Hostname detection
# ---------------------------------------------------------------------------


def test_detects_hostname(tmp_path: Path) -> None:
    """user@host.local patterns are detected."""
    (tmp_path / "recording.txt").write_text("prompt: jfreeman@m2-mb-air.local\n")
    config = PiiConfig()
    findings = scan_file("recording.txt", tmp_path, config)
    assert len(findings) == 1
    assert findings[0].category == "hostname"


# ---------------------------------------------------------------------------
# Custom deny patterns
# ---------------------------------------------------------------------------


def test_detects_deny_patterns(tmp_path: Path) -> None:
    """Custom deny strings are flagged."""
    (tmp_path / "config.toml").write_text('author = "JF"\n')
    config = PiiConfig(deny=["JF"])
    findings = scan_file("config.toml", tmp_path, config)
    assert len(findings) == 1
    assert findings[0].category == "deny"
    assert findings[0].match == "JF"


# ---------------------------------------------------------------------------
# File filtering
# ---------------------------------------------------------------------------


def test_ignores_files(tmp_path: Path) -> None:
    """Files matching ignore_files globs are skipped in run_pii."""
    _init_git(tmp_path)
    (tmp_path / "data.lock").write_text("secret@email.com\n")
    (tmp_path / "clean.py").write_text("x = 1\n")
    # Config that ignores *.lock files
    (tmp_path / ".punt-pii.toml").write_text('ignore_files = ["*.lock"]\n')
    _add_and_commit(tmp_path)

    # scan_file should still find it if called directly (no filtering)
    config = PiiConfig(ignore_files=["*.lock"])
    findings = scan_file("data.lock", tmp_path, config)
    assert len(findings) == 1

    # run_pii should skip it via ignore_files and not raise SystemExit
    run_pii(str(tmp_path))


def test_binary_files_skipped(tmp_path: Path) -> None:
    """Binary files are skipped."""
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02secret@email.com")
    config = PiiConfig()
    findings = scan_file("image.bin", tmp_path, config)
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_loads_pyproject_config(tmp_path: Path) -> None:
    """Config is read from [tool.punt.pii] in pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.punt.pii]\n"
        'allow_emails = ["hello@org.com"]\n'
        'deny = ["secret-string"]\n'
        'ignore_files = ["*.lock"]\n'
    )
    config = load_config(tmp_path)
    assert config.allow_emails == ["hello@org.com"]
    assert config.deny == ["secret-string"]
    assert config.ignore_files == ["*.lock"]


def test_loads_standalone_config(tmp_path: Path) -> None:
    """Config is read from .punt-pii.toml when no pyproject.toml section."""
    (tmp_path / ".punt-pii.toml").write_text(
        'allow_emails = ["team@org.com"]\ndeny = ["leaked-value"]\n'
    )
    config = load_config(tmp_path)
    assert config.allow_emails == ["team@org.com"]
    assert config.deny == ["leaked-value"]


def test_pyproject_takes_precedence(tmp_path: Path) -> None:
    """pyproject.toml [tool.punt.pii] takes precedence over .punt-pii.toml."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.punt.pii]\nallow_emails = ["from-pyproject@org.com"]\n'
    )
    (tmp_path / ".punt-pii.toml").write_text(
        'allow_emails = ["from-standalone@org.com"]\n'
    )
    config = load_config(tmp_path)
    assert config.allow_emails == ["from-pyproject@org.com"]


def test_explicit_config_path(tmp_path: Path) -> None:
    """--config flag overrides default config locations."""
    custom = tmp_path / "custom.toml"
    custom.write_text('deny = ["custom-deny"]\n')
    config = load_config(tmp_path, str(custom))
    assert config.deny == ["custom-deny"]


# ---------------------------------------------------------------------------
# Allow patterns (regex suppression)
# ---------------------------------------------------------------------------


def test_allow_patterns_suppress_emails(tmp_path: Path) -> None:
    """allow_patterns regexes suppress matching findings."""
    (tmp_path / "file.txt").write_text("contact: bot@internal.corp\n")
    config = PiiConfig(allow_patterns=[r"@internal\.corp$"])
    findings = scan_file("file.txt", tmp_path, config)
    assert len(findings) == 0


def test_allow_patterns_suppress_paths(tmp_path: Path) -> None:
    """allow_patterns can suppress path findings."""
    (tmp_path / "file.txt").write_text("path: /Users/admin/tools\n")
    config = PiiConfig(allow_patterns=[r"/Users/admin/"])
    findings = scan_file("file.txt", tmp_path, config)
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Integration: run_pii
# ---------------------------------------------------------------------------


def test_clean_repo_passes(tmp_path: Path) -> None:
    """A repo with no PII exits cleanly (no SystemExit)."""
    _init_git(tmp_path)
    (tmp_path / "main.py").write_text("print('hello')\n")
    _add_and_commit(tmp_path)

    # Should not raise
    run_pii(str(tmp_path))


def test_dirty_repo_fails(tmp_path: Path) -> None:
    """A repo with PII raises SystemExit(1)."""
    _init_git(tmp_path)
    (tmp_path / "config.py").write_text('EMAIL = "person@private.com"\n')
    _add_and_commit(tmp_path)

    with pytest.raises(SystemExit, match="1"):
        run_pii(str(tmp_path))


def test_staged_mode(tmp_path: Path) -> None:
    """--staged scans only staged files."""
    _init_git(tmp_path)
    # Create initial clean commit
    (tmp_path / "clean.py").write_text("x = 1\n")
    _add_and_commit(tmp_path)

    # Add a file with PII but don't stage it
    (tmp_path / "dirty.py").write_text('EMAIL = "leak@private.com"\n')

    # Staged mode should find nothing (dirty.py not staged)
    run_pii(str(tmp_path), staged=True)

    # Now stage it
    subprocess.run(["git", "add", "dirty.py"], cwd=str(tmp_path), capture_output=True)

    with pytest.raises(SystemExit, match="1"):
        run_pii(str(tmp_path), staged=True)
