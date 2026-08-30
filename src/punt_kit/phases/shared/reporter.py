"""Colored console reporting for the release workflow."""

from __future__ import annotations

from typing import ClassVar, NoReturn, final

from rich.console import Console

from punt_kit.phases.shared.errors import ReleaseError


@final
class Reporter:
    """Prints colored status lines. Exactly one process-wide instance.

    ``ok``/``info``/``dry``/``warn``/``fail`` share the console vocabulary
    and the same rendering surface — the canonical case where these would
    otherwise be free functions missing a class to live on (PY-OO-7).
    """

    __slots__ = ("_console",)

    _console: Console
    _instance: ClassVar[Reporter | None] = None

    # Singleton (PY-DP-7): __new__ returns the cached instance across calls,
    # so this annotates -> Reporter rather than -> Self — the class is
    # @final, so the two are equivalent, and Self would force an unsound
    # Self | Reporter union at the join point below.
    def __new__(cls) -> Reporter:
        instance = cls._instance
        if instance is None:
            instance = super().__new__(cls)
            instance._console = Console()
            cls._instance = instance
        return instance

    def ok(self, msg: str) -> None:
        self._console.print(f"  [green]✓[/green] {msg}")

    def info(self, msg: str) -> None:
        self._console.print(f"  [dim]▶[/dim] {msg}")

    def dry(self, msg: str) -> None:
        self._console.print(f"  [yellow]DRY[/yellow] {msg}")

    def warn(self, msg: str) -> None:
        """Emit a loud, unmistakable warning without aborting the release.

        For conditions the operator must see and act on but that are not
        failures — e.g. a post-publish propagation step skipped because a
        sibling is absent. Louder than ``info`` (dimmed and easily
        swallowed) so the skip does not read as routine progress.
        """
        self._console.print(f"  [yellow]⚠ WARNING:[/yellow] {msg}")

    def fail(self, msg: str) -> NoReturn:
        self._console.print(f"[red]Error:[/red] {msg}")
        raise ReleaseError(msg)


# Process-wide singleton — release.py aliases _ok/_info/_dry/_warn/_fail to
# this instance's bound methods.
reporter = Reporter()
