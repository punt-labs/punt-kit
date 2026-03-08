---
description: "[DEV] Convert this plugin's commands to Cursor skills using the working tree"
argument-hint: "[output-path]"
allowed-tools: Read, Write, Glob, Edit, Delete
---

# Claude to Cursor Conversion (Dev)

Run the same conversion as `/punt claude2cursor`, but using the **local working tree** as the plugin root (`${CLAUDE_PLUGIN_ROOT}`). Use this when developing punt-kit to convert from the repo you are editing. The full specification below is identical to the prod command.

Convert this Punt Labs plugin's prod commands (and optionally CLAUDE.md/AGENTS.md) into Cursor-compatible skills and rules. Safe to run repeatedly: each run overwrites existing artifacts and removes obsolete skill dirs so output stays in sync with the plugin.

## Input

- **Output base path:** If the user provided a path as $ARGUMENTS, use it. Otherwise use the **current workspace root**. All output goes under `<output-base>/.cursor/`.

## Source (what to read)

1. **Prod commands:** Read all Markdown files in `${CLAUDE_PLUGIN_ROOT}/commands/` that:
   - Match `*.md`
   - Do **not** end with `-dev.md`
   - Are **not** named `claude2cursor.md` (no self-conversion)

2. **Slug rule:** For each command file, the **slug** is the filename with `.md` removed, lowercased (e.g. `audit.md` → `audit`, `release.md` → `release`). Use this slug for the output directory name and for the Cursor skill `name` field.

3. **Optional rules source:** If `${CLAUDE_PLUGIN_ROOT}/CLAUDE.md` or `${CLAUDE_PLUGIN_ROOT}/AGENTS.md` exist, read them for the optional rule file (see Output step 3 below).

## Output (what to write)

### 1. Skills (required)

For **each** prod command file (from the list above):

- **Path:** `<output-base>/.cursor/skills/&lt;slug&gt;/SKILL.md`
- **Create** the directory if it does not exist. **Overwrite** `SKILL.md` if it already exists (never skip-if-exists).
- **Frontmatter** (YAML at top of SKILL.md):
  - `name: &lt;slug&gt;`
  - `description: <from the command's description or first heading>`
  - `disable-model-invocation: true`
  - Do **not** include `allowed-tools`, `model`, `argument-hint`, or any other Claude-only frontmatter.
- **Body:** Same structure and steps as the source command, but **rewrite** Claude-specific syntax as follows:
  - **$ARGUMENTS / $1 / $2:** Replace with instructions to the Cursor agent, e.g. "If the user provided a project path (or first/second argument), use it; otherwise use `.` (or ask the user)."
  - **@path / @file:** Replace with "Read the file the user specified, or ask for the path if missing."
  - **Bash / shell blocks:** Keep the command text but wrap in instructions, e.g. "Run in the shell: `punt audit &lt;path&gt;` using the path from above."
  - **Preserve:** All substantive steps, lists, tables, and workflow logic; only the syntax of arguments and tool use is adapted for Cursor.

### 2. Commands (required) — slash commands that invoke the skills

For **each** prod command you converted to a skill (same slug set as in step 1):

- **Path:** `<output-base>/.cursor/commands/&lt;slug&gt;.md`
- **Format:** Plain Markdown only — **no YAML frontmatter**. Cursor commands are prompt-only.
- **Content:** A short prompt (one to three sentences) that instructs the agent to run the corresponding skill. Use this pattern:
  - First line: `# &lt;Title&gt;` (e.g. `# Punt Audit`) — this is the label shown in the `/` menu.
  - Next line(s): "Apply the **&lt;slug&gt;** skill. Follow the full procedure in `.cursor/skills/&lt;slug&gt;/SKILL.md`." Optionally add one line: "If the user provided a path or arguments, use them; otherwise use `.` (or ask)."
- **Overwrite** if the file already exists. Create `.cursor/commands/` if needed.
- **Purpose:** So the user can type `/audit`, `/init`, `/reconcile`, etc. and have the agent run the same workflow as the skill (by reading and following the skill file).

After writing all skills, write the command files. After writing all commands, **cleanup:** list files in `<output-base>/.cursor/commands/` and remove any `.md` file whose stem (filename minus `.md`) is not in the current slug set. Do not remove other user-added command files; only remove files that correspond to slugs we no longer produce (e.g. a removed plugin command).

### 3. Rules (optional)

If you read CLAUDE.md or AGENTS.md:

- **Path:** `<output-base>/.cursor/rules/punt-kit-context.mdc`
- **Overwrite** the file if it exists. Create the `.cursor/rules/` directory if needed.
- **Frontmatter:** `description: Punt Labs project context (from CLAUDE.md/AGENTS.md)` and `alwaysApply: true`.
- **Body:** Combined or single-file content from CLAUDE.md (and optionally AGENTS.md). Do **not** delete or overwrite any other `.mdc` files in `.cursor/rules/` that may exist; only write this specific file.

## Cleanup (repeatability)

After writing all skills and commands:

1. List the **current slug set:** the slugs derived from the prod command files you converted (exclude claude2cursor).
2. **Skills:** List existing **directories** under `<output-base>/.cursor/skills/`. Remove any directory whose name is **not** in the current slug set. Do not remove `.cursor/skills/` itself or directories that match a current slug.
3. **Commands:** List existing **files** in `<output-base>/.cursor/commands/*.md`. Remove any file whose stem (filename minus `.md`) is **not** in the current slug set. Do not remove other user-added command files; only remove files that correspond to slugs we produce (so when a plugin command is removed, its Cursor command is removed too).

## Conversion rules summary

- **Frontmatter:** Cursor skill gets only `name`, `description`, and `disable-model-invocation: true`.
- **Body:** Replace $ARGUMENTS/$1/$2 with natural-language instructions; replace @file with "read or ask for path"; keep bash blocks but add "Run in the shell: ..." wrapper; preserve all steps, tables, and logic.
- **Overwrite:** Always overwrite existing SKILL.md, command `.md` files, and the named rule file; never skip. Same source must produce identical output on re-run.
- **Cleanup:** Remove skill dirs and command files that are no longer in the current prod-command slug set.

## Requirements reflected in output

Quality gates (from CLAUDE.md/AGENTS.md) include **markdown lint** (`make check` / `punt audit`). When writing the rule file or when the source mentions quality gates:

- Preserve that **markdown lint** (e.g. `npx markdownlint-cli2 '**/*.md'`) is part of the gate.
- Standard markdownlint ignores (in `.markdownlint-cli2.jsonc`) should include `.tmp/`, `.beads/`, `.claude/`, `.venv/` so scratch and generated paths are excluded; add project-specific paths (e.g. `research/`, `session.md`) as needed.

This ensures generated rules and skills align with the audit check and with running markdown lint locally or in CI.

## Scope

Convert only this project's commands and optional CLAUDE.md/AGENTS.md. Do not discover or convert other plugins. The source of truth is always the **current** plugin root at `${CLAUDE_PLUGIN_ROOT}` at invocation time.

After completing the conversion, report to the user: how many skills were written, how many commands were written, whether the optional rule file was written, and how many obsolete skill dirs or command files (if any) were removed.
