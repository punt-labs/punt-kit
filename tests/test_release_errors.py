"""Every way a release can fail shows the operator what failed, exactly once."""

from __future__ import annotations

import shutil
import subprocess
import threading
from concurrent.futures import Future
from typing import TYPE_CHECKING

import pytest

from punt_kit import release
from punt_kit.phases.shared.errors import OperationalFailure, ReleaseError
from punt_kit.phases.shared.pipeline import ThreadedStep
from punt_kit.phases.shared.reporter import reporter
from punt_kit.release import run_release
from tests.helpers import (
    fake_which,
    flat,
    make_release_project,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_a_file_error_before_any_phase_names_the_file_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed pyproject.toml is reported with its name and reason, once."""
    root = make_release_project(tmp_path)
    (root / "pyproject.toml").write_text('[project\nname = "x"\n')
    monkeypatch.setattr(shutil, "which", fake_which)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0")

    out = flat(capsys.readouterr().out)
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
    root = make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", fake_which)

    def phase11(*_a: object, **_k: object) -> None:
        raise ReleaseError("somefile.toml is not valid TOML: boom")

    monkeypatch.setattr(release, "_phase11_verify", phase11)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", resume_from="verify")

    out = flat(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert out.count("somefile.toml is not valid TOML: boom") == 1
    assert "--resume-from verify" in out


def test_a_reported_failure_is_not_printed_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reporter.fail already printed its message; the handler must not repeat it."""
    root = make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", fake_which)

    def phase11(*_a: object, **_k: object) -> None:
        reporter.fail("distinctive failure text")

    monkeypatch.setattr(release, "_phase11_verify", phase11)

    with pytest.raises(SystemExit):
        run_release(str(root), version="0.2.0", resume_from="verify")

    out = flat(capsys.readouterr().out)
    assert out.count("distinctive failure text") == 1


def _p9_p10_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, phase11: object
) -> Path:
    """A project whose Phase 10 website leg fails and whose verify is ``phase11``."""
    root = make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", fake_which)

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

    out = flat(capsys.readouterr().out)
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

    out = flat(capsys.readouterr().out)
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
    assert "KeyError: " in flat(captured.out)
    assert captured.err.count("Traceback") == 1
    assert "bug" in captured.err


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired(["gh", "run", "list"], 30),
        FileNotFoundError(2, "No such file or directory", "gh"),
        subprocess.CalledProcessError(1, ["gh", "pr", "list"]),
    ],
    ids=["timeout", "oserror", "called-process-error"],
)
def test_an_operational_failure_in_a_worker_thread_has_no_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    """A timeout or a missing tool is a one-line recap entry, not a stack dump."""

    def phase11(*_a: object, **_k: object) -> None:
        return None

    root = _p9_p10_project(tmp_path, monkeypatch, phase11=phase11)

    def fails(*_a: object, **_k: object) -> None:
        raise error

    monkeypatch.setattr(release, "_propagate_website", fails)

    with pytest.raises(SystemExit):
        run_release(str(root), version="0.2.0", resume_from="post-release")

    captured = capsys.readouterr()
    assert f"{type(error).__name__}: " in flat(captured.out)
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(2, "No such file or directory", "gh"),
        PermissionError(13, "Permission denied", "gh"),
        subprocess.CalledProcessError(1, ["gh", "pr", "list"]),
    ],
    ids=["missing-tool", "permission", "called-process-error"],
)
def test_an_operational_failure_in_a_synchronous_phase_has_no_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    """A missing tool in the main thread is one line with its type, like a worker's."""
    root = make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", fake_which)

    def phase11(*_a: object, **_k: object) -> None:
        raise error

    monkeypatch.setattr(release, "_phase11_verify", phase11)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", resume_from="verify")

    captured = capsys.readouterr()
    out = flat(captured.out)
    assert exc_info.value.code == 1
    assert out.count(f"{type(error).__name__}: ") == 1
    assert "Traceback" not in captured.err
    assert "--resume-from verify" in out


def test_a_bug_in_a_synchronous_phase_keeps_its_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A KeyError in the main thread is traced once, then the recap and hint."""
    root = make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", fake_which)

    def phase11(*_a: object, **_k: object) -> None:
        raise KeyError("version")

    monkeypatch.setattr(release, "_phase11_verify", phase11)

    with pytest.raises(SystemExit) as exc_info:
        run_release(str(root), version="0.2.0", resume_from="verify")

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert captured.err.count("Traceback") == 1
    assert "KeyError" in captured.err
    assert "--resume-from verify" in flat(captured.out)


def test_an_interrupt_before_any_phase_says_it_was_an_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_release_project(tmp_path)
    interrupted = release.interrupt_event()

    class _InterruptedThenFails:
        def clear(self) -> None:
            interrupted.set()
            raise ReleaseError("stopped by the operator")

        def drain(self) -> tuple[str, ...]:
            return ()

    monkeypatch.setattr(release, "_skips", _InterruptedThenFails())

    try:
        with pytest.raises(SystemExit) as exc_info:
            run_release(str(root), version="0.2.0")
    finally:
        interrupted.clear()

    out = flat(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert "interrupted before any phase ran" in out
    assert "failed before any phase ran" not in out


def _failed_command(*, stderr: str, output: str = "") -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(
        1, ["gh", "pr", "list"], output=output, stderr=stderr
    )


def test_a_failed_command_in_a_worker_thread_shows_its_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def phase11(*_a: object, **_k: object) -> None:
        return None

    root = _p9_p10_project(tmp_path, monkeypatch, phase11=phase11)

    def fails(*_a: object, **_k: object) -> None:
        raise _failed_command(stderr="HTTP 401: bad credentials\n")

    monkeypatch.setattr(release, "_propagate_website", fails)

    with pytest.raises(SystemExit):
        run_release(str(root), version="0.2.0", resume_from="post-release")

    assert "HTTP 401: bad credentials" in flat(capsys.readouterr().out)


def test_a_failed_command_in_a_synchronous_phase_shows_its_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", fake_which)

    def phase11(*_a: object, **_k: object) -> None:
        raise _failed_command(stderr="HTTP 401: bad credentials\n")

    monkeypatch.setattr(release, "_phase11_verify", phase11)

    with pytest.raises(SystemExit):
        run_release(str(root), version="0.2.0", resume_from="verify")

    assert "HTTP 401: bad credentials" in flat(capsys.readouterr().out)


def test_a_failed_command_with_no_stderr_shows_its_output() -> None:
    line = OperationalFailure.one_line(_failed_command(stderr="", output="plain\n"))

    assert line.endswith(": plain")


def test_a_failed_command_with_long_stderr_is_truncated() -> None:
    line = OperationalFailure.one_line(_failed_command(stderr="x" * 5000))

    assert len(line) < 1000


@pytest.mark.parametrize(
    "error",
    [
        ReleaseError("unique-xyz cannot be read"),
        KeyError("unique-xyz"),
        _failed_command(stderr="unique-xyz refused"),
    ],
    ids=["release-error", "bug", "operational"],
)
def test_an_error_in_flight_when_interrupted_is_still_shown_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    root = make_release_project(tmp_path)
    monkeypatch.setattr(shutil, "which", fake_which)
    interrupted = release.interrupt_event()

    def phase11(*_a: object, **_k: object) -> None:
        interrupted.set()
        raise error

    monkeypatch.setattr(release, "_phase11_verify", phase11)

    def no_reset(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(release, "_reset_propagation_siblings", no_reset)

    try:
        with pytest.raises(SystemExit) as exc_info:
            run_release(str(root), version="0.2.0", resume_from="verify")
    finally:
        interrupted.clear()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert (flat(captured.out) + captured.err).count("unique-xyz") == 1


def test_errors_gathered_before_an_interrupt_are_printed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    failed: Future[None] = Future()
    failed.set_exception(ReleaseError("unique-xyz cannot be read"))
    interrupted = threading.Event()
    interrupted.set()

    with pytest.raises(KeyboardInterrupt):
        ThreadedStep(ops=release._ops).collect(  # pyright: ignore[reportPrivateUsage]
            {failed: "website"}, interrupted=interrupted
        )

    assert "website: unique-xyz cannot be read" in flat(capsys.readouterr().out)


_REJECTED = "! [remote rejected] main -> main (protected branch hook declined)"


def test_bracketed_stderr_survives_the_worker_thread_recap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def phase11(*_a: object, **_k: object) -> None:
        return None

    root = _p9_p10_project(tmp_path, monkeypatch, phase11=phase11)

    def fails(*_a: object, **_k: object) -> None:
        raise _failed_command(stderr=f" {_REJECTED}\n")

    monkeypatch.setattr(release, "_propagate_website", fails)

    with pytest.raises(SystemExit):
        run_release(str(root), version="0.2.0", resume_from="post-release")

    assert "[remote rejected]" in flat(capsys.readouterr().out)


def test_reporter_fail_and_warn_print_bracketed_text_verbatim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reporter.warn(f"push said {_REJECTED}")
    with pytest.raises(ReleaseError):
        reporter.fail(f"push said {_REJECTED}")

    assert flat(capsys.readouterr().out).count("[remote rejected]") == 2


def test_a_reported_failure_is_not_repeated_on_interrupt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    failed: Future[None] = Future()
    try:
        reporter.fail("sibling has uncommitted changes")
    except ReleaseError as exc:
        failed.set_exception(exc)
    interrupted = threading.Event()
    interrupted.set()

    with pytest.raises(KeyboardInterrupt):
        ThreadedStep(ops=release._ops).collect(  # pyright: ignore[reportPrivateUsage]
            {failed: "website"}, interrupted=interrupted
        )

    assert flat(capsys.readouterr().out).count("sibling has uncommitted changes") == 1


def test_the_tail_of_long_stderr_is_kept() -> None:
    line = OperationalFailure.one_line(_failed_command(stderr="x" * 5000 + " the end"))

    assert (line.split(": ", 2)[2].startswith("..."), line.endswith("the end")) == (
        True,
        True,
    )


def test_credentials_in_a_url_in_stderr_are_not_shown() -> None:
    line = OperationalFailure.one_line(
        _failed_command(stderr="fatal: https://user:token@github.com/o/r.git denied")
    )

    assert ("user:token" in line, "https://github.com/o/r.git" in line) == (False, True)
