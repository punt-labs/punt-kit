"""Compose the public punt command tree."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Self

import typer

from punt_kit import __version__
from punt_kit.cli_group import ObservedGroup
from punt_kit.cli_options import OutputCommand, OutputGroup
from punt_kit.cli_output import (
    HELP,
    RESULTS,
    Output,
    ProjectPath,
)
from punt_kit.cli_release import release_app
from punt_kit.cli_repo import repo_app
from punt_kit.phases.shared.errors import ReleaseError
from punt_kit.status_view import StatusView

if TYPE_CHECKING:
    from punt_kit.enablement import EnablementReport


class PuntCli:
    """Register and serve the public punt command tree."""

    _app: typer.Typer
    _output: type[Output]

    def __new__(cls, output: type[Output]) -> Self:
        """Create and register a fresh Typer app."""
        self = super().__new__(cls)
        self._output = output
        self._app = ObservedGroup.create_app()
        self._app.add_typer(repo_app, name="repo", context_settings=HELP)
        self._app.add_typer(release_app, name="release", context_settings=HELP)
        self._app.callback(
            invoke_without_command=True, context_settings=HELP, epilog=RESULTS
        )(self._main_callback)
        self._app.command(cls=OutputCommand, epilog=RESULTS)(self.enable)
        self._app.command(cls=OutputCommand, epilog=RESULTS)(self.disable)
        self._app.command(cls=OutputCommand, epilog=RESULTS)(self.status)
        self._app.command(cls=OutputCommand, epilog=RESULTS)(self.doctor)
        self._app.command(cls=OutputCommand, epilog=RESULTS)(self.version)
        self._app.command(cls=OutputCommand, epilog=RESULTS)(self.install)
        return self

    @property
    def app(self) -> typer.Typer:
        """Return the registered command app."""
        return self._app

    def _main_callback(
        self,
        ctx: typer.Context,
    ) -> None:
        """punt: standards, scaffolding, and compliance tooling."""
        OutputGroup.show_help(ctx, self._output)

    def _toggle(self, output: Output, path: str, *, on: bool) -> None:
        from punt_kit.enablement import PuntEnablement

        root = output.project_path(path)
        with output.engine_output():
            punt = PuntEnablement(root)
            report = punt.enable() if on else punt.disable()
        self._report_toggle(output, report, "enabled" if on else "disabled")

    @staticmethod
    def _report_toggle(output: Output, report: EnablementReport, state: str) -> None:
        changes = list(report.changes)
        if report.error:
            output.fail_after_changes(report.error, changes)
        output.emit({"changes": changes}, "\n".join(changes) or f"punt already {state}")

    def enable(
        self,
        ctx: typer.Context,
        path: ProjectPath = ".",
    ) -> None:
        """Enable punt in this repo: guide, marker, import line, Skill rules."""
        self._toggle(self._output.from_context(ctx), path, on=True)

    def disable(
        self,
        ctx: typer.Context,
        path: ProjectPath = ".",
    ) -> None:
        """Disable punt in this repo; the guide stays in place, dormant."""
        self._toggle(self._output.from_context(ctx), path, on=False)

    def status(
        self,
        ctx: typer.Context,
        path: ProjectPath = ".",
    ) -> None:
        """Show detected project type and standards version."""
        from punt_kit.status import run_status

        output = self._output.from_context(ctx)
        output.project_path(path)
        try:
            info = run_status(path)
        except ReleaseError as exc:
            output.fail(str(exc))
        view = StatusView(info)
        output.emit_encoded(view.json(), view.text())

    def doctor(
        self,
        ctx: typer.Context,
    ) -> None:
        """Check punt-kit installation health."""
        from punt_kit.doctor import run_doctor

        output = self._output.from_context(ctx)
        code, results = run_doctor(print_results=not output.json and not output.quiet)
        checks = [asdict(check) for check in results]
        if code:
            output.fail("Required installation checks failed", checks=checks)
        output.emit(checks)

    def version(
        self,
        ctx: typer.Context,
    ) -> None:
        """Print the installed punt-kit version."""
        self._output.from_context(ctx).emit(
            {"version": __version__}, f"punt {__version__}"
        )

    def install(
        self,
        ctx: typer.Context,
    ) -> None:
        """Set up the punt plugin in Claude Code at user scope."""
        from punt_kit.install import InstallError, PluginInstaller

        output = self._output.from_context(ctx)
        try:
            report = PluginInstaller.install()
        except InstallError as exc:
            output.fail(str(exc))
        changes = list(report.changes)
        if report.error:
            output.fail_after_changes(report.error, changes)
        output.emit(
            {"plugin": "punt@punt-labs", "scope": "user", "changes": changes},
            "\n".join(changes),
        )


app = PuntCli(Output).app
