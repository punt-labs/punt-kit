"""The ``__version__`` a Python module assigns, classified from its syntax tree."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterator

_NAME = "__version__"
# A string the rewriter can set in place: one line, no prefix, no escape.
_PLAIN_STRING = re.compile(r"""(["'])[^"'\\\n]*\1""")
# What may follow the closing quote: whitespace and a comment, nothing else.
_TRAILER = re.compile(r"\s*(?:#.*)?")
# A string that spells a version somewhere in it: digits, a dot, digits.
_VERSION_TEXT = re.compile(r"\d+\.\d+")
# Any digit, full-width ones too: "2", "v2", " 2", "２".
_ANY_DIGIT = re.compile(r"\d")
# Names Python binds in every module; only a metadata reader may take them.
_MODULE_DUNDERS = frozenset({"__name__", "__package__"})
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

    # None: absence is the contract; a module may omit __version__, provided
    # no ``import *`` could supply it.
    def resolved(self) -> ComputedVersion | LiteralVersion | None:
        """What the module assigns to ``__version__``; ``None`` when nothing."""
        if not self._bindings.of(_NAME):
            for star in self._bindings.star_imports():
                msg = (
                    f"`{ast.unparse(star)}` at line {star.lineno} could supply "
                    f"{_NAME}; bind it explicitly"
                )
                raise UnpinnableVersionError(msg)
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
        for star in self._bindings.star_imports():
            if star.lineno > binding.stmt.lineno:  # an earlier one is overridden
                msg = (
                    f"`{ast.unparse(star)}` at line {star.lineno} could rebind "
                    f"{name}, so a bump could ship a stale version"
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

    It qualifies only when its callee is a name bound by import alone, or an
    imported module's path plus exactly one attribute: a function of that
    module. The module path is the ``as`` name, the full dotted path of
    ``import a.b.c`` or any prefix of it, or ``metadata`` for ``from importlib
    import metadata``; no other from-import binds a module, since it may bind
    a value such as a stale ``VERSION`` string. Every binding of the root name
    must be such a module and reach the callee, except that an unaliased
    ``import importlib`` may sit beside ``import importlib.metadata``.

    Every argument must be a plain string with no version text, or a name
    bound once, at module level, by a plain assignment to such a string. To a
    callee other than a metadata reader, any digit is version text. Only a
    metadata reader (``importlib.metadata``'s or ``importlib_metadata``'s)
    may also take an imported name, ``__name__`` or ``__package__``.
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
        parts = _dotted(self._call.func)
        bindings = self._bindings.of(parts[0]) if parts else []
        if not bindings or not all(binding.is_import for binding in bindings):
            return (
                f"calls `{callee}`, which is not a function imported from another "
                f"module; {_ADVICE}"
            )
        qualified = [
            name
            for binding in bindings
            if (name := binding.qualified(parts)) is not None
        ]
        # ``import importlib`` beside ``import importlib.metadata`` binds one
        # name twice, both modules; any other binding that does not reach the
        # callee could be what the call actually runs.
        is_shadowed = any(
            binding.qualified(parts) is None and not binding.is_dotted_import
            for binding in bindings
        )
        if not qualified or is_shadowed:
            return (
                f"calls `{callee}`, which is not a function of a module this file "
                f"imports; {_ADVICE}"
            )
        reads_metadata = all(name.startswith(_METADATA_READERS) for name in qualified)
        for argument in self._call.args:
            fault = self._argument_fault(argument, reads_metadata=reads_metadata)
            if fault is not None:
                return fault
        for keyword in self._call.keywords:
            if keyword.arg is None:
                return (
                    f"passes `**{ast.unparse(keyword.value)}`, whose values this "
                    f"file cannot see; {_ADVICE}"
                )
            fault = self._argument_fault(keyword.value, reads_metadata=reads_metadata)
            if fault is not None:
                return fault
        return None

    def _argument_fault(
        self, argument: ast.expr, *, reads_metadata: bool
    ) -> str | None:
        """Why ``argument`` may feed a stale version; ``None`` when it cannot."""
        match argument:
            case ast.Constant(value=str() as text) if _is_version_text(
                text, reads_metadata=reads_metadata
            ):
                return (
                    f"passes the hardcoded version {ast.unparse(argument)}, which "
                    f"could be stale; {_ADVICE}"
                )
            case ast.Constant(value=str()):
                return None
            case ast.Name(id=name):
                return self._name_fault(name, reads_metadata=reads_metadata)
            case _:
                return (
                    f"passes `{ast.unparse(argument)}`, which is not a plain string "
                    f"or a name bound to one; {_ADVICE}"
                )

    def _name_fault(self, name: str, *, reads_metadata: bool) -> str | None:
        """Why the argument ``name`` may feed a stale version; ``None`` if not."""
        bindings = self._bindings.of(name)
        if name in _MODULE_DUNDERS and not bindings:
            if reads_metadata:
                return None  # the package's own name, read by the metadata reader
            return f"passes {name}, which only a metadata reader may take; {_ADVICE}"
        if bindings and all(binding.is_import for binding in bindings):
            if reads_metadata:
                return None  # a distribution name, read by the metadata reader
            return (
                f"passes {name}, which is imported from another module; "
                "pin the version there"
            )
        text = bindings[0].plain_string if len(bindings) == 1 else None
        if text is None:
            return (
                f"passes {name}, which is neither imported nor bound once, at "
                f"module level, to a plain string; {_ADVICE}"
            )
        if _is_version_text(text, reads_metadata=reads_metadata):
            return (
                f"passes {name}, bound to the hardcoded version {text!r} "
                f"(line {bindings[0].stmt.lineno}), which could be stale; {_ADVICE}"
            )
        return None


@dataclass(frozen=True, slots=True)
class _Import:
    """What an import statement binds a name to."""

    origin: str  # the dotted name of what the bound name refers to
    module_path: str | None  # how a call spells the module; None if not one
    # An unaliased ``import a.b.c``: ``a``, ``a.b`` and ``a.b.c`` are modules.
    is_dotted: bool = False

    def qualified(self, parts: list[str]) -> str | None:
        """The dotted name a callee spelled ``parts`` reaches; ``None`` if none."""
        *path, function = parts
        if not path:
            return self.origin
        spelled = ".".join(path)
        if self.module_path is None:
            return None
        if self.is_dotted and f"{self.module_path}.".startswith(f"{spelled}."):
            return f"{spelled}.{function}"
        if spelled == self.module_path:
            return f"{self.origin}.{function}"
        return None


@dataclass(frozen=True, slots=True)
class _Binding:
    """One place a name is bound in a module's global scope."""

    stmt: ast.stmt  # the statement that holds the binding
    sources: tuple[ast.expr, ...]  # the expressions whose value flows in
    imported: _Import | None  # what an import binds; None for any other binding
    is_nested: bool  # inside a block or a function, not the module body
    is_in_except: bool  # inside an ``except`` branch

    @property
    def is_import(self) -> bool:
        """Whether an import statement makes this binding."""
        return self.imported is not None

    def qualified(self, parts: list[str]) -> str | None:
        """The dotted name a callee spelled ``parts`` reaches through this import."""
        return self.imported.qualified(parts) if self.imported else None

    @property
    def is_dotted_import(self) -> bool:
        """Whether this is an unaliased ``import a.b.c``, binding module ``a``."""
        return self.imported is not None and self.imported.is_dotted

    @property
    def plain_string(self) -> str | None:
        """The string a module-body assignment binds; ``None`` for anything else."""
        if self.is_nested:
            return None
        match self.stmt:
            case ast.Assign(targets=targets, value=ast.Constant(value=str() as text)):
                is_plain = all(isinstance(target, ast.Name) for target in targets)
                return text if is_plain else None  # never ``_, D = "x2"``
            case ast.AnnAssign(
                target=ast.Name(), value=ast.Constant(value=str() as text)
            ):
                return text
            case _:
                return None

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
        for name, sources, imported in _bound_names(stmt):
            if only is None or name in only:
                binding = _Binding(
                    stmt, sources, imported, is_nested, stmt in self._excepted
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
) -> Iterator[tuple[str, tuple[ast.expr, ...], _Import | None]]:
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
                    yield alias.asname, (), _Import(alias.name, alias.asname)
                else:
                    package = alias.name.split(".")[0]
                    imported = _Import(package, alias.name, is_dotted=True)
                    yield package, (), imported
        case ast.ImportFrom(module=module, names=aliases, level=level):
            prefix = "." * level + (f"{module}." if module else "")
            for alias in aliases:
                if alias.name != "*":
                    bound = alias.asname or alias.name
                    origin = prefix + alias.name
                    is_module = origin == "importlib.metadata"
                    yield bound, (), _Import(origin, bound if is_module else None)
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
) -> Iterator[tuple[str, tuple[ast.expr, ...], _Import | None]]:
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


def _is_version_text(text: str, *, reads_metadata: bool) -> bool:
    """Whether ``text`` could be a version: ``digits.digits`` anywhere, or,
    passed to anything but a metadata reader, any digit (``"v2"``, ``"２"``)."""
    if _VERSION_TEXT.search(text):
        return True
    return not reads_metadata and _ANY_DIGIT.search(text) is not None


def _dotted(func: ast.expr) -> list[str]:
    """``func`` as dotted name parts (``a.b.f`` is ``a``, ``b``, ``f``); else empty."""
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.insert(0, func.attr)
        func = func.value
    return [func.id, *parts] if isinstance(func, ast.Name) else []


def _is_a_fallback(bindings: list[_Binding]) -> bool:
    """Whether ``bindings`` read the version but fall back to a literal on error.

    Only when dropping the ``except`` branch leaves exactly one binding, a
    call, is the except branch the whole problem.
    """
    kept = [binding for binding in bindings if not binding.is_in_except]
    return (
        len(kept) == 1
        and kept[0].assigns_a_call
        and any(
            binding.assigns_a_string for binding in bindings if binding.is_in_except
        )
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
