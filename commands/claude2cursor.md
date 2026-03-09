---
description: Convert this plugin's commands and optional project docs to Cursor skills and rules
argument-hint: "[output-path]"
allowed-tools: Read, Write, Glob, Edit, Delete
---

# Claude to Cursor Conversion

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

- **Path:** `<output-base>/.cursor/skills/<slug>/SKILL.md`
- **Create** the directory if it does not exist. **Overwrite** `SKILL.md` if it already exists (never skip-if-exists).
- **Frontmatter** (YAML at top of SKILL.md):
  - `name: <slug>`
  - `description: <from the command's description or first heading>`
  - `disable-model-invocation: true`
  - Do **not** include `allowed-tools`, `model`, `argument-hint`, or any other Claude-only frontmatter.
- **Body:** Same structure and steps as the source command, but **rewrite** Claude-specific syntax as follows:
  - **$ARGUMENTS / $1 / $2:** Replace with instructions to the Cursor agent, e.g. "If the user provided a project path (or first/second argument), use it; otherwise use `.` (or ask the user)."
  - **@path / @file:** Replace with "Read the file the user specified, or ask for the path if missing."
  - **Bash / shell blocks:** Keep the command text but wrap in instructions, e.g. "Run in the shell: `punt audit <path>` using the path from above."
  - **Preserve:** All substantive steps, lists, tables, and workflow logic; only the syntax of arguments and tool use is adapted for Cursor.

### 2. Commands (required) — slash commands that invoke the skills

For **each** prod command you converted to a skill (same slug set as in step 1):

- **Path:** `<output-base>/.cursor/commands/<slug>.md`
- **Format:** Plain Markdown only — **no YAML frontmatter**. Cursor commands are prompt-only.
- **Content:** A short prompt (one to three sentences) that instructs the agent to run the corresponding skill. Use this pattern:
  - First line: `# <Title>` (e.g. `# Punt Audit`) — this is the label shown in the `/` menu.
  - Next line(s): "Apply the **`<slug>`** skill. Follow the full procedure in `.cursor/skills/<slug>/SKILL.md`." Optionally add one line: "If the user provided a path or arguments, use them; otherwise use `.` (or ask)."
- **Overwrite** if the file already exists. Create `.cursor/commands/` if needed.
- **Purpose:** So the user can type `/audit`, `/init`, `/reconcile`, etc. and have the agent run the same workflow as the skill (by reading and following the skill file).

After writing all skills, write the command files.

After writing all commands, run the **Cleanup** step below. Then write the **manifest** at `<output-base>/.cursor/punt-generated.json` with the current slug set, e.g. `{"generated_slugs": ["audit", "init", "pii", "reconcile", "release", "autopilot"]}`. The manifest must be written **after** cleanup completes so the previous manifest is still readable during cleanup.

### 3. Rules (optional)

If you read CLAUDE.md or AGENTS.md:

- **Path:** `<output-base>/.cursor/rules/punt-kit-context.mdc`
- **Overwrite** the file if it exists. Create the `.cursor/rules/` directory if needed.
- **Frontmatter:** `description: Punt Labs project context (from CLAUDE.md/AGENTS.md)` and `alwaysApply: true`.
- **Body:** Combined or single-file content from CLAUDE.md (and optionally AGENTS.md). Do **not** delete or overwrite any other `.mdc` files in `.cursor/rules/` that may exist; only write this specific file.

## Cleanup (repeatability)

After writing all skills and commands:

1. Read the **previous manifest** at `<output-base>/.cursor/punt-generated.json` (if it exists). Extract the previous slug set.
2. Compute **removed slugs**: slugs in the previous manifest but NOT in the current slug set.
3. **Skills:** For each removed slug, delete the directory `<output-base>/.cursor/skills/<slug>/` if it exists. Do not touch directories not listed in the previous manifest — those are user-created.
4. **Commands:** For each removed slug, delete `<output-base>/.cursor/commands/<slug>.md` if it exists. Do not touch files not listed in the previous manifest.

## Conversion rules summary

- **Frontmatter:** Cursor skill gets only `name`, `description`, and `disable-model-invocation: true`.
- **Body:** Replace $ARGUMENTS/$1/$2 with natural-language instructions; replace @file with "read or ask for path"; keep bash blocks but add "Run in the shell: ..." wrapper; preserve all steps, tables, and logic.
- **Overwrite:** Always overwrite existing SKILL.md, command `.md` files, and the named rule file; never skip. Same source must produce identical output on re-run.
- **Cleanup:** Use the manifest (`punt-generated.json`) to identify removed slugs. Only delete artifacts from the previous manifest's slug set — never touch user-created files.

## Requirements reflected in output

Quality gates (from CLAUDE.md/AGENTS.md) include code quality (`make check` — lint, type, test) and **markdown lint** (CI `docs` job via `npx markdownlint-cli2 '**/*.md'`). These are separate: `make check` runs ruff/mypy/pyright/pytest locally; markdownlint runs in CI. When writing the rule file:

- Preserve that **markdown lint** runs in CI (not in `make check`).
- Standard markdownlint ignores (in `.markdownlint-cli2.jsonc`) should include `.tmp/`, `.beads/`, `.claude/`, `.venv/` so scratch and generated paths are excluded; add project-specific paths (e.g. `research/`, `session.md`) as needed.

## Scope

Convert only this project's commands and optional CLAUDE.md/AGENTS.md. Do not discover or convert other plugins. The source of truth is always the **current** plugin root at `${CLAUDE_PLUGIN_ROOT}` at invocation time.

After completing the conversion, report to the user: how many skills were written, how many commands were written, whether the optional rule file was written, and how many obsolete skill dirs or command files (if any) were removed.
