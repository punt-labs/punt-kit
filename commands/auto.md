---
description: "Execute an automation playbook"
allowed-tools:
  - "Read"
  - "Edit"
  - "Write"
  - "Glob"
  - "Grep"
  - "Bash(git:*)"
  - "Bash(gh:*)"
  - "Bash(bd:*)"
  - "Bash(uv:*)"
  - "Bash(make:*)"
  - "Bash(punt:*)"
  - "Bash(python3:*)"
  - "Bash(shellcheck:*)"
  - "Bash(npx:*)"
  - "Bash(npm:*)"
  - "Bash(fly:*)"
  - "Bash(vercel:*)"
  - "Bash(test:*)"
  - "Bash(grep:*)"
  - "Bash(find:*)"
  - "Bash(mkdir:*)"
  - "mcp__github__*"
  - "mcp__plugin_github_github__*"
---

Load and execute the playbook specified below. Follow the executor protocol
defined in the `auto` skill (`.cursor/skills/auto/SKILL.md`).

Read the skill file first, then execute the playbook.

Arguments: $ARGUMENTS
