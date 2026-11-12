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

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKER = "# === Repo-specific ==="


def _repo_specific_patterns(gitignore: Path) -> list[tuple[int, str]]:
    """Return the (line number, pattern) pairs below the marker.

    Blank lines and comments are not patterns and are dropped.
    """
    lines = gitignore.read_text().splitlines()
    marker_index = lines.index(MARKER)
    return [
        (number, stripped)
        for number, line in enumerate(lines[marker_index + 1 :], marker_index + 2)
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def test_repo_specific_section_has_no_punt_labs_pattern() -> None:
    gitignore = REPO_ROOT / ".gitignore"

    offending = [
        f".gitignore:{number}:{pattern}"
        for number, pattern in _repo_specific_patterns(gitignore)
        if pattern.startswith(".punt-labs/")
    ]

    assert not offending, "repo-specific .punt-labs/ patterns:\n" + "\n".join(offending)
