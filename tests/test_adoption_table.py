"""The migration table in code matches the one in the standard, row for row.

The standard's § 9 tables are the sole source for the paths `punt audit`
grades. This suite parses those tables out of ``standards/punt-labs-dir.md``
at test time and compares them with :data:`MIGRATION_TABLE`, so an edit to
the Markdown without the matching data edit fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from punt_kit.adoption_table import MIGRATION_TABLE, MigrationRow, RowKind

STANDARD = Path(__file__).resolve().parents[1] / "standards" / "punt-labs-dir.md"

_SECTIONS: dict[str, RowKind] = {
    "9.1": RowKind.ROOT_SENTINEL,
    "9.2": RowKind.BARE_FILE,
    "9.3": RowKind.REGISTRY,
    "9.4": RowKind.LIVE_STATE,
}

_CODE = re.compile(r"`([^`]+)`")


def _section_tables() -> dict[str, list[list[str]]]:
    """The body rows of the Markdown table under each § 9.x heading."""
    tables: dict[str, list[list[str]]] = {}
    current = ""
    for line in STANDARD.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^### (9\.\d) ", line)
        if heading:
            current = heading.group(1)
            continue
        if line.startswith("## "):
            current = ""
        if current not in _SECTIONS or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] in {"Legacy", "Artifact"} or set(cells[0]) == {"-"}:
            continue
        tables.setdefault(current, []).append(cells)
    return tables


def _head(cell: str) -> str:
    """The cell up to its first parenthetical or dash-separated aside."""
    return re.split(r" \(| — ", cell, maxsplit=1)[0]


def _first_code(cell: str) -> str:
    """The first code span in ``cell``, or ``""`` for a ``—`` cell."""
    spans = _CODE.findall(cell)
    return spans[0] if spans else ""


def _row_from_markdown(section: str, cells: list[str]) -> MigrationRow:
    """Transcribe one table row the way the data module does.

    The artifact is the first cell's head with backticks stripped; the
    destination is the first code span of the Destination column; the paths
    are the code spans of the Live path column (§ 9.4) or of the Legacy cell's
    head (§ 9.1-9.3); a Rule that opens "No migration" marks a non-migrating row.
    """
    kind = _SECTIONS[section]
    artifact = _head(cells[0]).replace("`", "")
    if kind is RowKind.LIVE_STATE:
        paths = tuple(_CODE.findall(cells[1]))
        destination = _first_code(cells[2])
    else:
        paths = tuple(_CODE.findall(_head(cells[0])))
        destination = _first_code(cells[1])
    migrates = not cells[-1].startswith("No migration")
    return MigrationRow(section, kind, artifact, destination, paths, migrates)


def _expected_rows() -> tuple[MigrationRow, ...]:
    return tuple(
        _row_from_markdown(section, cells)
        for section, rows in _section_tables().items()
        for cells in rows
    )


def test_every_section_has_a_table() -> None:
    assert set(_section_tables()) == set(_SECTIONS)


def test_table_matches_the_standard_row_for_row() -> None:
    assert MIGRATION_TABLE.rows == _expected_rows()


@pytest.mark.parametrize(
    ("sentinel", "legacy_paths"),
    [
        (".biff", (".biff", ".biff")),
        (".vox", (".vox/config.md", ".vox")),
        (".lux", (".lux/config.md", ".lux")),
        (".ethos", (".ethos/missions.jsonl",)),
        (".quarry.toml", (".quarry.toml",)),
    ],
)
def test_rows_naming_each_sentinel(
    sentinel: str, legacy_paths: tuple[str, ...]
) -> None:
    rows = MIGRATION_TABLE.rows_naming_sentinel(sentinel)
    assert tuple(r.path_naming(sentinel) for r in rows) == legacy_paths


def test_live_paths_are_the_interim_excludes() -> None:
    assert MIGRATION_TABLE.live_paths() == (
        ".punt-labs/quarry/captures/",
        ".punt-labs/vox/ephemeral/",
    )


def test_bare_file_and_gitlink_rows() -> None:
    assert tuple(r.paths for r in MIGRATION_TABLE.rows_of(RowKind.BARE_FILE)) == (
        (".punt-labs/lux.md",),
    )
    assert tuple(r.paths for r in MIGRATION_TABLE.rows_of(RowKind.REGISTRY)) == (
        (".punt-labs/ethos",),
    )


def test_root_sentinels_are_first_path_segments() -> None:
    ethos = MIGRATION_TABLE.rows_naming_sentinel(".ethos")
    assert [r.root_sentinels for r in ethos] == [(".ethos",)]
    assert MIGRATION_TABLE.rows_naming_sentinel(".punt-labs") == ()
