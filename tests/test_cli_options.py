"""Tests for cli options."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from punt_kit.__main__ import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.parametrize(
    "args",
    [
        ["--json", "repo", "scan-pii"],
        ["repo", "--json", "scan-pii"],
        ["repo", "scan-pii", "--json"],
    ],
)
def test_json_flags_at_each_level(args: list[str], tmp_path: Path) -> None:
    result = runner.invoke(app, [*args, str(tmp_path / "missing")])
    assert result.exit_code == 1
    assert "not a directory" in json.loads(result.stdout)["error"]
    assert "not a directory" in result.stderr


def test_global_verbosity_conflicts_across_levels() -> None:
    result = runner.invoke(app, ["-q", "repo", "seed", "settings", "-v", "--json"])
    assert result.exit_code == 2
    assert "mutually exclusive" in json.loads(result.stdout)["error"]
