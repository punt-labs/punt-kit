"""punt auto — render and merge managed sections in project files.

Uses comment markers to delimit engine-owned sections. Content outside
markers is preserved untouched. Same input + same templates = identical
output (idempotent).
"""

from __future__ import annotations

import functools
import importlib.resources
import json
import re
from pathlib import Path
from typing import cast

import jinja2
from rich.console import Console

from punt_kit.detect import ProjectInfo, detect
from punt_kit.init import (
    STANDARD_DISPLAY_NAMES,
    build_standard_deny_rules,
    build_standard_permissions,
)

console = Console()

TEMPLATES = importlib.resources.files("punt_kit") / "templates" / "auto"

# ---------------------------------------------------------------------------
# Marker patterns by file type
# ---------------------------------------------------------------------------

_MARKERS: dict[str, tuple[str, str]] = {
    "markdown": ("<!-- punt:begin {id} -->", "<!-- punt:end {id} -->"),
    "makefile": ("# punt:begin {id}", "# punt:end {id}"),
}


def _compile_marker_patterns() -> tuple[
    dict[str, re.Pattern[str]], dict[str, re.Pattern[str]]
]:
    """Compile begin/end regex patterns for each file type."""
    begin_re: dict[str, re.Pattern[str]] = {}
    end_re: dict[str, re.Pattern[str]] = {}
    for ft, (begin_tmpl, end_tmpl) in _MARKERS.items():
        b_prefix, b_suffix = begin_tmpl.split("{id}")
        e_prefix, e_suffix = end_tmpl.split("{id}")
        begin_re[ft] = re.compile(rf"^{re.escape(b_prefix)}(\S+){re.escape(b_suffix)}$")
        end_re[ft] = re.compile(rf"^{re.escape(e_prefix)}(\S+){re.escape(e_suffix)}$")
    return begin_re, end_re


_BEGIN_RE, _END_RE = _compile_marker_patterns()


# ---------------------------------------------------------------------------
# Segment: a piece of a file, either managed or local
# ---------------------------------------------------------------------------

type Segment = tuple[str | None, str]
"""(section_id | None, content). None means local/unmanaged content."""


def parse_segments(content: str, file_type: str) -> list[Segment]:
    """Split file content into managed and unmanaged segments.

    Returns a list of ``(id | None, text)`` tuples. Managed segments include
    the marker lines. Unmanaged segments are everything between managed blocks.
    """
    begin_re = _BEGIN_RE[file_type]
    end_re = _END_RE[file_type]

    segments: list[Segment] = []
    lines = content.splitlines()
    local_lines: list[str] = []
    current_id: str | None = None
    managed_lines: list[str] = []

    for line in lines:
        if current_id is None:
            m = begin_re.match(line)
            if m:
                # Flush local content
                if local_lines:
                    segments.append((None, "\n".join(local_lines)))
                    local_lines = []
                current_id = m.group(1)
                managed_lines = [line]
            else:
                local_lines.append(line)
        else:
            managed_lines.append(line)
            m = end_re.match(line)
            if m and m.group(1) == current_id:
                segments.append((current_id, "\n".join(managed_lines)))
                managed_lines = []
                current_id = None

    # Unclosed marker is a structural error — proceeding would duplicate
    # the section on the next run (the unclosed block becomes "local" and
    # a fresh managed copy gets appended).
    if current_id is not None:
        console.print(
            f"[red]Error:[/red] Unclosed marker '{current_id}'"
            " — fix the end marker before running punt auto"
        )
        raise SystemExit(1)
    if local_lines:
        segments.append((None, "\n".join(local_lines)))

    return segments


def merge_file(
    original: str,
    rendered_sections: dict[str, str],
    file_type: str,
) -> str:
    """Merge rendered sections into a file, preserving local content.

    *rendered_sections* maps section IDs to their full rendered content
    (including marker lines). Existing managed sections are replaced;
    new sections are appended after the last existing managed section
    (or at the end if none exist).
    """
    segments = parse_segments(original, file_type)

    # Track which sections we've seen
    seen_ids: set[str] = set()
    result_parts: list[str] = []
    last_managed_result_idx = -1

    for sid, _text in segments:
        if sid is not None:
            seen_ids.add(sid)
            if sid in rendered_sections:
                result_parts.append(rendered_sections[sid])
            else:
                # Section no longer in templates — keep existing
                result_parts.append(_text)
            last_managed_result_idx = len(result_parts) - 1
        elif _text:
            # Skip empty local segments to avoid spurious leading newlines
            result_parts.append(_text)

    # Append new sections not yet in the file.
    # rendered_sections is iterated in insertion order (Python 3.7+);
    # callers must build the dict in the desired section order.
    new_sections = [
        rendered_sections[sid] for sid in rendered_sections if sid not in seen_ids
    ]
    if new_sections:
        if last_managed_result_idx >= 0:
            # Insert after the last managed section in result_parts
            insert_pos = last_managed_result_idx + 1
            for ns in reversed(new_sections):
                result_parts.insert(insert_pos, ns)
        else:
            # No managed sections yet — append at the end
            for ns in new_sections:
                result_parts.append(ns)

    return "\n".join(result_parts)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _jinja_env() -> jinja2.Environment:
    """Cached Jinja2 environment with a loader for auto templates."""

    def _load_template(name: str) -> str | None:
        path = TEMPLATES / name
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    loader = jinja2.FunctionLoader(_load_template)
    return jinja2.Environment(
        loader=loader,
        autoescape=False,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


def render_section(
    section_id: str,
    template_name: str,
    context: dict[str, object],
    file_type: str,
) -> str:
    """Render a managed section with markers.

    Returns the complete section text including begin/end markers.
    """
    begin_tmpl, end_tmpl = _MARKERS[file_type]
    begin_line = begin_tmpl.format(id=section_id)
    end_line = end_tmpl.format(id=section_id)

    try:
        template = _jinja_env().get_template(template_name)
    except jinja2.TemplateNotFound as e:
        console.print(
            f"[red]Error:[/red] Template '{template_name}'"
            " not found — punt-kit may need reinstalling"
        )
        raise SystemExit(1) from e
    try:
        body = template.render(**context).strip()
    except jinja2.TemplateError as e:
        console.print(f"[red]Error:[/red] Template '{template_name}' failed: {e}")
        raise SystemExit(1) from e

    return f"{begin_line}\n{body}\n{end_line}"


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------


def build_context(info: ProjectInfo) -> dict[str, object]:
    """Build template context from ProjectInfo."""
    has_makefile = (info.root / "Makefile").exists()

    if has_makefile:
        quality_gates_command = "make check"
    elif info.language == "python":
        quality_gates_command = (
            "uv run ruff check . && uv run ruff format --check . "
            "&& uv run mypy src/ tests/ && uv run pyright && uv run pytest"
        )
    elif info.language == "node":
        quality_gates_command = "npm run lint && npm test"
    else:
        quality_gates_command = "# No quality gates configured"

    return {
        "project_name": info.root.name,
        "language": info.language,
        "is_plugin": info.is_plugin,
        "has_makefile": has_makefile,
        "quality_gates_command": quality_gates_command,
        "standards_refs": info.standards_refs,
        "display_names": STANDARD_DISPLAY_NAMES,
        "has_prfaq": (info.root / "prfaq.tex").exists(),
        "has_design_md": (info.root / "DESIGN.md").exists(),
        "cli_commands": info.cli_commands,
        "plugin_mcp_servers": info.plugin_mcp_servers,
    }


# ---------------------------------------------------------------------------
# Target definitions: which sections each target manages
# ---------------------------------------------------------------------------

# Each target maps section_id -> template_name (relative to templates/auto/)
CLAUDE_SECTIONS: list[tuple[str, str]] = [
    ("no-preexisting", "claude/no-preexisting.md.j2"),
    ("scratch-files", "claude/scratch-files.md.j2"),
    ("quality-gates", "claude/quality-gates.md.j2"),
    ("code-review", "claude/code-review.md.j2"),
    ("pre-pr-checklist", "claude/pre-pr-checklist.md.j2"),
    ("standards-references", "claude/standards-references.md.j2"),
    ("available-tooling", "claude/available-tooling.md.j2"),
]

MAKEFILE_SECTIONS: list[tuple[str, str]] = [
    ("standard-targets", "makefile/python.mk.j2"),
    ("help", "makefile/help.mk.j2"),
]

TARGETS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "claude": ("markdown", CLAUDE_SECTIONS),
    "makefile": ("makefile", MAKEFILE_SECTIONS),
}


# ---------------------------------------------------------------------------
# JSON structural merge (settings.json)
# ---------------------------------------------------------------------------


def merge_json_permissions(
    existing: dict[str, object],
    info: ProjectInfo,
) -> tuple[dict[str, object], bool]:
    """Merge standard permissions into settings.json structure.

    Returns (merged_dict, changed). Never removes existing entries.
    """
    standard_perms = build_standard_permissions(info)
    standard_deny = build_standard_deny_rules()

    perms_raw = existing.get("permissions")
    if perms_raw is not None and not isinstance(perms_raw, dict):
        console.print(
            f"[red]Error:[/red] permissions is"
            f" {type(perms_raw).__name__}, expected dict"
            " — fix .claude/settings.json manually"
        )
        raise SystemExit(1)
    permissions: dict[str, object] = (
        cast("dict[str, object]", perms_raw) if isinstance(perms_raw, dict) else {}
    )
    existing["permissions"] = permissions

    # Allow list
    allow_raw = permissions.get("allow")
    if allow_raw is not None and not isinstance(allow_raw, list):
        console.print(
            f"[red]Error:[/red] permissions.allow is"
            f" {type(allow_raw).__name__}, expected list"
            " — fix .claude/settings.json manually"
        )
        raise SystemExit(1)
    allow: list[object] = (
        cast("list[object]", allow_raw) if isinstance(allow_raw, list) else []
    )
    permissions["allow"] = allow

    allow_set = {str(x) for x in allow}
    changed = False
    for perm in standard_perms:
        if perm not in allow_set:
            allow.append(perm)
            allow_set.add(perm)
            changed = True

    # Deny list
    deny_raw = permissions.get("deny")
    if deny_raw is not None and not isinstance(deny_raw, list):
        console.print(
            f"[red]Error:[/red] permissions.deny is"
            f" {type(deny_raw).__name__}, expected list"
            " — fix .claude/settings.json manually"
        )
        raise SystemExit(1)
    deny: list[object] = (
        cast("list[object]", deny_raw) if isinstance(deny_raw, list) else []
    )
    permissions["deny"] = deny

    deny_set = {str(x) for x in deny}
    for rule in standard_deny:
        if rule not in deny_set:
            deny.append(rule)
            deny_set.add(rule)
            changed = True

    return existing, changed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_auto(
    path: str,
    *,
    target: str,
    dry_run: bool = False,
) -> list[str]:
    """Render and merge managed sections for a target file type.

    Returns list of files changed (empty if dry_run or no changes).
    """
    root = Path(path).resolve()
    if not root.is_dir():
        console.print(f"[red]Error:[/red] {root} is not a directory")
        raise SystemExit(1)

    info = detect(root)
    ctx = build_context(info)
    changed: list[str] = []

    if target == "settings":
        changed.extend(_auto_settings(info, dry_run=dry_run))
    elif target in TARGETS:
        file_type, sections = TARGETS[target]
        changed.extend(
            _auto_file(info, ctx, target, file_type, sections, dry_run=dry_run)
        )
    else:
        valid = ", ".join([*TARGETS.keys(), "settings"])
        console.print(
            f"[red]Error:[/red] unknown target '{target}' — choose from: {valid}"
        )
        raise SystemExit(1)

    if dry_run:
        console.print("\n[dim]Dry run — no files modified.[/dim]")
    elif changed:
        console.print("\n[bold green]Updated:[/bold green]")
        for f in changed:
            console.print(f"  [green]✓[/green] {f}")
    else:
        console.print("\n[dim]No changes needed.[/dim]")

    return changed


def _auto_file(
    info: ProjectInfo,
    ctx: dict[str, object],
    target: str,
    file_type: str,
    sections: list[tuple[str, str]],
    *,
    dry_run: bool,
) -> list[str]:
    """Render and merge sections for a single file."""
    # Determine target file path
    if target == "claude":
        target_path = info.root / "CLAUDE.md"
    elif target == "makefile":
        target_path = info.root / "Makefile"
    else:
        msg = f"No file path mapping for target '{target}'"
        raise ValueError(msg)

    # Filter sections by relevance
    if target == "makefile" and info.language != "python":
        # Only python makefile templates for now
        console.print(
            "  [yellow]⚠[/yellow] Makefile templates only support Python — skipping"
        )
        return []

    # Read existing or start empty
    original = ""
    if target_path.exists():
        original = target_path.read_text(encoding="utf-8")

    # Render all sections
    rendered: dict[str, str] = {}
    for section_id, template_name in sections:
        rendered[section_id] = render_section(section_id, template_name, ctx, file_type)

    # Merge
    merged = merge_file(original, rendered, file_type)

    # Ensure trailing newline
    if merged and not merged.endswith("\n"):
        merged += "\n"

    if merged == original:
        return []

    if dry_run:
        _print_diff_summary(target_path, info.root, original, merged)
        return []

    target_path.write_text(merged, encoding="utf-8")
    rel = _relpath(target_path, info.root)
    return [rel]


def _auto_settings(
    info: ProjectInfo,
    *,
    dry_run: bool,
) -> list[str]:
    """Merge standard permissions into .claude/settings.json."""
    settings_path = info.root / ".claude" / "settings.json"

    existing: dict[str, object]
    if settings_path.exists():
        rel = _relpath(settings_path, info.root)
        try:
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            console.print(
                f"[red]Error:[/red] {rel} has invalid JSON (line {e.lineno}): {e.msg}"
            )
            raise SystemExit(1) from e
        if not isinstance(raw, dict):
            console.print(
                f"[red]Error:[/red] {rel} root is"
                f" {type(raw).__name__}, expected JSON object"
                " — fix the file manually or delete it"
            )
            raise SystemExit(1)
        else:
            existing = cast("dict[str, object]", raw)
    else:
        existing = {}

    merged, changed = merge_json_permissions(existing, info)

    if not changed:
        return []

    if dry_run:
        rel = _relpath(settings_path, info.root)
        console.print(f"  [yellow]~[/yellow] {rel} would be updated")
        return []

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return [_relpath(settings_path, info.root)]


def _print_diff_summary(
    path: Path,
    root: Path,
    original: str,
    merged: str,
) -> None:
    """Print a summary of changes for dry-run mode."""
    rel = _relpath(path, root)
    if not original:
        console.print(f"  [green]+[/green] Would create {rel}")
    else:
        orig_lines = original.split("\n")
        merged_lines = merged.split("\n")
        added = len(merged_lines) - len(orig_lines)
        if added > 0:
            console.print(f"  [yellow]~[/yellow] {rel} (+{added} lines)")
        elif added < 0:
            console.print(f"  [yellow]~[/yellow] {rel} ({added} lines)")
        else:
            console.print(f"  [yellow]~[/yellow] {rel} (content changed)")


def _relpath(path: Path, root: Path) -> str:
    """Return path relative to root as a string."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
