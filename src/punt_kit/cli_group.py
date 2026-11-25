"""Observe CLI invocations through the shared closed-schema facade."""

from __future__ import annotations

import json
import sys
from itertools import takewhile
from typing import TYPE_CHECKING, Any, final

import typer
from typer._click.exceptions import ClickException
from typer.core import TyperGroup

from punt_kit.cli_options import OutputGroup
from punt_kit.command_span import CommandSpan
from punt_kit.logging_config import EntryPointLogging

if TYPE_CHECKING:
    from collections.abc import Sequence

    from typer._click.core import Command


@final
class ObservedGroup(OutputGroup):
    """Own diagnostics and bounded telemetry for each CLI invocation."""

    @classmethod
    def create_app(cls) -> typer.Typer:
        """Create punt's CLI with observability at its outer boundary."""
        return typer.Typer(
            cls=cls,
            name="punt",
            no_args_is_help=False,
            rich_markup_mode=None,
        )

    def _metadata(self, arguments: list[str]) -> tuple[str, bool, str]:
        name, flags = self._parsed_flags(arguments)
        level = "WARNING"
        if "quiet" in flags:
            level = "ERROR"
        elif "verbose" in flags:
            level = "DEBUG"
        # A parse can stop before reaching a trailing output flag.
        output_json = "--json" in takewhile(lambda arg: arg != "--", arguments)
        return name, output_json, level

    def _parsed_flags(self, arguments: list[str]) -> tuple[str, set[str]]:
        command: Command = self
        name = "punt"
        flags: set[str] = set()
        remaining = list(arguments)
        while True:
            parsed, remaining = self._raw_options(command, remaining)
            flags.update(parsed)
            if not isinstance(command, TyperGroup) or not remaining:
                break
            if command is self:
                name = remaining[0] if remaining[0] in self.commands else "unknown"
            child = command.commands.get(remaining[0])
            if child is None:
                break
            command, remaining = child, remaining[1:]
        return name, flags

    def _raw_options(
        self, command: Command, arguments: list[str]
    ) -> tuple[set[str], list[str]]:
        settings = {**self.context_settings, **command.context_settings}
        with command.context_class(
            command, resilient_parsing=True, **settings
        ) as context:
            params, remaining, _ = command.make_parser(context).parse_args(arguments)
        # The raw parser reports option presence before expose_value is applied.
        flags = {flag for flag in ("verbose", "quiet") if params.get(flag)}
        return flags, remaining

    @staticmethod
    def _handle_parse_failure(
        exc: ClickException | typer.Abort, *, json_error: bool, standalone: bool
    ) -> int:
        if not standalone and not json_error:
            raise exc
        if isinstance(exc, ClickException):
            message, code = exc.format_message(), exc.exit_code
            if not json_error:
                exc.show()
        else:
            message, code = "Aborted", 1
            if not json_error:
                typer.echo(f"{message}!", err=True)
        if json_error:
            typer.echo(json.dumps({"error": message}))
        return code

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        """Observe one invocation and format errors from the command parser."""
        arguments = list(sys.argv[1:] if args is None else args)
        command, output_json, level = self._metadata(arguments)
        parent_main = super().main

        def invoke() -> Any:
            try:
                value = parent_main(
                    arguments,
                    prog_name,
                    complete_var,
                    False,
                    windows_expand_args,
                    **extra,
                )
            except (ClickException, typer.Abort) as exc:
                value = self._handle_parse_failure(
                    exc, json_error=output_json, standalone=standalone_mode
                )
            if value == 130 and output_json:
                typer.echo(json.dumps({"error": "Interrupted"}))
            if standalone_mode and isinstance(value, int):
                raise SystemExit(value)
            return value

        try:
            EntryPointLogging("cli", stderr_level=level).configure()
        except OSError:
            typer.echo("Warning: cannot initialize the private punt log", err=True)

        return CommandSpan(tuple(self.commands), command, output_json).record(
            invoke, standalone_mode=standalone_mode
        )
