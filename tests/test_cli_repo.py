"""Tests for cli repo."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from punt_kit.__main__ import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_json_init_does_not_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "punt_kit.init._prompt_language", lambda: pytest.fail("prompted")
    )

    result = runner.invoke(app, ["repo", "init", str(tmp_path), "--json"])

    assert result.exit_code == 0
    assert "changes" in json.loads(result.stdout)


@pytest.mark.parametrize("verb", ["init", "audit"])
def test_repo_json_reports_the_unreadable_file(tmp_path: Path, verb: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project\nname=")

    result = runner.invoke(app, ["repo", verb, str(tmp_path), "--json"])

    assert result.exit_code == 1
    assert "pyproject.toml" in json.loads(result.stdout)["error"]


@pytest.mark.parametrize("verbosity", [[], ["-q"]])
def test_audit_json_reports_failed_checks(tmp_path: Path, verbosity: list[str]) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')

    result = runner.invoke(app, [*verbosity, "repo", "audit", str(tmp_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]
    assert payload["failed"] == len(payload["findings"]) > 0
    assert all(finding["check"] for finding in payload["findings"])


def test_seed_json_reports_the_unclosed_marker(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "Makefile").write_text("# punt:begin help\n")

    result = runner.invoke(app, ["repo", "seed", "makefile", str(tmp_path), "--json"])

    assert result.exit_code == 1
    assert "Unclosed marker 'help'" in json.loads(result.stdout)["error"]


def test_quiet_audit_only_reports_failing_checks(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# demo\n")
    (tmp_path / ".markdownlint.jsonc").write_text("{}\n")

    result = runner.invoke(app, ["-q", "repo", "audit", str(tmp_path)])

    assert result.exit_code == 1
    assert not result.stdout
    assert "CHANGELOG.md exists" in result.stderr
    assert ".markdownlint.jsonc exists" not in result.stderr
    assert "passed," not in result.stderr


@pytest.mark.parametrize("preview", [[], ["--dry-run"]])
def test_seed_rejects_non_python_makefiles(tmp_path: Path, preview: list[str]) -> None:
    (tmp_path / "go.mod").write_text("module example.com/demo\n")
    result = runner.invoke(
        app, ["repo", "seed", "makefile", str(tmp_path), "--json", *preview]
    )

    assert result.exit_code == 1
    assert "only support Python" in json.loads(result.stdout)["error"]
    assert not (tmp_path / "Makefile").exists()
