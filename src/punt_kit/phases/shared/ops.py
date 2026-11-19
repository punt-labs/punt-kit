"""Define subprocess and reporting operations for release phases."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn, Protocol, runtime_checkable

from punt_kit.phases.shared.timeouts import DEFAULT_RUN

if TYPE_CHECKING:
    import subprocess


@runtime_checkable
class ReleaseOps(Protocol):
    """Expose subprocess execution and console reporting to release phases.

    Use ``check=False`` and diagnose nonzero exits for network operations,
    external tools, hook-firing mutations, and sibling checkout reads.
    Keep ``check=True`` for routine local reads and staging in a known checkout.
    """

    def run(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
        errors: str = "strict",
    ) -> subprocess.CompletedProcess[str]:
        """Run a release command with a hook-aware timeout.

        Args:
            timeout: Timeout in seconds, subject to the Git hook minimum.
            errors: Error handler for decoding captured output.

        Raises:
            subprocess.CalledProcessError: The command exits nonzero with ``check`` set.
            subprocess.TimeoutExpired: The command exceeds its timeout.
            OSError: The command cannot start.
            UnicodeDecodeError: Captured output cannot be decoded with ``errors``.
        """
        ...

    def ok(self, msg: str) -> None:
        """Report a successful operation."""
        ...

    def info(self, msg: str) -> None:
        """Report release progress."""
        ...

    def dry(self, msg: str) -> None:
        """Describe an operation without performing it."""
        ...

    def warn(self, msg: str) -> None:
        """Report a nonfatal warning."""
        ...

    def error(self, msg: str) -> None:
        """Report an error without raising."""
        ...

    def fail(self, msg: str) -> NoReturn:
        """Report and raise a release failure.

        Raises:
            ReleaseError: Always, with the supplied diagnosis.
        """
        ...
