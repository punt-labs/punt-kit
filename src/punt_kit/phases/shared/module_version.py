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
# Callees that read installed package metadata, however they were imported.
_METADATA_READERS = ("importlib.metadata.", "importlib_metadata.")
_ADVICE = (
    "use a plain string or a call to an imported reader such as "
    "importlib.metadata.version()"
)
_LAST_WINS = "Python keeps the last, so a bump of one could ship a stale version"
_FALLBACK = (
    "a fallback version is not allowed (python.md Version Reporting: no "
    '"0.0.0" fallback); remove the except branch'
)
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
    value, or augmented), an import, a walrus (a lambda default's too), a
    ``for``/``with``/``match`` target, and an assignment under ``global``
    inside a function, whether in the module body or inside an
    ``if``/``try``/``with``/``for``/``while``/``match`` block. A bare
    annotation is not a binding. ``resolved`` answers one of:

    - ``None`` — nothing in the module binds ``__version__``.
    - ``LiteralVersion`` — a one-line, unprefixed, single- or double-quoted
      string that ends its statement (a ``# comment`` may follow), optionally
      annotated. A plain name bound once, in the module body, to such a
      literal (``VERSION = "1.0"``; ``__version__ = VERSION``) resolves to
      that literal, and it is the one rewritten.
    - ``ComputedVersion`` — the value, through the same plain-name aliases,
      is exactly one call to an imported reader (``installed_version()``,
      ``version("x")``, ``importlib.metadata.version("x")``): read from
      installed metadata at import time, so there is nothing to bump or
      verify. ``_ReaderCall`` holds the rules for the call.

    That is an allow-list: anything else raises ``UnpinnableVersionError``,
    because skipping it could ship a stale version. That covers a file that
    does not parse; ``__version__``, or a name it resolves through, bound
    more than once (Python keeps the last), bound only inside a block or a
    function, or imported from another module; an ``import *`` beside them;
    an f-, r-, u- or b-string; a parenthesised, concatenated, triple-quoted
    or conditional value; and any expression built on a call
    (``version("x").split("+")[0]``, ``get_versions()["version"]``,
    ``".".join(...)``, ``__import__("x").VERSION``).
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
            case ast.Call():
                fault = _ReaderCall(value, self._bindings).fault()
                if fault is not None:
                    msg = f"`{source}` (line {stmt.lineno}) {fault}"
                    raise UnpinnableVersionError(msg)
                return ComputedVersion(source)
            case _:
                raise _not_plain(source, stmt.lineno, name)

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
            why = _FALLBACK if _is_a_fallback(bindings) else _LAST_WINS
            msg = f"{name} is assigned {len(bindings)} times (lines {lines}); {why}"
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
            raise _not_plain(source, stmt.lineno, name)
        return LiteralVersion(str(node.value), node.lineno - 1, start + 1, end - 1)

    def _source(self, stmt: ast.stmt) -> str:
        """The first line of ``stmt``, stripped, for messages."""
        return self._lines[stmt.lineno - 1].strip()


@final
class _ReaderCall:
    """A call that may read ``__version__`` from package metadata at import time.

    It qualifies only when its callee is a name, or an attribute chain on a
    name, that the module binds by import alone. An attribute chain must
    start from a module (``import X``, ``import X.Y``, ``import X as Z``,
    ``from importlib import metadata``, ``from importlib_metadata import
    ...``), never another from-import, which may bind a value such as a
    stale ``VERSION`` string. No argument may hardcode a
    version (``_is_version_like``) or, unless the callee is
    ``importlib.metadata``'s or ``importlib_metadata``'s, reads an imported
    name, directly or through a name bound in this module. An imported
    argument could be a stale literal pinned in the other module.
    """

    __slots__ = ("_bindings", "_call")

    _bindings: _ModuleBindings
    _call: ast.Call

    def __new__(cls, call: ast.Call, bindings: _ModuleBindings) -> Self:
        self = super().__new__(cls)
        self._call = call
        self._bindings = bindings
        return self

    def fault(self) -> str | None:
        """Why the call cannot be trusted to read the version; ``None`` if it can."""
        callee = ast.unparse(self._call.func)
        base, attributes = _callee_path(self._call.func)
        bindings = self._bindings.of(base.id) if base is not None else []
        if not bindings or not all(binding.is_import for binding in bindings):
            return (
                f"calls `{callee}`, which is not a function imported from another "
                f"module; {_ADVICE}"
            )
        if attributes and not all(binding.imports_a_module for binding in bindings):
            return (
                f"calls `{callee}` on a name a from-import binds, which may be a "
                f"value rather than a module; {_ADVICE}"
            )
        callees = [
            ".".join([binding.origin or "", *attributes]) for binding in bindings
        ]
        arguments = [*self._call.args, *(kw.value for kw in self._call.keywords)]
        for argument in arguments:
            literal = self._version_literal(argument, frozenset())
            if literal is not None:
                return (
                    f"passes the hardcoded value {ast.unparse(literal)} "
                    f"(line {literal.lineno}), which could be a stale version; "
                    f"{_ADVICE}"
                )
        if all(callee.startswith(_METADATA_READERS) for callee in callees):
            return None
        for argument in arguments:
            imported = self._imported_name(argument, frozenset())
            if imported is not None:
                return (
                    f"passes {imported}, which is imported from another module; "
                    "pin the version there"
                )
        return None

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

    def _imported_name(self, expr: ast.expr, seen: frozenset[str]) -> str | None:
        """An imported name that reaches ``expr``, through names too."""
        for node in ast.walk(expr):
            if not isinstance(node, ast.Name) or node.id in seen:
                continue
            seen |= {node.id}
            bindings = self._bindings.of(node.id)
            if any(binding.is_import for binding in bindings):
                return node.id
            for binding in bindings:
                for feed in binding.sources:
                    found = self._imported_name(feed, seen)
                    if found is not None:
                        return found
        return None


@dataclass(frozen=True, slots=True)
class _Binding:
    """One place a name is bound in a module's global scope."""

    stmt: ast.stmt  # the statement that holds the binding
    sources: tuple[ast.expr, ...]  # the expressions whose value flows in
    origin: str | None  # the dotted name an import binds; None otherwise
    is_nested: bool  # inside a block or a function, not the module body
    is_in_except: bool  # inside an ``except`` branch

    @property
    def is_import(self) -> bool:
        """Whether an import statement makes this binding."""
        return self.origin is not None

    @property
    def imports_a_module(self) -> bool:
        """Whether the bound name is surely a module: ``import X`` or metadata."""
        return isinstance(self.stmt, ast.Import) or (
            self.origin is not None
            and (
                self.origin == "importlib.metadata"
                or self.origin.startswith("importlib_metadata.")
            )
        )

    @property
    def assigns_a_call(self) -> bool:
        """Whether the value bound is a call."""
        return isinstance(self.stmt, ast.Assign | ast.AnnAssign) and isinstance(
            self.stmt.value, ast.Call
        )

    @property
    def assigns_a_string(self) -> bool:
        """Whether the value bound is a string literal."""
        return (
            isinstance(self.stmt, ast.Assign | ast.AnnAssign)
            and isinstance(self.stmt.value, ast.Constant)
            and isinstance(self.stmt.value.value, str)
        )


@final
class _ModuleBindings:
    """Every binding of every name in a module's global scope."""

    __slots__ = ("_by_name", "_excepted", "_stars")

    _by_name: defaultdict[str, list[_Binding]]
    _excepted: set[ast.stmt]
    _stars: list[ast.ImportFrom]

    def __new__(cls, tree: ast.Module) -> Self:
        self = super().__new__(cls)
        self._by_name = defaultdict(list)
        self._stars = []
        self._excepted = {
            stmt
            for handler in ast.walk(tree)
            if isinstance(handler, ast.excepthandler)
            for stmt in ast.walk(handler)
            if isinstance(stmt, ast.stmt)
        }
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
        for name, sources, origin in _bound_names(stmt):
            if only is None or name in only:
                binding = _Binding(
                    stmt, sources, origin, is_nested, stmt in self._excepted
                )
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
    """Nodes of ``node``'s own expressions, not nested statements.

    A lambda's body is its own scope, but its defaults run in this one, as
    does a ``match`` case's guard.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.match_case):
            if child.guard is not None:
                yield child.guard
                yield from _own_expressions(child.guard)
        elif isinstance(child, ast.Lambda):
            defaults = [*child.args.defaults, *child.args.kw_defaults]
            for default in defaults:
                if default is not None:
                    yield default
                    yield from _own_expressions(default)
        elif not isinstance(child, ast.stmt | ast.excepthandler):
            yield child
            yield from _own_expressions(child)


def _bound_names(
    stmt: ast.stmt,
) -> Iterator[tuple[str, tuple[ast.expr, ...], str | None]]:
    """Each name ``stmt`` binds, what flows into it, and what it imports."""
    match stmt:
        case ast.Assign(targets=targets, value=value):
            for target in targets:
                yield from _stored(target, (value,))
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value):
            yield name, (value,), None
        case ast.AugAssign(target=ast.Name(id=name), value=value):
            yield name, (value,), None
        case ast.TypeAlias(name=ast.Name(id=name), value=value):
            yield name, (value,), None
        case ast.Import(names=aliases):
            for alias in aliases:
                if alias.asname:
                    yield alias.asname, (), alias.name
                else:
                    package = alias.name.split(".")[0]
                    yield package, (), package
        case ast.ImportFrom(module=module, names=aliases, level=level):
            prefix = "." * level + (f"{module}." if module else "")
            for alias in aliases:
                if alias.name != "*":
                    yield alias.asname or alias.name, (), prefix + alias.name
        case ast.For(target=target, iter=feed) | ast.AsyncFor(target=target, iter=feed):
            yield from _stored(target, (feed,))
        case ast.With(items=items) | ast.AsyncWith(items=items):
            for item in items:
                if item.optional_vars is not None:
                    yield from _stored(item.optional_vars, (item.context_expr,))
        case ast.Match(subject=subject, cases=cases):
            for case in cases:
                for name in _captured(case.pattern):
                    yield name, (subject,), None
        case ast.Try(handlers=handlers) | ast.TryStar(handlers=handlers):
            for handler in handlers:
                if handler.name:
                    yield handler.name, (), None
        case (
            ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
        ):
            yield name, (), None
        case _:
            pass
    for node in _own_expressions(stmt):
        if isinstance(node, ast.NamedExpr):
            yield node.target.id, (node.value,), None


def _stored(
    target: ast.expr, sources: tuple[ast.expr, ...]
) -> Iterator[tuple[str, tuple[ast.expr, ...], str | None]]:
    """Each plain name ``target`` stores into, fed by ``sources``."""
    for node in ast.walk(target):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            yield node.id, sources, None


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


def _is_version_like(
    node: ast.AST,
) -> TypeIs[ast.Constant | ast.List | ast.Set | ast.Tuple]:
    """Whether ``node`` could hardcode a version or a part of one.

    A string holding ``digits.digits``; any int, float or bytes constant; a
    list, set or tuple of two or more numbers or digit-only strings.
    """
    match node:
        case ast.Constant(value=str() as text):
            return _VERSION_TEXT.search(text) is not None
        case ast.Constant(value=bool()):
            return False
        case ast.Constant(value=int() | float() | bytes()):
            return True
        case ast.List(elts=elts) | ast.Set(elts=elts) | ast.Tuple(elts=elts):
            return sum(map(_is_version_part, elts)) >= 2
        case _:
            return False


def _is_version_part(node: ast.expr) -> bool:
    """Whether ``node`` is a number or a digit-only string."""
    match node:
        case ast.Constant(value=bool()):
            return False
        case ast.Constant(value=int() | float()):
            return True
        case ast.Constant(value=str() as text):
            return text.isdigit()
        case _:
            return False


def _callee_path(func: ast.expr) -> tuple[ast.Name | None, list[str]]:
    """The name a callee starts from and the attributes it then reads."""
    attributes: list[str] = []
    while isinstance(func, ast.Attribute):
        attributes.insert(0, func.attr)
        func = func.value
    return (func if isinstance(func, ast.Name) else None), attributes


def _is_a_fallback(bindings: list[_Binding]) -> bool:
    """Whether ``bindings`` read the version but fall back to a literal on error."""
    return any(binding.assigns_a_call for binding in bindings) and any(
        binding.is_in_except and binding.assigns_a_string for binding in bindings
    )


def _not_plain(source: str, line: int, name: str) -> UnpinnableVersionError:
    """The refusal for a value that is neither a plain string nor a reader call."""
    return UnpinnableVersionError(
        f"`{source}` (line {line}) is not a plain quoted string "
        f'({name} = "X.Y.Z") or a call to an imported reader; {_ADVICE}'
    )


def _char_offset(line: str, byte_offset: int) -> int:
    """Turn ``ast``'s UTF-8 byte column into a character index into ``line``."""
    return len(line.encode()[:byte_offset].decode())
