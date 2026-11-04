"""The ``__version__`` a Python module assigns, classified from its syntax tree."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, TypeIs, final

if TYPE_CHECKING:
    from collections.abc import Iterator

_NAME = "__version__"
# A string the rewriter can set in place: one line, no prefix, no escape.
_PLAIN_STRING = re.compile(r"""(["'])[^"'\\\n]*\1""")
# What may follow the closing quote: whitespace and a comment, nothing else.
_TRAILER = re.compile(r"\s*(?:#.*)?")
# A string that spells a version somewhere in it: digits, a dot, digits.
_VERSION_TEXT = re.compile(r"\d+\.\d+")
# Statements that open a scope of their own: their bodies bind other names.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


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
    ``__version__ = "9.9"`` is not an assignment. Every binding in the
    module's global scope counts: an assignment (plain, annotated with a
    value, or augmented), an import, a walrus, a ``for``/``with``/``match``
    target, and an assignment under ``global`` inside a function, whether in
    the module body or inside an ``if``/``try``/``with``/``for``/``while``/
    ``match`` block. A bare annotation is not a binding. ``resolved`` answers
    one of:

    - ``None`` — nothing in the module binds ``__version__``.
    - ``ComputedVersion`` — the value contains a call (``installed_version()``,
      ``version("x").split("+")[0]``, versioneer's
      ``get_versions()["version"]``) and no version-like literal reaches it:
      read from installed metadata at import time, so there is nothing to
      bump or verify.
    - ``LiteralVersion`` — a one-line, unprefixed, single- or double-quoted
      string that ends its statement (a ``# comment`` may follow), optionally
      annotated. A plain name bound once, in the module body, to such a
      literal (``VERSION = "1.0"``; ``__version__ = VERSION``) resolves to
      that literal, and it is the one rewritten.

    Anything else raises ``UnpinnableVersionError``, because skipping it would
    ship a stale version: a file that does not parse; ``__version__``, or a
    name it resolves through, bound more than once (Python keeps the last),
    bound only inside a block or a function, or imported from another module;
    an ``import *`` beside them; an f-, r-, u- or b-string; a parenthesised,
    concatenated, triple-quoted or conditional value; and a call that a
    version-like literal reaches (``str("0.1.0")``,
    ``os.environ.get("V", "0.1.0")``, ``".".join(map(str, VERSION_INFO))``
    with ``VERSION_INFO = (0, 1, 0)``). A version-like literal is a string
    holding ``digits.digits`` or a tuple of two or more ints; it reaches a
    value when it appears inside it or a name inside it is bound in this
    module to a value it reaches.
    """

    __slots__ = ("_bindings", "_lines")

    _bindings: _ModuleBindings
    _lines: list[str]

    def __new__(cls, text: str) -> Self:
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            msg = f"the file does not parse ({exc.msg}, line {exc.lineno})"
            raise UnpinnableVersionError(msg) from exc
        self = super().__new__(cls)
        self._lines = text.split("\n")
        self._bindings = _ModuleBindings(tree)
        return self

    # None: absence is the contract; a module may omit __version__.
    def resolved(self) -> ComputedVersion | LiteralVersion | None:
        """What the module assigns to ``__version__``; ``None`` when nothing."""
        if not self._bindings.of(_NAME):
            return None
        return self._resolve(_NAME, frozenset())

    def _resolve(
        self, name: str, seen: frozenset[str]
    ) -> ComputedVersion | LiteralVersion:
        stmt = self._only_binding(name)
        source = self._source(stmt)
        seen |= {name}
        value = self._value(stmt, name, source)
        match value:
            case ast.Name(id=other) if other not in seen:
                return self._resolve(other, seen)
            case ast.Constant(value=str()):
                return self._literal(stmt, value, name, source)
            case _ if any(isinstance(node, ast.Call) for node in ast.walk(value)):
                return self._computed(value, name, source)
            case _:
                msg = f'`{source}` is not a plain quoted string ({name} = "X.Y.Z")'
                raise UnpinnableVersionError(msg)

    def _only_binding(self, name: str) -> ast.stmt:
        """The one module-body statement that binds ``name``."""
        for star in self._bindings.star_imports():
            msg = (
                f"`{ast.unparse(star)}` at line {star.lineno} could rebind {name}, "
                "so a bump could ship a stale version"
            )
            raise UnpinnableVersionError(msg)
        bindings = self._bindings.of(name)
        if not bindings:
            msg = f"{name} is not assigned at module level"
            raise UnpinnableVersionError(msg)
        if len(bindings) > 1:
            lines = ", ".join(str(binding.stmt.lineno) for binding in bindings)
            msg = (
                f"{name} is assigned {len(bindings)} times (lines {lines}); "
                "Python keeps the last, so a bump of one could ship a stale version"
            )
            raise UnpinnableVersionError(msg)
        [binding] = bindings
        if binding.is_import:
            msg = f"{name} is imported from another module; pin the version there"
            raise UnpinnableVersionError(msg)
        if binding.is_nested:
            msg = (
                f"{name} is assigned inside a block at line {binding.stmt.lineno}; "
                "a bump cannot tell whether it runs, so it could ship a stale version"
            )
            raise UnpinnableVersionError(msg)
        return binding.stmt

    @staticmethod
    def _value(stmt: ast.stmt, name: str, source: str) -> ast.expr:
        """The expression ``stmt`` assigns to ``name`` alone."""
        match stmt:
            case ast.Assign(targets=[ast.Name(id=target)], value=value) if (
                target == name
            ):
                return value
            case ast.AnnAssign(
                target=ast.Name(id=target), value=ast.expr() as value
            ) if target == name:
                return value
            case _:
                msg = f"`{source}` does not assign one plain name"
                raise UnpinnableVersionError(msg)

    def _computed(self, value: ast.expr, name: str, source: str) -> ComputedVersion:
        """``value`` as computed, unless a hardcoded version feeds the call."""
        literal = self._version_literal(value, frozenset())
        if literal is not None:
            msg = (
                f"`{source}` computes {name} from the hardcoded version "
                f"{ast.unparse(literal)} (line {literal.lineno}), so a bump could "
                f'ship a stale version; write {name} = "X.Y.Z" or read it from '
                "package metadata"
            )
            raise UnpinnableVersionError(msg)
        return ComputedVersion(source)

    def _version_literal(self, expr: ast.expr, seen: frozenset[str]) -> ast.expr | None:
        """A version-like literal that reaches ``expr``, through names too."""
        for node in ast.walk(expr):
            if _is_version_like(node):
                return node
            if isinstance(node, ast.Name) and node.id not in seen:
                seen |= {node.id}
                for binding in self._bindings.of(node.id):
                    for feed in binding.sources:
                        found = self._version_literal(feed, seen)
                        if found is not None:
                            return found
        return None

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


@dataclass(frozen=True, slots=True)
class _Binding:
    """One place a name is bound in a module's global scope."""

    stmt: ast.stmt  # the statement that holds the binding
    sources: tuple[ast.expr, ...]  # the expressions whose value flows in
    is_import: bool
    is_nested: bool  # inside a block or a function, not the module body


@final
class _ModuleBindings:
    """Every binding of every name in a module's global scope."""

    __slots__ = ("_by_name", "_stars")

    _by_name: defaultdict[str, list[_Binding]]
    _stars: list[ast.ImportFrom]

    def __new__(cls, tree: ast.Module) -> Self:
        self = super().__new__(cls)
        self._by_name = defaultdict(list)
        self._stars = []
        body = set(tree.body)
        for stmt in _own_statements(tree):
            self._record(stmt, is_nested=stmt not in body, only=None)
        for scope in ast.walk(tree):
            if isinstance(scope, _SCOPES):
                self._record_globals(scope)
        return self

    def of(self, name: str) -> list[_Binding]:
        """Every binding of ``name``, in source order of discovery."""
        return self._by_name.get(name, [])

    def star_imports(self) -> list[ast.ImportFrom]:
        """Every ``from x import *`` in the module's global scope."""
        return self._stars

    def _record_globals(self, scope: ast.stmt) -> None:
        """Note the bindings ``scope`` makes to names it declares ``global``."""
        statements = list(_own_statements(scope))
        declared = frozenset(
            name
            for stmt in statements
            if isinstance(stmt, ast.Global)
            for name in stmt.names
        )
        if declared:
            for stmt in statements:
                self._record(stmt, is_nested=True, only=declared)

    def _record(
        self, stmt: ast.stmt, *, is_nested: bool, only: frozenset[str] | None
    ) -> None:
        """Note the names ``stmt`` binds, keeping only ``only`` when given."""
        if isinstance(stmt, ast.ImportFrom) and only is None:
            self._stars.extend(stmt for alias in stmt.names if alias.name == "*")
        for name, sources, is_import in _bound_names(stmt):
            if only is None or name in only:
                binding = _Binding(stmt, sources, is_import, is_nested)
                self._by_name[name].append(binding)


def _own_statements(node: ast.AST) -> Iterator[ast.stmt]:
    """Statements under ``node`` in its own scope, not in nested defs or classes."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            yield child
            if not isinstance(child, _SCOPES):
                yield from _own_statements(child)
        elif isinstance(child, ast.excepthandler | ast.match_case):
            yield from _own_statements(child)


def _own_expressions(node: ast.AST) -> Iterator[ast.AST]:
    """Nodes of ``node``'s own expressions: not nested statements or lambdas."""
    for child in ast.iter_child_nodes(node):
        if not isinstance(
            child, ast.stmt | ast.Lambda | ast.excepthandler | ast.match_case
        ):
            yield child
            yield from _own_expressions(child)


def _bound_names(
    stmt: ast.stmt,
) -> Iterator[tuple[str, tuple[ast.expr, ...], bool]]:
    """Each name ``stmt`` binds, what flows into it, and whether it is imported."""
    match stmt:
        case ast.Assign(targets=targets, value=value):
            for target in targets:
                yield from _stored(target, (value,))
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value):
            yield name, (value,), False
        case ast.AugAssign(target=ast.Name(id=name), value=value):
            yield name, (value,), False
        case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
            for alias in aliases:
                if alias.name != "*":
                    yield (alias.asname or alias.name).split(".")[0], (), True
        case ast.For(target=target, iter=feed) | ast.AsyncFor(target=target, iter=feed):
            yield from _stored(target, (feed,))
        case ast.With(items=items) | ast.AsyncWith(items=items):
            for item in items:
                if item.optional_vars is not None:
                    yield from _stored(item.optional_vars, (item.context_expr,))
        case ast.Match(subject=subject, cases=cases):
            for case in cases:
                for name in _captured(case.pattern):
                    yield name, (subject,), False
        case ast.Try(handlers=handlers) | ast.TryStar(handlers=handlers):
            for handler in handlers:
                if handler.name:
                    yield handler.name, (), False
        case (
            ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
        ):
            yield name, (), False
        case _:
            pass
    for node in _own_expressions(stmt):
        if isinstance(node, ast.NamedExpr):
            yield node.target.id, (node.value,), False


def _stored(
    target: ast.expr, sources: tuple[ast.expr, ...]
) -> Iterator[tuple[str, tuple[ast.expr, ...], bool]]:
    """Each plain name ``target`` stores into, fed by ``sources``."""
    for node in ast.walk(target):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            yield node.id, sources, False


def _captured(pattern: ast.pattern) -> Iterator[str]:
    """Each name a ``match`` pattern captures."""
    for node in ast.walk(pattern):
        match node:
            case ast.MatchAs(name=str() as name) | ast.MatchStar(name=str() as name):
                yield name
            case ast.MatchMapping(rest=str() as name):
                yield name
            case _:
                pass


def _is_version_like(node: ast.AST) -> TypeIs[ast.Constant | ast.Tuple]:
    """Whether ``node`` hardcodes a version: ``"1.2"`` text or ``(1, 2)`` ints."""
    match node:
        case ast.Constant(value=str() as text):
            return _VERSION_TEXT.search(text) is not None
        case ast.Tuple(elts=elts):
            ints = [
                elt
                for elt in elts
                if isinstance(elt, ast.Constant) and type(elt.value) is int
            ]
            return len(ints) >= 2
        case _:
            return False


def _char_offset(line: str, byte_offset: int) -> int:
    """Turn ``ast``'s UTF-8 byte column into a character index into ``line``."""
    return len(line.encode()[:byte_offset].decode())
