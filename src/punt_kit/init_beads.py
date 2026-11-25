"""Run the ``bd init`` step for ``punt repo init``."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING, Self, final

from rich.console import Console
from rich.markup import escape

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
    """Initialize beads in a project that has none."""

    __slots__ = ("_info",)

    _info: ProjectInfo

    def __new__(cls, info: ProjectInfo) -> Self:
        """Initialize beads in the project ``info`` describes."""
        self = super().__new__(cls)
        self._info = info
        return self

    def run(self) -> list[str]:
        """Return the paths created by ``bd init``, or none if it is skipped.

        Raises:
            BeadsInitError: ``bd init`` fails, times out, or cannot start.
        """
        info = self._info
        if info.has_beads:
            return []

        bd = shutil.which("bd")
        if bd is None:
            console.print("  [yellow]⚠[/yellow] bd not found — skipping beads init")
            return []

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
                msg = f"{msg} — {detail}"
            raise BeadsInitError(self._with_partial(msg)) from exc
        except subprocess.CalledProcessError as exc:
            msg = f"beads init failed: {OperationalFailure.one_line(exc)}"
            raise BeadsInitError(self._with_partial(msg)) from exc
        except OSError as exc:
            msg = f"beads init failed: {exc}"
            raise BeadsInitError(self._with_partial(msg)) from exc
        shown = escape(prefix)
        console.print(f"  [green]+[/green] Initialized beads (prefix: {shown})")
        return [".beads/"]

    def _with_partial(self, msg: str) -> str:
        """Add a cleanup hint if the failed run left a partial ``.beads/``."""
        if not (self._info.root / ".beads").exists():
            return msg
        return f"{msg}; bd init left a partial .beads/ — remove it before retrying"
