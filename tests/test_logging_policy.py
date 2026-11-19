"""Reject unsafe diagnostic setup regardless of import spelling."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_HANDLERS = {"RotatingFileHandler", "TimedRotatingFileHandler", "WatchedFileHandler"}
_BANNED = {"logging.basicConfig", *(f"logging.handlers.{name}" for name in _HANDLERS)}


class LoggingPolicyScan:
    """Resolve logging aliases before inspecting references and config strings."""

    def __init__(self, source: str) -> None:
        self._tree = ast.parse(source)
        self._aliases: dict[str, str] = {}

    def _name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self._aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return f"{self._name(node.value)}.{node.attr}"
        return ""

    def _imports(self) -> None:
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    self._aliases[item.asname or item.name.split(".")[0]] = (
                        item.name if item.asname else item.name.split(".")[0]
                    )
            elif isinstance(node, ast.ImportFrom):
                for item in node.names:
                    self._aliases[item.asname or item.name] = (
                        f"{node.module}.{item.name}"
                    )

    def violations(self) -> list[int]:
        self._imports()
        assignments = [
            node for node in ast.walk(self._tree) if isinstance(node, ast.Assign)
        ]
        for _ in range(len(assignments) + 1):
            for assignment in assignments:
                for target in assignment.targets:
                    if isinstance(target, ast.Name):
                        self._aliases[target.id] = self._name(assignment.value)
        findings: set[int] = set()
        for node in ast.walk(self._tree):
            if (
                isinstance(node, (ast.Name, ast.Attribute))
                and self._name(node) in _BANNED
            ):
                findings.add(node.lineno)
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and (node.value in _BANNED or node.value in _HANDLERS)
            ):
                findings.add(node.lineno)
        return sorted(findings)


def test_sources_use_shared_safe_logging() -> None:
    root = Path(__file__).resolve().parents[1]
    findings = {
        str(path.relative_to(root)): lines
        for directory in (root / "src", root / "tools")
        for path in directory.rglob("*.py")
        if (lines := LoggingPolicyScan(path.read_text()).violations())
    }
    assert findings == {}


@pytest.mark.parametrize(
    "source",
    [
        "import logging; logging.basicConfig()",
        "import logging as log; log.basicConfig()",
        "from logging import basicConfig as setup; setup()",
        "import logging as log; setup = log.basicConfig; setup()",
        *(
            source
            for name in sorted(_HANDLERS)
            for source in (
                f"import logging.handlers; logging.handlers.{name}('private')",
                f"import logging.handlers as handlers; handlers.{name}('private')",
                f"from logging import handlers as h; h.{name}('private')",
                f"from logging.handlers import {name} as Handler; Handler('private')",
                f"from logging.handlers import {name} as Handler\n"
                "class Custom(Handler): pass",
                f"import logging.handlers as h\nclass Custom(h.{name}): pass",
                "import logging.config as c; "
                f"c.dictConfig({{'class': 'logging.handlers.{name}'}})",
                "import logging.config as c; "
                f"c.dictConfig({{'()': 'logging.handlers.{name}'}})",
                f"config = {{'class': '{name}'}}",
            )
        ),
    ],
)
def test_scanner_rejects_unsafe_forms(source: str) -> None:
    assert LoggingPolicyScan(source).violations()


@pytest.mark.parametrize(
    "source",
    [
        "from punt_observe.logging import configure_logging; "
        "configure_logging('punt', 'cli')",
        "import logging; logger = logging.getLogger(__name__); logger.info('Complete')",
        "import logging.config; logging.config.dictConfig({'handlers': {}})",
        "",
    ],
)
def test_scanner_allows_safe_and_empty_sources(source: str) -> None:
    assert LoggingPolicyScan(source).violations() == []
