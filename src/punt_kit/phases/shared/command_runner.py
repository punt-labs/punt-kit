"""Run subprocesses for the release workflow."""

from __future__ import annotations

import subprocess
from typing import final

from punt_kit.phases.shared import hook_firing, timeouts
from punt_kit.phases.shared.command_diagnostics import CommandDiagnostics


@final
class CommandRunner:
    """Run commands with release defaults and a hook-aware timeout."""

    __slots__ = ()

    @staticmethod
    def run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = timeouts.DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
        errors: str = "strict",
    ) -> subprocess.CompletedProcess[str]:
        """Run a subprocess with release defaults.

        Args:
            timeout: Timeout in seconds, raised to the hook budget for commands
                that may run a Git hook.
            errors: Error handler for decoding captured output.

        Raises:
            subprocess.CalledProcessError: The command exits nonzero with ``check`` set.
            subprocess.TimeoutExpired: The command exceeds its timeout.
            OSError: The command cannot start.
            UnicodeDecodeError: Captured output cannot be decoded with ``errors``.
        """
        with CommandDiagnostics(cmd) as diagnostics:
            return diagnostics.completed(
                subprocess.run(
                    cmd,
                    cwd=cwd,
                    capture_output=capture,
                    text=True,
                    errors=errors,
                    timeout=hook_firing.HookFiringCommand(cmd).timeout(timeout),
                    check=check,
                )
            )
