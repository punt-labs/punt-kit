"""Record outcomes for an already parsed punt CLI invocation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_observe.telemetry import BoolAttr, EnumAttr, SignalSchema, open_telemetry

from punt_kit.paths import PuntPaths

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger("punt_kit.telemetry")


class _CommandFailed(Exception):
    pass


@final
class CommandSpan:
    """Record outcomes without consulting the CLI parser or its arguments."""

    _schema: SignalSchema
    _command: str
    _output_json: bool

    def __new__(cls, commands: Sequence[str], command: str, output_json: bool) -> Self:
        """Bind the closed command and output format for one invocation."""
        self = super().__new__(cls)
        self._schema = self.command_schema(commands)
        self._command = command
        self._output_json = output_json
        return self

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

    @staticmethod
    def _invoke[T](
        invoke: Callable[[], T], command: str, standalone_mode: bool
    ) -> tuple[T | None, SystemExit | None]:
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

    def record[T](self, invoke: Callable[[], T], *, standalone_mode: bool) -> T | None:
        """Run the command while recording its bounded outcome."""
        command = self._command
        telemetry = open_telemetry(
            "punt", [self._schema], config=PuntPaths.telemetry_config()
        )
        successful_exit: SystemExit | None = None
        result: T | None = None
        try:
            try:
                with telemetry.span(
                    "punt.cli.command", 1, command=command, json=self._output_json
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
