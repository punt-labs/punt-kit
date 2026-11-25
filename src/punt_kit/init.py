"""punt repo init — generate missing config files and report manual steps."""

from __future__ import annotations

import importlib.resources
import logging
import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

import jinja2
from rich.console import Console
from rich.markup import escape

from punt_kit.claude_markers import ClaudeMarkers
from punt_kit.detect import ProjectInfo, detect
from punt_kit.errors import CommandFailure, ReleaseError
from punt_kit.init_beads import BeadsInit, BeadsInitError
from punt_kit.permission_rules import RuleSet, Tier
from punt_kit.phases.shared.json_file import JsonFile
from punt_kit.phases.shared.text_file import TextFile
from punt_kit.tool_config import ToolConfigPatch

console = Console()
logger = logging.getLogger(__name__)

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

# The per-language build tools standards/permissions.md §3 adds to the baseline.
LANGUAGE_TOOLS: dict[str, tuple[str, ...]] = {
    "python": ("Bash(uv:*)", "Bash(uvx:*)", "Bash(python3:*)"),
    "node": ("Bash(npx:*)", "Bash(npm:*)"),
    "go": ("Bash(go:*)", "Bash(staticcheck:*)", "Bash(gofmt:*)", "Bash(gofumpt:*)"),
    "swift": (
        "Bash(swiftformat:*)",
        "Bash(swiftlint:*)",
        "Bash(xcodebuild:*)",
        "Bash(xcodegen:*)",
    ),
}


def run_init(path: str, *, language: str | None = None) -> list[str]:
    """Detect project type, generate/update missing files, report manual steps.

    *language* overrides auto-detection; an empty string detects without
    prompting. The default, None, allows a prompt on an interactive terminal.
    No file is ever rewritten from a guess at what it held.

    Raises:
        SystemExit: Exit code 1 for a non-directory path, unsupported language,
            unreadable input file, or beads initialization failure.
    """
    try:
        return _init_project(path, language=language)
    except ReleaseError as exc:
        logger.info("Project initialization rejected a project or its input")
        console.print(f"[red]Error:[/red] {escape(str(exc))}")
        raise CommandFailure(str(exc)) from exc


def _init_project(path: str, *, language: str | None) -> list[str]:
    """Run every init step against the project at *path*."""
    root = Path(path).resolve()
    if not root.is_dir():
        raise ReleaseError(f"{root} is not a directory")

    info = detect(root)

    if language:
        if language not in SUPPORTED_LANGUAGES:
            raise ReleaseError(
                f"unsupported language '{language}'"
                f" — choose from: {', '.join(SUPPORTED_LANGUAGES)}"
            )
        info = _with_language(info, language)
    elif info.language is None and language is None:
        prompted = _prompt_language()
        if prompted is not None:
            info = _with_language(info, prompted)

    console.print(
        f"\n[bold]punt repo init[/bold] — {escape(root.name)}\n"
        f"  Language:     {info.language or 'none'}\n"
        f"  Project type: {info.project_type or 'unknown'}\n"
        f"  MCP server:   {info.is_mcp_server}\n"
        f"  Plugin:       {info.is_plugin}\n"
        f"  CI exists:    {info.has_ci}\n"
        f"  CLAUDE.md:    {info.has_claude_md}\n"
        f"  Beads:        {info.has_beads}\n"
    )

    # Read every file init will merge into BEFORE writing any, so a file it
    # cannot read fails the run with nothing half-initialised.
    _validate_inputs(info)

    changed = _init_workflows(info)
    changed.extend(_init_python_config(info))
    beads_failure = _init_beads(info, changed)
    changed.extend(_init_claude_md(info))
    changed.extend(_init_permissions(info))
    changed.extend(_prune_settings_local(info))
    changed.extend(_init_gitignore_claude(info))
    changed.extend(rel for rel in _init_gitignore_locks(info) if rel not in changed)

    if changed:
        logger.info("Project initialization updated files count=%d", len(changed))
        console.print("\n[bold green]Files generated/updated:[/bold green]")
        for f in changed:
            console.print(f"  [green]✓[/green] {f}")
    else:
        logger.info("Project initialization found no files needing updates")
        console.print("\n[dim]No files needed updating.[/dim]")

    _report_manual_steps()
    if beads_failure is not None:
        # Printed when it happened; run_init would only print it a second time.
        raise CommandFailure(
            str(beads_failure), {"changes": changed}
        ) from beads_failure
    return changed


def _init_beads(info: ProjectInfo, changed: list[str]) -> BeadsInitError | None:
    """Run the beads step; return its failure so the other steps still run.

    ``None`` is the documented success: the failure ends the run only after
    every other step has been given its turn. It is shown now, so a later
    step that raises cannot hide it.
    """
    try:
        changed.extend(BeadsInit(info).run())
    except BeadsInitError as exc:
        console.print(f"[red]Error:[/red] {escape(str(exc))}")
        return exc
    return None


def _validate_inputs(info: ProjectInfo) -> None:
    """Raise :class:`ReleaseError` if a file init will read or merge is unreadable."""
    root = info.root
    settings = root / ".claude" / "settings.json"
    if settings.exists():
        JsonFile(settings).load_object()
    # A plugin manifest init cannot parse is a repo it must not scaffold: the
    # release and the audit read that file, and a half-initialised repo around
    # a broken manifest is worse than no files at all.
    for manifest in info.plugin_manifests:
        JsonFile(manifest).load_object()
    workflows_dir = root / ".github" / "workflows"
    merged = (
        workflows_dir / target
        for _template, target in _workflow_targets(
            info, with_release=info.language == "python"
        )
    )
    for path in (*merged, root / "CLAUDE.md", root / ".gitignore"):
        if path.exists():
            TextFile(path).read()


def _prompt_language() -> str | None:
    """Prompt the user to choose a language only on an interactive terminal."""
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        return None

    prompt = Console(stderr=True)
    prompt.print(
        "[yellow]No language detected.[/yellow] Choose one (or press Enter to skip):"
    )
    menu = dict(enumerate(SUPPORTED_LANGUAGES, 1))
    for i, lang in menu.items():
        prompt.print(f"  {i}. {lang}")

    prompt.print("> ", end="")
    try:
        choice = input().strip()
    except EOFError:
        return None

    if not choice:
        return None

    if choice in SUPPORTED_LANGUAGES:
        return choice

    try:
        return menu[int(choice)]
    except (ValueError, KeyError):
        prompt.print(f"[red]Invalid choice:[/red] '{escape(choice)}'")
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
    if language in {"python", "go"} and "cli" not in standards_refs:
        standards_refs.append("cli")

    # replace(), not a field-by-field rebuild: this function overrides three
    # fields and must carry every other field through untouched, including
    # any field ProjectInfo gains.
    return replace(
        info,
        language=language,
        project_type=project_type,
        standards_refs=standards_refs,
    )


def _workflow_targets(
    info: ProjectInfo, *, with_release: bool
) -> list[tuple[str, str]]:
    """Return the ``(template, target file)`` pairs init may write under workflows/.

    One list for the merge and for the validation that precedes it, so init
    reads exactly the files it may touch and no others. Release needs package
    metadata, so the caller says whether it has it.
    """
    pairs: list[tuple[str, str]] = []
    if info.language == "python":
        pairs.append(("lint-python.yml", "lint.yml"))
        pairs.append(("test-python.yml", "test.yml"))
    elif info.language == "node":
        pairs.append(("lint-node.yml", "lint.yml"))
    if with_release:
        pairs.append(("release-python.yml.j2", "release.yml"))
    pairs.append(("docs.yml", "docs.yml"))
    return pairs


def _init_workflows(info: ProjectInfo) -> list[str]:
    """Generate CI workflow files based on project type."""
    changed: list[str] = []
    workflows_dir = info.root / ".github" / "workflows"

    if info.language == "python":
        template_vars = _get_template_vars(info)
        has_release = "package_name" in template_vars and "cli_command" in template_vars
        if not has_release:
            missing = [
                k for k in ("package_name", "cli_command") if k not in template_vars
            ]
            console.print(
                f"  [yellow]⚠[/yellow] Skipping release.yml — "
                f"missing {', '.join(missing)} in pyproject.toml"
            )
    else:
        template_vars = {}
        has_release = False

    templates_to_install = _workflow_targets(info, with_release=has_release)

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
            existing = TextFile(target_path).read()
            if existing == rendered:
                continue
            rel = _relpath(target_path, info.root)
            console.print(
                f"  [yellow]⚠[/yellow] {rel} differs from template"
                " — use [bold]/punt:reconcile[/bold] to review"
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
    """Ensure standard tool configs exist in pyproject.toml.

    Missing tables are appended to the file as written: nothing already in it
    is re-serialized, so comments, line endings and a BOM survive. When the
    tables cannot be appended safely the file is left alone and the tables to
    add by hand are printed.
    """
    if info.language != "python":
        return []

    pyproject_path = info.root / "pyproject.toml"
    if not pyproject_path.exists():
        return []

    pyproject = TextFile(pyproject_path)
    text = pyproject.read()
    data = TextFile.parse_toml(text, source=str(pyproject_path))
    patch = ToolConfigPatch(data)
    if patch.is_empty:
        return []

    updated = patch.appended_to(text, data)
    if updated is None:
        console.print(
            "  [yellow]![/yellow] pyproject.toml left as is: the tool tables cannot"
            " be added without rewriting it. Add these tables by hand:"
        )
        console.print(escape(patch.fragment()), highlight=False)
        return []

    pyproject.write(updated)
    console.print("  [yellow]↻[/yellow] Updated tool config in pyproject.toml")
    return ["pyproject.toml"]


def _build_quality_gates(info: ProjectInfo) -> str:
    """Build the quality gates command string for the project type."""
    if info.language == "python":
        return (
            "uv run ruff check . && uv run ruff format --check . "
            "&& uv run mypy src/ tests/ && uv run pyright src/ tests/ && uv run pytest"
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

    template_ref = TEMPLATES / "claude-md.md.j2"
    template_str = template_ref.read_text(encoding="utf-8")
    env = jinja2.Environment(autoescape=False)
    template = env.from_string(template_str)
    references_block = template.render(
        standards_refs=info.standards_refs,
        display_names=STANDARD_DISPLAY_NAMES,
        quality_gates=_build_quality_gates(info),
    ).strip()

    return ClaudeMarkers(TextFile(claude_md_path)).update(references_block)


def build_standard_permissions(info: ProjectInfo) -> list[str]:
    """Build the baseline permission list for a detected project type.

    The baseline is what standards/permissions.md §3 says no tool's ``enable``
    owns: the github MCP wildcard, the generic Bash commands, the language
    tools, and ``Bash(<name>-server:*)`` for each declared entry point whose
    name ends in ``-server`` (nothing for a CLI without one). A permission value
    lives in exactly one place, so every plugin MCP wildcard
    (``mcp__plugin_<plugin>_<server>__*``), every ``Skill(<plugin>:<cmd>)``
    rule, and a tool's own ``Bash(<cli>:*)`` are granted by that tool's
    ``enable`` and removed by its ``disable``; seeding them here would make
    ``disable`` strip a baseline value, or leave the seeded copy behind.
    Public so that both init and audit can share the same logic.

    Raises:
        KeyError: ``info.language`` has no entry in ``LANGUAGE_TOOLS``.
    """
    # github is not a Punt Labs plugin: it ships with Claude Code, no enable
    # owns it, and these settings scaffold a development environment.
    perms: list[str] = ["mcp__github__*"]

    # A bash wildcard bypasses the command deny list; a sed wildcard bypasses
    # path restrictions on edits. Keep both out of committed permissions.
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

    # Language-specific tools (§3); a project with no language gets none. A
    # language outside the table is a bug in this module, so it raises rather
    # than silently seeding a project with no tools.
    perms.extend(() if info.language is None else LANGUAGE_TOOLS[info.language])

    # A CLI project's own `Bash(<cli>:*)` reaches its repo the way it reaches
    # every repo, through `<tool> enable`; only a server binary, which no
    # enable grants, is baseline. The rule names a declared `<name>-server`
    # entry point as-is; nothing is synthesized for a CLI that ships none.
    for cmd in info.cli_commands:
        if not cmd.endswith("-server"):
            continue
        perm = f"Bash({cmd}:*)"
        if perm not in perms:
            perms.append(perm)

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
        # Commands that print environment variable values. Principle: deny the
        # bare command and every flag form, because flags combine and reorder
        # (`export -np`, `export -n -p`, `declare -x`) and cannot be enumerated.
        # Flag rules are written `cmd -*` with no space before `*`: Claude Code
        # reads `:*` as a space-star, so `cmd -:*` means `cmd - *` and misses
        # attached flags such as `export -p`. Plain assignment stays allowed:
        # `export VAR=value` does not start with `export -`. `env` is denied
        # entirely; set a variable for one command with `VAR='value' command`.
        "Bash(env)",
        "Bash(env:*)",
        "Bash(printenv)",
        "Bash(printenv:*)",
        "Bash(set)",
        "Bash(export)",
        "Bash(export -*)",
        "Bash(declare)",
        "Bash(declare -*)",
        "Bash(typeset)",
        "Bash(typeset -*)",
        # Secrets and environment
        "Edit(.env)",
        "Edit(.envrc)",
        "Bash(direnv allow:*)",
    ]


def _init_permissions(info: ProjectInfo) -> list[str]:
    """Generate or merge .claude/settings.json with standard permissions."""
    settings_path = info.root / ".claude" / "settings.json"
    standard_perms = build_standard_permissions(info)

    # An unreadable settings.json raises: starting from {} would write back
    # permissions only, destroying the user's hooks, env, and every other key.
    settings = JsonFile(settings_path)
    existing: dict[str, object] = (
        settings.load_object() if settings_path.exists() else {}
    )

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

    # Prune rules Claude Code can never match, such as Write(.env) and
    # Write(.envrc): each one warns once per session until it is gone.
    dead = _prune_dead_rules(permissions)

    if not added and not added_deny and not dead:
        return []

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings.save(existing)

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
        console.print(f"    [dim]dead rule removed:[/dim] {escape(rule)}")

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

    local = JsonFile(settings_path)
    rel = _relpath(settings_path, info.root)
    try:
        data = local.load_object()
    except ReleaseError as exc:
        # A personal, gitignored file: init does not fail over it, but it does
        # not pretend the file was clean either.
        console.print(
            f"  [yellow]![/yellow] {escape(str(exc))} — {rel} left as is, dead rules"
            " in it are not pruned"
        )
        return []
    perms_raw = data.get("permissions")
    if not isinstance(perms_raw, dict):
        return []

    removed = _prune_dead_rules(cast("dict[str, object]", perms_raw))
    if not removed:
        return []

    local.save(data)

    console.print(f"  [yellow]↻[/yellow] Updated {rel} (-{len(removed)} dead)")
    for rule in removed:
        console.print(f"    [dim]dead rule removed:[/dim] {escape(rule)}")
    return [rel]


# Every punt CLI's enable/disable serializes on a sibling lock such as
# ``.CLAUDE.md.punt-import.lock``, left in place so all tools share one inode.
_LOCK_GITIGNORE_LINE = "*.punt-import.lock"

_CLAUDE_GITIGNORE_LINES = [
    ".claude/",
    "!.claude/settings.json",
    "!.claude/hooks/",
]


def _names_claude_dir(pattern: str) -> bool:
    """Return True when a gitignore pattern names the ``.claude`` directory.

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
        existing = TextFile(gitignore_path).read()

    eol = TextFile.line_ending(existing)
    lines = existing.split(eol)
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
        updated = eol.join(lines)
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
        block = eol.join(_CLAUDE_GITIGNORE_LINES)
        separator = eol if existing and not existing.endswith("\n") else ""
        extra_newline = eol if existing else ""
        updated = existing + separator + extra_newline + block + eol

    TextFile(gitignore_path).write(updated)
    console.print(f"  [yellow]↻[/yellow] Updated {rel} (.claude/ exceptions)")
    return [rel]


def _init_gitignore_locks(info: ProjectInfo) -> list[str]:
    """Ensure .gitignore ignores the enable/disable sibling lock files.

    Without it the root ``.CLAUDE.md.punt-import.lock`` dirties the tree after
    any tool's ``enable``, and the release clean-tree check refuses to run.
    Re-running ``punt repo init`` adds the line to an already-initialized repo.
    """
    gitignore_path = info.root / ".gitignore"
    existing = TextFile(gitignore_path).read() if gitignore_path.exists() else ""
    eol = TextFile.line_ending(existing)
    if _LOCK_GITIGNORE_LINE in (line.strip() for line in existing.split(eol)):
        return []
    separator = eol if existing and not existing.endswith("\n") else ""
    TextFile(gitignore_path).write(existing + separator + _LOCK_GITIGNORE_LINE + eol)
    rel = _relpath(gitignore_path, info.root)
    console.print(f"  [yellow]↻[/yellow] Updated {rel} ({_LOCK_GITIGNORE_LINE})")
    return [rel]


def _report_manual_steps() -> None:
    """Print steps that require manual action."""
    steps: list[str] = [
        "Create branch protection ruleset on main"
        " (require PR, 0 approvals, status checks,"
        " conversation resolution, zero bypass actors)",
        f"Copy {escape(str(TEMPLATES / 'pr_agent.toml'))} to .pr_agent.toml,"
        " fill its placeholders, and merge it to main;"
        " set Qodo 'Review every push' to Disable and Bugbot to"
        " review each PR once (Cursor dashboard);"
        " do not add a copilot_code_review ruleset rule",
        "Enable Dependabot alerts + security updates",
        "Enable secret scanning + push protection",
        "Enable auto-delete head branches",
    ]

    console.print("\n[bold]Manual steps remaining:[/bold]")
    for step in steps:
        # soft_wrap keeps the template path in one piece for copy and paste
        console.print(f"  [dim]○[/dim] {step}", soft_wrap=True)
    console.print()


def _relpath(path: Path, root: Path) -> str:
    """Return path relative to root as a string."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
