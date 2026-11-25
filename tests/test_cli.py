"""CLI compliance tests for the punt command."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

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


def test_quiet_release_keeps_failure_diagnostics(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = runner.invoke(app, ["-q", "release", "run", "--path", str(missing)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not a directory" in result.stderr


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
    assert json.loads(result.stdout)["error"]
    assert "--json is not a directory" in result.stderr


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


@pytest.mark.parametrize("installed", [False, True])
def test_install_confirms_user_scope(installed: bool) -> None:
    marketplace = (
        '[{"name":"punt-labs","source":"github","repo":"punt-labs/claude-plugins"}]'
        if installed
        else "[]"
    )
    plugin = '{"id":"punt@punt-labs","scope":"user"}'
    entries = f"[{plugin}]" if installed else "[]"
    expected = (
        ["marketplace", "update", "punt-labs"]
        if installed
        else [
            "marketplace",
            "add",
            "punt-labs/claude-plugins",
        ]
    )
    outputs = [
        marketplace,
        "",
        entries,
        "",
        f"[{plugin}]",
    ]
    with (
        patch("punt_kit.install.shutil.which", return_value="/bin/claude"),
        patch(
            "punt_kit.install.PluginInstaller._claude", side_effect=outputs
        ) as claude,
    ):
        result = runner.invoke(app, ["install", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["scope"] == "user"
    calls = [call.args for call in claude.call_args_list]
    assert calls == [
        ("marketplace", "list", "--json"),
        tuple(expected),
        ("list", "--json"),
        ("update" if installed else "install", "punt@punt-labs", "--scope", "user"),
        ("list", "--json"),
    ]


def test_install_rejects_a_marketplace_from_another_repository() -> None:
    marketplace = '[{"name":"punt-labs","source":"github","repo":"test/other"}]'
    with (
        patch("punt_kit.install.shutil.which", return_value="/bin/claude"),
        patch(
            "punt_kit.install.PluginInstaller._claude", return_value=marketplace
        ) as claude,
    ):
        result = runner.invoke(app, ["install", "--json"])

    assert result.exit_code == 1
    assert (
        "not registered from punt-labs/claude-plugins"
        in json.loads(result.stdout)["error"]
    )
    claude.assert_called_once_with("marketplace", "list", "--json")


def test_install_rejects_invalid_claude_output_as_json() -> None:
    with (
        patch("punt_kit.install.shutil.which", return_value="/bin/claude"),
        patch(
            "punt_kit.install.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=b"\xff"),
        ),
    ):
        result = runner.invoke(app, ["install", "--json"])

    assert result.exit_code == 1
    assert "invalid UTF-8" in json.loads(result.stdout)["error"]


def test_install_reports_completed_steps_when_the_plugin_fails() -> None:
    from punt_kit.phases.shared.errors import ReleaseError

    with (
        patch("punt_kit.install.shutil.which", return_value="/bin/claude"),
        patch(
            "punt_kit.install.PluginInstaller._claude",
            side_effect=["[]", "", "[]", ReleaseError("plugin install failed")],
        ),
    ):
        result = runner.invoke(app, ["install", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error": "plugin install failed",
        "changes": ["Registered the punt-labs marketplace"],
    }


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
