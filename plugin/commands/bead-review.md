---
description: "Audit every open bead in a repo — clarity, validity, priority"
allowed-tools:
  - "Read"
  - "Grep"
  - "Glob"
  - "Bash(bd:*)"
  - "Bash(git:*)"
  - "Bash(cat:*)"
  - "Skill(punt:bead-review-item)"
---

Load and execute the `bead-review` skill
(`${CLAUDE_PLUGIN_ROOT}/skills/bead-review/SKILL.md`).

Read the skill file first, then run it against the current repo (or the
repo named in the argument, if given).

Arguments: $ARGUMENTS
