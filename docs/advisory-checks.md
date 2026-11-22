# Agent quality checks

The project selects `punt-kit` in `.punt-labs/ethos.yaml`. Its named check set
lives in `.punt-labs/ethos/checks/punt-kit.yaml`.

- Edits: advisory, read-only Ruff lint/format checks, shellcheck and Markdownlint.
- Commits: blocking staged-file lint/format checks and source/baseline ratchets.
- Handoff: blocking `make check`, with `files: all` and a 20-minute limit.

Type errors, tests, standards and Python documentation checks now wait until
handoff (or an explicit `make check`); source ratchets also run at commit.
Partially staged matched paths are refused because tools read the working tree.
Hooks never format files, update baselines or stage changes.

## Prerequisites

Use an ethos build containing DES-085 (tested with main `f4f884f`;
the latest release tag available during migration, v5.1.1, predates it).
Put that binary first on `PATH` for Claude and Git hooks. Run ethos SessionStart
to regenerate marked agents and install/refresh the local pre-commit shim.
Do not edit generated agent Markdown. Preserve the three unmarked reviewers.

Enable the matching ethos Claude plugin: its existing `SubagentStop` wrapper
dispatches the handoff check. Do not add a second project dispatcher, which
would run the full gate twice. Provision `uv sync --frozen`, shellcheck and
`markdownlint-cli2` before starting; Markdownlint uses `npx --no-install` and
does not download dependencies in a hook (tested with CLI v0.24.2).

Creating `~/.punt-hooks-kill` silences ethos checks, including handoff.
Remove it to restore checks.

### Linux harness limitation

The generator at `f4f884f` emits direct `ethos hook post-edit` commands.
Ethos documents an inherited-stdin problem on Linux (DES-027) requiring shell
forwarding in plugin wrappers. Fresh-pipe CLI measurements do not establish
that Claude's inherited stdin works. This upstream generator limitation is
not repaired by this repository's policy migration; generated files must
remain generator-owned. The plugin's handoff wrapper already forwards stdin.

## Reproduce timings

Run from the checkout with the new ethos first on `PATH`. The old command is
decoded verbatim from the pre-migration agent. Each Python run executes the
whole gate; expect about 12 minutes for five runs. The Git override isolates
tests from machine-global proxy rewriting; the hook command is unchanged.

```bash
export PATH="/home/ubuntu/repos/ethos:$PATH"
export CLAUDE_PROJECT_DIR="$PWD"
export GIT_CONFIG_GLOBAL=/dev/null
python - <<'PY'
import json
import os
import statistics
import subprocess
import time

base = "8940567d3e81f1c4544d2aa37ae88551cbd88f6b"
agent = subprocess.check_output([
    "git", "show", f"{base}:.claude/agents/gstack-implementer.md"
], text=True)
old = json.loads(next(line.split("command: ", 1)[1]
                      for line in agent.splitlines() if "command: " in line))
commands = {"before": ["sh", "-c", old],
            "after": ["ethos", "hook", "post-edit", "--agent", "gstack-implementer"]}
for label, command in commands.items():
    for file in ["src/punt_kit/__init__.py", "standards/hooks.md"]:
        payload = json.dumps({
            "session_id": "advisory-migration", "cwd": os.getcwd(),
            "hook_event_name": "PostToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": os.path.join(os.getcwd(), file),
                           "old_string": "before", "new_string": "after"},
            "tool_response": {"success": True}})
        times = []
        for _ in range(5):
            start = time.perf_counter()
            result = subprocess.run(command, input=payload, text=True,
                                    capture_output=True)
            times.append(time.perf_counter() - start)
            assert result.returncode == 0, result.stdout + result.stderr
        print(label, file, "median/min/max:", statistics.median(times),
              min(times), max(times))
PY
```
