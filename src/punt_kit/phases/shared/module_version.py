"""The ``__version__`` a Python module assigns, classified from its syntax tree."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Self, final

_NAME = "__version__"
# A string the rewriter can set in place: one line, no prefix, no escape.
_PLAIN_STRING = re.compile(r"""(["'])[^"'\\\n]*\1""")
# What may follow the closing quote: whitespace and a comment, nothing else.
_TRAILER = re.compile(r"\s*(?:#.*)?")


class UnpinnableVersionError(ValueError):
    """A ``__version__`` that is neither a plain literal nor computed."""


@dataclass(frozen=True, slots=True)
class ComputedVersion:
    """A ``__version__`` computed at import time: there is nothing to pin."""

    source: str


@dataclass(frozen=True, slots=True)
class LiteralVersion:
    """A plain quoted version, located so it can be set in place."""

    value: str
    line: int  # 0-based index into the text's ``\n``-separated lines
    start: int  # first character inside the quotes
    end: int  # the closing quote

    def rewritten(self, text: str, version: str) -> str:
        """``text`` with this literal set to ``version``, quotes kept."""
        lines = text.split("\n")
        old = lines[self.line]
        lines[self.line] = f"{old[: self.start]}{version}{old[self.end :]}"
        return "\n".join(lines)


@final
class ModuleVersion:
    """The module-level ``__version__`` of a Python source file.

    Read from the syntax tree, never the text, so a docstring that mentions
    ``__version__ = "9.9"`` is not an assignment. Only statements in the
    module body count; one inside ``try``/``if`` is not seen. ``resolved``
    answers one of:

    - ``None`` — the module does not assign ``__version__`` (it may import it).
    - ``ComputedVersion`` — the value is a call (``installed_version()``,
      ``importlib.metadata.version("x")``): read from installed metadata at
      import time, so there is nothing to bump or verify.
    - ``LiteralVersion`` — a one-line, unprefixed, single- or double-quoted
      string that ends its statement (a ``# comment`` may follow), optionally
      annotated. A plain name bound once, at module level, to such a literal
      (``VERSION = "1.0"``; ``__version__ = VERSION``) resolves to that
      literal, and it is the one rewritten.

    Anything else raises ``UnpinnableVersionError``, because skipping it would
    ship a stale version: a file that does not parse; more than one
    module-level assignment (Python keeps the last); an f-, r-, u- or b-string;
    a parenthesised, concatenated, triple-quoted or conditional value; and a
    name or attribute bound in another module.
    """

    __slots__ = ("_assigned", "_imported", "_lines")

    _assigned: defaultdict[str, list[ast.stmt]]
    _imported: set[str]
    _lines: list[str]

    def __new__(cls, text: str) -> Self:
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            msg = f"the file does not parse ({exc.msg}, line {exc.lineno})"
            raise UnpinnableVersionError(msg) from exc
        self = super().__new__(cls)
        self._lines = text.split("\n")
        self._assigned = defaultdict(list)
        self._imported = set()
        for stmt in tree.body:
            self._record(stmt)
        return self

    # None: absence is the contract; a module may import or omit __version__.
    def resolved(self) -> ComputedVersion | LiteralVersion | None:
        """What the module assigns to ``__version__``; ``None`` when nothing."""
        if _NAME not in self._assigned:
            return None
        return self._resolve(_NAME, frozenset())

    def _record(self, stmt: ast.stmt) -> None:
        """Note which names ``stmt`` binds at module level."""
        match stmt:
            case ast.Assign(targets=targets):
                stored = {
                    node.id
                    for target in targets
                    for node in ast.walk(target)
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
                }
                for name in stored:
                    self._assigned[name].append(stmt)
            case ast.AnnAssign(target=ast.Name(id=name), value=value) if value:
                self._assigned[name].append(stmt)
            case ast.AugAssign(target=ast.Name(id=name)):
                self._assigned[name].append(stmt)
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                self._imported.update(
                    (alias.asname or alias.name).split(".")[0] for alias in aliases
                )
            case _:
                pass

    def _resolve(
        self, name: str, seen: frozenset[str]
    ) -> ComputedVersion | LiteralVersion:
        stmt = self._only_assignment(name)
        source = self._source(stmt)
        seen |= {name}
        match self._value(stmt, source):
            case ast.Call():
                return ComputedVersion(source)
            case ast.Name(id=other) if other not in seen:
                return self._resolve(other, seen)
            case ast.Constant(value=str()) as node:
                return self._literal(stmt, node, name, source)
            case _:
                msg = f'`{source}` is not a plain quoted string ({name} = "X.Y.Z")'
                raise UnpinnableVersionError(msg)

    def _only_assignment(self, name: str) -> ast.stmt:
        """The one module-level statement that binds ``name``."""
        stmts = self._assigned.get(name, [])
        if not stmts:
            where = (
                "imported from another module; pin the version there"
                if name in self._imported
                else "not assigned at module level"
            )
            msg = f"{name} is {where}"
            raise UnpinnableVersionError(msg)
        if len(stmts) > 1:
            lines = ", ".join(str(stmt.lineno) for stmt in stmts)
            msg = (
                f"{name} is assigned {len(stmts)} times at module level "
                f"(lines {lines}); Python keeps the last, so a bump of one "
                "could ship a stale version"
            )
            raise UnpinnableVersionError(msg)
        return stmts[0]

    @staticmethod
    def _value(stmt: ast.stmt, source: str) -> ast.expr:
        """The expression ``stmt`` assigns to a single plain name."""
        match stmt:
            case ast.Assign(targets=[ast.Name()], value=value):
                return value
            case ast.AnnAssign(value=ast.expr() as value):
                return value
            case _:
                msg = f"`{source}` does not assign one plain name"
                raise UnpinnableVersionError(msg)

    def _literal(
        self, stmt: ast.stmt, node: ast.Constant, name: str, source: str
    ) -> LiteralVersion:
        """``node`` located for rewriting, when its source form is plain."""
        line = self._lines[node.lineno - 1]
        start = _char_offset(line, node.col_offset)
        end = _char_offset(line, node.end_col_offset or 0)
        head = line[_char_offset(line, stmt.col_offset) : start]
        is_plain = (
            node.end_lineno == node.lineno == stmt.lineno
            and re.fullmatch(rf"{re.escape(name)}\s*(?::[^=]*)?=\s*", head)
            and _PLAIN_STRING.fullmatch(line, start, end)
            and _TRAILER.fullmatch(line, end)
        )
        if not is_plain:
            msg = f'`{source}` is not a plain quoted string ({name} = "X.Y.Z")'
            raise UnpinnableVersionError(msg)
        return LiteralVersion(str(node.value), node.lineno - 1, start + 1, end - 1)

    def _source(self, stmt: ast.stmt) -> str:
        """The first line of ``stmt``, stripped, for messages."""
        return self._lines[stmt.lineno - 1].strip()


def _char_offset(line: str, byte_offset: int) -> int:
    """Turn ``ast``'s UTF-8 byte column into a character index into ``line``."""
    return len(line.encode()[:byte_offset].decode())
