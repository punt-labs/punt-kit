"""Tests for ``punt enable`` / ``punt disable`` (tool-enable-disable.md §2.10)."""

from __future__ import annotations

import json
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
