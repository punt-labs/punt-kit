"""Report subprocess outcomes without retaining arguments or captured output."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    import logging
    from types import TracebackType


@final
class CommandDiagnostics:
    """Bind privacy-safe subprocess reporting to the boundary's module logger."""

    __slots__ = ("_command", "_logger")

    _command: str
    _logger: logging.Logger

    def __new__(cls, cmd: list[str], logger: logging.Logger) -> Self:
        """Bind reporting to the caller's diagnostic namespace."""
        self = super().__new__(cls)
        self._command = (
            cmd[0] if cmd and cmd[0] in {"git", "gh", "uv", "uvx"} else "external"
        )
        self._logger = logger
        return self

    def __enter__(self) -> Self:
        """Report the safe command category before crossing the process boundary."""
        self._logger.debug("Starting subprocess command=%s", self._command)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Report unsuccessful boundaries without suppressing their exceptions."""
        if isinstance(exc, subprocess.CalledProcessError):
            self._logger.info(
                "Subprocess finished command=%s status=%d",
                self._command,
                exc.returncode,
            )
        elif exc is not None:
            self._logger.info("Subprocess did not complete command=%s", self._command)

    def completed(
        self, result: subprocess.CompletedProcess[str]
    ) -> subprocess.CompletedProcess[str]:
        """Report a completed process and return the original result unchanged."""
        self._logger.info(
            "Subprocess finished command=%s status=%d", self._command, result.returncode
        )
        return result
