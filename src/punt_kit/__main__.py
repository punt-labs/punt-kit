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
) -> None:
    """Check compliance against Punt Labs standards (read-only)."""
    from punt_kit.audit import run_audit

    run_audit(path)


@app.command()
def version() -> None:
    """Print the punt-kit version."""
    console.print(f"punt-kit {__version__}")


if __name__ == "__main__":
    app()
