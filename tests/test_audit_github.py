"""Tests for the GitHub-side findings of `punt audit`."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from punt_kit.audit_github import GithubSettingsAudit
from punt_kit.audit_verdict import FAIL, INFO, PASS
from punt_kit.detect import detect

_NOT_GITHUB_OWNER_REPO = [
    pytest.param("https://github.com/proj", id="no-owner"),
    pytest.param("https://github.com/o/r/extra", id="three-parts"),
    pytest.param("https://gitlab.com/o/r", id="other-host"),
]


def _github_settings_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote: str | None
) -> list[str]:
    """The labels ``GithubSettingsAudit.findings`` reports for ``remote``."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    if remote is not None:
        subprocess.run(
            ["git", "remote", "add", "origin", remote], cwd=tmp_path, check=True
        )

    def fake_which(_name: str) -> str:
        return "/usr/bin/gh"

    monkeypatch.setattr(shutil, "which", fake_which)
    findings = GithubSettingsAudit(detect(tmp_path).root).findings()
    return [label for _status, label, _detail in findings]


def test_audit_reports_no_git_repo_for_a_subdirectory_of_a_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = tmp_path / "pkg"
    sub.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def fake_which(_name: str) -> str:
        return "/usr/bin/gh"

    monkeypatch.setattr(shutil, "which", fake_which)
    findings = GithubSettingsAudit(detect(sub).root).findings()
    labels = [label for _status, label, _detail in findings]
    assert labels == ["GitHub settings (no git repo at root)"]


def test_audit_reports_no_remote_when_origin_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _github_settings_labels(tmp_path, monkeypatch, None) == [
        "GitHub settings (no remote detected)"
    ]


@pytest.mark.parametrize("remote", _NOT_GITHUB_OWNER_REPO)
def test_audit_reports_a_remote_that_is_not_a_github_owner_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote: str
) -> None:
    assert _github_settings_labels(tmp_path, monkeypatch, remote) == [
        f"GitHub settings (origin remote is not a GitHub owner/repo: {remote})"
    ]


def _dependabot(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
    raises: BaseException | None = None,
) -> list[tuple[str, str, str]]:
    """What ``dependabot_alerts`` reports when ``gh api`` answers this way."""

    def fake_run(
        cmd: list[str], *, capture_output: bool, text: bool, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return GithubSettingsAudit(Path("/unused")).dependabot_alerts("/usr/bin/gh", "o/r")


def test_dependabot_alerts_are_enabled_on_http_204(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _dependabot(
        monkeypatch, returncode=0, stdout="HTTP/2.0 204 No Content\nDate: x\n\n"
    )

    assert out == [(PASS, "Dependabot vulnerability alerts", "Enabled")]


def test_dependabot_alerts_are_not_enabled_on_http_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _dependabot(
        monkeypatch,
        returncode=1,
        stdout='HTTP/2.0 404 Not Found\n\n{"message":"Not Found"}',
        stderr="gh: Not Found (HTTP 404)",
    )

    assert out == [(FAIL, "Dependabot vulnerability alerts", "Not enabled")]


def test_a_204_elsewhere_in_the_response_is_not_a_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _dependabot(
        monkeypatch,
        returncode=1,
        stdout="HTTP/2.0 403 Forbidden\nX-Request-Id: 204\n\n",
        stderr="gh: Resource not accessible (HTTP 403)",
    )

    assert out == [
        (
            INFO,
            "Dependabot vulnerability alerts",
            "could not check: gh: Resource not accessible (HTTP 403)",
        )
    ]


def test_a_success_exit_without_a_status_line_is_not_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _dependabot(monkeypatch, returncode=0, stdout="", stderr="odd")

    assert [status for status, _label, _detail in out] == [INFO]


def test_a_timeout_is_reported_as_one(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _dependabot(
        monkeypatch, returncode=0, raises=subprocess.TimeoutExpired(["gh"], 10)
    )

    ((status, label, detail),) = out
    assert (status, label) == (INFO, "Dependabot vulnerability alerts")
    assert detail.startswith("could not check:") and "timed out" in detail


def _rulesets(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
    raises: BaseException | None = None,
) -> list[tuple[str, str, str]]:
    """What ``rulesets`` reports when ``gh api .../rulesets`` answers this way."""

    def fake_run(
        cmd: list[str], *, capture_output: bool, text: bool, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return GithubSettingsAudit(Path("/unused")).rulesets("/usr/bin/gh", "o/r")


def test_a_rulesets_listing_that_is_not_found_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _rulesets(
        monkeypatch, returncode=1, stdout="{}", stderr="gh: Not Found (HTTP 404)"
    )

    assert out == [
        (FAIL, "Branch protection ruleset exists", "No rulesets or no access")
    ]


def test_a_rulesets_listing_with_no_rulesets_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _rulesets(monkeypatch, returncode=0, stdout="[]")

    assert out == [(FAIL, "Branch protection ruleset exists", "No rulesets configured")]


@pytest.mark.parametrize(
    "stderr",
    [
        "gh: Resource not accessible by integration (HTTP 403)",
        "gh: Bad credentials (HTTP 401)",
        "gh: Server Error (HTTP 502)",
        "error connecting to api.github.com",
    ],
)
def test_a_rulesets_listing_gh_refused_is_a_check_that_could_not_be_made(
    monkeypatch: pytest.MonkeyPatch, stderr: str
) -> None:
    out = _rulesets(monkeypatch, returncode=1, stderr=stderr)

    assert out == [
        (INFO, "Branch protection (could not check)", f"could not check: {stderr}")
    ]


def test_a_rulesets_timeout_names_the_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _rulesets(
        monkeypatch, returncode=0, raises=subprocess.TimeoutExpired(["gh"], 10)
    )

    ((status, label, detail),) = out
    assert (status, label) == (INFO, "Branch protection (could not check)")
    assert detail.startswith("could not check:") and "timed out" in detail
