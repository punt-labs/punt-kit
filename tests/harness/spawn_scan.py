"""Static scan for every way a module can start a process."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path

# Modules whose import can lead to a process being started.
_WATCHED = frozenset({"subprocess", "os", "pty", "asyncio", "multiprocessing"})

# What a module may take from `subprocess` without being able to start one.
_SUBPROCESS_TYPES = frozenset(
    {"TimeoutExpired", "CalledProcessError", "CompletedProcess"}
)

_OS_SPAWNERS = frozenset({"system", "popen", "fork", "forkpty", "startfile"})
_OS_SPAWN_PREFIXES = ("exec", "spawn", "posix_spawn")

# Ways to reach a module by name at runtime, which a static scan cannot follow.
_DYNAMIC_IMPORTS = frozenset({"__import__", "import_module"})

_PACKAGE = "punt_kit"


@final
class SpawnScan:
    """The process-starting names one module binds or uses."""

    __slots__ = ("_tree",)

    _tree: ast.Module

    def __new__(cls, tree: ast.Module) -> Self:
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
    def reachable_from(cls, entry: Path) -> list[Path]:
        """``entry`` and every package module it imports, transitively."""
        root = next(p for p in entry.parents if p.name == _PACKAGE)
        seen: set[Path] = set()
        pending = [entry]
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            for module in cls.of_file(path).internal_modules():
                pending.extend(cls._files_of(root, module))
        return sorted(seen)

    def spawning_names(self) -> list[str]:
        """Sorted, canonical names such as ``subprocess.run`` or ``os.execvp``."""
        aliases = self._module_aliases()
        found: set[str] = set()
        for node in ast.walk(self._tree):
            if isinstance(node, ast.ImportFrom):
                found.update(self._imported_spawners(node))
            elif isinstance(node, ast.Call):
                found.update(self._dynamic_import(node))
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
                and self._spawns(aliases[node.value.id], node.attr)
            ):
                found.add(f"{aliases[node.value.id]}.{node.attr}")
        return sorted(found)

    def _module_aliases(self) -> dict[str, str]:
        """Local name -> watched module, for every ``import x`` / ``import x as y``."""
        names = (
            (alias.asname or alias.name.split(".")[0], alias.name.split(".")[0])
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        return {local: root for local, root in names if root in _WATCHED}

    def internal_modules(self) -> list[str]:
        """Dotted names of the package modules this module imports."""
        names: list[str] = []
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import):
                names.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
                names.extend(f"{node.module}.{a.name}" for a in node.names)
        return [n for n in names if n.split(".")[0] == _PACKAGE]

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
        if node.level or root not in _WATCHED:
            return []
        return [
            f"{root}.{a.name}"
            for a in node.names
            if a.name == "*" or cls._spawns(root, a.name)
        ]

    @staticmethod
    def _dynamic_import(node: ast.Call) -> list[str]:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        return [name] if name in _DYNAMIC_IMPORTS else []

    @staticmethod
    def _spawns(module: str, name: str) -> bool:
        if module == "subprocess":
            return name not in _SUBPROCESS_TYPES
        if module == "os":
            return name in _OS_SPAWNERS or name.startswith(_OS_SPAWN_PREFIXES)
        if module == "asyncio":
            return name.startswith("create_subprocess")
        return True
