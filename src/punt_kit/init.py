"""punt init — generate missing config files and report manual steps."""

from __future__ import annotations

import importlib.resources
import json
import shutil
import subprocess
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import cast

import jinja2
import tomli_w
from rich.console import Console

from punt_kit.detect import ProjectInfo, detect
from punt_kit.permission_rules import RuleSet, Tier

console = Console()

TEMPLATES = importlib.resources.files("punt_kit") / "templates"

STANDARD_DISPLAY_NAMES: dict[str, str] = {
    "python": "Python",
    "node": "Node.js",
    "go": "Go",
    "github": "GitHub",
    "workflow": "Workflow",
    "cli": "CLI",
    "plugins": "Plugins",
    "distribution": "Distribution",
    "naming": "Naming",
}


SUPPORTED_LANGUAGES = ("python", "node", "go", "swift")


STANDARD_SKILL_PERMISSIONS: tuple[str, ...] = (
    # Derived from the installed Punt Labs plugin set. Skill() rules ARE
    # enforced — SkillTool honors explicit allow rules — so a missing entry
    # means that skill prompts on every use. Regenerate with:
    #   make skills-check
    # beadle
    "Skill(beadle:beadle)",
    "Skill(beadle:contacts)",
    "Skill(beadle:inbox)",
    "Skill(beadle:mail)",
    "Skill(beadle:send)",
    # biff
    "Skill(biff:biff)",
    "Skill(biff:finger)",
    "Skill(biff:last)",
    "Skill(biff:mesg)",
    "Skill(biff:plan)",
    "Skill(biff:poll)",
    "Skill(biff:read)",
    "Skill(biff:talk)",
    "Skill(biff:tty)",
    "Skill(biff:wall)",
    "Skill(biff:who)",
    "Skill(biff:write)",
    # dungeon
    "Skill(dungeon:d)",
    "Skill(dungeon:dungeon)",
    # ethos
    "Skill(ethos:ext)",
    "Skill(ethos:identity)",
    "Skill(ethos:personality)",
    "Skill(ethos:role)",
    "Skill(ethos:session)",
    "Skill(ethos:talent)",
    "Skill(ethos:team)",
    "Skill(ethos:writing-style)",
    # lux
    "Skill(lux:beads)",
    "Skill(lux:dashboard)",
    "Skill(lux:data-explorer)",
    "Skill(lux:lux)",
    # prfaq
    "Skill(prfaq:badge)",
    "Skill(prfaq:export)",
    "Skill(prfaq:externalize)",
    "Skill(prfaq:feedback)",
    "Skill(prfaq:feedback-to-us)",
    "Skill(prfaq:import)",
    "Skill(prfaq:meeting)",
    "Skill(prfaq:meeting-hive)",
    "Skill(prfaq:meeting-listen)",
    "Skill(prfaq:permissions)",
    "Skill(prfaq:prfaq)",
    "Skill(prfaq:research)",
    "Skill(prfaq:review)",
    "Skill(prfaq:streamline)",
    "Skill(prfaq:vote)",
    # punt
    "Skill(punt:audit)",
    "Skill(punt:auto)",
    "Skill(punt:bead-review)",
    "Skill(punt:bead-review-item)",
    "Skill(punt:init)",
    "Skill(punt:pii)",
    "Skill(punt:reconcile)",
    # quarry
    "Skill(quarry:explain)",
    "Skill(quarry:find)",
    "Skill(quarry:ingest)",
    "Skill(quarry:quarry)",
    "Skill(quarry:remember)",
    "Skill(quarry:source)",
    "Skill(quarry:use)",
    # vox
    "Skill(vox:music)",
    "Skill(vox:mute)",
    "Skill(vox:recap)",
    "Skill(vox:unmute)",
    "Skill(vox:vibe)",
    "Skill(vox:vox)",
    # z-spec
    "Skill(z-spec:audit)",
    "Skill(z-spec:b-animate)",
    "Skill(z-spec:b-check)",
    "Skill(z-spec:b-create)",
    "Skill(z-spec:b-refine)",
    "Skill(z-spec:check)",
    "Skill(z-spec:cleanup)",
    "Skill(z-spec:code2model)",
    "Skill(z-spec:contracts)",
    "Skill(z-spec:disable)",
    "Skill(z-spec:doctor)",
    "Skill(z-spec:elaborate)",
    "Skill(z-spec:enable)",
    "Skill(z-spec:help)",
    "Skill(z-spec:model2code)",
    "Skill(z-spec:oracle)",
    "Skill(z-spec:partition)",
    "Skill(z-spec:prove)",
    "Skill(z-spec:refine)",
    "Skill(z-spec:setup)",
    "Skill(z-spec:test)",
)


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
    changed.extend(_prune_settings_local(info))
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
        if language in ("python", "node", "go"):
            project_type = "package"
        elif language == "swift":
            project_type = "app"

    standards_refs = list(info.standards_refs)
    if language not in standards_refs:
        standards_refs.append(language)
    if language == "python" and "cli" not in standards_refs:
        standards_refs.append("cli")
    if language == "go" and "cli" not in standards_refs:
        standards_refs.append("cli")

    # replace(), not a field-by-field rebuild: this function overrides three
    # fields and must carry the rest through untouched. A rebuild silently
    # drops any field added to ProjectInfo later — a language override would
    # have quietly erased the plugin manifests it never mentioned.
    return replace(
        info,
        language=language,
        project_type=project_type,
        standards_refs=standards_refs,
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
    if info.language == "go":
        return "make check"
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
    # MCP wildcards (§3). Every Punt Labs plugin that ships an MCP server, and
    # nothing else — the set is all-or-nothing rather than a subset someone
    # picked. Each entry is the tool prefix Claude Code derives from the
    # plugin's manifest: mcp__plugin_<plugin>_<server>__*. Verify against a
    # plugin's .claude-plugin/plugin.json "mcpServers" key before editing.
    # github is not a Punt Labs plugin; it ships with Claude Code and is
    # included because this file scaffolds a development environment.
    perms: list[str] = [
        "mcp__github__*",
        "mcp__plugin_beadle_email__*",
        "mcp__plugin_biff_tty__*",
        "mcp__plugin_dungeon_grimoire__*",
        "mcp__plugin_ethos_self__*",
        "mcp__plugin_lux_lux__*",
        "mcp__plugin_quarry_quarry__*",
        "mcp__plugin_vox_mic__*",
        "mcp__plugin_z-spec_zspec__*",
    ]

    # Cross-project file access belongs in settings.local.json with absolute
    # paths per DES-004 rule 3 — not in the portable settings.json.

    # Generic Bash commands required for all projects (§3).
    #
    # Deliberately absent: Bash(bash:*) and Bash(sed:*).
    #
    # Bash(bash:*) permits any command at all — `bash -c "<anything>"` matches
    # it — which makes every other entry here decorative and reaches straight
    # through the deny list in §4. Seeding it granted a scaffolded repo an
    # unrestricted shell in a committed file that nobody reviews.
    #
    # Bash(sed:*) edits any file in place, bypassing the Edit(path) rules that
    # gate file modification.
    #
    # git and gh stay: they are development tools, and this file scaffolds a
    # development environment.
    perms.extend(
        [
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
    elif info.language == "go":
        perms.extend(
            ["Bash(go:*)", "Bash(staticcheck:*)", "Bash(gofmt:*)", "Bash(gofumpt:*)"]
        )
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

    # Plugin skills
    perms.extend(STANDARD_SKILL_PERMISSIONS)

    return perms


def build_standard_deny_rules() -> list[str]:
    """Build the standard deny rules from standards/permissions.md §4.

    Deny rules are identical for all project types — no project info needed.
    Public so that both init and audit can share the same logic.

    Path-scoped rules use ``Edit(path)`` only. Claude Code matches file
    permission rules under ``Read(path)`` and ``Edit(path)``; ``Edit`` covers
    the Write, Edit, MultiEdit, and NotebookEdit tools. A ``Write(path)`` rule
    matches nothing and warns once per session.
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
        "Edit(.envrc)",
        "Bash(direnv allow:*)",
    ]


def _get_plugin_name(info: ProjectInfo) -> str:
    """Extract plugin name from plugin.json for MCP permission patterns."""
    for pj_path in info.plugin_manifests:
        try:
            data = json.loads(pj_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        name = data.get("name")
        if isinstance(name, str):
            return name
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

    # Prune rules Claude Code can never match. Earlier versions of this seeder
    # wrote Write(.env) / Write(.envrc); every repo it touched warns once per
    # session until the entries are gone.
    dead = _prune_dead_rules(permissions)

    if not added and not added_deny and not dead:
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
        if dead:
            parts.append(f"-{len(dead)} dead")
        console.print(f"  [yellow]↻[/yellow] Updated {rel} ({', '.join(parts)})")

    for rule in dead:
        console.print(f"    [dim]dead rule removed:[/dim] {rule}")

    return [rel]


def _prune_dead_rules(permissions: dict[str, object]) -> list[str]:
    """Remove unmatched path rules in place; return what was removed.

    Each tier is pruned independently under its own orphan policy, so the
    result is never more permissive than the input. See
    :class:`~punt_kit.permission_rules.Tier`.
    """
    removed: list[str] = []
    for tier in Tier:
        raw = permissions.get(tier.value)
        if not isinstance(raw, list):
            continue
        entries = cast("list[object]", raw)
        # Rewriting a tier replaces every entry, so a non-string one would be
        # coerced to its repr. Leave malformed tiers untouched.
        if not all(isinstance(x, str) for x in entries):
            continue
        rule_set = RuleSet.from_strings(cast("list[str]", entries))
        if not rule_set.dead:
            continue
        covered = set(rule_set.covered)
        for rule in rule_set.dead:
            if rule in covered:
                removed.append(f"{rule} — {rule.live_equivalent} already covers it")
            else:
                removed.append(
                    f"{rule} — never took effect;"
                    f" add {rule.live_equivalent} to {tier.value} if you meant it"
                )
        # Slice assignment keeps the caller's reference to this list valid.
        entries[:] = cast("list[object]", rule_set.pruned().to_strings())
    return removed


def _prune_settings_local(info: ProjectInfo) -> list[str]:
    """Clean unmatched path rules out of the gitignored local settings file.

    ``settings.local.json`` is machine-specific and never seeded by punt, but
    it is the natural home for the absolute-path rules the standard describes
    (§5) — and so it accumulates the same dead forms by hand. The file is only
    rewritten when there is something dead in it.
    """
    settings_path = info.root / ".claude" / "settings.local.json"
    if not settings_path.exists():
        return []

    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, dict):
        return []

    data = cast("dict[str, object]", raw)
    perms_raw = data.get("permissions")
    if not isinstance(perms_raw, dict):
        return []

    removed = _prune_dead_rules(cast("dict[str, object]", perms_raw))
    if not removed:
        return []

    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    rel = _relpath(settings_path, info.root)
    console.print(f"  [yellow]↻[/yellow] Updated {rel} (-{len(removed)} dead)")
    for rule in removed:
        console.print(f"    [dim]dead rule removed:[/dim] {rule}")
    return [rel]


_CLAUDE_GITIGNORE_LINES = [
    ".claude/",
    "!.claude/settings.json",
    "!.claude/hooks/",
]


def _names_claude_dir(pattern: str) -> bool:
    """True when a gitignore pattern names the ``.claude`` directory.

    Matches every spelling git accepts — ``.claude/``, ``.claude/*``,
    ``/.claude/`` (root-anchored), ``**/.claude/*`` — by testing path
    segments rather than the leading characters. An anchored form reaching
    the "no reference" branch would get the unanchored block appended, which
    broadens the ignore from root-only to any depth.
    """
    stripped = pattern.strip().lstrip("!")
    if not stripped or stripped.startswith("#"):
        return False
    return ".claude" in stripped.split("/")


def _init_gitignore_claude(info: ProjectInfo) -> list[str]:
    """Ensure .gitignore has the .claude/ pattern with settings.json exception.

    The exception lines are only meaningful under the exact ``.claude/`` parent
    this function writes. Under a different parent — ``.claude/*``, say — git
    descends into the directory and the same negations become live rules that
    re-include paths the repo has never tracked. So a stanza punt did not write
    is left alone: seeding must not change what a repo currently ignores.
    """
    gitignore_path = info.root / ".gitignore"

    existing = ""
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")

    lines = existing.split("\n")
    stripped = [line.strip() for line in lines]

    missing = [line for line in _CLAUDE_GITIGNORE_LINES if line not in stripped]
    if not missing:
        return []

    rel = _relpath(gitignore_path, info.root)
    anchor = _CLAUDE_GITIGNORE_LINES[0]

    if anchor in stripped:
        # The parent is the form punt wrote, so the negations behave as intended.
        insert_idx = stripped.index(anchor) + 1
        for entry in missing:
            lines.insert(insert_idx, entry)
            insert_idx += 1
        updated = "\n".join(lines)
    elif any(_names_claude_dir(s) for s in stripped):
        # A deliberate stanza this function did not write. Appending to it can
        # activate rules that have never been in effect, or broaden an anchored
        # pattern, so report and leave the file untouched. Only the exceptions
        # are suggested — recommending the `.claude/` anchor to a repo that
        # deliberately chose a different parent would contradict its own stanza.
        suggestions = [entry for entry in missing if entry.startswith("!")]
        detail = (
            " Add these by hand if you want them: " + ", ".join(suggestions)
            if suggestions
            else ""
        )
        console.print(
            f"  [yellow]![/yellow] {rel} has its own .claude stanza — left as is."
            f"{detail}"
        )
        return []
    else:
        block = "\n".join(_CLAUDE_GITIGNORE_LINES)
        separator = "\n" if existing and not existing.endswith("\n") else ""
        extra_newline = "\n" if existing else ""
        updated = existing + separator + extra_newline + block + "\n"

    gitignore_path.write_text(updated, encoding="utf-8")
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
