"""Tests for cli release."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from punt_kit.__main__ import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_quiet_release_keeps_failure_diagnostics(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = runner.invoke(app, ["-q", "release", "run", "--path", str(missing)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not a directory" in result.stderr


def test_quiet_json_release_reports_the_unexpected_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(_path: Path) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr("punt_kit.release.detect", unavailable)

    result = runner.invoke(
        app, ["-q", "--json", "release", "run", "--path", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "disk full" in json.loads(result.stdout)["error"]


@pytest.mark.parametrize(
    "args",
    [
        ["--json", "release", "run", "--path"],
        ["release", "run", "--path", "--json"],
        ["release", "run", "-p", "--json"],
    ],
)
def test_release_json_with_a_missing_option_value(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "requires an argument" in json.loads(result.stdout)["error"]


def test_release_json_can_use_a_flag_as_an_attached_option_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["release", "run", "--path=--json", "--json"])

    assert result.exit_code == 1
    assert "--json is not a directory" in json.loads(result.stdout)["error"]
    assert "--json is not a directory" in result.stderr
