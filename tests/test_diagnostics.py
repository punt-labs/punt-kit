"""Verify boundary outcomes without recording command content."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from punt_kit import __main__ as cli
from punt_kit import __version__
from punt_kit.phases.shared.command_diagnostics import CommandDiagnostics
from punt_kit.phases.shared.command_runner import CommandRunner
from punt_kit.phases.shared.phase_diagnostics import PhaseDiagnostics
from punt_kit.phases.shared.pipeline import PhaseStep, ReleasePipeline

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "mode,status",
    [
        ("success", 0),
        ("nonzero", 7),
        ("checked", 7),
        ("timeout", None),
        ("unavailable", None),
        ("decode", None),
    ],
)
def test_subprocess_outcomes_are_content_free(
    mode: str,
    status: int | None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    command = ["git", "private-argument", "token=private-token", "/private/path"]

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if mode == "checked":
            raise subprocess.CalledProcessError(
                7, command, "private-stdout", "private-stderr"
            )
        if mode == "timeout":
            raise subprocess.TimeoutExpired(
                command, 1, "private-stdout", "private-stderr"
            )
        if mode == "unavailable":
            raise FileNotFoundError("private-path")
        if mode == "decode":
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "private-output")
        return subprocess.CompletedProcess(
            command, status or 0, "private-stdout", "private-stderr"
        )

    monkeypatch.setattr(subprocess, "run", run)
    if mode in {"checked", "timeout", "unavailable", "decode"}:
        with pytest.raises(
            (
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
                FileNotFoundError,
                UnicodeDecodeError,
            )
        ):
            CommandRunner.run(command)
    else:
        assert CommandRunner.run(command).returncode == status
    assert "Starting subprocess command=git" in caplog.text
    if status is not None:
        assert f"Subprocess finished command=git status={status}" in caplog.text
    else:
        assert "Subprocess did not complete command=git" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    "command,category",
    [([], "external"), (["/private/path"], "external"), (["gh", "private"], "gh")],
)
def test_command_diagnostics_categories_and_result_identity(
    command: list[str], category: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    result = subprocess.CompletedProcess(command, 0, "private-output", "private-error")
    with CommandDiagnostics(command, logging.getLogger(__name__)) as diagnostics:
        assert diagnostics.completed(result) is result
    assert f"Starting subprocess command={category}" in caplog.text
    assert f"Subprocess finished command={category} status=0" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    "failure", [None, RuntimeError("private-content"), SystemExit(7)]
)
def test_phase_outcomes_are_symmetric(
    failure: BaseException | None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    def run() -> None:
        if failure is not None:
            raise failure

    step = PhaseStep(4, "private-phase-name", PhaseDiagnostics(4)(run))
    pipeline = ReleasePipeline([step], ops=MagicMock())
    if failure is None:
        pipeline.run(start=1)
    else:
        with pytest.raises(type(failure)):
            pipeline.run(start=1)
    assert "Release phase started number=4" in caplog.text
    outcome = "ok" if failure is None else "error"
    assert f"Release phase finished number=4 outcome={outcome}" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize("json_output", [False, True])
def test_cli_echo_preserves_output_bytes(
    json_output: bool,
    tmp_path: Path,
) -> None:
    args = ["--json", "version"] if json_output else ["version"]
    result = CliRunner().invoke(
        cli.app, args, env={"HOME": str(tmp_path), "PUNT_TELEMETRY": "off"}
    )
    expected = (
        json.dumps({"version": __version__}) if json_output else f"punt {__version__}"
    )
    assert result.stdout == expected + "\n"
    assert result.stderr == ""


def test_cli_error_preserves_stderr(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Unicode ✓\x1b[31merror\x1b[0m"
    result = CliRunner().invoke(
        cli.app,
        ["status", str(path)],
        env={"HOME": str(tmp_path), "PUNT_TELEMETRY": "off"},
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == f"Error: {path} is not a directory\n"
