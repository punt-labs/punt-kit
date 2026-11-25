"""Tests for cli release."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from punt_kit.__main__ import app
from punt_kit.errors import ReleaseError
from punt_kit.phases.phase11_checks import VerificationCheck
from punt_kit.phases.phase11_verify import Phase11Verify
from tests.helpers import fake_which, make_release_project

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


@pytest.mark.parametrize("times_out", [False, True])
def test_quiet_json_release_reports_failed_verification_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, times_out: bool
) -> None:
    project = make_release_project(tmp_path)
    monkeypatch.setattr("shutil.which", fake_which)
    with (
        patch.object(
            Phase11Verify,
            "_local_checks",
            return_value=[VerificationCheck("Git tag", False, "not found")],
            side_effect=subprocess.TimeoutExpired(["git", "tag"], 30)
            if times_out
            else None,
        ),
        patch.object(Phase11Verify, "_remote_slug", return_value=(None, [])),
        patch.object(Phase11Verify, "_pypi_checks", return_value=[]),
    ):
        result = runner.invoke(
            app,
            [
                "release",
                "run",
                "-q",
                "--json",
                "--path",
                str(project),
                "0.2.0",
                "--resume-from",
                "verify",
            ],
        )

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert ("did not return within 30s" if times_out else "Git tag") in report["error"]
    assert report["resume_from"] == "verify"


def test_json_verification_failure_resumes_at_earlier_propagation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_release_project(tmp_path)
    monkeypatch.setattr("shutil.which", fake_which)
    with (
        patch(
            "punt_kit.release._phase10_propagate",
            side_effect=ReleaseError("marketplace update failed"),
        ),
        patch(
            "punt_kit.release._phase11_verify",
            side_effect=ReleaseError("Git tag not found"),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "release",
                "run",
                "-q",
                "--json",
                "--path",
                str(project),
                "0.2.0",
                "--resume-from",
                "propagate",
            ],
        )

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error": "Git tag not found",
        "resume_from": "propagate",
    }


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
