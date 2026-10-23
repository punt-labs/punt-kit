"""One unreadable file is one FAIL finding; every other finding still prints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from rich.console import Console

from punt_kit import audit
from punt_kit.audit import run_audit
from tests.helpers import (
    make_compliant_hybrid,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOT_UTF8 = b"\xff\xfe not utf-8 \xc3\x28\n"


@pytest.mark.parametrize("name", ["Makefile", "install.sh", "README.md"])
def test_an_unreadable_file_fails_alone_and_the_rest_still_prints(
    tmp_path: Path,
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The unreadable file is named with its reason; unrelated checks still run."""
    # Wide enough that rich never wraps the path mid-word.
    monkeypatch.setattr(audit, "console", Console(width=1000))
    make_compliant_hybrid(tmp_path)
    (tmp_path / name).write_bytes(_NOT_UTF8)

    with pytest.raises(SystemExit) as exc_info:
        run_audit(str(tmp_path))

    out = " ".join(capsys.readouterr().out.split())
    assert exc_info.value.code == 1
    assert f"{name} is not valid UTF-8" in out
    assert "CI lint workflow exists" in out
    assert "Linting configured" in out
    assert "passed" in out
