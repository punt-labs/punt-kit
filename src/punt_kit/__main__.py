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
    language: str = typer.Option(
        "",
        "--language",
        "-l",
        help="Override detected language (python, node, swift)",
    ),
) -> None:
    """Detect project type, generate missing files, and report manual steps."""
    from punt_kit.init import run_init

    run_init(path, language=language or None)


@app.command()
def audit(
    path: str = typer.Argument(".", help="Path to the project root"),
    fix: bool = typer.Option(False, "--fix", help="Create missing mechanical files"),
) -> None:
    """Check compliance against Punt Labs standards."""
    from punt_kit.audit import run_audit

    run_audit(path, fix=fix)


@app.command()
def pii(
    path: str = typer.Argument(".", help="Path to the project root"),
    staged: bool = typer.Option(False, "--staged", help="Scan only staged files"),
    config: str = typer.Option("", "--config", help="Config file path override"),
) -> None:
    """Scan for personally identifiable information."""
    from punt_kit.pii import run_pii

    run_pii(path, staged=staged, config=config or None)


@app.command()
def release(
    version_arg: str = typer.Argument(
        "", help="Target version (e.g. 1.2.3). Auto-detected if omitted."
    ),
    path: str = typer.Option(".", "--path", "-p", help="Path to the project root"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would happen without changes"
    ),
    resume_from: str = typer.Option(
        "",
        "--resume-from",
        help="Resume from a specific phase (e.g. propagate, verify)",
    ),
) -> None:
    """Run the deterministic release workflow (phases 1-11)."""
    from punt_kit.release import run_release

    run_release(
        path,
        version=version_arg or None,
        dry_run=dry_run,
        resume_from=resume_from or None,
    )


@app.command()
def auto(
    target: str = typer.Argument(help="Target to render: claude, makefile, settings"),
    path: str = typer.Argument(".", help="Path to the project root"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would change without modifying files"
    ),
) -> None:
    """Render and merge managed sections in project files."""
    from punt_kit.auto import run_auto

    run_auto(path, target=target, dry_run=dry_run)


@app.command()
def version() -> None:
    """Print the punt-kit version."""
    console.print(f"punt-kit {__version__}")


if __name__ == "__main__":
    app()
