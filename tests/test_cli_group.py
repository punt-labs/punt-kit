"""Tests for cli group."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from punt_kit.__main__ import app

runner = CliRunner()


def test_logging_setup_failure_does_not_break_json() -> None:
    with patch(
        "punt_kit.cli_group.EntryPointLogging.configure", side_effect=PermissionError
    ):
        result = runner.invoke(app, ["version", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["version"]
    assert "cannot initialize the private punt log" in result.stderr


@pytest.mark.parametrize(
    ("args", "target", "failure"),
    [
        (["doctor"], "punt_kit.doctor.run_doctor", KeyboardInterrupt()),
        (["release", "run"], "punt_kit.release.run_release", SystemExit(130)),
    ],
)
def test_interruption_emits_one_json_error(
    args: list[str], target: str, failure: BaseException
) -> None:
    with patch(target, side_effect=failure):
        result = runner.invoke(app, [*args, "--json"])

    assert result.exit_code == 130
    assert json.loads(result.stdout) == {"error": "Interrupted"}
