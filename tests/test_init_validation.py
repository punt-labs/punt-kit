"""punt repo init validates before it writes and never runs ``bd``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_kit.init import TEMPLATES, run_init
from tests.helpers import (
    fake_bd,
    python_project,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_init_reads_every_plugin_manifest_before_writing(tmp_path: Path) -> None:
    """A nameless first manifest sends init on to a malformed second one."""
    python_project(tmp_path)
    (tmp_path / "plugin" / ".claude-plugin").mkdir(parents=True)
    (tmp_path / "plugin" / ".claude-plugin" / "plugin.json").write_text("{}")
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{broken")

    with pytest.raises(SystemExit) as raised:
        run_init(str(tmp_path))

    assert raised.value.code == 1
    assert not (tmp_path / ".github").exists()
    assert not (tmp_path / ".claude").exists()


def test_init_never_runs_bd_or_creates_beads(tmp_path: Path) -> None:
    """Work is tracked in Linear: init neither runs ``bd`` nor makes ``.beads/``."""
    project = tmp_path / "project"
    project.mkdir()
    python_project(project)
    bin_dir = fake_bd(tmp_path / "bin", '#!/bin/sh\ntouch "$0.ran"\nmkdir .beads\n')

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
        changed = run_init(str(project))

    assert not (tmp_path / "bin" / "bd.ran").exists()
    assert not (project / ".beads").exists()
    assert ".beads/" not in changed


def test_init_does_not_report_a_bom_workflow_identical_to_the_template(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "README.md").write_text("# Test")
    workflow = tmp_path / ".github" / "workflows" / "docs.yml"
    workflow.parent.mkdir(parents=True)
    template = (TEMPLATES / "workflows" / "docs.yml").read_text(encoding="utf-8")
    workflow.write_bytes(("﻿" + template).encode("utf-8"))

    run_init(str(tmp_path))

    assert "differs from template" not in capsys.readouterr().out
