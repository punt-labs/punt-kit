"""Check STANDARD_SKILL_PERMISSIONS against the installed plugin set.

Skill() rules are enforced — SkillTool honors explicit allow rules — so a
missing entry means that skill prompts the user on every invocation, and a
stale entry names a skill that no longer exists. The list is hand-maintained
Python, so it drifts silently every time a plugin adds or removes a skill.
This makes the drift visible.

Usage:
    python tools/skills_check.py           # report drift, exit 1 if any
    python tools/skills_check.py --write   # rewrite the tuple in place
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


def installed_skills() -> dict[str, list[str]]:
    """Map plugin name to its skill names, from the installed plugin set."""
    found: dict[str, list[str]] = {}
    for plugin_dir in glob.glob(os.path.expanduser(PLUGIN_CACHE)):
        versions = sorted(glob.glob(plugin_dir + "/*/"))
        if not versions:
            continue
        latest = versions[-1]
        name = os.path.basename(plugin_dir)
        manifest = os.path.join(latest, ".claude-plugin", "plugin.json")
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as fh:
                name = json.load(fh).get("name", name)
        skills: set[str] = set()
        for path in glob.glob(latest + "skills/*/SKILL.md"):
            skills.add(os.path.basename(os.path.dirname(path)))
        for path in glob.glob(latest + "commands/*.md"):
            skills.add(os.path.basename(path)[:-3])
        if skills:
            found[name] = sorted(skills)
    return found


def seeded_skills() -> set[str]:
    """The Skill() entries currently declared in init.py."""
    text = INIT_PY.read_text(encoding="utf-8")
    block = text.split(MARKER, 1)[1].split("\n)", 1)[0]
    return set(re.findall(r'"Skill\(([^)]+)\)"', block))


def render(found: dict[str, list[str]]) -> str:
    """Render the tuple source from the installed set."""
    lines = [
        MARKER,
        "    # Derived from the installed Punt Labs plugin set. Skill() rules ARE",
        "    # enforced — SkillTool honors explicit allow rules — so a missing entry",
        "    # means that skill prompts on every use. Regenerate with:",
        "    #   make skills-check",
    ]
    for plugin in sorted(found):
        lines.append(f"    # {plugin}")
        lines.extend(f'    "Skill({plugin}:{skill})",' for skill in found[plugin])
    lines.append(")")
    return "\n".join(lines)


def main() -> int:
    found = installed_skills()
    if not found:
        print("no punt-labs plugins installed — cannot check drift")
        return 0

    expected = {f"{p}:{s}" for p, skills in found.items() for s in skills}
    seeded = seeded_skills()
    stale = sorted(seeded - expected)
    missing = sorted(expected - seeded)

    if "--write" in sys.argv:
        text = INIT_PY.read_text(encoding="utf-8")
        start = text.index(MARKER)
        end = text.index("\n)", start) + 2
        INIT_PY.write_text(text[:start] + render(found) + text[end:], encoding="utf-8")
        print(f"wrote {len(expected)} entries across {len(found)} plugins")
        return 0

    if not stale and not missing:
        print(f"skills in sync: {len(seeded)} entries")
        return 0

    for entry in stale:
        print(f"  stale (seeded, not installed): Skill({entry})")
    for entry in missing:
        print(f"  missing (installed, not seeded): Skill({entry})")
    print(f"\n{len(stale)} stale, {len(missing)} missing — run: make skills-check-fix")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
