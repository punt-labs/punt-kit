"""Tests for pii checkout."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from punt_kit.errors import CommandFailure
from punt_kit.pii_checkout import run_pii

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("config_file", ["pyproject.toml", ".punt-pii.toml"])
def test_staged_scan_uses_the_index_rules(tmp_path: Path, config_file: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    header = "[tool.punt.pii]\n" if config_file == "pyproject.toml" else ""
    config = tmp_path / config_file
    config.write_text(header + 'deny = ["fixture-token"]\n')
    (tmp_path / "example.txt").write_text("contains fixture-token\n")
    subprocess.run(
        ["git", "add", "--", config_file, "example.txt"], cwd=tmp_path, check=True
    )
    config.write_text(header + "deny = []\n")
    (tmp_path / "example.txt").write_text("clean worktree\n")

    assert run_pii(str(tmp_path))["findings"] == []
    with pytest.raises(CommandFailure) as exc_info:
        run_pii(str(tmp_path), staged=True)
    findings = exc_info.value.details["findings"]
    assert isinstance(findings, list)
    assert {"file": "example.txt", "line": 1, "category": "deny"} in findings

    explicit = tmp_path / "explicit.toml"
    explicit.write_text("deny = []\n")
    assert run_pii(str(tmp_path), staged=True, config=str(explicit))["findings"] == []


def test_invalid_staged_rules_are_not_replaced_by_worktree_rules(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    config = tmp_path / ".punt-pii.toml"
    config.write_text("deny = [\n")
    subprocess.run(["git", "add", "--", config.name], cwd=tmp_path, check=True)
    config.write_text("deny = []\n")

    with pytest.raises(CommandFailure) as caught:
        run_pii(str(tmp_path), staged=True)
    assert "staged .punt-pii.toml is not valid TOML" in caught.value.message
