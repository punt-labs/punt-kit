"""Every way a release can fail shows the operator what failed, exactly once."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from punt_kit import release
from punt_kit.release import ReleaseError, run_release
from tests.test_release import (
    _fake_which,  # pyright: ignore[reportPrivateUsage]
    _flat,  # pyright: ignore[reportPrivateUsage]
    _make_release_project,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from pathlib import Path


def test_a_file_error_before_any_phase_names_the_file_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed pyproject.toml is reported with its name and reason, once."""
    root = _make_release_project(tmp_path)
    (root / "pyproject.toml").write_text('[project\nname = "x"\n')
    monkeypatch.setattr(shutil, "which", _fake_which)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0")

    out = _flat(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert out.count("pyproject.toml") == 1
    assert "failed before any phase ran" in out
    assert "Not confirmed landed" not in out
    assert "phase 0" not in out


def test_a_file_error_inside_a_phase_is_reported_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A ReleaseError raised outside Reporter.fail is printed before the recap."""
    root = _make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", _fake_which)

    def phase11(*_a: object, **_k: object) -> None:
        raise ReleaseError("somefile.toml is not valid TOML: boom")

    monkeypatch.setattr(release, "_phase11_verify", phase11)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", resume_from="verify")

    out = _flat(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert out.count("somefile.toml is not valid TOML: boom") == 1
    assert "--resume-from verify" in out


def test_a_reported_failure_is_not_printed_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reporter.fail already printed its message; the handler must not repeat it."""
    root = _make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", _fake_which)

    def phase11(*_a: object, **_k: object) -> None:
        release._fail("distinctive failure text")  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(release, "_phase11_verify", phase11)

    with pytest.raises(SystemExit):
        run_release(str(root), version="0.2.0", resume_from="verify")

    out = _flat(capsys.readouterr().out)
    assert out.count("distinctive failure text") == 1


def _p9_p10_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, phase11: object
) -> Path:
    """A project whose Phase 10 website leg fails and whose verify is ``phase11``."""
    root = _make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", _fake_which)

    def quiet(*_a: object, **_k: object) -> None:
        return None

    def website(*_a: object, **_k: object) -> None:
        raise ReleaseError("website: kaboom")

    monkeypatch.setattr(release, "_phase9_post_release", quiet)
    monkeypatch.setattr(release, "_propagate_website", website)
    monkeypatch.setattr(release, "_propagate_install_all", quiet)
    monkeypatch.setattr(release, "_propagate_marketplace", quiet)
    monkeypatch.setattr(release, "_reset_propagation_siblings", quiet)
    monkeypatch.setattr(release, "_phase11_verify", phase11)
    return root


def test_a_phase_11_timeout_after_a_propagation_failure_names_phase_11(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A verify timeout is reported where it happened, not as the earlier failure."""

    def phase11(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired(["pip", "index", "versions", "proj"], 30)

    root = _p9_p10_project(tmp_path, monkeypatch, phase11=phase11)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", resume_from="post-release")

    out = _flat(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert "in phase 11 (verify)" in out
    assert "website: kaboom" in out


def test_a_phase_11_failure_after_a_propagation_failure_names_phase_11(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The recap says verify stopped; the recorded failure still resumes earlier."""

    def phase11(*_a: object, **_k: object) -> None:
        raise KeyError("version")

    root = _p9_p10_project(tmp_path, monkeypatch, phase11=phase11)

    with pytest.raises(SystemExit):
        run_release(str(root), version="0.2.0", resume_from="post-release")

    out = _flat(capsys.readouterr().out)
    assert "stopped during phase 11 (verify)" in out
    assert "--resume-from post-release" in out


def test_a_bug_in_a_worker_thread_keeps_its_type_and_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A KeyError from a propagator is named in the recap and traced once."""

    def phase11(*_a: object, **_k: object) -> None:
        return None

    root = _p9_p10_project(tmp_path, monkeypatch, phase11=phase11)

    def bug(*_a: object, **_k: object) -> None:
        raise KeyError("version")

    monkeypatch.setattr(release, "_propagate_website", bug)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", resume_from="post-release")

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "KeyError: " in _flat(captured.out)
    assert captured.err.count("Traceback") == 1
    assert "bug" in captured.err
