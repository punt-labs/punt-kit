"""Check STANDARD_SKILL_PERMISSIONS against the installed plugin set.

Skill() rules are enforced — SkillTool honors explicit allow rules — so a
missing entry means that skill prompts the user on every invocation, and a
stale entry names a skill that no longer exists. The list is hand-maintained
Python, so it drifts every time a plugin adds or removes a skill.

This tool can only see plugins installed on the machine running it. That
bounds what it is allowed to conclude:

- A plugin that IS installed is authoritative for its own skills. Entries for
  skills it no longer ships are stale, and missing skills are real gaps.
- A plugin that is NOT installed says nothing. Its entries are left alone,
  because absence from this machine is not evidence about the fleet.
- No plugins installed at all means the tool cannot verify anything, and it
  says so with a non-zero exit rather than reporting success.

That last case is why this is not part of `make check`: CI has no plugins
installed, so a gate there would pass vacuously.

Usage:
    python tools/skills_check.py           # report drift, exit 1 if any
    python tools/skills_check.py --write   # reconcile installed plugins only
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INIT_PY = PROJECT_ROOT / "src" / "punt_kit" / "init.py"
MARKER = "STANDARD_SKILL_PERMISSIONS: tuple[str, ...] = ("
PLUGIN_CACHE = "~/.claude/plugins/cache/punt-labs/*"


def _version_key(path: str) -> tuple[int, ...]:
    """Sort key for a version directory.

    Lexicographic sorting puts 0.9.0 after 0.12.0, which would select an
    outdated plugin and sync the skill list against the wrong version.
    """
    name = os.path.basename(path.rstrip("/"))
    parts: list[int] = []
    for chunk in re.split(r"[.\-+]", name):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


def _plugin_root(version_dir: str) -> str:
    """The directory inside a cache entry that holds .claude-plugin/.

    A ``git-subdir`` marketplace source sparse-checks-out the repo, so the
    cache entry may hold the checkout with the plugin one level down rather
    than the plugin contents directly. Probing both keeps the tool honest
    across the fleet's migration; guessing one would report a plugin as
    shipping zero skills, which reads as "no drift" instead of "not read".
    """
    for candidate in (os.path.join(version_dir, "plugin"), version_dir):
        if os.path.isdir(os.path.join(candidate, ".claude-plugin")):
            return candidate
    return version_dir


def installed_skills() -> dict[str, list[str]]:
    """Map plugin name to its skill names, from the newest installed version."""
    found: dict[str, list[str]] = {}
    for plugin_dir in glob.glob(os.path.expanduser(PLUGIN_CACHE)):
        versions = sorted(glob.glob(plugin_dir + "/*/"), key=_version_key)
        if not versions:
            continue
        root = _plugin_root(versions[-1])
        name = os.path.basename(plugin_dir)
        manifest = os.path.join(root, ".claude-plugin", "plugin.json")
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as fh:
                name = json.load(fh).get("name", name)
        skills: set[str] = set()
        for path in glob.glob(os.path.join(root, "skills", "*", "SKILL.md")):
            skills.add(os.path.basename(os.path.dirname(path)))
        for path in glob.glob(os.path.join(root, "commands", "*.md")):
            skills.add(os.path.basename(path)[:-3])
        if skills:
            found[name] = sorted(skills)
    return found


def seeded_entries() -> list[str]:
    """The Skill() entries currently declared in init.py, in file order."""
    text = INIT_PY.read_text(encoding="utf-8")
    block = text.split(MARKER, 1)[1].split("\n)", 1)[0]
    return re.findall(r'"Skill\(([^)]+)\)"', block)


def render(entries: list[str]) -> str:
    """Render the tuple source, grouped by plugin."""
    grouped: dict[str, list[str]] = {}
    for entry in entries:
        plugin, _, skill = entry.partition(":")
        grouped.setdefault(plugin, []).append(skill)
    lines = [
        MARKER,
        "    # Skill() rules ARE enforced — SkillTool honors explicit allow",
        "    # rules — so a missing entry means that skill prompts on every use.",
        "    # Reconcile against installed plugins with: make skills-check-fix",
    ]
    for plugin in sorted(grouped):
        lines.append(f"    # {plugin}")
        lines.extend(f'    "Skill({plugin}:{s})",' for s in sorted(grouped[plugin]))
    lines.append(")")
    return "\n".join(lines)


def main() -> int:
    found = installed_skills()
    if not found:
        print("cannot verify: no Punt Labs plugins installed on this machine.")
        print("Run where the plugins are installed; CI cannot check this.")
        return 1

    seeded = seeded_entries()
    seeded_set = set(seeded)
    installed_plugins = set(found)
    expected = {f"{p}:{s}" for p, skills in found.items() for s in skills}

    # Only plugins present on this machine can testify about their own skills.
    stale = sorted(
        e
        for e in seeded_set
        if e.split(":")[0] in installed_plugins and e not in expected
    )
    missing = sorted(expected - seeded_set)
    unverifiable = sorted(
        {
            e.split(":")[0]
            for e in seeded_set
            if e.split(":")[0] not in installed_plugins
        }
    )

    if "--write" in sys.argv:
        # Preserve entries for plugins this machine cannot see. Rendering only
        # from the installed set would delete them.
        kept = [e for e in seeded if e.split(":")[0] not in installed_plugins]
        reconciled = sorted(set(kept) | expected)
        text = INIT_PY.read_text(encoding="utf-8")
        start = text.index(MARKER)
        end = text.index("\n)", start) + 2
        INIT_PY.write_text(
            text[:start] + render(reconciled) + text[end:], encoding="utf-8"
        )
        print(f"reconciled {len(installed_plugins)} installed plugins")
        if kept:
            print(f"preserved {len(kept)} entries for plugins not installed here")
        return 0

    for entry in stale:
        print(f"  stale (plugin installed, skill gone): Skill({entry})")
    for entry in missing:
        print(f"  missing (installed, not seeded): Skill({entry})")
    for plugin in unverifiable:
        print(f"  unverifiable (plugin not installed here): {plugin}")

    if stale or missing:
        print(
            f"\n{len(stale)} stale, {len(missing)} missing — run: make skills-check-fix"
        )
        return 1
    print(f"skills in sync: {len(seeded)} entries, {len(installed_plugins)} plugins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
