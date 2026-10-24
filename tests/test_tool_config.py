"""Tests for the standard tool tables appended to a pyproject.toml."""

from __future__ import annotations

import tomllib

from punt_kit.tool_config import ToolConfigPatch


def test_a_file_with_every_standard_table_needs_nothing() -> None:
    data = tomllib.loads(
        "[tool.ruff.lint]\nselect = ['E']\n[tool.mypy]\n[tool.pyright]\n"
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )

    assert ToolConfigPatch(data).is_empty


def test_only_the_missing_tables_are_rendered() -> None:
    data = tomllib.loads("[tool.ruff]\nline-length = 100\n[tool.mypy]\nstrict = true\n")

    fragment = ToolConfigPatch(data).fragment()

    assert "[tool.ruff.lint]" in fragment
    assert "[tool.pyright]" in fragment
    assert "[tool.pytest.ini_options]" in fragment
    assert "[tool.mypy]" not in fragment
    assert "line-length" not in fragment


def test_the_appended_text_keeps_the_original_and_its_line_endings() -> None:
    text = '[project]\r\nname = "t"\r\n'
    data = tomllib.loads(text)

    updated = ToolConfigPatch(data).appended_to(text, data)

    assert updated is not None
    assert updated.startswith(text)
    assert "\n" not in updated.replace("\r\n", "")
