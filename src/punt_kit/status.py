"""Summarize a project's status for punt-kit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from punt_kit import __version__


@dataclass(frozen=True)
class StatusInfo:
    """Record a project's detected configuration."""

    punt_kit_version: str
    language: str | None
    project_type: str | None
    is_plugin: bool
    is_mcp_server: bool


def run_status(path: str = ".") -> StatusInfo:
    """Gather project status information.

    Raises:
        ReleaseError: A project file detection reads is unreadable.
    """
    from punt_kit.detect import detect

    info = detect(Path(path).resolve())

    return StatusInfo(
        punt_kit_version=__version__,
        language=info.language,
        project_type=info.project_type,
        is_plugin=info.is_plugin,
        is_mcp_server=info.is_mcp_server,
    )
