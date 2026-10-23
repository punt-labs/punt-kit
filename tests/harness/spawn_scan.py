"""Static scan for the ways a module can start a process through the APIs it watches.

It watches ``subprocess``, ``os``, ``pty``, ``asyncio``, ``multiprocessing`` and
``concurrent.futures.ProcessPoolExecutor``, plus string-based imports and
``getattr`` on those modules. It follows absolute imports inside the package and
refuses a relative one rather than skip it. It does not see a process started
by a program a module runs, or by code it cannot resolve statically.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Modules whose import can lead to a process being started.
_WATCHED = frozenset(
    {"subprocess", "os", "pty", "asyncio", "multiprocessing", "concurrent"}
)

# What a module may take from `subprocess` without being able to start one.
_SUBPROCESS_TYPES = frozenset(
    {"TimeoutExpired", "CalledProcessError", "CompletedProcess"}
)

_OS_SPAWNERS = frozenset({"system", "popen", "fork", "forkpty", "startfile"})
_OS_SPAWN_PREFIXES = ("exec", "spawn", "posix_spawn")

_PACKAGE = "punt_kit"
_MODULE_SCOPE = "<module>"


@final
class SpawnScan:
    """The process-starting names one module binds or uses."""

    __slots__ = ("_tree",)

    _tree: ast.Module

    def __new__(cls, tree: ast.Module) -> Self:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                msg = (
                    f"relative import at line {node.lineno}: the scan follows "
                    "absolute imports only, so it would skip the module"
                )
                raise ValueError(msg)
        self = super().__new__(cls)
        self._tree = tree
        return self

    @classmethod
    def of_source(cls, source: str) -> Self:
        return cls(ast.parse(source))

    @classmethod
    def of_file(cls, path: Path) -> Self:
        return cls.of_source(path.read_text("utf-8"))

    @classmethod
    def reachable_from(
        cls, entry: Path, *, entry_point: str | None = None
    ) -> list[Path]:
        """``entry`` and every package module it imports, transitively.

        ``entry_point`` names a function: only the imports at module level and
        inside that function count for ``entry``, so a CLI module's other
        commands are not pulled in with the one being scanned.
        """
        root = next(p for p in entry.parents if p.name == _PACKAGE)
        seen: set[Path] = set()
        pending = [(entry, entry_point)]
        while pending:
            path, only = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            for module in cls.of_file(path).internal_modules(only):
                pending.extend((file, None) for file in cls._files_of(root, module))
        return sorted(seen)

    def spawning_names(self) -> list[str]:
        """Sorted, canonical names such as ``subprocess.run`` or ``os.execvp``."""
        return sorted({name for name, _scope in self.spawn_sites()})

    def spawn_sites(self) -> list[tuple[str, str]]:
        """Sorted ``(name, enclosing function)`` for every use; ``<module>`` at top."""
        aliases = self._module_aliases()
        loaders = self._loader_names()
        found: set[tuple[str, str]] = set()
        for node, scope in self._scoped_nodes():
            if isinstance(node, ast.ImportFrom):
                found.update((name, scope) for name in self._imported_spawners(node))
            elif isinstance(node, ast.Call):
                found.update(
                    (name, scope)
                    for name in self._dynamic_import(node, loaders, aliases)
                )
            elif isinstance(node, ast.Attribute):
                base = self._base_name(node.value)
                module = aliases.get(base, "")
                if module and self._spawns(module, node.attr):
                    found.add((f"{module}.{node.attr}", scope))
        return sorted(found)

    def internal_modules(self, entry_point: str | None = None) -> list[str]:
        """Dotted names of the package modules this module imports.

        With ``entry_point``, only imports at module level or inside that
        function; otherwise every import in the file.
        """
        names: list[str] = []
        for node, scope in self._scoped_nodes():
            if entry_point is not None and scope not in {_MODULE_SCOPE, entry_point}:
                continue
            if isinstance(node, ast.Import):
                names.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
                names.extend(f"{node.module}.{a.name}" for a in node.names)
        return [n for n in names if n.split(".")[0] == _PACKAGE]

    def _scoped_nodes(self) -> Iterator[tuple[ast.AST, str]]:
        """Every node with the name of the innermost function that holds it."""

        def visit(node: ast.AST, scope: str) -> Iterator[tuple[ast.AST, str]]:
            yield node, scope
            for child in ast.iter_child_nodes(node):
                inner = (
                    child.name
                    if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                    else scope
                )
                yield from visit(child, inner)

        return visit(self._tree, _MODULE_SCOPE)

    def _module_aliases(self) -> dict[str, str]:
        """Local name -> watched module, for every way a watched module is bound.

        ``import x``, ``import x as y``, and ``from concurrent import futures``
        (which binds a submodule of ``concurrent``).
        """
        names: list[tuple[str, str]] = []
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                names.extend(
                    (alias.asname or alias.name.split(".")[0], alias.name.split(".")[0])
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module == "concurrent":
                names.extend(
                    (alias.asname or alias.name, "concurrent")
                    for alias in node.names
                    if alias.name == "futures"
                )
        return {local: root for local, root in names if root in _WATCHED}

    @staticmethod
    def _base_name(node: ast.expr) -> str:
        """The leftmost name of ``a.b.c`` (``a``); empty if it is not a name."""
        while isinstance(node, ast.Attribute):
            node = node.value
        return node.id if isinstance(node, ast.Name) else ""

    @staticmethod
    def _files_of(root: Path, module: str) -> list[Path]:
        """The files that run when ``module`` is imported, packages included."""
        parts = module.split(".")[1:]
        files: list[Path] = []
        for depth in range(len(parts) + 1):
            base = root.joinpath(*parts[:depth])
            if (base / "__init__.py").exists():
                files.append(base / "__init__.py")
        leaf = root.joinpath(*parts)
        if parts and leaf.with_suffix(".py").exists():
            files.append(leaf.with_suffix(".py"))
        return files

    @classmethod
    def _imported_spawners(cls, node: ast.ImportFrom) -> list[str]:
        root = (node.module or "").split(".")[0]
        if root not in _WATCHED:
            return []
        return [
            f"{root}.{a.name}"
            for a in node.names
            if a.name == "*" or cls._spawns(root, a.name)
        ]

    def _loader_names(self) -> set[str]:
        """Local names that load a module by string: ``__import__`` and any
        binding of ``importlib.import_module``, whatever it is aliased to."""
        return {"__import__"} | {
            alias.asname or alias.name
            for node in ast.walk(self._tree)
            if isinstance(node, ast.ImportFrom) and node.module == "importlib"
            for alias in node.names
            if alias.name in {"import_module", "*"}
        }

    @classmethod
    def _dynamic_import(
        cls, node: ast.Call, loaders: set[str], aliases: dict[str, str]
    ) -> list[str]:
        """Calls that load a module by string, or reach into a watched module."""
        func = node.func
        if isinstance(func, ast.Attribute):
            return ["import_module"] if func.attr == "import_module" else []
        if not isinstance(func, ast.Name):
            return []
        if func.id in loaders:
            return [func.id if func.id == "__import__" else "import_module"]
        return cls._getattr_on_watched(node, aliases) if func.id == "getattr" else []

    @staticmethod
    def _getattr_on_watched(node: ast.Call, aliases: dict[str, str]) -> list[str]:
        target = node.args[0] if node.args else None
        module = aliases.get(target.id) if isinstance(target, ast.Name) else None
        return [f"getattr({module})"] if module else []

    @staticmethod
    def _spawns(module: str, name: str) -> bool:
        if module == "subprocess":
            return name not in _SUBPROCESS_TYPES
        if module == "os":
            return name in _OS_SPAWNERS or name.startswith(_OS_SPAWN_PREFIXES)
        if module == "asyncio":
            return name.startswith("create_subprocess")
        if module == "concurrent":
            return name == "ProcessPoolExecutor"
        return True
