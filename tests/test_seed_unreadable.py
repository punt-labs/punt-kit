"""An unreadable file is reported by name; seed does not crash with a traceback."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from rich.console import Console

from punt_kit import seed
from punt_kit.seed import run_seed

if TYPE_CHECKING:
    from pathlib import Path

_NOT_UTF8 = b"\xff\xfe not utf-8 \xc3\x28\n"


def test_seed_reports_an_unreadable_makefile_and_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The Makefile cannot be decoded: its name and the reason are printed."""
    monkeypatch.setattr(seed, "console", Console(width=1000))
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
    (tmp_path / "Makefile").write_bytes(_NOT_UTF8)

    with pytest.raises(SystemExit) as exc_info:
        run_seed(str(tmp_path), target="makefile")

    out = " ".join(capsys.readouterr().out.split())
    assert exc_info.value.code == 1
    assert "Makefile is not valid UTF-8" in out
