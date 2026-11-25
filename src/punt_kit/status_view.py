"""Render a checkout status result for the terminal."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from punt_kit.status import StatusInfo


class StatusView:
    """Format one checkout status without running detection again."""

    _status: StatusInfo

    def __new__(cls, status: StatusInfo) -> Self:
        """Retain the status captured by the command."""
        self = super().__new__(cls)
        self._status = status
        return self

    def json(self) -> str:
        """Serialize the status fields in the CLI's JSON format."""
        return json.dumps(asdict(self._status), default=str)

    def text(self) -> str:
        """Return the human-readable status lines in display order."""
        info = self._status
        rows = [f"punt {info.punt_kit_version}"]
        if info.language:
            rows.append(f"Language:     {info.language}")
        if info.project_type:
            rows.append(f"Project type: {info.project_type}")
        if info.is_plugin:
            rows.append("Plugin:       yes")
        if info.is_mcp_server:
            rows.append("MCP server:   yes")
        if info.has_beads:
            rows.append(
                f"Beads:        {info.beads_open} open, "
                f"{info.beads_in_progress} in progress"
            )
        return "\n".join(rows)
