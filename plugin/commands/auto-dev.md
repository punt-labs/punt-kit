---
description: "[DEV] Execute local playbooks with the local executor skill"
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
defined in the `auto` skill (`${CLAUDE_PLUGIN_ROOT}/skills/auto/SKILL.md`).

Read the skill file first, then execute the playbook.

This selects the working tree's playbook and executor instructions. Each step
runs the command written in its playbook; a `punt` step uses the installed CLI.

IMPORTANT: `${CLAUDE_PLUGIN_ROOT}` is used ONLY for playbook discovery (finding
the YAML file). All preconditions and steps execute in the user's current
working directory — the project they invoked this command from, NOT punt-kit.

Arguments: $ARGUMENTS
