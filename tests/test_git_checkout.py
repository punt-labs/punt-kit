"""Tests for a git checkout's GitHub origin."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from punt_kit.git_checkout import GitCheckout

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _checkout(tmp_path: Path, remote: str | None) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    if remote is not None:
        subprocess.run(
            ["git", "remote", "add", "origin", remote], cwd=tmp_path, check=True
        )
    return tmp_path


@pytest.mark.parametrize(
    ("remote", "slug"),
    [
        pytest.param("https://github.com/o/r/", "o/r", id="trailing-slash"),
        pytest.param("git@github.com:o/r.git/", "o/r", id="scp-dot-git-slash"),
        pytest.param("https://github.com/o/r.git", "o/r", id="dot-git"),
    ],
)
def test_github_slug_is_clean(tmp_path: Path, remote: str, slug: str) -> None:
    """The audit builds ``repos/{slug}/...`` URLs, so the slug must be clean."""
    assert GitCheckout(_checkout(tmp_path, remote)).github_slug() == slug


def test_github_slug_says_when_there_is_no_origin(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^no remote detected$"):
        GitCheckout(_checkout(tmp_path, None)).github_slug()


def test_github_slug_says_when_root_is_a_subdirectory_of_a_checkout(
    tmp_path: Path,
) -> None:
    sub = _checkout(tmp_path, "https://github.com/o/r") / "pkg"
    sub.mkdir()
    with pytest.raises(ValueError, match="^no git repo at root$"):
        GitCheckout(sub).github_slug()


def test_github_slug_says_when_root_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^no git repo at root$"):
        GitCheckout(tmp_path / "absent").github_slug()


@pytest.mark.parametrize(
    "remote",
    [
        pytest.param("https://github.com/proj", id="no-owner"),
        pytest.param("https://github.com/o/r/extra", id="three-parts"),
        pytest.param("https://gitlab.com/o/r", id="other-host"),
    ],
)
def test_github_slug_names_an_origin_that_is_not_a_github_owner_repo(
    tmp_path: Path, remote: str
) -> None:
    with pytest.raises(ValueError, match=f"^origin remote is not .*: {remote}$"):
        GitCheckout(_checkout(tmp_path, remote)).github_slug()


@pytest.mark.parametrize(
    ("remote", "shown"),
    [
        pytest.param(
            "https://u:s3cret@gitlab.com/o/r", "https://gitlab.com/o/r", id="user"
        ),
        pytest.param(
            "https://t0k@gitlab.com:8443/o/r", "https://gitlab.com:8443/o/r", id="port"
        ),
        pytest.param("https://gitlab.com/o/r", "https://gitlab.com/o/r", id="none"),
    ],
)
def test_the_message_never_echoes_embedded_credentials(
    tmp_path: Path, remote: str, shown: str
) -> None:
    with pytest.raises(ValueError, match="not a GitHub owner/repo") as caught:
        GitCheckout(_checkout(tmp_path, remote)).github_slug()
    assert str(caught.value).endswith(f": {shown}")


def test_git_missing_from_the_path_is_said_plainly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    def no_git(_name: str) -> None:
        return None

    monkeypatch.setattr(shutil, "which", no_git)
    with pytest.raises(ValueError, match="^git is not installed$"):
        GitCheckout(_checkout(tmp_path, None)).github_slug()


def test_a_failed_remote_lookup_reports_git_s_own_complaint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _checkout(tmp_path, "https://github.com/o/r")
    real_run = subprocess.run

    def fake_run(
        cmd: list[str],
        *,
        cwd: str,
        capture_output: bool,
        text: bool,
        timeout: int,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        if cmd[1:3] == ["remote", "get-url"]:
            return subprocess.CompletedProcess(cmd, 128, "", "fatal: bad config\n")
        return real_run(
            cmd,
            cwd=cwd,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            env=env,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="remote get-url origin failed: fatal: bad"):
        GitCheckout(root).github_slug()


def test_an_unparseable_origin_is_never_echoed(tmp_path: Path) -> None:
    remote = "https://u:t0k3n@[bad/x"
    with pytest.raises(ValueError, match="not a GitHub owner/repo") as caught:
        GitCheckout(_checkout(tmp_path, remote)).github_slug()
    assert "t0k3n" not in str(caught.value)
    assert str(caught.value).endswith(": <unparseable url>")


def _patch_git(
    monkeypatch: pytest.MonkeyPatch,
    reply: Callable[[list[str], dict[str, str]], subprocess.CompletedProcess[str]],
) -> None:
    def fake_run(
        cmd: list[str],
        *,
        cwd: str,
        capture_output: bool,
        text: bool,
        timeout: int,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return reply(cmd, env)

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_a_toplevel_lookup_that_times_out_says_it_did_not_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def hang(cmd: list[str], _env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, 5)

    _patch_git(monkeypatch, hang)
    with pytest.raises(ValueError, match=r"rev-parse --show-toplevel did not finish"):
        GitCheckout(tmp_path).github_slug()


def test_a_git_that_cannot_start_says_it_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(
        cmd: list[str], _env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        raise PermissionError("denied")

    _patch_git(monkeypatch, broken)
    with pytest.raises(ValueError, match=r"^git is not installed"):
        GitCheckout(tmp_path).github_slug()


def test_a_toplevel_refusal_is_reported_with_gits_own_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(
        cmd: list[str], _env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            cmd, 128, "", "fatal: detected dubious ownership in repository\n"
        )

    _patch_git(monkeypatch, refuse)
    with pytest.raises(ValueError, match=r"show-toplevel failed: .*dubious ownership"):
        GitCheckout(tmp_path).github_slug()


def test_git_runs_in_the_c_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def record(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        seen.append(env["LC_ALL"])
        return subprocess.CompletedProcess(cmd, 128, "", "fatal: not a git repository")

    _patch_git(monkeypatch, record)
    with pytest.raises(ValueError, match="^no git repo at root$"):
        GitCheckout(tmp_path).github_slug()
    assert seen == ["C"]


@pytest.mark.parametrize(
    ("remote", "shown"),
    [
        pytest.param(
            "ghp_SECRET@example.com:o/r/x.git", "example.com:o/r/x.git", id="scp-token"
        ),
        pytest.param("git@gitlab.com:o/r.git", "gitlab.com:o/r.git", id="scp-user"),
        pytest.param(
            "https://example.com/o/r.git?private_token=SECRET",
            "https://example.com/o/r.git",
            id="query",
        ),
        pytest.param(
            "https://u:SECRET@example.com/o/r#SECRET",
            "https://example.com/o/r",
            id="userinfo-and-fragment",
        ),
    ],
)
def test_the_message_drops_scp_users_queries_and_fragments(
    tmp_path: Path, remote: str, shown: str
) -> None:
    with pytest.raises(ValueError, match="not a GitHub owner/repo") as caught:
        GitCheckout(_checkout(tmp_path, remote)).github_slug()
    assert (
        str(caught.value).endswith(f": {shown}"),
        "SECRET" in str(caught.value),
    ) == (
        True,
        False,
    )
