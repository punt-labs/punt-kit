---
description: "[DEV] Execute an automation playbook using the working tree"
allowed-tools:
  - "Bash(git:*)"
  - "Bash(gh:*)"
  - "Bash(bd:*)"
  - "Bash(uv:*)"
  - "Bash(make:*)"
  - "Bash(punt:*)"
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
defined in the `auto` skill (`${CLAUDE_PLUGIN_ROOT}/.cursor/skills/auto/SKILL.md`).

Read the skill file first, then execute the playbook. For playbook discovery,
check `${CLAUDE_PLUGIN_ROOT}/playbooks/` for org-wide playbooks.

Arguments: $ARGUMENTS
