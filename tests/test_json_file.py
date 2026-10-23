"""Tests for rewriting a JSON file as it was found."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.text_file import TextFile

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


def test_unparseable_json_raises_a_release_error_naming_the_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plugin.json"
    path.write_text("{not json")

    with pytest.raises(ReleaseError, match=r"plugin\.json.*not valid JSON"):
        JsonFile(path).load()


def test_non_utf8_bytes_raise_a_release_error_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "plugin.json"
    path.write_bytes(b'{"name": "caf\xe9"}')

    with pytest.raises(ReleaseError, match=r"plugin\.json.*not valid UTF-8"):
        JsonFile(path).load()


def test_a_text_file_with_non_utf8_bytes_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_bytes(b"caf\xe9")

    with pytest.raises(ReleaseError, match=r"CHANGELOG\.md.*not valid UTF-8"):
        TextFile(path).read()


def test_from_bytes_drops_a_leading_bom() -> None:
    assert TextFile.from_bytes(b"\xef\xbb\xbf{}", source="git show") == "{}"


def test_parse_drops_a_leading_bom_from_text_that_is_not_a_file() -> None:
    assert JsonFile.parse('\ufeff{"a": 1}', source="git show") == {"a": 1}


def test_parse_object_names_the_source_when_the_text_is_not_json() -> None:
    with pytest.raises(ReleaseError, match=r"v1:plugin\.json is not valid JSON"):
        JsonFile.parse_object("{broken", source="v1:plugin.json")


def test_parse_object_rejects_a_json_array() -> None:
    with pytest.raises(ReleaseError, match=r"v1:plugin\.json must hold a JSON object"):
        JsonFile.parse_object("[1]", source="v1:plugin.json")
