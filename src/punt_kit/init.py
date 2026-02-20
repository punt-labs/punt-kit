"""punt init — generate missing config files and report manual steps."""

from __future__ import annotations

import importlib.resources
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import cast

import jinja2
import tomli_w
from rich.console import Console

from punt_kit.detect import ProjectInfo, detect

console = Console()

TEMPLATES = importlib.resources.files("punt_kit") / "templates"

STANDARD_DISPLAY_NAMES: dict[str, str] = {
    "python": "Python",
    "node": "Node.js",
    "github": "GitHub",
    "workflow": "Workflow",
    "cli": "CLI",
    "plugins": "Plugins",
    "distribution": "Distribution",
    "naming": "Naming",
}


def run_init(path: str) -> None:
    """Detect project type, generate/update missing files, report manual steps."""
    root = Path(path).resolve()
    if not root.is_dir():
        console.print(f"[red]Error:[/red] {root} is not a directory")
        raise SystemExit(1)

    info = detect(root)

    console.print(f"\n[bold]punt init[/bold] — {root.name}")
    console.print(f"  Language:     {info.language or 'none'}")
    console.print(f"  Project type: {info.project_type or 'unknown'}")
    console.print(f"  MCP server:   {info.is_mcp_server}")
    console.print(f"  Plugin:       {info.is_plugin}")
    console.print(f"  CI exists:    {info.has_ci}")
    console.print(f"  CLAUDE.md:    {info.has_claude_md}")
    console.print(f"  Beads:        {info.has_beads}")
    console.print()

    changed: list[str] = []

    changed.extend(_init_workflows(info))
    changed.extend(_init_python_config(info))
    changed.extend(_init_beads(info))
    changed.extend(_init_claude_md(info))

    if changed:
        console.print("\n[bold green]Files generated/updated:[/bold green]")
        for f in changed:
            console.print(f"  [green]✓[/green] {f}")
    else:
        console.print("\n[dim]No files needed updating.[/dim]")

    _report_manual_steps(info)


def _init_workflows(info: ProjectInfo) -> list[str]:
    """Generate CI workflow files based on project type."""
    changed: list[str] = []
    workflows_dir = info.root / ".github" / "workflows"

    templates_to_install: list[tuple[str, str]] = []

    if info.language == "python":
        templates_to_install.append(("lint-python.yml", "lint.yml"))
        templates_to_install.append(("test-python.yml", "test.yml"))
    elif info.language == "node":
        templates_to_install.append(("lint-node.yml", "lint.yml"))

    # Release workflow requires package metadata (name + CLI entry point)
    if info.language == "python":
        template_vars = _get_template_vars(info)
        if "package_name" in template_vars and "cli_command" in template_vars:
            templates_to_install.append(("release-python.yml.j2", "release.yml"))
        else:
            missing = [
                k for k in ("package_name", "cli_command") if k not in template_vars
            ]
            console.print(
                f"  [yellow]⚠[/yellow] Skipping release.yml — "
                f"missing {', '.join(missing)} in pyproject.toml"
            )
    else:
        template_vars = {}

    # All repos get docs.yml for markdown linting
    templates_to_install.append(("docs.yml", "docs.yml"))

    for template_name, target_name in templates_to_install:
        template_ref = TEMPLATES / "workflows" / template_name
        raw_content = template_ref.read_text(encoding="utf-8")

        if template_name.endswith(".j2"):
            env = jinja2.Environment(
                autoescape=False,
                keep_trailing_newline=True,
                undefined=jinja2.StrictUndefined,
            )
            template = env.from_string(raw_content)
            rendered = template.render(template_vars)
        else:
            rendered = raw_content

        target_path = workflows_dir / target_name

        if target_path.exists():
            existing = target_path.read_text(encoding="utf-8")
            if existing == rendered:
                continue
            rel = _relpath(target_path, info.root)
            console.print(f"  [yellow]↻[/yellow] Updating {rel}")
        else:
            rel = _relpath(target_path, info.root)
            console.print(f"  [green]+[/green] Creating {rel}")

        workflows_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_text(rendered, encoding="utf-8")
        changed.append(_relpath(target_path, info.root))

    return changed


def _get_template_vars(info: ProjectInfo) -> dict[str, str]:
    """Extract template variables from project metadata."""
    variables: dict[str, str] = {}

    if info.pyproject is None:
        return variables

    project_raw = info.pyproject.get("project")
    if not isinstance(project_raw, dict):
        return variables

    project = cast("dict[str, object]", project_raw)

    name = project.get("name")
    if isinstance(name, str):
        variables["package_name"] = name

    scripts = project.get("scripts")
    if isinstance(scripts, dict) and scripts:
        first_key = next(iter(cast("dict[str, object]", scripts)))
        variables["cli_command"] = first_key

    return variables


def _init_python_config(info: ProjectInfo) -> list[str]:
    """Ensure standard tool configs exist in pyproject.toml."""
    if info.language != "python":
        return []

    pyproject_path = info.root / "pyproject.toml"
    if not pyproject_path.exists():
        return []

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    original = _toml_dump(data)
    changed = False

    # Ensure [tool.ruff]
    tool = data.setdefault("tool", {})
    if "ruff" not in tool:
        tool["ruff"] = {
            "line-length": 88,
            "target-version": "py313",
        }
        changed = True
    ruff = tool["ruff"]
    if "lint" not in ruff:
        ruff["lint"] = {"select": ["E", "F", "I", "UP", "B", "SIM", "TCH"]}
        changed = True

    # Ensure [tool.mypy]
    if "mypy" not in tool:
        tool["mypy"] = {
            "python_version": "3.13",
            "strict": True,
            "warn_return_any": True,
            "warn_unused_configs": True,
        }
        changed = True

    # Ensure [tool.pyright]
    if "pyright" not in tool:
        tool["pyright"] = {
            "pythonVersion": "3.13",
            "typeCheckingMode": "strict",
        }
        changed = True

    # Ensure [tool.pytest.ini_options]
    if "pytest" not in tool:
        tool["pytest"] = {"ini_options": {"testpaths": ["tests"]}}
        changed = True
    elif "ini_options" not in tool["pytest"]:
        tool["pytest"]["ini_options"] = {"testpaths": ["tests"]}
        changed = True

    if not changed:
        return []

    new_content = _toml_dump(data)
    if new_content == original:
        return []

    with open(pyproject_path, "wb") as f:
        tomli_w.dump(data, f)

    console.print("  [yellow]↻[/yellow] Updated tool config in pyproject.toml")
    return ["pyproject.toml"]


def _init_beads(info: ProjectInfo) -> list[str]:
    """Initialize beads if not present."""
    if info.has_beads:
        return []

    bd = shutil.which("bd")
    if bd is None:
        console.print("  [yellow]⚠[/yellow] bd not found — skipping beads init")
        return []

    # Derive prefix from directory name
    prefix = info.root.name.replace("-", "").replace("_", "")
    try:
        subprocess.run(
            [bd, "init", "--prefix", prefix],
            cwd=str(info.root),
            check=True,
            capture_output=True,
            text=True,
        )
        console.print(f"  [green]+[/green] Initialized beads (prefix: {prefix})")
        return [".beads/"]
    except subprocess.CalledProcessError as e:
        console.print(f"  [red]✗[/red] beads init failed: {e.stderr.strip()}")
        return []


def _init_claude_md(info: ProjectInfo) -> list[str]:
    """Generate or update CLAUDE.md with standards references."""
    claude_md_path = info.root / "CLAUDE.md"

    # Render the standards references section
    template_ref = TEMPLATES / "claude-md.md.j2"
    template_str = template_ref.read_text(encoding="utf-8")
    env = jinja2.Environment(autoescape=False)
    template = env.from_string(template_str)
    references_block = template.render(
        standards_refs=info.standards_refs,
        display_names=STANDARD_DISPLAY_NAMES,
    ).strip()

    if claude_md_path.exists():
        existing = claude_md_path.read_text(encoding="utf-8")

        # Check if standards references section already exists
        if "## Standards References" in existing:
            return []

        # Append the references section
        updated = existing.rstrip() + "\n\n" + references_block + "\n"
        claude_md_path.write_text(updated, encoding="utf-8")
        console.print("  [yellow]↻[/yellow] Added standards references to CLAUDE.md")
    else:
        claude_md_path.write_text(references_block + "\n", encoding="utf-8")
        console.print("  [green]+[/green] Created CLAUDE.md")

    return ["CLAUDE.md"]


def _report_manual_steps(info: ProjectInfo) -> None:
    """Print steps that require manual action."""
    steps: list[str] = [
        "Enable branch protection on main (require PR, 1 approval, status checks)",
        "Enable GitHub Copilot code review",
        "Enable Dependabot alerts + security updates",
        "Enable secret scanning + push protection",
        "Enable auto-delete head branches",
    ]

    console.print("\n[bold]Manual steps remaining:[/bold]")
    for step in steps:
        console.print(f"  [dim]○[/dim] {step}")
    console.print()


def _relpath(path: Path, root: Path) -> str:
    """Return path relative to root as a string."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _toml_dump(data: dict[str, object]) -> str:
    """Dump TOML data to string for comparison."""
    import io

    buf = io.BytesIO()
    tomli_w.dump(data, buf)
    return buf.getvalue().decode("utf-8")
