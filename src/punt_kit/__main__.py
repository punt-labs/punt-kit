from __future__ import annotations

import json
import sys
from typing import Annotated

import typer

from punt_kit import __version__

app = typer.Typer(
    name="punt",
    no_args_is_help=False,
    rich_markup_mode=None,
)

# Global flag state, set by the callback before any command runs.
_json_output: bool = False
_verbose: bool = False
_quiet: bool = False


def _emit(data: object, text: str) -> None:
    """Print text or JSON depending on --json flag. Respects --quiet."""
    if _json_output:
        print(json.dumps(data, default=str))
    elif not _quiet:
        print(text)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    output_json: Annotated[
        bool, typer.Option("--json", help="Output as JSON.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Verbose output.")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress non-essential output.")
    ] = False,
) -> None:
    """punt: standards, scaffolding, and compliance tooling for Punt Labs projects."""
    global _json_output, _verbose, _quiet  # noqa: PLW0603
    if verbose and quiet:
        print("Error: --verbose and --quiet are mutually exclusive.", file=sys.stderr)
        raise typer.Exit(code=1)
    _json_output = output_json
    _verbose = verbose
    _quiet = quiet
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())
        raise typer.Exit(code=0)


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
    _emit({"version": __version__}, f"punt {__version__}")


@app.command()
def doctor() -> None:
    """Check punt-kit installation health."""
    from punt_kit.doctor import run_doctor

    code, results = run_doctor(print_results=not _json_output and not _quiet)
    if _json_output:
        print(
            json.dumps(
                [
                    {
                        "name": r.name,
                        "passed": r.passed,
                        "message": r.message,
                        "required": r.required,
                    }
                    for r in results
                ]
            )
        )
    if _quiet and code != 0:
        print("doctor: required checks failed", file=sys.stderr)
    raise typer.Exit(code=code)


@app.command()
def status(
    path: str = typer.Argument(".", help="Path to the project root"),
) -> None:
    """Show detected project type, standards version, and beads state."""
    from dataclasses import asdict

    from punt_kit.status import run_status

    info = run_status(path)
    if _json_output:
        print(json.dumps(asdict(info), default=str))
    elif not _quiet:
        print(f"punt-kit {info.punt_kit_version}")
        if info.language:
            print(f"Language:     {info.language}")
        if info.project_type:
            print(f"Project type: {info.project_type}")
        if info.is_plugin:
            print("Plugin:       yes")
        if info.is_mcp_server:
            print("MCP server:   yes")
        if info.has_beads:
            open_n, ip_n = info.beads_open, info.beads_in_progress
            print(f"Beads:        {open_n} open, {ip_n} in progress")


if __name__ == "__main__":
    app()
