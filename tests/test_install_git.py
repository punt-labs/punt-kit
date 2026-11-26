"""Tests for install_git."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from punt_kit.install_git import InstallError, MarketplaceGitEnvironment

if TYPE_CHECKING:
    from pathlib import Path


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
@pytest.mark.parametrize("indexed", [False, True])
def test_marketplace_flattens_includes_without_their_rewrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, indexed: bool
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "outer.gitconfig").write_text(
        "[include]\npath = inner.gitconfig\n", encoding="utf-8"
    )
    (tmp_path / "inner.gitconfig").write_text(
        '[url "git@example.invalid:"]\n'
        "insteadOf = git@github.com:punt-labs/claude-plugins\n"
        "[http]\nproxy = http://proxy.invalid:3128\n",
        encoding="utf-8",
    )
    if indexed:
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "include.path")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "~/outer.gitconfig")
    else:
        monkeypatch.setenv(
            "GIT_CONFIG_PARAMETERS", "'include.path'='~/outer.gitconfig'"
        )

    env = MarketplaceGitEnvironment().prepare()

    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_0"] == "http.proxy"
    assert env["GIT_CONFIG_VALUE_0"] == "http://proxy.invalid:3128"
    assert env["GIT_CONFIG_KEY_1"] == "url.https://github.com/punt-labs/.insteadOf"
    assert "GIT_CONFIG_PARAMETERS" not in env


@pytest.mark.skipif(shutil.which("git") is None, reason="requires Git")
def test_marketplace_diagnoses_conditional_git_command_includes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    monkeypatch.setenv(
        "GIT_CONFIG_PARAMETERS",
        "'includeIf.gitdir:/**.path'='/unused/special.gitconfig'",
    )

    with pytest.raises(
        InstallError, match="Move conditional Git command includes to your Git config"
    ):
        MarketplaceGitEnvironment().prepare()


@pytest.mark.skipif(shutil.which("git") is None, reason="requires Git")
def test_marketplace_does_not_echo_invalid_git_c_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "secret-invalid-setting")

    with pytest.raises(
        InstallError,
        match="^Could not read inherited Git command settings; "
        "check Git options and include paths$",
    ):
        MarketplaceGitEnvironment().prepare()
