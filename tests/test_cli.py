"""CLI compliance tests for the punt command."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from punt_kit.__main__ import app

runner = CliRunner()


# --- version ---


def test_version_plain_text() -> None:
    """Version output is plain text: 'punt X.Y.Z'."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    output = result.output.strip()
    assert output.startswith("punt ")
    # No ANSI codes or rich markup
    assert "\x1b" not in output
    assert "╭" not in output


def test_version_json() -> None:
    """--json version produces {"version": "..."}."""
    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "version" in data
    assert isinstance(data["version"], str)


# --- help ---


def test_help_tagline() -> None:
    """Help text contains 'punt:' tagline."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "punt:" in result.output.lower()


def test_help_no_rich_panels() -> None:
    """Help text uses plain text, no box-drawing characters."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for char in ("╭", "╰", "│", "─"):
        assert char not in result.output, f"Rich panel char '{char}' found in help"


def test_global_flags_in_help() -> None:
    """Global flags --json, --verbose, --quiet appear in help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--json" in result.output
    assert "--verbose" in result.output
    assert "--quiet" in result.output


# --- global flags ---


def test_verbose_quiet_mutually_exclusive() -> None:
    """--verbose and --quiet together produce an error."""
    result = runner.invoke(app, ["--verbose", "--quiet", "version"])
    assert result.exit_code == 1


# --- doctor ---


def test_doctor_runs() -> None:
    """Doctor command runs and reports check names."""
    result = runner.invoke(app, ["doctor"])
    # Exit code depends on environment — 0 or 1 both valid
    assert result.exit_code in (0, 1)
    assert "python" in result.output.lower()


def test_doctor_json() -> None:
    """--json doctor produces a JSON array of check results."""
    result = runner.invoke(app, ["--json", "doctor"])
    assert result.exit_code in (0, 1)
    data: list[dict[str, object]] = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) > 0
    assert "name" in data[0]
    assert "passed" in data[0]


# --- status ---


def test_status_runs() -> None:
    """Status command runs successfully."""
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "punt" in result.output.lower()


def test_status_json() -> None:
    """--json status produces a JSON object with expected keys."""
    result = runner.invoke(app, ["--json", "status"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "punt_kit_version" in data
    assert "language" in data
    assert "project_type" in data
