"""This repository's own root .gitignore honors the .punt-labs/ ignore contract.

standards/punt-labs-dir.md § 4 makes the local convention the only ignore
convention under .punt-labs/: no manifest, no per-file exception, no directory
glob. § 6 then sanctions exactly one place for a ``.punt-labs/`` ignore line in
a root .gitignore: the canonical block, plus one interim exclude per § 9.4
live-state row. That block sits above the ``# === Repo-specific ===`` marker
and is owned by the workspace rollout (``.bin/gitignore-canonical.template`` in
punt-labs/punt-labs), so the repo-specific section below the marker must carry
no ``.punt-labs/`` pattern at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKER = "# === Repo-specific ==="


def _is_punt_labs_pattern(pattern: str) -> bool:
    """Return whether a .gitignore line is a pattern addressing .punt-labs/.

    A leading ``!`` (re-include) or ``/`` (root anchor) does not change what
    the pattern addresses, and ``**/.punt-labs/`` reaches the same tree.
    """
    bare = pattern.removeprefix("!").removeprefix("/")
    return bare.startswith((".punt-labs/", "**/.punt-labs/"))


def _offending_lines(gitignore: Path) -> list[str]:
    """Return ``.gitignore:<line>:<pattern>`` per .punt-labs/ pattern below the marker.

    Blank lines and comments are not patterns and are dropped. A file without
    the marker has no repo-specific section to grade and raises ``ValueError``.
    """
    lines = gitignore.read_text().splitlines()
    marker_index = lines.index(MARKER)
    return [
        f".gitignore:{number}:{stripped}"
        for number, line in enumerate(lines[marker_index + 1 :], marker_index + 2)
        if (stripped := line.strip())
        and not stripped.startswith("#")
        and _is_punt_labs_pattern(stripped)
    ]


@pytest.mark.parametrize(
    "pattern",
    [".punt-labs/x", "!.punt-labs/x", "/.punt-labs/x", "**/.punt-labs/x"],
)
def test_every_spelling_of_a_punt_labs_pattern_is_flagged(pattern: str) -> None:
    assert _is_punt_labs_pattern(pattern)


@pytest.mark.parametrize(
    "pattern",
    [".punt-labs-other/x", "punt-labs/x", "# .punt-labs/x", ""],
)
def test_a_line_outside_punt_labs_is_not_flagged(pattern: str) -> None:
    assert not _is_punt_labs_pattern(pattern)


def test_a_negated_punt_labs_line_below_the_marker_is_offending(
    tmp_path: Path,
) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        f".punt-labs/local/\n{MARKER}\n# note\n\n!.punt-labs/ethos/foo\n"
    )

    assert _offending_lines(gitignore) == [".gitignore:5:!.punt-labs/ethos/foo"]


def test_a_gitignore_without_the_marker_raises(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".punt-labs/local/\n")

    with pytest.raises(ValueError, match="not in list"):
        _offending_lines(gitignore)


def test_repo_specific_section_has_no_punt_labs_pattern() -> None:
    offending = _offending_lines(REPO_ROOT / ".gitignore")

    assert not offending, "repo-specific .punt-labs/ patterns:\n" + "\n".join(offending)
