# Playbook Schema

A playbook is a YAML file that defines a multi-step process. Steps are either
**deterministic** (shell commands) or **judgment** (LLM-driven). An executor
agent reads the playbook and drives execution, running scripts directly and
applying reasoning for judgment steps.

## Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique identifier (matches filename without `.yaml`) |
| `description` | string | yes | One-line summary of what this playbook automates |
| `mode` | `once` \| `loop` | no | `once` (default): run steps then stop. `loop`: repeat from step 1 after completion |
| `parameters` | list | no | Inputs the playbook accepts |
| `preconditions` | list | no | Checks to run before starting |
| `steps` | list | yes | Ordered sequence of steps |

## Parameters

```yaml
parameters:
  - name: version
    type: string
    required: true
    description: Semantic version to release (e.g. 1.2.3)
  - name: dry_run
    type: bool
    default: false
    description: Preview without making changes
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Parameter name (snake_case) |
| `type` | `string` \| `bool` \| `list` \| `int` | yes | Data type |
| `required` | bool | no | Whether the executor must have a value before starting (default: true) |
| `default` | any | no | Default value (implies required: false) |
| `description` | string | yes | What this parameter controls |
| `enum` | list | no | Allowed values |

## Preconditions

```yaml
preconditions:
  - description: Working directory is a punt-labs project
    check: test -f CLAUDE.md
  - description: On main branch
    check: test "$(git branch --show-current)" = "main"
```

Each precondition has a `description` (human-readable) and a `check` (shell
command that exits 0 on success). All preconditions must pass before step
execution begins.

## Steps

```yaml
steps:
  - id: run-quality-gates
    description: Run the project's quality gates
    type: script
    command: make check
    on_failure: diagnose

  - id: update-changelog
    description: Add release entry to CHANGELOG.md
    type: llm
    context: |
      Read CHANGELOG.md. Move items under ## [Unreleased] into a new
      ## [X.Y.Z] section dated today. Follow Keep a Changelog format.
    postcondition:
      check: grep -q "## \[${version}\]" CHANGELOG.md
    on_failure: retry
```

### Step Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique step identifier (kebab-case) |
| `description` | string | yes | What this step accomplishes |
| `type` | `script` \| `llm` | yes | Execution mode |
| `command` | string | script only | Shell command to execute |
| `context` | string | llm only | Guidance for the LLM — what to do, what to consider |
| `postcondition` | object | no | Verification after the step completes |
| `on_failure` | `retry` \| `diagnose` \| `abort` | no | Failure strategy (default: `diagnose`) |
| `max_retries` | int | no | Maximum retry attempts (default: 3) |
| `env` | map | no | Environment variables to set for this step |

### Step Types

**`script`** — Deterministic execution. The executor runs the command via Bash
and checks the postcondition. The LLM does not modify the command; it runs it
as written. If the postcondition fails, the failure strategy applies.

**`llm`** — Judgment-required execution. The executor reads the `context`,
assesses the current state, takes action using any available tools, and then
checks the postcondition. The context is guidance, not a rigid script — the LLM
adapts to what it finds.

### Postconditions

```yaml
postcondition:
  check: grep -q "Read(../**)" .claude/settings.json
```

A postcondition has a required `check` (shell command). The executor runs this
command and considers the step failed if it exits with a non-zero status.

### Failure Strategies

| Strategy | Behavior |
|----------|----------|
| `retry` | Re-run the step (up to `max_retries`). No diagnosis. |
| `diagnose` | LLM reads the error output, diagnoses root cause, attempts a fix, then re-runs. Default. |
| `abort` | Stop the playbook immediately. Report what completed and what remains. |

## Variable References

Step commands and contexts can reference parameters by name using `${name}`
syntax. The executor substitutes scalar values before execution:

```yaml
command: punt release ${version}
```

### Substitution rules

- **Scalar types** (`string`, `int`, `bool`): substituted directly as their
  string representation.
- **List parameters**: use `type: string` with comma-separated values instead
  of `type: list` for shell compatibility. The executor does not support
  indexing syntax (`${param[0]}`).
- **LLM steps**: all parameter values are passed as context. The LLM reads
  them and applies judgment — no mechanical substitution needed.
- **Quoting**: the executor does not shell-escape substituted values. If a
  parameter value may contain spaces or special characters, the playbook
  author must handle quoting in the command.

Prefer LLM steps for postconditions that require complex parameter access.
Script step postconditions should use simple, self-contained shell commands.

## Playbook Discovery

The executor searches for playbooks in order:

1. `./playbooks/<name>.yaml` — project-local playbooks (current working directory)
2. `${CLAUDE_PLUGIN_ROOT}/playbooks/<name>.yaml` — punt-kit plugin root (when invoked as a command)
3. `../punt-kit/playbooks/<name>.yaml` — org-wide fallback (when run from a sibling repo)

Project-local playbooks take precedence over org-wide playbooks with the same name.
When `${CLAUDE_PLUGIN_ROOT}` is not set, path 2 is skipped.

## Example: Minimal Playbook

```yaml
name: sync-quarry
description: Rebuild and deploy the quarry chat database to Fly.io
mode: once

preconditions:
  - description: In the quarry project directory
    check: test -f pyproject.toml && grep -q "punt-quarry" pyproject.toml

steps:
  - id: rebuild-db
    description: Rebuild the chat database from all workspace projects
    type: script
    command: ./scripts/sync-chat-db.sh
    postcondition:
      check: fly status --app quarry
    on_failure: diagnose
```
