"""punt init — generate missing config files and report manual steps."""

from __future__ import annotations

import importlib.resources
import json
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


SUPPORTED_LANGUAGES = ("python", "node", "swift")


def run_init(path: str, *, language: str | None = None) -> None:
    """Detect project type, generate/update missing files, report manual steps.

    *language* overrides auto-detection. When detection returns no language
    and no override is given, prompts interactively (if stdin is a tty).
    """
    root = Path(path).resolve()
    if not root.is_dir():
        console.print(f"[red]Error:[/red] {root} is not a directory")
        raise SystemExit(1)

    info = detect(root)

    # Apply language override or prompt when detection fails
    if language is not None:
        if language not in SUPPORTED_LANGUAGES:
            console.print(
                f"[red]Error:[/red] unsupported language '{language}'"
                f" — choose from: {', '.join(SUPPORTED_LANGUAGES)}"
            )
            raise SystemExit(1)
        info = _with_language(info, language)
    elif info.language is None:
        prompted = _prompt_language()
        if prompted is not None:
            info = _with_language(info, prompted)

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
    changed.extend(_init_permissions(info))
    changed.extend(_init_gitignore_claude(info))

    if changed:
        console.print("\n[bold green]Files generated/updated:[/bold green]")
        for f in changed:
            console.print(f"  [green]✓[/green] {f}")
    else:
        console.print("\n[dim]No files needed updating.[/dim]")

    _report_manual_steps(info)


def _prompt_language() -> str | None:
    """Prompt the user to choose a language if stdin is a tty."""
    import sys

    if not sys.stdin.isatty():
        return None

    console.print(
        "[yellow]No language detected.[/yellow] Choose one (or press Enter to skip):"
    )
    for i, lang in enumerate(SUPPORTED_LANGUAGES, 1):
        console.print(f"  {i}. {lang}")

    try:
        choice = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if not choice:
        return None

    if choice in SUPPORTED_LANGUAGES:
        return choice

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(SUPPORTED_LANGUAGES):
            return SUPPORTED_LANGUAGES[idx]
    except ValueError:
        pass

    console.print(f"[red]Invalid choice:[/red] '{choice}'")
    return None


def _with_language(info: ProjectInfo, language: str) -> ProjectInfo:
    """Return a new ProjectInfo with the language and project_type set."""
    project_type = info.project_type
    if project_type is None:
        if language in ("python", "node"):
            project_type = "package"
        elif language == "swift":
            project_type = "app"

    standards_refs = list(info.standards_refs)
    if language not in standards_refs:
        standards_refs.append(language)
    if language == "python" and "cli" not in standards_refs:
        standards_refs.append("cli")

    return ProjectInfo(
        root=info.root,
        language=language,
        project_type=project_type,
        has_ci=info.has_ci,
        has_claude_md=info.has_claude_md,
        has_beads=info.has_beads,
        is_mcp_server=info.is_mcp_server,
        is_plugin=info.is_plugin,
        pyproject=info.pyproject,
        package_json=info.package_json,
        workflow_files=info.workflow_files,
        standards_refs=standards_refs,
        cli_commands=info.cli_commands,
        plugin_mcp_servers=info.plugin_mcp_servers,
    )


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
            console.print(
                f"  [yellow]⚠[/yellow] {rel} differs from template"
                " — use [bold]/punt reconcile[/bold] to review"
            )
            continue
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


def _build_quality_gates(info: ProjectInfo) -> str:
    """Build the quality gates command string for the project type."""
    if info.language == "python":
        return (
            "uv run ruff check . && uv run ruff format --check . "
            "&& uv run mypy src/ tests/ && uv run pyright && uv run pytest"
        )
    if info.language == "swift":
        return "make format && make lint && make test"
    if info.language == "node":
        return "npm run lint && npm test"
    return "# No language-specific quality gates"


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
        quality_gates=_build_quality_gates(info),
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


def build_standard_permissions(info: ProjectInfo) -> list[str]:
    """Build the standard permission list for a detected project type.

    Includes all required rules from standards/permissions.md §3:
    MCP wildcards, generic Bash commands, and language-specific tools.
    Public so that both init and audit can share the same logic.
    """
    # MCP plugin wildcards (§3)
    perms: list[str] = [
        "mcp__plugin_biff_tty__*",
        "mcp__plugin_github_github__*",
        "mcp__plugin_quarry_quarry__*",
        "mcp__github__*",
        "mcp__quarry__*",
    ]

    # Cross-project file access belongs in settings.local.json with absolute
    # paths per DES-004 rule 3 — not in the portable settings.json.

    # Generic Bash commands required for all projects (§3)
    perms.extend(
        [
            "Bash(bash:*)",
            "Bash(bd:*)",
            "Bash(cat:*)",
            "Bash(chmod +x:*)",
            "Bash(claude mcp:*)",
            "Bash(claude plugin:*)",
            "Bash(export:*)",
            "Bash(find:*)",
            "Bash(gh:*)",
            "Bash(git:*)",
            "Bash(ls:*)",
            "Bash(make:*)",
            "Bash(pip index:*)",
            "Bash(punt:*)",
            "Bash(sed:*)",
            "Bash(shellcheck:*)",
            "Bash(tail:*)",
            "Bash(test:*)",
        ]
    )

    # Language-specific tools (§3)
    if info.language == "python":
        perms.extend(["Bash(uv:*)", "Bash(uvx:*)", "Bash(python3:*)"])
    elif info.language == "node":
        perms.extend(["Bash(npx:*)", "Bash(npm:*)"])
    elif info.language == "swift":
        perms.extend(
            [
                "Bash(swiftformat:*)",
                "Bash(swiftlint:*)",
                "Bash(xcodebuild:*)",
                "Bash(xcodegen:*)",
            ]
        )

    for cmd in info.cli_commands:
        perm = f"Bash({cmd}:*)"
        if perm not in perms:
            perms.append(perm)

    # Plugin MCP server permissions
    plugin_name = _get_plugin_name(info)
    for server in info.plugin_mcp_servers:
        perms.append(f"mcp__plugin_{plugin_name}_{server}__*")

    return perms


def build_standard_deny_rules() -> list[str]:
    """Build the standard deny rules from standards/permissions.md §4.

    Deny rules are identical for all project types — no project info needed.
    Public so that both init and audit can share the same logic.
    """
    return [
        # Destructive operations
        "Bash(rm -rf /:*)",
        "Bash(rm -rf ~:*)",
        "Bash(dd:*)",
        # Privilege escalation
        "Bash(sudo:*)",
        "Bash(su:*)",
        # Network access
        "Bash(curl:*)",
        "Bash(wget:*)",
        "Bash(ssh:*)",
        "Bash(scp:*)",
        "Bash(ftp:*)",
        "Bash(tftp:*)",
        "Bash(nc:*)",
        "Bash(netcat:*)",
        "Bash(ncat:*)",
        "Bash(telnet:*)",
        "Bash(socat:*)",
        # Secrets and environment
        "Edit(.env)",
        "Write(.env)",
        "Edit(.envrc)",
        "Write(.envrc)",
        "Bash(direnv allow:*)",
    ]


def _get_plugin_name(info: ProjectInfo) -> str:
    """Extract plugin name from plugin.json for MCP permission patterns."""
    for pj_path in (
        info.root / ".claude-plugin" / "plugin.json",
        info.root / "plugin.json",
    ):
        if pj_path.exists():
            try:
                data = json.loads(pj_path.read_text(encoding="utf-8"))
                name = data.get("name")
                if isinstance(name, str):
                    return name
            except (json.JSONDecodeError, OSError):
                pass
    return info.root.name


def _init_permissions(info: ProjectInfo) -> list[str]:
    """Generate or merge .claude/settings.json with standard permissions."""
    settings_path = info.root / ".claude" / "settings.json"
    standard_perms = build_standard_permissions(info)

    existing: dict[str, object]
    if settings_path.exists():
        try:
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            existing = cast("dict[str, object]", raw) if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError):
            existing = {}
    else:
        existing = {}

    perms_raw = existing.get("permissions")
    permissions: dict[str, object] = (
        cast("dict[str, object]", perms_raw) if isinstance(perms_raw, dict) else {}
    )
    existing["permissions"] = permissions

    allow_raw = permissions.get("allow")
    allow: list[object] = (
        cast("list[object]", allow_raw) if isinstance(allow_raw, list) else []
    )
    permissions["allow"] = allow

    # Merge allow: add missing permissions, never remove existing
    allow_strs = [str(x) for x in allow]
    added: list[str] = []
    for perm in standard_perms:
        if perm not in allow_strs:
            allow.append(perm)
            added.append(perm)

    # Merge deny: add missing deny rules, never remove existing
    standard_deny = build_standard_deny_rules()
    deny_raw = permissions.get("deny")
    deny: list[object] = (
        cast("list[object]", deny_raw) if isinstance(deny_raw, list) else []
    )
    permissions["deny"] = deny

    deny_strs = [str(x) for x in deny]
    added_deny: list[str] = []
    for rule in standard_deny:
        if rule not in deny_strs:
            deny.append(rule)
            added_deny.append(rule)

    if not added and not added_deny:
        return []

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    rel = _relpath(settings_path, info.root)
    is_new = len(added) == len(allow) and len(added_deny) == len(deny)
    if is_new:
        console.print(
            f"  [green]+[/green] Created {rel}"
            f" ({len(added)} allow, {len(added_deny)} deny)"
        )
    else:
        parts: list[str] = []
        if added:
            parts.append(f"+{len(added)} allow")
        if added_deny:
            parts.append(f"+{len(added_deny)} deny")
        console.print(f"  [yellow]↻[/yellow] Updated {rel} ({', '.join(parts)})")

    return [rel]


_CLAUDE_GITIGNORE_LINES = [
    ".claude/",
    "!.claude/settings.json",
    "!.claude/hooks/",
]


def _init_gitignore_claude(info: ProjectInfo) -> list[str]:
    """Ensure .gitignore has the .claude/ pattern with settings.json exception."""
    gitignore_path = info.root / ".gitignore"

    existing = ""
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")

    # Check if the pattern is already present (all three lines)
    if all(line in existing for line in _CLAUDE_GITIGNORE_LINES):
        return []

    # Find which lines are missing
    missing = [line for line in _CLAUDE_GITIGNORE_LINES if line not in existing]
    if not missing:
        return []

    # Append the full block if the anchor line (.claude/) is missing,
    # otherwise just append the missing exception lines
    block = "\n".join(_CLAUDE_GITIGNORE_LINES)
    if ".claude/" not in existing:
        # Append the full block
        separator = "\n" if existing and not existing.endswith("\n") else ""
        extra_newline = "\n" if existing else ""
        updated = existing + separator + extra_newline + block + "\n"
    else:
        # .claude/ exists but exceptions are missing — append them after .claude/ line
        lines = existing.split("\n")
        insert_idx = None
        for i, line in enumerate(lines):
            if line.strip() == ".claude/":
                insert_idx = i + 1
                break
        if insert_idx is not None:
            for m in missing:
                lines.insert(insert_idx, m)
                insert_idx += 1
            updated = "\n".join(lines)
        else:
            separator = "\n" if existing and not existing.endswith("\n") else ""
            updated = existing + separator + "\n".join(missing) + "\n"

    gitignore_path.write_text(updated, encoding="utf-8")

    rel = _relpath(gitignore_path, info.root)
    console.print(f"  [yellow]↻[/yellow] Updated {rel} (.claude/ exceptions)")
    return [rel]


def _report_manual_steps(info: ProjectInfo) -> None:
    """Print steps that require manual action."""
    steps: list[str] = [
        "Create branch protection ruleset on main"
        " (require PR, 0 approvals, status checks,"
        " conversation resolution, zero bypass actors)",
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
