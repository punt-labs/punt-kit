"""Configure private diagnostics at process entry points."""

from __future__ import annotations

from typing import Self, final

from punt_observe.logging import configure_logging as _configure_logging


@final
class EntryPointLogging:
    """Bind punt's durable diagnostics to a process role and terminal level."""

    __slots__ = ("_role", "_stderr_level")

    _role: str
    _stderr_level: str

    def __new__(cls, role: str = "cli", *, stderr_level: str = "WARNING") -> Self:
        """Bind diagnostic operations to this process's role and terminal policy."""
        self = super().__new__(cls)
        self._role = role
        self._stderr_level = stderr_level
        return self

    def configure(self) -> None:
        """Configure the shared private sink for this entry point."""
        _configure_logging("punt", self._role, stderr_level=self._stderr_level)
