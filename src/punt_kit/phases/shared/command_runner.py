"""The one place the release starts a process."""

from __future__ import annotations

import subprocess
from typing import final

from punt_kit.phases.shared import hook_firing, timeouts


@final
class CommandRunner:
    """Runs a command with the release's standard options and timeout floor."""

    __slots__ = ()

    @staticmethod
    def run(
        cmd: list[str],
        *,
        cwd: str | None = None,
        timeout: int = timeouts.DEFAULT_RUN,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a subprocess with standard options.

        ``timeout`` defaults to a short metadata budget. Call sites that need
        longer (installs, quality gates, network git, ``gh run watch``) pass a
        named ``timeouts`` budget; every hook-firing command is floored at
        ``GIT_HOOK`` here.
        """
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=hook_firing.HookFiringCommand(cmd).timeout(timeout),
            check=check,
        )
