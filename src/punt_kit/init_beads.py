"""punt init's beads step: run ``bd init`` and report why it failed."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING, Self, final

from rich.console import Console

from punt_kit.phases.shared import timeouts
from punt_kit.phases.shared.command_runner import CommandRunner
from punt_kit.phases.shared.errors import OperationalFailure, ReleaseError

if TYPE_CHECKING:
    from punt_kit.detect import ProjectInfo

console = Console()


class BeadsInitError(ReleaseError):
    """``bd init`` ran and failed, or could not be run at all."""


@final
class BeadsInit:
    """Initializes beads in a project that has none."""

    __slots__ = ("_info",)

    _info: ProjectInfo

    def __new__(cls, info: ProjectInfo) -> Self:
        self = super().__new__(cls)
        self._info = info
        return self

    def run(self) -> list[str]:
        """Files created, or empty when beads is present or ``bd`` is absent.

        Raises :class:`BeadsInitError` when ``bd init`` fails: the caller
        finishes its other steps and then ends the run with the failure.
        """
        info = self._info
        if info.has_beads:
            return []

        bd = shutil.which("bd")
        if bd is None:
            console.print("  [yellow]⚠[/yellow] bd not found — skipping beads init")
            return []

        # Derive prefix from directory name
        prefix = info.root.name.replace("-", "").replace("_", "")
        try:
            CommandRunner.run(
                [bd, "init", "--prefix", prefix],
                cwd=str(info.root),
                timeout=timeouts.BD_INIT,
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"beads init timed out after {timeouts.BD_INIT}s"
            if detail := OperationalFailure.detail(exc):
                msg = f"{msg}: {detail}"
            raise BeadsInitError(msg) from exc
        except subprocess.CalledProcessError as exc:
            msg = f"beads init failed: {OperationalFailure.one_line(exc)}"
            raise BeadsInitError(msg) from exc
        except OSError as exc:
            msg = f"beads init failed: {exc}"
            raise BeadsInitError(msg) from exc
        console.print(f"  [green]+[/green] Initialized beads (prefix: {prefix})")
        return [".beads/"]
