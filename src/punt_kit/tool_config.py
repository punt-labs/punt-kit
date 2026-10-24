"""The standard tool tables a pyproject.toml lacks, appended without a rewrite."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Self, cast, final

import tomli_w

if TYPE_CHECKING:
    from collections.abc import Mapping

_RUFF_LINT: dict[str, object] = {"select": ["E", "F", "I", "UP", "B", "SIM", "TCH"]}
_RUFF: dict[str, object] = {
    "line-length": 88,
    "target-version": "py313",
    "lint": _RUFF_LINT,
}
_MYPY: dict[str, object] = {
    "python_version": "3.13",
    "strict": True,
    "warn_return_any": True,
    "warn_unused_configs": True,
}
_PYRIGHT: dict[str, object] = {"pythonVersion": "3.13", "typeCheckingMode": "strict"}
_PYTEST_INI: dict[str, object] = {"testpaths": ["tests"]}


@final
class ToolConfigPatch:
    """The ``[tool.*]`` tables a pyproject.toml lacks, and how to append them.

    A structural rewrite (parse, edit, dump) drops every comment and the
    file's line endings and BOM, so the missing tables are rendered on their
    own and appended to the text as found. Existing tables are never edited:
    a table the file already has is the user's.
    """

    __slots__ = ("_additions",)

    _additions: dict[str, object]

    def __new__(cls, data: Mapping[str, object]) -> Self:
        self = super().__new__(cls)
        tool_raw = data.get("tool")
        tool = cast("dict[str, object]", tool_raw) if isinstance(tool_raw, dict) else {}
        additions: dict[str, object] = {}
        ruff = tool.get("ruff")
        if "ruff" not in tool:
            additions["ruff"] = _RUFF
        elif isinstance(ruff, dict) and "lint" not in ruff:
            additions["ruff"] = {"lint": _RUFF_LINT}
        if "mypy" not in tool:
            additions["mypy"] = _MYPY
        if "pyright" not in tool:
            additions["pyright"] = _PYRIGHT
        pytest_cfg = tool.get("pytest")
        lacks_ini = isinstance(pytest_cfg, dict) and "ini_options" not in pytest_cfg
        if "pytest" not in tool or lacks_ini:
            additions["pytest"] = {"ini_options": _PYTEST_INI}
        self._additions = additions
        return self

    @property
    def is_empty(self) -> bool:
        """True when the file already has every standard table."""
        return not self._additions

    def fragment(self) -> str:
        """The missing tables as TOML text with ``\\n`` line endings."""
        return tomli_w.dumps({"tool": self._additions})

    def appended_to(self, text: str, data: Mapping[str, object]) -> str | None:
        """``text`` with the missing tables appended, or ``None`` when unsafe.

        Appending is only valid TOML when it parses and means what was
        intended: a table defined as an inline value (``ruff = {...}``)
        cannot be extended by a later ``[tool.ruff.lint]`` header. The result
        is parsed and compared with ``data`` plus the additions; any
        difference returns ``None`` and the caller leaves the file alone.
        """
        eol = "\r\n" if "\r\n" in text else "\n"
        body = text if text.endswith("\n") or not text else text + eol
        joined = body + eol + self.fragment().replace("\n", eol)
        expected = self._merged(data, {"tool": self._additions})
        try:
            parsed = tomllib.loads(joined)
        except tomllib.TOMLDecodeError:
            return None
        return joined if parsed == expected else None

    @classmethod
    def _merged(
        cls, base: Mapping[str, object], extra: Mapping[str, object]
    ) -> dict[str, object]:
        """``base`` with the tables of ``extra`` merged in, recursively."""
        merged = dict(base)
        for key, value in extra.items():
            current = merged.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                merged[key] = cls._merged(
                    cast("dict[str, object]", current),
                    cast("dict[str, object]", value),
                )
            else:
                merged[key] = value
        return merged
