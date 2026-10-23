"""Invariants of the release package that no single behavior test would notice."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Self, final

import pytest

import punt_kit

_PACKAGE = Path(punt_kit.__file__).parent
_PLUGIN = _PACKAGE.parent.parent / "plugin"

# The one parser and the one reader of CHANGELOG.md content.
_CHANGELOG_MODULES = frozenset(
    {
        "changelog.py",
        "changelog_blocks.py",
        "changelog_parser.py",
        "changelog_sections.py",
    }
)
_READ_METHODS = frozenset({"read_text", "read_bytes", "readlines", "read", "open"})
_CHANGELOG = "CHANGELOG.md"


@final
class ChangelogReads:
    """The lines where a module reads CHANGELOG.md content itself."""

    __slots__ = ("_tree",)

    _tree: ast.Module

    def __new__(cls, source: str) -> Self:
        self = super().__new__(cls)
        self._tree = ast.parse(source)
        return self

    def lines(self) -> list[int]:
        """Line numbers of reads of a path built from ``"CHANGELOG.md"``."""
        paths = self._names_bound_to_the_changelog()
        return sorted(
            node.lineno
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Call) and self._reads(node, paths)
        )

    def _names_bound_to_the_changelog(self) -> set[str]:
        return {
            target.id
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Assign) and self._mentions_changelog(node.value)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

    @staticmethod
    def _mentions_changelog(node: ast.AST) -> bool:
        return any(
            isinstance(part, ast.Constant) and part.value == _CHANGELOG
            for part in ast.walk(node)
        )

    def _reads(self, call: ast.Call, paths: set[str]) -> bool:
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr in _READ_METHODS:
            target: ast.AST = func.value
        elif isinstance(func, ast.Name) and func.id == "open" and call.args:
            target = call.args[0]
        else:
            return False
        return self._mentions_changelog(target) or (
            isinstance(target, ast.Name) and target.id in paths
        )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('(root / "CHANGELOG.md").read_text()', id="inline"),
        pytest.param('p = root / "CHANGELOG.md"\np.read_text("utf-8")', id="bound"),
        pytest.param('p = root / "CHANGELOG.md"\np.read_bytes()', id="bytes"),
        pytest.param('open(root / "CHANGELOG.md")', id="open"),
        pytest.param('p = base / "CHANGELOG.md"\nopen(p)', id="open-bound"),
    ],
)
def test_the_scan_finds_a_module_reading_the_changelog(source: str) -> None:
    assert ChangelogReads(source).lines()


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('p = root / "CHANGELOG.md"\np.exists()', id="exists"),
        pytest.param('p = root / "CHANGELOG.md"\nfiles = [p]', id="staged"),
        pytest.param('(root / "README.md").read_text()', id="another-file"),
        pytest.param(
            'p = root / "CHANGELOG.md"\nq = root / "x"\nq.read_text()', id="other"
        ),
    ],
)
def test_the_scan_ignores_paths_that_are_not_read(source: str) -> None:
    assert ChangelogReads(source).lines() == []


def test_only_the_changelog_modules_read_changelog_content() -> None:
    """One parser, every reader: nothing else opens CHANGELOG.md itself."""
    readers = {
        str(path.relative_to(_PACKAGE)): lines
        for path in sorted(_PACKAGE.rglob("*.py"))
        if path.name not in _CHANGELOG_MODULES
        if (lines := ChangelogReads(path.read_text("utf-8")).lines())
    }
    assert readers == {}


def _frontmatter(path: Path) -> str:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text("utf-8"), re.DOTALL)
    assert match is not None, f"{path} has no frontmatter"
    return match.group(1)


def test_every_skill_with_a_command_is_hidden_from_the_slash_menu() -> None:
    """A skill the command of the same name loads must not list itself twice."""
    skills = sorted((_PLUGIN / "skills").glob("*/SKILL.md"))
    twinned = [
        s for s in skills if (_PLUGIN / "commands" / f"{s.parent.name}.md").exists()
    ]
    assert twinned, "no skill has a command of the same name: the guard guards nothing"
    visible = [
        s.parent.name
        for s in twinned
        if not re.search(r"^user-invocable:\s*false\s*$", _frontmatter(s), re.MULTILINE)
    ]
    assert visible == []


def test_phase_9_does_not_import_the_readme_pin() -> None:
    """Phase 4 owns the README pin; Phase 9 is the dev restore only."""
    tree = ast.parse(
        (_PACKAGE / "phases" / "phase09_post_release.py").read_text("utf-8")
    )
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert "punt_kit.phases.shared.readme_sha" not in imported
