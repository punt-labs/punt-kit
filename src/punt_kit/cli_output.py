"""Handle output modes and finite command results."""

from __future__ import annotations

import json
import os
import shutil
import sys
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryFile
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer

from punt_kit.errors import CommandFailure

if TYPE_CHECKING:
    from collections.abc import Generator
    from typing import TextIO


RESULTS = "For exit codes and JSON results, see the README's Command results section."
HELP = {"help_option_names": ["-h", "--help"]}

ProjectPath = Annotated[str, typer.Argument(help="Path to the project root.")]
DryRun = Annotated[
    bool, typer.Option("--dry-run", "-n", help="Preview without modifying files.")
]


@dataclass(frozen=True, slots=True)
class Output:
    """Render a command's result in its selected output mode."""

    json: bool
    quiet: bool

    @classmethod
    def from_context(cls, ctx: typer.Context) -> Output:
        """Read flags from every level and reject contradictory verbosity."""
        output = cls(bool(ctx.meta.get("output_json")), bool(ctx.meta.get("quiet")))
        if output.quiet and ctx.meta.get("verbose"):
            raise typer.BadParameter("--verbose and --quiet are mutually exclusive")
        return output

    def emit(self, data: object, text: str = "") -> None:
        """Write a JSON result or its human-readable equivalent."""
        if self.json:
            typer.echo(json.dumps(data))
        elif text and not self.quiet:
            typer.echo(text)

    def emit_encoded(self, encoded: str, text: str) -> None:
        """Write a result whose view already serialized the JSON."""
        if self.json:
            typer.echo(encoded)
        elif not self.quiet:
            typer.echo(text)

    def project_path(self, path: str) -> Path:
        """Resolve a checkout target or emit a result error."""
        root = Path(path).resolve()
        if not root.is_dir():
            self.fail(f"{root} is not a directory")
        return root

    def fail(self, message: str, **details: object) -> NoReturn:
        """Emit an error and exit unsuccessfully."""
        if self.json:
            self.emit({"error": message, **details})
        else:
            sys.stderr.write(f"Error: {message}\n")
        raise typer.Exit(1)

    def fail_after_changes(self, message: str, changes: list[str]) -> NoReturn:
        """Include already-applied changes in either output mode."""
        if changes and not self.json:
            typer.echo("\n".join(changes), err=True)
        self.fail(message, changes=changes)

    @staticmethod
    @contextmanager
    def _redirect_progress(stream: TextIO, fd: int) -> Generator[None]:
        # Release children and hooks inherit the OS descriptor, not sys.stdout.
        sys.stdout.flush()
        saved = os.dup(1)
        try:
            os.dup2(fd, 1)
            with redirect_stdout(stream):
                try:
                    yield
                finally:
                    stream.flush()
        finally:
            os.dup2(saved, 1)
            os.close(saved)

    @contextmanager
    def _progress_stream(self) -> Generator[None]:
        if self.quiet:
            with TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as sink:
                try:
                    with self._redirect_progress(sink, sink.fileno()):
                        yield
                except SystemExit as exc:
                    if exc.code and (
                        not self.json or not isinstance(exc, CommandFailure)
                    ):
                        sink.seek(0)
                        shutil.copyfileobj(sink, sys.stderr)
                    raise
        elif self.json:
            with self._redirect_progress(sys.stderr, 2):
                yield
        else:
            yield

    @contextmanager
    def engine_output(self) -> Generator[None]:
        """Capture expected engine failures and keep progress off JSON stdout."""
        try:
            with self._progress_stream():
                yield
        except CommandFailure as exc:
            if self.json:
                self.fail(exc.message, **exc.details)
            raise typer.Exit(1) from None
        except SystemExit as exc:
            self._engine_exit(exc)
        except OSError as exc:
            self.fail(str(exc))

    def _engine_exit(self, exc: SystemExit) -> NoReturn:
        if exc.code == 130:
            raise typer.Exit(130) from None
        if (self.json or self.quiet) and exc.code:
            message = "Operation did not complete successfully"
            self.fail(exc.code if isinstance(exc.code, str) else message)
        raise exc
