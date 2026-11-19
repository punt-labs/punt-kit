"""Report subprocess outcomes without retaining arguments or captured output."""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)


@final
class CommandDiagnostics:
    """Report subprocess outcomes in this module's diagnostic namespace."""

    __slots__ = ("_command",)

    _command: str

    def __new__(cls, cmd: list[str]) -> Self:
        """Bind reporting to a safe command category, never its arguments."""
        self = super().__new__(cls)
        self._command = (
            cmd[0] if cmd and cmd[0] in {"git", "gh", "uv", "uvx"} else "external"
        )
        return self

    def __enter__(self) -> Self:
        """Report the safe command category before crossing the process boundary."""
        logger.debug("Starting subprocess command=%s", self._command)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Report unsuccessful boundaries without suppressing their exceptions."""
        if isinstance(exc, subprocess.CalledProcessError):
            logger.info(
                "Subprocess finished command=%s status=%d",
                self._command,
                exc.returncode,
            )
        elif exc is not None:
            logger.info("Subprocess did not complete command=%s", self._command)

    def completed(
        self, result: subprocess.CompletedProcess[str]
    ) -> subprocess.CompletedProcess[str]:
        """Report a completed process and return the original result unchanged."""
        logger.info(
            "Subprocess finished command=%s status=%d", self._command, result.returncode
        )
        return result
