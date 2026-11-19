"""Represent the migration tables in the repo-local state directory standard.

The tables supply every path the layout audit grades.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Self, final


@final
class RowKind(Enum):
    """Identify which migration rule the audit applies."""

    ROOT_SENTINEL = "root-sentinel"
    BARE_FILE = "bare-file"
    REGISTRY = "registry"
    LIVE_STATE = "live-state"


@final
@dataclass(frozen=True, slots=True)
class MigrationRow:
    """Describe what moves, where to, and the paths the audit observes.

    ``paths`` are the legacy paths the row names (the Live path column for a
    live-state row); ``destination`` is the first path the Destination column
    names, or ``""`` for a row that only deletes. ``migrates`` is False for a
    row whose Rule says no migration exists, so a matching artifact is a stray.
    """

    section: str
    kind: RowKind
    artifact: str
    destination: str
    paths: tuple[str, ...]
    migrates: bool = True

    @property
    def root_sentinels(self) -> tuple[str, ...]:
        """The repo-root entries this row's paths sit under (§ 9.1 rows only)."""
        if self.kind is not RowKind.ROOT_SENTINEL:
            return ()
        return tuple(path.split("/", 1)[0] for path in self.paths)

    def path_naming(self, sentinel: str) -> str:
        """Return the row's legacy path under root entry ``sentinel``.

        Raises:
            KeyError: No path of this row sits under ``sentinel``.
        """
        for path in self.paths:
            if path.split("/", 1)[0] == sentinel:
                return path
        msg = f"{sentinel} is not named by row {self.artifact!r}"
        raise KeyError(msg)


@final
class MigrationTable:
    """Look up migration rows for the layout audit."""

    __slots__ = ("_rows",)

    _rows: tuple[MigrationRow, ...]

    def __new__(cls, rows: tuple[MigrationRow, ...]) -> Self:
        """Create a table that answers the audit's queries over ``rows``."""
        self = super().__new__(cls)
        self._rows = rows
        return self

    @property
    def rows(self) -> tuple[MigrationRow, ...]:
        """Every row, in the order given."""
        return self._rows

    def rows_of(self, kind: RowKind) -> tuple[MigrationRow, ...]:
        """Return the rows of table ``kind``, in the order given."""
        return tuple(row for row in self._rows if row.kind is kind)

    def live_paths(self) -> tuple[str, ...]:
        """Return every § 9.4 live path: the gitignore block's interim excludes."""
        return tuple(
            path for row in self.rows_of(RowKind.LIVE_STATE) for path in row.paths
        )

    def rows_naming_sentinel(self, sentinel: str) -> tuple[MigrationRow, ...]:
        """Return the § 9.1 rows with a legacy path under root entry ``sentinel``."""
        return tuple(
            row
            for row in self.rows_of(RowKind.ROOT_SENTINEL)
            if sentinel in row.root_sentinels
        )

    def row_naming_path(self, kind: RowKind, path: str) -> MigrationRow | None:
        """Return the row of ``kind`` naming ``path`` exactly, or ``None``."""
        for row in self.rows_of(kind):
            if path in row.paths:
                return row
        return None


MIGRATION_TABLE = MigrationTable(
    (
        MigrationRow(
            "9.1",
            RowKind.ROOT_SENTINEL,
            ".biff",
            ".punt-labs/biff/config.yaml",
            (".biff",),
        ),
        MigrationRow(
            "9.1",
            RowKind.ROOT_SENTINEL,
            ".quarry.toml",
            ".punt-labs/quarry/config.md",
            (".quarry.toml",),
            migrates=False,
        ),
        MigrationRow(
            "9.1",
            RowKind.ROOT_SENTINEL,
            ".vox/config.md",
            ".punt-labs/vox/vox.md",
            (".vox/config.md",),
        ),
        MigrationRow(
            "9.1",
            RowKind.ROOT_SENTINEL,
            ".lux/config.md",
            ".punt-labs/lux/config.md",
            (".lux/config.md",),
        ),
        MigrationRow(
            "9.1",
            RowKind.ROOT_SENTINEL,
            ".biff / .vox / .lux",
            "",
            (".biff", ".vox", ".lux"),
        ),
        MigrationRow(
            "9.1",
            RowKind.ROOT_SENTINEL,
            ".ethos/missions.jsonl",
            ".punt-labs/local/ethos/missions.jsonl",
            (".ethos/missions.jsonl",),
        ),
        MigrationRow(
            "9.2",
            RowKind.BARE_FILE,
            ".punt-labs/lux.md",
            ".punt-labs/lux/",
            (".punt-labs/lux.md",),
        ),
        MigrationRow(
            "9.3",
            RowKind.REGISTRY,
            ".punt-labs/ethos gitlink",
            ".punt-labs/ethos/",
            (".punt-labs/ethos",),
        ),
        MigrationRow(
            "9.4",
            RowKind.LIVE_STATE,
            "quarry captures/",
            "~/.punt-labs/quarry/captures/",
            (".punt-labs/quarry/captures/",),
        ),
        MigrationRow(
            "9.4",
            RowKind.LIVE_STATE,
            "vox ephemeral/",
            "~/.punt-labs/vox/",
            (".punt-labs/vox/ephemeral/",),
        ),
        MigrationRow(
            "9.4",
            RowKind.LIVE_STATE,
            "ethos live logs",
            ".punt-labs/local/ethos/",
            (),
        ),
    )
)
