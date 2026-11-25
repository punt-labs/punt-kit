"""Tests for install_git."""

from __future__ import annotations

import shutil

import pytest

from punt_kit.install_git import InstallError, MarketplaceGitEnvironment


@pytest.mark.skipif(shutil.which("git") is None, reason="requires Git")
def test_marketplace_preserves_nonrewrite_git_c_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "http.proxy")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "http://default.invalid:3128")
    monkeypatch.setenv(
        "GIT_CONFIG_PARAMETERS",
        "'http.proxy'='http://proxy.invalid:3128' "
        "'http.extraHeader'='X-Demo: let'\\''s '\\!'' "
        "'http.sslVerify'= 'url.example.invalid.insteadOf=git@'",
    )

    env = MarketplaceGitEnvironment().prepare()

    assert env["GIT_CONFIG_COUNT"] == "5"
    assert [env[f"GIT_CONFIG_KEY_{index}"] for index in range(4)] == [
        "http.proxy",
        "http.proxy",
        "http.extraheader",
        "http.sslverify",
    ]
    assert [env[f"GIT_CONFIG_VALUE_{index}"] for index in range(4)] == [
        "http://default.invalid:3128",
        "http://proxy.invalid:3128",
        "X-Demo: let's !",
        "true",
    ]
    assert "GIT_CONFIG_PARAMETERS" not in env


@pytest.mark.skipif(shutil.which("git") is None, reason="requires Git")
def test_marketplace_does_not_echo_invalid_git_c_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "secret-invalid-setting")

    with pytest.raises(
        InstallError, match="^Could not read inherited Git command settings$"
    ):
        MarketplaceGitEnvironment().prepare()
