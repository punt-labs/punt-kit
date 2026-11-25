"""CLI compliance tests for the punt command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from punt_kit.__main__ import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

PUBLIC_PATHS = (
    (),
    ("repo",),
    ("repo", "init"),
    ("repo", "audit"),
    ("repo", "scan-pii"),
    ("repo", "seed"),
    ("release",),
    ("release", "run"),
    ("enable",),
    ("disable",),
    ("status",),
    ("doctor",),
    ("version",),
    ("install",),
)


@pytest.mark.parametrize("path", PUBLIC_PATHS)
def test_help_at_every_public_path(path: tuple[str, ...]) -> None:
    short = runner.invoke(app, [*path, "-h"])
    long = runner.invoke(app, [*path, "--help"])
    assert short.exit_code == long.exit_code == 0
    assert short.stdout == long.stdout
    assert "Usage:" in short.stdout


def test_bare_punt_prints_help() -> None:
    bare = runner.invoke(app, [])
    assert bare.exit_code == 0
    assert bare.stdout == runner.invoke(app, ["-h"]).stdout


@pytest.mark.parametrize("legacy", ("audit", "init", "pii", "seed", "--version", "-V"))
def test_parser_rejects_old_spellings(legacy: str) -> None:
    result = runner.invoke(app, [legacy, "--json"])
    assert result.exit_code == 2
    assert isinstance(json.loads(result.stdout)["error"], str)


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
    assert result.exit_code == 2


def test_verbose_quiet_mutually_exclusive_json() -> None:
    """--json + --verbose + --quiet produces a JSON-formatted error."""
    result = runner.invoke(app, ["--json", "--verbose", "--quiet", "version"])
    assert result.exit_code == 2
    data = json.loads(result.output.strip())
    assert isinstance(data, dict)
    assert "error" in data


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
    data = json.loads(result.stdout)
    if result.exit_code:
        assert isinstance(data["error"], str)
        data = data["checks"]
    assert isinstance(data, list)
    checks = cast("list[dict[str, object]]", data)
    assert checks
    assert "name" in checks[0]
    assert "passed" in checks[0]


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


# --- seed ---


def test_seed_help_lists_targets() -> None:
    """The managed-section renderer is spelled 'seed' and names its targets."""
    result = runner.invoke(app, ["repo", "seed", "--help"])
    assert result.exit_code == 0
    assert "makefile, settings" in result.output


def test_auto_is_not_a_command() -> None:
    """The old 'auto' spelling is unknown to the parser — no alias, no shim.

    Exit code 2 is the parser rejecting an unknown command. A deprecation
    shim that warned and exited 1 would satisfy a bare non-zero assertion.
    """
    result = runner.invoke(app, ["auto", "makefile"])
    assert result.exit_code == 2
    assert "No such command 'auto'" in result.output


def test_status_reports_an_unreadable_plugin_manifest_and_exits_1(
    tmp_path: Path,
) -> None:
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{broken")

    result = runner.invoke(app, ["status", str(tmp_path)])

    assert result.exit_code == 1
    assert "plugin.json" in result.output


def test_status_reports_a_malformed_pyproject_and_exits_1(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project\nname=")

    result = runner.invoke(app, ["status", str(tmp_path)])

    assert result.exit_code == 1
    assert "pyproject.toml is not valid TOML" in result.output
