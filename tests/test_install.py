"""Tests for install."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from punt_kit.__main__ import app
from punt_kit.install import PluginInstaller

runner = CliRunner()


def test_install_ignores_inherited_git_rewrite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "3")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url.https://elsewhere.invalid/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "git@github.com:punt-labs/claude-plugins")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "url.https://elsewhere.invalid/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "https://github.com/punt-labs/")
    monkeypatch.setenv("GIT_CONFIG_KEY_2", "http.proxy")
    monkeypatch.setenv("GIT_CONFIG_VALUE_2", "http://proxy.invalid:3128")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/path/to/custom.gitconfig")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'url.example.invalid.insteadOf=git@'")

    reports = (
        b"[]",
        b"",
        b"[]",
        b"",
        b'[{"id":"punt@punt-labs","scope":"user"}]',
    )
    with patch(
        "punt_kit.install.subprocess.run",
        side_effect=[subprocess.CompletedProcess([], 0, report) for report in reports],
    ) as claude:
        assert not PluginInstaller("/bin/claude").run().error
    env = claude.call_args.kwargs["env"]

    assert {
        key: value
        for key, value in env.items()
        if key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    } == {
        "GIT_CONFIG_KEY_0": "http.proxy",
        "GIT_CONFIG_VALUE_0": "http://proxy.invalid:3128",
        "GIT_CONFIG_KEY_1": "url.https://github.com/punt-labs/.insteadOf",
        "GIT_CONFIG_VALUE_1": "git@github.com:punt-labs/",
    }
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_GLOBAL"] == "/path/to/custom.gitconfig"
    assert "GIT_CONFIG_PARAMETERS" not in env


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
    report = json.loads(result.stdout)
    assert report["scope"] == "user"
    assert report["changes"][-1] == (
        "Checked for updates to punt@punt-labs at user scope"
        if installed
        else "Installed punt@punt-labs at user scope"
    )
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
