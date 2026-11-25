"""Prepare synchronized uv workspace manifest updates."""

from __future__ import annotations

import re
from fnmatch import translate
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast, final

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, Specifier
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.exceptions import ParseError
from tomlkit.items import Array, InlineTable, String, Table

from punt_kit.phases.shared.errors import ReleaseError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, MutableMapping, Set

    from packaging.utils import NormalizedName
    from tomlkit import TOMLDocument

type _Table = MutableMapping[str, object]


@final
class WorkspaceVersions:
    """Discover the uv workspace and plan edits without writing any files."""

    __slots__ = ("_config", "_read", "_root")

    _config: dict[str, object]
    _read: Callable[[Path], str]
    _root: Path

    def __new__(
        cls, root: Path, config: dict[str, object], read: Callable[[Path], str]
    ) -> Self:
        """Bind the workspace root and its uv configuration."""
        self = super().__new__(cls)
        self._root = root
        self._config = config
        self._read = read
        return self

    @classmethod
    def from_manifest(
        cls, root: Path, manifest: dict[str, object], *, read: Callable[[Path], str]
    ) -> WorkspaceVersions | None:
        """Return a planner for a root manifest that declares workspace members."""
        workspace = cls._mapping(cls._uv(manifest).get("workspace"))
        return cls(root, workspace, read) if "members" in workspace else None

    @staticmethod
    def _mapping(value: object) -> dict[str, object]:
        return cast("dict[str, object]", value) if isinstance(value, dict) else {}

    @classmethod
    def _uv(cls, manifest: dict[str, object]) -> dict[str, object]:
        return cls._mapping(cls._mapping(manifest.get("tool")).get("uv"))

    def _patterns(self, key: str) -> Iterator[str]:
        patterns = self._config.get(key, [])
        if not isinstance(patterns, list):
            msg = f"tool.uv.workspace.{key} must be an array of relative glob patterns"
            raise ReleaseError(msg)
        for pattern in cast("list[object]", patterns):
            if (
                not isinstance(pattern, str)
                or not pattern
                or Path(pattern).is_absolute()
                or ".." in Path(pattern).parts
            ):
                msg = f"Invalid tool.uv.workspace.{key} pattern: {pattern!r}"
                raise ReleaseError(msg)
            yield Path(pattern).as_posix()

    @staticmethod
    def _exclusion(pattern: str) -> re.Pattern[str]:
        # uv matches exclusions against the whole path, allowing '*' across '/'.
        chunks = re.split(r"(?<![^/])\*\*/", pattern)
        return re.compile(
            r"(?:.*/)?".join(translate(chunk)[:-2] for chunk in chunks), re.DOTALL
        )

    @staticmethod
    def _parse(path: Path, text: str) -> TOMLDocument:
        try:
            return tomlkit.parse(text)
        except ParseError as exc:
            msg = f"{path} is not valid TOML: {exc}"
            raise ReleaseError(msg) from exc

    @staticmethod
    def _table(value: object) -> _Table | None:
        if isinstance(value, Table | InlineTable | OutOfOrderTableProxy):
            return cast("_Table", value)
        return None

    @staticmethod
    def _dependencies(document: TOMLDocument, project: _Table) -> Iterator[Array]:
        direct = project.get("dependencies")
        if isinstance(direct, Array):
            yield direct
        for table in (
            project.get("optional-dependencies"),
            cast("_Table", document).get("dependency-groups"),
        ):
            if (group := WorkspaceVersions._table(table)) is not None:
                for value in group.values():
                    if isinstance(value, Array):
                        yield value

    @staticmethod
    def _replace_string(original: String, new: str) -> String:
        source = original.as_string()
        return tomlkit.string(
            new,
            literal=source.startswith("'"),
            multiline=source.startswith(("'''", '"""')),
        )

    @staticmethod
    def _pin(
        value: str, names: Set[NormalizedName], current: str, target: str
    ) -> str | None:
        try:
            requirement = Requirement(value)
        except InvalidRequirement:
            return None
        if canonicalize_name(requirement.name) not in names:
            return None
        specs = list(requirement.specifier)
        if len(specs) != 1 or specs[0].operator != "==":
            return None
        spec = specs[0]
        try:
            old_pin, new_pin = Specifier(f"=={current}"), Specifier(f"=={target}")
        except InvalidSpecifier:
            return None
        if spec == new_pin:
            return value
        if spec != old_pin:
            return None
        return re.sub(
            r"==(\s*)" + re.escape(spec.version),
            lambda match: f"=={match[1]}{target}",
            value,
            count=1,
        )

    def _rewrite_array(
        self, dependencies: Array, names: Set[NormalizedName], current: str, target: str
    ) -> bool:
        participates = False
        for index in range(len(dependencies)):
            value = dependencies.item(index)
            if not isinstance(value, String):
                continue
            pin = self._pin(value, names, current, target)
            if pin is not None:
                participates = True
                if pin != value:
                    dependencies[index] = self._replace_string(value, pin)
        return participates

    def _member_paths(self) -> list[Path]:
        root_file = self._root / "pyproject.toml"
        exclusions = [self._exclusion(pattern) for pattern in self._patterns("exclude")]
        members = {
            path
            for pattern in self._patterns("members")
            for path in self._root.glob(pattern)
        }
        paths = [
            path / "pyproject.toml"
            for path in sorted(members - {self._root})
            if (path / "pyproject.toml").exists()
            and not any(
                pattern.fullmatch(path.relative_to(self._root).as_posix())
                for pattern in exclusions
            )
        ]
        paths.append(root_file)
        return paths

    def _read_members(self, root_text: str) -> list[tuple[Path, TOMLDocument, _Table]]:
        root_file = self._root / "pyproject.toml"
        manifests: list[tuple[Path, TOMLDocument, _Table]] = []
        for path in self._member_paths():
            if not path.resolve().is_relative_to(self._root.resolve()):
                msg = f"uv workspace manifest is outside the project: {path}"
                raise ReleaseError(msg)
            text = root_text if path == root_file else self._read(path)
            document = self._parse(path, text)
            if (
                path != root_file
                and self._uv(document.unwrap()).get("managed") is False
            ):
                continue
            project = self._table(cast("_Table", document).get("project"))
            if project is None:
                msg = f"{path}: uv workspace package has no [project] table"
                raise ReleaseError(msg)
            manifests.append((path, document, project))
        return manifests

    @staticmethod
    def _same_version(value: object, expected: str) -> bool:
        if not isinstance(value, str):
            return False
        try:
            return Version(value) == Version(expected)
        except InvalidVersion:
            return value == expected

    @staticmethod
    def _release_names(
        manifests: list[tuple[Path, TOMLDocument, _Table]],
        current: str,
        target: str,
        previous: Callable[[Path], str | None],
    ) -> set[NormalizedName]:
        return {
            canonicalize_name(name)
            for path, _, project in manifests
            if isinstance(name := project.get("name"), str)
            and (
                WorkspaceVersions._same_version(project.get("version"), current)
                or (
                    WorkspaceVersions._same_version(project.get("version"), target)
                    and WorkspaceVersions._same_version(previous(path), current)
                )
            )
        }

    def rewrites(
        self,
        root_text: str,
        current: str,
        target: str,
        previous: Callable[[Path], str | None],
    ) -> dict[Path, str]:
        """Return updated manifests, including unchanged participants for resume.

        Raises:
            ReleaseError: A workspace manifest or declaration could not be read.
        """
        manifests = self._read_members(root_text)
        names = self._release_names(manifests, current, target, previous)
        results: dict[Path, str] = {}
        for path, document, project in manifests:
            version = project.get("version")
            name = project.get("name")
            participates = isinstance(name, str) and canonicalize_name(name) in names
            if (
                isinstance(version, String)
                and self._same_version(version, current)
                and version != target
            ):
                project["version"] = self._replace_string(version, target)
            for dependencies in self._dependencies(document, project):
                if self._rewrite_array(dependencies, names, current, target):
                    participates = True
            if participates:
                results[path] = document.as_string()
        return results
