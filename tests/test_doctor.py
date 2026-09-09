"""Tests for installation health checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_kit.doctor import run_doctor

if TYPE_CHECKING:
    import pytest


def _stub_which(present: set[str]) -> object:
    """Return a ``shutil.which`` stand-in that finds only names in ``present``."""

    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in present else None

    return which


def test_not_found_optional_binary_shows_optional_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing optional binary must not double the '(optional)' annotation."""
    monkeypatch.setattr("shutil.which", _stub_which(set()))

    run_doctor(print_results=True)

    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "pyright" in line)
    assert line == "  ✗ pyright: not found (optional)"
    assert line.count("(optional)") == 1


def test_not_found_required_binary_is_distinguishable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing required binary is annotated '(required)', not doubled."""
    monkeypatch.setattr("shutil.which", _stub_which(set()))

    run_doctor(print_results=True)

    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "uv" in line)
    assert line == "  ✗ uv: not found (required)"


def test_found_optional_binary_shows_path_and_optional(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A present optional binary reports its path plus the '(optional)' tag."""
    monkeypatch.setattr("shutil.which", _stub_which({"pyright"}))

    run_doctor(print_results=True)

    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "pyright" in line)
    assert line == "  ✓ pyright: /usr/bin/pyright (optional)"


def test_found_required_binary_has_no_annotation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A present required binary reports its bare path — no annotation needed."""
    monkeypatch.setattr("shutil.which", _stub_which({"uv"}))

    run_doctor(print_results=True)

    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "uv" in line)
    assert line == "  ✓ uv: /usr/bin/uv"
