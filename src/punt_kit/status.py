"""Project status summary for punt-kit."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from punt_kit import __version__


@dataclass(frozen=True)
class StatusInfo:
    """Operational state summary for a project."""

    punt_kit_version: str
    language: str | None
    project_type: str | None
    is_plugin: bool
    is_mcp_server: bool
    has_beads: bool
    beads_open: int
    beads_in_progress: int


def _count_beads(root: Path) -> tuple[int, int]:
    """Count open and in-progress beads from the JSONL file."""
    jsonl = root / ".beads" / "issues.jsonl"
    if not jsonl.exists():
        return (0, 0)
    try:
        text = jsonl.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"Warning: could not read {jsonl}: {exc}",
            file=sys.stderr,
        )
        return (0, 0)
    open_count = 0
    in_progress = 0
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            issue = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        st = issue.get("status", "")
        if st == "open":
            open_count += 1
        elif st == "in_progress":
            in_progress += 1
    if skipped:
        print(
            f"Warning: skipped {skipped} malformed line(s) in {jsonl}",
            file=sys.stderr,
        )
    return (open_count, in_progress)


def run_status(path: str = ".") -> StatusInfo:
    """Gather project status information."""
    from punt_kit.detect import detect

    root = Path(path).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        raise SystemExit(1)

    info = detect(root)
    has_beads = (root / ".beads").is_dir()
    beads_open, beads_in_progress = _count_beads(root) if has_beads else (0, 0)

    return StatusInfo(
        punt_kit_version=__version__,
        language=info.language,
        project_type=info.project_type,
        is_plugin=info.is_plugin,
        is_mcp_server=info.is_mcp_server,
        has_beads=has_beads,
        beads_open=beads_open,
        beads_in_progress=beads_in_progress,
    )
