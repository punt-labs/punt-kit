"""Register the shared output flags for every public command path."""

from __future__ import annotations

from itertools import pairwise, takewhile
from typing import TYPE_CHECKING, Self

import typer
from typer._click.exceptions import BadOptionUsage
from typer._coercion import TypeDescriptor
from typer.core import TyperCommand, TyperGroup, TyperOption
from typer.models import OptionInfo

from punt_kit.cli_output import Output

if TYPE_CHECKING:
    from typer._click.core import Context, Parameter


class OutputOptions:
    """Share one registry of output flags across the command tree."""

    _flags: tuple[TyperOption, ...]

    def __new__(cls) -> Self:
        """Build the registry with the same callbacks at each command level."""
        self = super().__new__(cls)
        self._flags = (
            self._flag("output_json", ("--json",), "Emit one JSON result."),
            self._flag("verbose", ("-v", "--verbose"), "Log to stderr."),
            self._flag("quiet", ("-q", "--quiet"), "Suppress routine output."),
        )
        return self

    @property
    def flags(self) -> tuple[TyperOption, ...]:
        """Return the output options in help order."""
        return self._flags

    def check_values(
        self, ctx: Context, args: list[str], parameters: list[Parameter]
    ) -> None:
        """Keep a bare output flag from becoming a preceding option's value."""
        output_flags = {switch for flag in self._flags for switch in flag.opts}
        value_options = {
            switch
            for param in parameters
            if isinstance(param, TyperOption) and not param.is_flag
            for switch in param.opts
        }
        for option, value in pairwise(takewhile(lambda arg: arg != "--", args)):
            if option in value_options and value in output_flags:
                raise BadOptionUsage(
                    option, f"Option {option!r} requires an argument.", ctx=ctx
                )

    @staticmethod
    def _set_flag(ctx: Context, option: Parameter, value: bool) -> None:
        if value:
            ctx.meta[option.name] = True

    def _flag(
        self, name: str, switches: tuple[str, ...], help_text: str
    ) -> TyperOption:
        return TyperOption(
            param_decls=[name, *switches],
            type_descriptor=TypeDescriptor(bool, OptionInfo(), None),
            default=False,
            is_flag=True,
            expose_value=False,
            callback=self._set_flag,
            help=help_text,
        )


_OPTIONS = OutputOptions()


class OutputCommand(TyperCommand):
    """Expose the shared output flags on a result-producing command."""

    def get_params(self, ctx: Context) -> list[Parameter]:
        """Return the command parameters and shared output flags."""
        return [*_OPTIONS.flags, *super().get_params(ctx)]

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        """Don't consume a bare output flag as a preceding option's value."""
        if not ctx.resilient_parsing:
            _OPTIONS.check_values(ctx, args, super().get_params(ctx))
        return super().parse_args(ctx, args)


class OutputGroup(TyperGroup):
    """Expose the shared output flags on command groups."""

    def get_params(self, ctx: Context) -> list[Parameter]:
        """Return the group parameters and shared output flags."""
        return [*_OPTIONS.flags, *super().get_params(ctx)]

    def list_commands(self, ctx: Context) -> list[str]:
        """List product groups before the top-level verbs."""
        return sorted(
            super().list_commands(ctx),
            key=lambda name: not isinstance(self.commands[name], TyperGroup),
        )

    @staticmethod
    def show_help(ctx: typer.Context, output_type: type[Output] = Output) -> None:
        """Show a bare group's help, or return a JSON usage error."""
        if ctx.invoked_subcommand is not None:
            return
        output = output_type.from_context(ctx)
        if output.json:
            raise typer.BadParameter("A command is required")
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
