"""Represent punt's compatibility inventory in docs/repo-layout.md.

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
    REGISTRY = "registry"
    LIVE_STATE = "live-state"


@final
@dataclass(frozen=True, slots=True)
class MigrationRow:
    """Describe what moves, where to, and the paths the audit observes.

    ``section`` cites the policy clause governing the row. ``paths`` are the
    legacy paths the row names (the Live path column for a
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
        """The repo-root entries this row's paths sit under (root rows only)."""
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
        """Return each compatibility live path needing an ignore exemption."""
        return tuple(
            path for row in self.rows_of(RowKind.LIVE_STATE) for path in row.paths
        )

    def rows_naming_sentinel(self, sentinel: str) -> tuple[MigrationRow, ...]:
        """Return the root rows with a legacy path under entry ``sentinel``."""
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
            "PLD-10",
            RowKind.ROOT_SENTINEL,
            ".biff",
            ".punt-labs/biff/config.yaml",
            (".biff",),
        ),
        MigrationRow(
            "PLD-10",
            RowKind.ROOT_SENTINEL,
            ".quarry.toml",
            ".punt-labs/quarry/config.md",
            (".quarry.toml",),
            migrates=False,
        ),
        MigrationRow(
            "PLD-10",
            RowKind.ROOT_SENTINEL,
            ".vox/config.md",
            ".punt-labs/vox/vox.md",
            (".vox/config.md",),
        ),
        MigrationRow(
            "PLD-10",
            RowKind.ROOT_SENTINEL,
            ".lux/config.md",
            ".punt-labs/lux.md",
            (".lux/config.md",),
        ),
        MigrationRow(
            "PLD-10",
            RowKind.ROOT_SENTINEL,
            ".biff / .vox / .lux",
            "",
            (".biff", ".vox", ".lux"),
        ),
        MigrationRow(
            "PLD-10",
            RowKind.ROOT_SENTINEL,
            ".ethos/missions.jsonl",
            ".punt-labs/ethos/missions.jsonl",
            (".ethos/missions.jsonl",),
        ),
        MigrationRow(
            "PLD-12",
            RowKind.REGISTRY,
            ".punt-labs/ethos gitlink",
            ".punt-labs/ethos/",
            (".punt-labs/ethos",),
        ),
        MigrationRow(
            "PLD-2",
            RowKind.LIVE_STATE,
            "quarry captures/",
            "~/.punt-labs/quarry/captures/",
            (".punt-labs/quarry/captures/",),
        ),
        MigrationRow(
            "PLD-2",
            RowKind.LIVE_STATE,
            "vox ephemeral/",
            "~/.punt-labs/vox/",
            (".punt-labs/vox/ephemeral/",),
        ),
        MigrationRow(
            "PLD-2",
            RowKind.LIVE_STATE,
            "ethos live logs",
            ".punt-labs/local/ethos/",
            (),
        ),
    )
)
