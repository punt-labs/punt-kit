"""Expose the checkout operations under punt repo."""

from __future__ import annotations

from typing import Annotated, Self

import typer

from punt_kit.cli_options import OutputCommand, OutputGroup
from punt_kit.cli_output import (
    RESULTS,
    DryRun,
    Output,
    ProjectPath,
)


class RepoCli:
    """Register the repository commands."""

    _app: typer.Typer
    _output: type[Output]

    def __new__(cls, output: type[Output]) -> Self:
        """Create and register a fresh Typer app."""
        self = super().__new__(cls)
        self._output = output
        self._app = typer.Typer(cls=OutputGroup, rich_markup_mode=None)
        self._app.callback(invoke_without_command=True, epilog=RESULTS)(
            self._repo_group
        )
        self._app.command(cls=OutputCommand, epilog=RESULTS)(self.init)
        self._app.command(cls=OutputCommand, epilog=RESULTS)(self.audit)
        self._app.command("scan-pii", cls=OutputCommand, epilog=RESULTS)(self.pii)
        self._app.command(cls=OutputCommand, epilog=RESULTS)(self.seed)
        return self

    @property
    def app(self) -> typer.Typer:
        """Return the registered command app."""
        return self._app

    def _repo_group(
        self,
        ctx: typer.Context,
    ) -> None:
        """Scaffold, check, and update a repository checkout."""
        OutputGroup.show_help(ctx, self._output)

    def init(
        self,
        ctx: typer.Context,
        path: ProjectPath = ".",
        language: Annotated[
            str,
            typer.Option("--language", "-l", help="Override the detected language."),
        ] = "",
    ) -> None:
        """Generate missing project files and report manual steps."""
        from punt_kit.init import run_init

        output = self._output.from_context(ctx)
        with output.engine_output():
            result = run_init(path, language=language or None)
        output.emit({"changes": result})

    def audit(
        self,
        ctx: typer.Context,
        path: ProjectPath = ".",
        fix: Annotated[
            bool, typer.Option("--fix", help="Create missing mechanical files.")
        ] = False,
    ) -> None:
        """Check the repository against Punt Labs standards."""
        from punt_kit.audit import run_audit

        output = self._output.from_context(ctx)
        with output.engine_output():
            passed, fixed = run_audit(path, fix=fix)
        output.emit({"passed": passed, "failed": 0, "fixed": fixed})

    def pii(
        self,
        ctx: typer.Context,
        path: ProjectPath = ".",
        staged: Annotated[
            bool,
            typer.Option("--staged", help="Read staged changes from the Git index."),
        ] = False,
        config: Annotated[
            str, typer.Option("--config", help="Override the scanner config file.")
        ] = "",
    ) -> None:
        """Scan tracked files for personally identifiable information."""
        from punt_kit.pii_checkout import run_pii

        output = self._output.from_context(ctx)
        with output.engine_output():
            result = run_pii(path, staged=staged, config=config or None)
        output.emit(result)

    def seed(
        self,
        ctx: typer.Context,
        target: Annotated[
            str, typer.Argument(help="Target to render: makefile, settings.")
        ],
        path: ProjectPath = ".",
        dry_run: DryRun = False,
    ) -> None:
        """Render and merge managed sections in project files."""
        from punt_kit.seed import run_seed

        output = self._output.from_context(ctx)
        with output.engine_output():
            files = run_seed(path, target=target, dry_run=dry_run)
        output.emit(
            {
                "target": target,
                "dry_run": dry_run,
                "would_change" if dry_run else "changes": files,
            }
        )


repo_app = RepoCli(Output).app
