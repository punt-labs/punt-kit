from __future__ import annotations

import typer
from rich.console import Console

from punt_kit import __version__

app = typer.Typer(
    name="punt",
    help="Standards, scaffolding, and compliance tooling for Punt Labs projects.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def init(
    path: str = typer.Argument(".", help="Path to the project root"),
) -> None:
    """Detect project type, generate missing files, and report manual steps."""
    from punt_kit.init import run_init

    run_init(path)


@app.command()
def audit(
    path: str = typer.Argument(".", help="Path to the project root"),
    fix: bool = typer.Option(False, "--fix", help="Create missing mechanical files"),
) -> None:
    """Check compliance against Punt Labs standards."""
    from punt_kit.audit import run_audit

    run_audit(path, fix=fix)


@app.command()
def install() -> None:
    """Install the punt Claude Code plugin."""
    from punt_kit.installer import install as do_install

    result = do_install()
    for step in result.steps:
        symbol = "\u2713" if step.passed else "\u2717"
        console.print(f"  {symbol} {step.name}: {step.message}")
    console.print()
    console.print(result.message)
    if not result.installed:
        raise typer.Exit(code=1)


@app.command()
def uninstall() -> None:
    """Uninstall the punt Claude Code plugin."""
    from punt_kit.installer import uninstall as do_uninstall

    result = do_uninstall()
    for step in result.steps:
        symbol = "\u2713" if step.passed else "\u2717"
        console.print(f"  {symbol} {step.name}: {step.message}")
    console.print()
    console.print(result.message)
    if not result.uninstalled:
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the punt-kit version."""
    console.print(f"punt-kit {__version__}")


if __name__ == "__main__":
    app()
