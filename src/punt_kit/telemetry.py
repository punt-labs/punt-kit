"""Observe CLI invocations through the shared closed-schema facade."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, final

import typer
from typer.core import TyperCommand, TyperGroup

from punt_kit.command_span import CommandSpan
from punt_kit.logging_config import EntryPointLogging

if TYPE_CHECKING:
    from collections.abc import Sequence


@final
class ObservedGroup(TyperGroup):
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

    def _metadata(self, arguments: list[str]) -> tuple[str, bool]:
        with self.context_class(self, resilient_parsing=True) as context:
            parser = TyperCommand(name=self.name, params=self.get_params(context))
            remaining = parser.parse_args(context, list(arguments))
            output_json = bool(context.params.get("output_json", False))
        command = remaining[0] if remaining else "punt"
        if command not in self.commands and command != "punt":
            command = "unknown"
        return command, output_json

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        """Run Click unchanged while recording only a closed command and outcome."""
        EntryPointLogging("cli").configure()
        arguments = list(sys.argv[1:] if args is None else args)
        parent_main = super().main
        command, output_json = self._metadata(arguments)
        return CommandSpan(tuple(self.commands), command, output_json).record(
            lambda: parent_main(
                arguments,
                prog_name,
                complete_var,
                standalone_mode,
                windows_expand_args,
                **extra,
            ),
            standalone_mode=standalone_mode,
        )
