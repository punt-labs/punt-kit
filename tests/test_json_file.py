"""Tests for rewriting a JSON file as it was found."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from punt_kit.phases.shared.json_file import JsonFile

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("bom", ["", "\ufeff"])
@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("final_newline", [True, False])
def test_a_round_trip_keeps_bom_line_endings_and_final_newline(
    tmp_path: Path, bom: str, eol: str, final_newline: bool
) -> None:
    path = tmp_path / "plugin.json"
    body = eol.join(["{", '  "name": "café",', '  "version": "0.1.0"', "}"])
    original = bom + body + (eol if final_newline else "")
    path.write_bytes(original.encode())

    file = JsonFile(path)
    data = cast("dict[str, object]", file.load())
    file.save(data)

    assert path.read_bytes().decode() == original


def test_a_changed_value_is_written_in_the_files_own_style(tmp_path: Path) -> None:
    path = tmp_path / "plugin.json"
    path.write_bytes('\ufeff{\r\n  "version": "0.1.0"\r\n}\r\n'.encode())

    file = JsonFile(path)
    data = cast("dict[str, object]", file.load())
    data["version"] = "0.2.0"
    file.save(data)

    assert path.read_bytes().decode() == '\ufeff{\r\n  "version": "0.2.0"\r\n}\r\n'
