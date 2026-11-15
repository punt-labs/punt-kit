"""Tests for ``punt enable`` / ``punt disable`` (tool-enable-disable.md §2.10)."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from punt_kit.__main__ import app
from punt_kit.audit_verdict import FAIL
from punt_kit.claude_permissions import PUNT_RULES
from punt_kit.enablement import IMPORT_LINE, PuntEnablement

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _settings(root: Path) -> dict[str, dict[str, list[str]]]:
    data: dict[str, dict[str, list[str]]] = json.loads(
        (root / ".claude" / "settings.json").read_text()
    )
    return data


def _failures(root: Path) -> list[str]:
    result = runner.invoke(app, ["audit", str(root)])
    return [line for line in result.output.splitlines() if FAIL in line]


class TestEnable:
    def test_deposits_guide_marker_import_and_rules(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Repo\n")
        report = PuntEnablement(tmp_path).enable()
        assert not report.error
        assert (tmp_path / ".punt-labs/punt/CLAUDE.md").read_text().startswith("# ")
        assert (tmp_path / ".punt-labs/punt/enabled").is_file()
        assert (tmp_path / "CLAUDE.md").read_text() == f"# Repo\n{IMPORT_LINE}\n"
        perms = _settings(tmp_path)["permissions"]
        assert perms["allow"] == list(PUNT_RULES["allow"])
        assert perms["ask"] == list(PUNT_RULES["ask"])

    def test_is_idempotent(self, tmp_path: Path) -> None:
        PuntEnablement(tmp_path).enable()
        assert PuntEnablement(tmp_path).enable().changes == ()

    def test_overwrites_an_edited_guide(self, tmp_path: Path) -> None:
        PuntEnablement(tmp_path).enable()
        guide = tmp_path / ".punt-labs/punt/CLAUDE.md"
        original = guide.read_text()
        guide.write_text("stale")
        PuntEnablement(tmp_path).enable()
        assert guide.read_text() == original

    def test_refused_settings_changes_nothing(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{not json")
        report = PuntEnablement(tmp_path).enable()
        assert "not valid JSON" in report.error
        assert not (tmp_path / ".punt-labs").exists()
        assert not (tmp_path / "CLAUDE.md").exists()


class TestDisable:
    def test_reverses_enable_and_leaves_guide(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Repo\n")
        PuntEnablement(tmp_path).enable()
        report = PuntEnablement(tmp_path).disable()
        assert not report.error
        assert (tmp_path / "CLAUDE.md").read_text() == "# Repo\n"
        assert not (tmp_path / ".punt-labs/punt/enabled").exists()
        assert (tmp_path / ".punt-labs/punt/CLAUDE.md").is_file()
        assert _settings(tmp_path)["permissions"] == {"allow": [], "ask": []}

    def test_on_a_repo_never_enabled_changes_nothing(self, tmp_path: Path) -> None:
        assert PuntEnablement(tmp_path).disable().changes == ()
        assert list(tmp_path.iterdir()) == []


class TestCli:
    def test_round_trip_adds_no_audit_failure(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").write_text("# Repo\n")
        before = _failures(tmp_path)
        enabled = runner.invoke(app, ["enable", str(tmp_path)])
        assert enabled.exit_code == 0, enabled.output
        assert "Skill(punt:*)" in enabled.output
        assert _failures(tmp_path) == before
        disabled = runner.invoke(app, ["disable", str(tmp_path)])
        assert disabled.exit_code == 0, disabled.output
        assert _failures(tmp_path) == before

    def test_json_lists_changes(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["--json", "enable", str(tmp_path)])
        assert result.exit_code == 0
        assert (
            f"Added {IMPORT_LINE} to CLAUDE.md" in json.loads(result.output)["changes"]
        )

    def test_refusal_exits_nonzero(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("[]")
        result = runner.invoke(app, ["disable", str(tmp_path)])
        assert result.exit_code == 1
        assert "not a JSON object" in result.output


class TestHardening:
    def test_refuses_symlinked_guide(self, tmp_path: Path) -> None:
        victim = tmp_path / "victim.txt"
        victim.write_text("keep me")
        (tmp_path / ".punt-labs/punt").mkdir(parents=True)
        (tmp_path / ".punt-labs/punt/CLAUDE.md").symlink_to(victim)
        report = PuntEnablement(tmp_path).enable()
        assert "symlink" in report.error
        assert victim.read_text() == "keep me"
        assert not (tmp_path / ".claude").exists()

    def test_refuses_symlinked_subtree(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".punt-labs").symlink_to(outside, target_is_directory=True)
        assert "symlink" in PuntEnablement(repo).enable().error
        assert "symlink" in PuntEnablement(repo).disable().error
        assert list(outside.iterdir()) == []

    def test_does_not_truncate_through_symlinked_import_lock(
        self, tmp_path: Path
    ) -> None:
        victim = tmp_path / "victim.txt"
        victim.write_text("keep me")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".CLAUDE.md.punt-import.lock").symlink_to(victim)
        report = PuntEnablement(repo).enable()
        assert report.error
        assert victim.read_text() == "keep me"

    def test_replaces_a_non_utf8_guide(self, tmp_path: Path) -> None:
        guide = tmp_path / ".punt-labs/punt/CLAUDE.md"
        guide.parent.mkdir(parents=True)
        guide.write_bytes(b"\xff\xfe")
        assert not PuntEnablement(tmp_path).enable().error
        assert guide.read_text().startswith("# ")

    def test_filesystem_failure_is_a_json_error(self, tmp_path: Path) -> None:
        (tmp_path / ".punt-labs").write_text("a file, not a directory")
        result = runner.invoke(app, ["--json", "enable", str(tmp_path)])
        assert result.exit_code == 1
        assert "Skill(punt:*)" in json.loads(result.output)["error"]

    def test_disable_runs_with_a_symlinked_guide(self, tmp_path: Path) -> None:
        PuntEnablement(tmp_path).enable()
        guide = tmp_path / ".punt-labs/punt/CLAUDE.md"
        guide.unlink()
        guide.symlink_to(tmp_path / "elsewhere.md")
        assert not PuntEnablement(tmp_path).disable().error
        assert not (tmp_path / ".punt-labs/punt/enabled").exists()

    def test_partial_enable_reports_files_written(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE.md").mkdir()
        report = PuntEnablement(tmp_path).enable()
        assert report.error
        assert "Wrote .punt-labs/punt/enabled" in report.changes

    def test_guide_upgrade_replaces_the_file_atomically(self, tmp_path: Path) -> None:
        guide = tmp_path / ".punt-labs/punt/CLAUDE.md"
        guide.parent.mkdir(parents=True)
        guide.write_text("old guide\n")
        old_inode = tmp_path / "old-inode"
        os.link(guide, old_inode)
        assert not PuntEnablement(tmp_path).enable().error
        assert old_inode.read_text() == "old guide\n"
        assert guide.read_text() != "old guide\n"
        assert list(guide.parent.glob("*.tmp")) == []

    def test_refuses_a_directory_at_the_marker(self, tmp_path: Path) -> None:
        (tmp_path / ".punt-labs/punt/enabled").mkdir(parents=True)
        assert "not a regular file" in PuntEnablement(tmp_path).enable().error
        assert "not a regular file" in PuntEnablement(tmp_path).disable().error
        assert not (tmp_path / ".claude").exists()
