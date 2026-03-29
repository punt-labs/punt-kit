---
name: auto
description: Execute an automation playbook — deterministic scripts with LLM error recovery
disable-model-invocation: true
---

# /punt:auto — Playbook Executor

Execute an automation playbook. Playbooks define multi-step processes as YAML
files with deterministic scripts and LLM judgment steps. The executor drives
each step, checks postconditions, and handles failures autonomously.

## Usage

- `/punt:auto <playbook>` — run a playbook by name
- `/punt:auto <playbook> key=value key=value` — run with parameters
- `/punt:auto list` — list available playbooks

## Argument Parsing

Parse the first argument as the playbook name. Remaining arguments are
`key=value` parameter pairs. If `list`, skip to the listing behavior.

## Playbook Discovery

Search for playbooks in order:

1. `./playbooks/<name>.yaml` — project-local (current working directory)
2. `${CLAUDE_PLUGIN_ROOT}/playbooks/<name>.yaml` — punt-kit plugin root (when invoked as a command)
3. `../punt-kit/playbooks/<name>.yaml` — org-wide fallback (when run from a sibling repo)

Project-local playbooks take precedence over org-wide playbooks with the same name.
When `${CLAUDE_PLUGIN_ROOT}` is not set, skip path 2.

For `list`, scan all applicable locations and print a table:

```
Name                Source      Description
───────────────────────────────────────────────────────────────────
autopilot           org         Autonomous bead-driven development loop
permissions-rollout org         Roll out permission changes to all projects
release             org         Release a Punt Labs project
standards-rollout   org         Roll out a standards change across all projects
<name>              local       <description>
```

## Execution Protocol

### Phase 0: Load and Validate

1. Read the YAML file.
2. Extract `name`, `description`, `mode`, `parameters`, `preconditions`, `steps`.
3. Validate required parameters have values (from arguments or defaults).
4. If any required parameter is missing, report which ones and stop.

### Phase 1: Preconditions

If no preconditions, skip to Phase 2. Otherwise, run all precondition
`check` commands as parallel Bash tool calls in a single message. Each
check is its own Bash call so it matches allowed-tool patterns and
auto-approves. If any fails, print which one and stop.

### Phase 2: Execute Steps

For each step in order:

**Script steps** (`type: script`):

1. Print: `[step N/M] <description>`
2. Substitute `${param}` references in `command` with parameter values.
3. If `background: true`:
   a. Run the command via Bash with `run_in_background: true`.
   b. Print: `[step N/M] running in background...`
   c. Do NOT wait — remain responsive to user messages.
   d. When the background task completes (notification), check exit code.
   e. If user asks for status, report which step is running.
   f. Continue to postcondition check after completion.
4. Otherwise, run the command via Bash (foreground).
5. If the step has a postcondition, run its `check` command.
6. If postcondition passes (exit 0), move to next step.
7. If postcondition fails, apply the failure strategy.

**LLM steps** (`type: llm`):

1. Print: `[step N/M] <description> (judgment)`
2. Delegate to a sub-agent via the Agent tool with `run_in_background: true`.
   The sub-agent receives the `context` field and all parameter values.
3. Do NOT wait — remain responsive to user messages.
4. When the sub-agent completes (notification), read its result.
5. If the step has a postcondition, run its `check` command.
6. If postcondition passes, move to next step.
7. If postcondition fails, apply the failure strategy.

### Failure Strategies

- **retry**: Re-run the step. Track attempts. After `max_retries` (default 3),
  escalate to `diagnose`.
- **diagnose**: Read the error output. Identify the root cause (do not guess —
  only facts). Attempt a fix. Re-run the step. After 3 diagnosis attempts,
  report the failure and stop.
- **abort**: Stop immediately. Print what completed and what remains.

### Phase 3: Loop or Complete

If `mode: loop`, go back to Phase 2 step 1. Continue until the user interrupts
or a step aborts.

If `mode: once`, print a completion summary:

```
Playbook '<name>' complete.
  Steps: N/N passed
  Duration: Xm Ys
```

## Progress Reporting

At each step, print a concise status line. Do not narrate or explain between
steps unless something fails. The flow should feel like watching a CI pipeline.

## Working Directory

**All preconditions and steps execute in the user's current working directory** —
the project they invoked `/punt:auto` from. `${CLAUDE_PLUGIN_ROOT}` and the
discovery paths above are used ONLY to locate the YAML playbook file. Never
`cd` to the plugin root or punt-kit directory to run playbook steps.

## Environment

All steps inherit the current shell environment. Steps can add variables via
the `env` field. Parameter values are available as `${param_name}` in commands.

## Principles

- **Deterministic steps run as written.** Do not modify script commands. If a
  script fails, diagnose the environment, not the script.
- **LLM steps adapt to reality.** The `context` is guidance, not a rigid
  script. Read the actual state and adjust.
- **Postconditions are truth.** A step is not done until its postcondition
  passes. No exceptions.
- **Failures are diagnosed, not retried blindly.** The default strategy is
  `diagnose` — understand why before trying again.
- **Full autonomy.** Do not ask the user for confirmation between steps. Only
  stop for unrecoverable errors or when `abort` is triggered.
- **Report, don't narrate.** Status lines at each step. Detailed output only on
  failure.
