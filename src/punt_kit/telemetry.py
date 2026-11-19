"""Observe CLI invocations through the shared closed-schema facade."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, final

import typer
from punt_observe.telemetry import BoolAttr, EnumAttr, SignalSchema, open_telemetry
from typer.core import TyperCommand, TyperGroup

from punt_kit.logging_config import EntryPointLogging

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)


class _CommandFailed(Exception):
    pass


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

    @staticmethod
    def command_schema(commands: Sequence[str]) -> SignalSchema:
        """Declare a closed command vocabulary without recording arguments."""
        return SignalSchema(
            "punt.cli.command",
            1,
            "span",
            {
                "command": EnumAttr(tuple(sorted({"punt", "unknown", *commands}))),
                "outcome": EnumAttr(("ok", "error")),
                "json": BoolAttr(),
            },
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
        return self._record(
            arguments,
            lambda: parent_main(
                arguments,
                prog_name,
                complete_var,
                standalone_mode,
                windows_expand_args,
                **extra,
            ),
            standalone_mode,
        )

    @staticmethod
    def _invoke(
        invoke: Callable[[], Any], command: str, standalone_mode: bool
    ) -> tuple[Any, SystemExit | None]:
        outcome = "error"
        exit_code = 1
        try:
            result = invoke()
            exit_code = result if not standalone_mode and isinstance(result, int) else 0
            outcome = "ok" if exit_code == 0 else "error"
            return result, None
        except SystemExit as exc:
            exit_code = (
                exc.code if isinstance(exc.code, int) else int(exc.code is not None)
            )
            outcome = "ok" if exc.code in (None, 0) else "error"
            if exc.code not in (None, 0):
                raise
            return None, exc
        finally:
            logger.info(
                "CLI invocation finished command=%s outcome=%s exit_code=%d",
                command,
                outcome,
                exit_code,
            )

    def _record(
        self, arguments: list[str], invoke: Callable[[], Any], standalone_mode: bool
    ) -> Any:
        command, output_json = self._metadata(arguments)
        telemetry = open_telemetry("punt", [self.command_schema(tuple(self.commands))])
        successful_exit: SystemExit | None = None
        result: Any = None
        try:
            try:
                with telemetry.span(
                    "punt.cli.command", 1, command=command, json=output_json
                ):
                    logger.info("CLI invocation command=%s", command)
                    result, successful_exit = self._invoke(
                        invoke, command, standalone_mode
                    )
                    if not standalone_mode and isinstance(result, int) and result != 0:
                        raise _CommandFailed
            except _CommandFailed:
                pass
        finally:
            telemetry.shutdown(timeout_s=2)
        if successful_exit is not None:
            raise successful_exit
        return result
