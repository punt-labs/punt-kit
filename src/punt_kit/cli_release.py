"""Expose the release workflow under punt release run."""

from __future__ import annotations

from typing import Annotated, Self

import typer

from punt_kit.cli_options import OutputCommand, OutputGroup
from punt_kit.cli_output import (
    RESULTS,
    DryRun,
    Output,
)


class ReleaseCli:
    """Register the release workflow command."""

    _app: typer.Typer
    _output: type[Output]

    def __new__(cls, output: type[Output]) -> Self:
        """Create and register a fresh Typer app."""
        self = super().__new__(cls)
        self._output = output
        self._app = typer.Typer(cls=OutputGroup, rich_markup_mode=None)
        self._app.callback(invoke_without_command=True, epilog=RESULTS)(
            self._release_group
        )
        self._app.command("run", cls=OutputCommand, epilog=RESULTS)(self.release)
        return self

    @property
    def app(self) -> typer.Typer:
        """Return the registered command app."""
        return self._app

    def _release_group(
        self,
        ctx: typer.Context,
    ) -> None:
        """Run or resume a specific release workflow."""
        OutputGroup.show_help(ctx, self._output)

    def release(
        self,
        ctx: typer.Context,
        version_arg: Annotated[
            str,
            typer.Argument(
                metavar="VERSION", help="Release version (auto-detected if omitted)."
            ),
        ] = "",
        path: Annotated[
            str, typer.Option("--path", "-p", help="Path to the project root.")
        ] = ".",
        dry_run: DryRun = False,
        resume_from: Annotated[
            str,
            typer.Option("--resume-from", help="Start at a named phase, e.g. verify."),
        ] = "",
    ) -> None:
        """Perform the release workflow or preview it without making changes."""
        from punt_kit.release import run_release

        output = self._output.from_context(ctx)
        with output.engine_output():
            result = run_release(
                path,
                version=version_arg or None,
                dry_run=dry_run,
                resume_from=resume_from or None,
            )
        output.emit({"version": result, "dry_run": dry_run})


release_app = ReleaseCli(Output).app
