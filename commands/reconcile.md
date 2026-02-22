---
description: LLM-powered standards reconciliation for a Punt Labs project
argument-hint: "[project-path]"
allowed-tools: Read, Glob, Grep, Edit, Write, Bash(punt:*), Bash(git:*)
---

# Reconcile Project with Punt Labs Standards

Analyze a project against Punt Labs standards and surgically apply fixes. This command
handles files that need **contextual judgment** — workflow customizations, CLAUDE.md
quality, pyproject.toml drift — where a deterministic tool would be too blunt.

## Input

Project path: $ARGUMENTS (defaults to `.` if empty)

## Process

### 0. Detect Project

Read the project's `pyproject.toml` or `package.json` to determine:

- Language (python, node, swift, or none)
- Project type (application, library, plugin, docs)
- Whether it has an MCP server (`server.py` or MCP-related deps)
- Whether it has a CLI entry point (`[project.scripts]`)

Also read the project's `CLAUDE.md` if it exists — it may document intentional overrides.

### 1. Run Deterministic Audit

Run the mechanical checks first:

```bash
punt audit <project-path>
```

Report the output to the user. The deterministic layer catches missing files, config
gaps, and formatting issues. This command focuses on what `punt audit` cannot: contextual
reconciliation.

### 2. Load Standards

Read the following files from the punt-kit standards directory. If punt-kit is a sibling
directory (i.e., `../punt-kit/` relative to the project), read from the local filesystem.
Otherwise, read from the punt-kit repo on GitHub.

- `standards/python.md` — toolchain, quality gates, project layout
- `standards/github.md` — CI workflows, markdownlint config, action SHA pins
- `standards/cli.md` — required subcommands, init rules
- `standards/distribution.md` — install paths, PyPI publishing
- `standards/plugins.md` — plugin structure (if applicable)

### 3. Reconcile Workflow Files

For each workflow file in `.github/workflows/`:

1. Read the project's current workflow
2. Read the corresponding punt-kit template from `src/punt_kit/templates/workflows/`
3. Identify:
   - **Intentional customizations to PRESERVE**: extra dependencies, cache config,
     system packages (e.g., ffmpeg), coverage integration, project-specific env vars,
     custom test commands, extra linting steps
   - **Missing standard elements to ADD**: new jobs, updated action versions, missing
     timeout settings, missing permissions declarations
   - **Stale elements to UPDATE**: outdated action SHA pins, deprecated syntax

4. Apply changes surgically using the Edit tool — preserve project-specific content,
   add missing standard elements, update stale pins.

**Decision framework for workflows:**

| What you see | Action |
|-------------|--------|
| Project has extra steps not in template | PRESERVE — these are intentional |
| Template has steps the project is missing | ADD — explain what and why |
| Action versions differ (project is older) | UPDATE — with the template's version |
| Action versions differ (project is newer) | PRESERVE — project may have intentionally upgraded |
| Project has different cache/dependency config | PRESERVE — project knows its own deps |
| Project is missing timeout-minutes | ADD — use template's value |
| Template has a whole new workflow the project lacks | CREATE — but only the workflow file, not modifications to existing ones |

### 4. Reconcile CLAUDE.md

Check the project's `CLAUDE.md` for:

1. **Required sections present:**
   - `## Standards References` — with links to relevant punt-kit standards
   - `## Quality Gates` — with the actual commands for this project's toolchain

2. **Quality gate accuracy:**
   - Compare the listed commands against what the project actually uses
   - If the project has pyright in deps but CLAUDE.md doesn't mention it → flag
   - If CLAUDE.md lists a command the project can't run → flag

3. **Apply fixes:**
   - Add missing sections (append, don't clobber existing content)
   - Update quality gates to match actual toolchain
   - Do NOT rewrite the user's custom instructions or project description

### 5. Reconcile pyproject.toml (Python projects only)

Compare the project's `[tool.*]` sections against the Python standard:

| Section | Standard | Check |
|---------|----------|-------|
| `[tool.ruff]` | line-length=88, target-version="py313" | Report if different |
| `[tool.ruff.lint]` | select includes E, F, I, UP, B, SIM, TCH | Report missing rule sets |
| `[tool.mypy]` | strict=true | Report if not strict |
| `[tool.pyright]` | typeCheckingMode="strict" | Report if not strict |
| `[tool.pytest.ini_options]` | testpaths=["tests"] | Report if missing |

**Do NOT auto-fix pyproject.toml** — these settings affect build behavior and need human
judgment. Report drift with a clear recommendation. Example:

> `[tool.ruff] target-version` is `"py312"` but standard is `"py313"`. This may be
> intentional if the project supports Python 3.12. Confirm before updating.

### 6. Clean Permission Bloat

Read `.claude/settings.local.json` in the target project. If it doesn't exist, skip this
phase. This file accumulates bloat as Claude Code appends narrow permission patterns over
time — capturing commit messages, stale paths, and shell loop fragments as approval entries.

Focus on the `allow` and `deny` arrays (typically under keys like `"permissions"`). Preserve
all non-permission fields (`enableAllProjectMcpServers`, `enabledPlugins`, etc.) untouched.

#### 6a. Remove corrupt entries

Delete any permission entry that contains:

- Literal newlines or `\n` sequences within the pattern
- `EOF` or heredoc markers
- `Co-Authored-By`
- Shell control keywords used as line content: `for`, `do`, `done`, `then`, `else`,
  `fi`, `if [`, `while` (match as word prefixes, not substrings)
- Embedded commit messages (lines containing `git commit -m` followed by 50+ characters)

These are artifacts of Claude Code capturing multi-line shell commands or commit operations
as single permission entries.

#### 6b. Remove stale absolute paths

Delete entries containing absolute paths that don't match the current project. Specifically:

- `/Users/*/Coding/*/` paths where the project name doesn't match the target project
- `/Users/*/.claude/plugins/cache/local/*/` version-specific plugin cache paths
- Any path referencing a directory that no longer exists

Preserve paths that correctly reference the current project directory.

#### 6c. Collapse redundant patterns

When multiple narrow patterns exist for the same tool family, collapse them to a single
wildcard. Apply these standard collapses:

| Narrow patterns (examples) | Collapse to |
|----------------------------|-------------|
| `Bash(git add:*)`, `Bash(git commit:*)`, `Bash(git push:*)` | `Bash(git:*)` |
| `Bash(gh pr:*)`, `Bash(gh issue:*)`, `Bash(gh api:*)` | `Bash(gh:*)` |
| `Bash(uv run:*)`, `Bash(uv sync:*)`, `Bash(uv build:*)` | `Bash(uv:*)` |
| `Bash(bd create:*)`, `Bash(bd update:*)`, `Bash(bd sync:*)` | `Bash(bd:*)` |
| `Bash(python3 -c:*)`, `Bash(python3 -m:*)` | `Bash(python3:*)` |
| `Bash(make build:*)`, `Bash(make test:*)` | `Bash(make:*)` |
| `Bash(curl -s:*)`, `Bash(curl -X:*)` | `Bash(curl:*)` |
| Multiple specific `mcp__plugin_github_github__*` tools | `mcp__plugin_github_github__*` |

**Collapse rule**: If 3+ entries share the same tool prefix, collapse to the wildcard. If
only 1–2 entries exist, leave them as-is (they may be intentionally scoped).

**Do NOT collapse** project-specific tools — entries like `Bash(quarry:*)`, `Bash(ffmpeg:*)`,
`Bash(pdflatex:*)`, or `Bash(swift:*)` should be preserved as-is.

#### 6d. Flag stale MCP tool names

If permission entries reference MCP tool prefixes that don't match any currently installed
plugin (check `.claude/settings.local.json` `enabledPlugins` and the project's
`.claude-plugin/plugin.json` if present), flag them for review rather than auto-removing.

#### 6e. Apply and report

- Write the cleaned file using the Edit tool (or Write if the changes are extensive)
- Report the before/after entry count
- List removed entries grouped by reason (corrupt, stale path, collapsed)
- List any entries flagged for review

### 7. Report Summary

After all checks, print a structured summary:

```text
## Reconciliation Report

### Applied (safe fixes)
- ✓ Added timeout-minutes to lint.yml
- ✓ Created release.yml from template
- ✓ Added Standards References section to CLAUDE.md
- ✓ Permissions: removed 12 corrupt entries (commit messages, shell fragments)
- ✓ Permissions: collapsed 18 narrow git patterns → Bash(git:*)
- ✓ Permissions: 47 → 15 entries (68% reduction)

### Needs Review (human judgment required)
- ⚠ pyproject.toml: ruff target-version is py312, standard is py313
- ⚠ lint.yml: uses actions/checkout@abc123 but template uses @def456
- ⚠ Permissions: 3 entries reference unknown MCP prefix mcp__plugin_old_tool__

### Already Compliant
- ✓ docs.yml matches template
- ✓ CLAUDE.md has all required sections
- ✓ pyproject.toml tool configs are standard-compliant
```

## Important Rules

1. **Never delete project-specific content.** Reconciliation is additive. If you're
   unsure whether something is intentional, preserve it and flag it for review.

2. **Explain every change.** Before applying an edit, tell the user what you're changing
   and why. Reference the specific standard that requires it.

3. **Respect CLAUDE.md overrides.** If a project's CLAUDE.md explicitly says "we use X
   instead of Y", that override wins. Don't flag it as drift.

4. **One project at a time.** Even if you can see sibling directories, only reconcile
   the specified project path.

5. **Deterministic checks belong in `punt audit`.** If you find yourself wanting to add
   a mechanical check (file exists? config key present?), note it as a potential
   `punt audit` enhancement instead.
