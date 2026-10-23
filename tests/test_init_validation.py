"""punt init validates before it writes, and reports a failed `bd init`."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from punt_kit.init import TEMPLATES, run_init
from tests.test_init import (
    _no_bd,  # pyright: ignore[reportPrivateUsage]
    _python_project,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from pathlib import Path


def test_init_reads_every_plugin_manifest_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nameless first manifest sends init on to a malformed second one."""
    monkeypatch.setattr(shutil, "which", _no_bd)
    _python_project(tmp_path)
    (tmp_path / "plugin" / ".claude-plugin").mkdir(parents=True)
    (tmp_path / "plugin" / ".claude-plugin" / "plugin.json").write_text("{}")
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{broken")

    with pytest.raises(SystemExit) as raised:
        run_init(str(tmp_path))

    assert raised.value.code == 1
    assert not (tmp_path / ".github").exists()
    assert not (tmp_path / ".claude").exists()


def test_init_does_not_report_a_bom_workflow_identical_to_the_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(shutil, "which", _no_bd)
    (tmp_path / "README.md").write_text("# Test")
    workflow = tmp_path / ".github" / "workflows" / "docs.yml"
    workflow.parent.mkdir(parents=True)
    template = (TEMPLATES / "workflows" / "docs.yml").read_text(encoding="utf-8")
    workflow.write_bytes(("\ufeff" + template).encode("utf-8"))

    run_init(str(tmp_path))

    assert "differs from template" not in capsys.readouterr().out


def _fake_bd(directory: Path, script: str) -> str:
    """Put a ``bd`` that is ``script`` on PATH and return the new PATH."""
    directory.mkdir()
    bd = directory / "bd"
    bd.write_text(script)
    bd.chmod(0o755)
    return str(directory)


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        pytest.param(
            "#!/bin/sh\necho no database >&2\nexit 3\n", "no database", id="exit"
        ),
        pytest.param("#!/nonexistent/interpreter\n", "No such file", id="oserror"),
    ],
)
def test_a_failed_bd_init_fails_the_run_after_the_other_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    script: str,
    reason: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _python_project(project)
    bin_dir = _fake_bd(tmp_path / "bin", script)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")

    with pytest.raises(SystemExit) as raised:
        run_init(str(project))

    out = " ".join(capsys.readouterr().out.split())
    assert raised.value.code == 1
    assert "beads init failed" in out
    assert reason in out
    assert (project / "CLAUDE.md").exists()
    assert (project / ".claude" / "settings.json").exists()
