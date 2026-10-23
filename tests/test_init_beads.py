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

    with pytest.raises(BeadsInitError, match="beads init failed: no database"):
        BeadsInit(detect(root)).run()


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
