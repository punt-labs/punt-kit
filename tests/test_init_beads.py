"""The beads step of punt init: the success path, the shortcut and both failures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_kit.detect import detect
from punt_kit.init_beads import BeadsInit, BeadsInitError
from punt_kit.phases.shared import timeouts
from tests.helpers import fake_bd

if TYPE_CHECKING:
    from pathlib import Path

_RECORDING_BD = '#!/bin/sh\necho "$@" > bd-args.txt\nmkdir .beads\n'


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "my-project_x"
    root.mkdir()
    return root


def _with_bd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, script: str) -> None:
    bin_dir = fake_bd(tmp_path / "bin", script)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")


def test_a_successful_bd_init_reports_the_beads_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _with_bd(monkeypatch, tmp_path, _RECORDING_BD)

    changed = BeadsInit(detect(root)).run()

    assert changed == [".beads/"]
    assert (root / "bd-args.txt").read_text().split() == [
        "init",
        "--prefix",
        "myprojectx",
    ]


def test_a_project_with_beads_never_runs_bd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    (root / ".beads").mkdir()
    _with_bd(monkeypatch, tmp_path, _RECORDING_BD)

    changed = BeadsInit(detect(root)).run()

    assert (changed, (root / "bd-args.txt").exists()) == ([], False)


def test_a_missing_bd_is_skipped_with_a_notice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _project(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))

    changed = BeadsInit(detect(root)).run()

    assert changed == []
    assert "bd not found" in capsys.readouterr().out


def test_a_bd_that_exits_non_zero_raises_with_its_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _with_bd(monkeypatch, tmp_path, "#!/bin/sh\necho no database >&2\nexit 3\n")

    with pytest.raises(BeadsInitError, match=r"beads init failed: .*: no database$"):
        BeadsInit(detect(root)).run()


def test_a_bd_failure_redacts_credentials_in_its_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    script = (
        "#!/bin/sh\n"
        "echo 'fatal: https://user:ghp_SECRET@github.com/o/r.git denied' >&2\n"
        "exit 3\n"
    )
    _with_bd(monkeypatch, tmp_path, script)

    with pytest.raises(BeadsInitError) as caught:
        BeadsInit(detect(root)).run()

    assert "ghp_SECRET" not in str(caught.value)


def test_a_bd_failure_is_one_line_and_keeps_the_tail_of_its_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    script = (
        "#!/bin/sh\n"
        "i=0\n"
        'while [ "$i" -lt 200 ]; do echo "noise line $i padding padding" >&2;'
        " i=$((i+1)); done\n"
        "echo the real reason >&2\n"
        "exit 3\n"
    )
    _with_bd(monkeypatch, tmp_path, script)

    with pytest.raises(BeadsInitError) as caught:
        BeadsInit(detect(root)).run()

    message = str(caught.value)
    assert ("\n" in message, message.endswith("the real reason")) == (False, True)
    assert len(message) < 800


def test_a_bd_that_cannot_run_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _with_bd(monkeypatch, tmp_path, "#!/nonexistent/interpreter\n")

    with pytest.raises(BeadsInitError, match="beads init failed: .*No such file"):
        BeadsInit(detect(root)).run()


def test_a_bd_that_hangs_raises_naming_the_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _with_bd(monkeypatch, tmp_path, "#!/bin/sh\nexec sleep 30\n")
    monkeypatch.setattr(timeouts, "BD_INIT", 1)

    with pytest.raises(BeadsInitError, match="beads init timed out after 1s"):
        BeadsInit(detect(root)).run()


def test_a_bd_that_hangs_after_creating_beads_names_the_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    script = (
        "#!/bin/sh\nmkdir .beads\n"
        "echo 'cloning https://u:ghp_SECRET@host.example/db' >&2\n"
        "exec sleep 30\n"
    )
    _with_bd(monkeypatch, tmp_path, script)
    monkeypatch.setattr(timeouts, "BD_INIT", 1)

    with pytest.raises(BeadsInitError) as caught:
        BeadsInit(detect(root)).run()

    message = str(caught.value)
    assert ("ghp_SECRET" in message, "cloning" in message) == (False, True)
    assert "bd init left a partial .beads/ — remove it before retrying" in message


def test_a_bd_that_fails_after_creating_beads_names_the_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    script = "#!/bin/sh\nmkdir .beads\necho half done >&2\nexit 3\n"
    _with_bd(monkeypatch, tmp_path, script)

    with pytest.raises(BeadsInitError, match=r"half done.*partial \.beads/"):
        BeadsInit(detect(root)).run()


def test_a_bd_failure_that_created_nothing_does_not_mention_a_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _with_bd(monkeypatch, tmp_path, "#!/bin/sh\necho no database >&2\nexit 3\n")

    with pytest.raises(BeadsInitError) as caught:
        BeadsInit(detect(root)).run()

    assert "partial" not in str(caught.value)
