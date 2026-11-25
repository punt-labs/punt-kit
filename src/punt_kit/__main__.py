"""Run the ``punt`` command-line interface."""

from __future__ import annotations

import json
from typing import Annotated, NoReturn

import typer

from punt_kit import __version__
from punt_kit.telemetry import ObservedGroup

app = ObservedGroup.create_app()

_json_output: bool = False
_verbose: bool = False
_quiet: bool = False


def _die(msg: str) -> NoReturn:
    """Report an error as JSON or on stderr, and exit 1."""
    if _json_output:
        typer.echo(json.dumps({"error": msg}), color=True)
    else:
        typer.echo(f"Error: {msg}", err=True, color=True)
    raise typer.Exit(code=1)


def _emit(data: object, text: str) -> None:
    """Print text or JSON depending on --json flag. Respects --quiet."""
    if _json_output:
        typer.echo(json.dumps(data, default=str), color=True)
    elif not _quiet:
        typer.echo(text, color=True)


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
    global _json_output, _verbose, _quiet
    _json_output = output_json
    _verbose = verbose
    _quiet = quiet
    if verbose and quiet:
        _die("--verbose and --quiet are mutually exclusive")
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help(), color=True)
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


def _toggle(path: str, *, on: bool) -> None:
    """Run ``enable`` or ``disable`` in the repo at ``path`` and report it."""
    from pathlib import Path

    from punt_kit.enablement import PuntEnablement

    root = Path(path).resolve()
    if not root.is_dir():
        _die(f"{root} is not a directory")
    punt = PuntEnablement(root)
    report = punt.enable() if on else punt.disable()
    if report.error:
        done = "; ".join(report.changes) or "nothing changed"
        _die(f"{report.error} ({done})")
    verb = "enabled" if on else "disabled"
    text = "\n".join(report.changes) or f"punt already {verb} in {root}"
    _emit({"changes": list(report.changes)}, text)


@app.command()
def enable(
    path: str = typer.Argument(".", help="Path to the repo root"),
) -> None:
    """Enable punt in this repo: guide, marker, import line, Skill rules."""
    _toggle(path, on=True)


@app.command()
def disable(
    path: str = typer.Argument(".", help="Path to the repo root"),
) -> None:
    """Disable punt in this repo; the guide stays in place, dormant."""
    _toggle(path, on=False)


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
def seed(
    target: str = typer.Argument(help="Target to render: makefile, settings"),
    path: str = typer.Argument(".", help="Path to the project root"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would change without modifying files"
    ),
) -> None:
    """Render and merge managed sections in project files."""
    from punt_kit.seed import run_seed

    run_seed(path, target=target, dry_run=dry_run)


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
        typer.echo(
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
            ),
            color=True,
        )
    if _quiet and code != 0:
        typer.echo("doctor: required checks failed", err=True, color=True)
    raise typer.Exit(code=code)


@app.command()
def status(
    path: str = typer.Argument(".", help="Path to the project root"),
) -> None:
    """Show detected project type, standards version, and beads state."""
    from pathlib import Path

    from punt_kit.phases.shared.errors import ReleaseError
    from punt_kit.status import run_status
    from punt_kit.status_view import StatusView

    resolved = Path(path).resolve()
    if not resolved.is_dir():
        _die(f"{resolved} is not a directory")

    try:
        info = run_status(path)
    except ReleaseError as exc:
        _die(str(exc))
    view = StatusView(info)
    if _json_output:
        typer.echo(view.json(), color=True)
    elif not _quiet:
        typer.echo(view.text(), color=True)
    if info.beads_skipped and not _quiet:
        typer.echo(
            f"Warning: skipped {info.beads_skipped} malformed bead line(s)",
            err=True,
            color=True,
        )


if __name__ == "__main__":
    app()
