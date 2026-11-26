---
description: "Audit every open Linear issue of a repo — clarity, validity, priority"
allowed-tools:
  - "Read"
  - "Grep"
  - "Glob"
  - "Bash(git:*)"
  - "mcp__linear__list_issues"
  - "mcp__linear__get_issue"
  - "mcp__linear__list_comments"
  - "mcp__linear__list_issue_labels"
---

Load and execute the `issue-review` skill
(`${CLAUDE_PLUGIN_ROOT}/skills/issue-review/SKILL.md`).

Read the skill file first, then run it against the current repo (or the
repo named in the argument, if given). The skill proposes changes and
asks before any Linear write; this command does not preapprove
`save_issue`.

Arguments: $ARGUMENTS
