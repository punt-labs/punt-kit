# Agent quality checks

The project selects `punt-kit` in `.punt-labs/ethos.yaml`. Its named check set
lives in `.punt-labs/ethos/checks/punt-kit.yaml`.
The stage split and single handoff dispatcher are recorded in
[DES-042](../DESIGN.md#des-042-advisory-edit-checks-and-one-handoff-dispatcher).

- Edits: advisory, read-only Ruff lint/format checks, shellcheck and Markdownlint.
- Commits: blocking staged-file lint/format checks and source/baseline ratchets.
- Handoff: blocking `make check`, with `files: all` and a 20-minute limit.

Ethos skips all handoff checks for a provably read-only agent: the start
fingerprint must be unchanged and the audit must contain no own or recent
unattributed mutating tool calls. Changes through Bash also change the
fingerprint. Missing or unreadable evidence runs the gate, not a skip.

Type errors, tests, standards and Python documentation checks now wait until
handoff (or an explicit `make check`); source ratchets also run at commit.
Partially staged matched paths are refused because tools read the working tree.
Hooks never format files, update baselines or stage changes.

## Prerequisites

Use an ethos build containing DES-085 and the generated-hook stdin fix.
Tested with main `d43e70e` (v5.2.0 candidate code; the build identifies itself
as `5.1.1-20-gd43e70e`). The original rollout used `f4f884f`;
the latest release tag available then, v5.1.1, predates DES-085.
Put that binary first on `PATH` for Claude and Git hooks. Run `ethos seed` to
install the full global bundle, not a symlinked roles layer. Run ethos SessionStart
to regenerate marked agents and install/refresh the local pre-commit shim.
Do not edit generated agent Markdown. Preserve the three unmarked reviewers.

Enable the matching ethos Claude plugin: its existing `SubagentStop` wrapper
dispatches the handoff check. Do not add a second project dispatcher, which
would run the full gate twice. Provision `uv sync --frozen`, shellcheck and
`markdownlint-cli2` before starting; Markdownlint uses `npx --no-install` and
does not download dependencies in a hook (tested with CLI v0.24.2).

Creating `~/.punt-hooks-kill` silences ethos checks, including handoff.
Remove it to restore checks.

### Linux stdin forwarding

The generator at `d43e70e` captures the full payload in Bash with a ten-second
read budget, then forwards it through a fresh pipe to `ethos hook post-edit`.
This replaces direct reads from Claude's inherited stdin, which are unreliable
on Linux (DES-027). The command honors the kill switch before reading stdin,
fails open and keeps the 70-second outer timeout. Generated files remain
generator-owned. The plugin's handoff wrapper also forwards stdin.

## Reproduce timings

Wall seconds with main `d43e70e`, five runs per edit scenario. Both edit
measurements execute the literal generated command through `sh -c` with the
same JSON; the new measurements include the Bash stdin-forwarding wrapper.

| Edit | Old median / min / max | New median / min / max |
|---|---:|---:|
| Python (`src/punt_kit/__init__.py`) | 164.943 / 158.873 / 166.287 | 0.063391 / 0.059131 / 0.073872 |
| Markdown (`standards/hooks.md`) | 0.021689 / 0.019729 / 0.021891 | 0.775031 / 0.763308 / 0.792155 |

Old Markdown edits were skipped. New ones receive lint feedback. A staged,
valid root-level Python fixture passed commit checks in 0.11 seconds. A staged
source fixture missing a ratchet baseline was blocked in 1.93 seconds (exit 2);
neither fixture nor any baseline changes were retained. The full handoff gate
took 150.05 seconds (exit 0), with no start fingerprint or attributed edits,
so the read-only optimization did not apply. The synthetic session was not
registered; ethos warned that it could not remove the roster entry, then ran
the gate.

The generated edit command emitted Ruff F821 advice with exit 0 using both
pipe and regular-file stdin. Empty and malformed input failed open; the kill
switch suppressed all output. These are command-level checks, not a live
Claude Code harness session.

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
from pathlib import Path
import statistics
import subprocess
import time

base = "8940567d3e81f1c4544d2aa37ae88551cbd88f6b"
agent = subprocess.check_output([
    "git", "show", f"{base}:.claude/agents/gstack-implementer.md"
], text=True)
old = json.loads(next(line.split("command: ", 1)[1]
                      for line in agent.splitlines() if "command: " in line))
current = Path(".claude/agents/gstack-implementer.md").read_text()
new = json.loads(next(line.split("command: ", 1)[1]
                      for line in current.splitlines() if "command: " in line))
commands = {"before": ["sh", "-c", old], "after": ["sh", "-c", new]}
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

For the commit measurement, create a new, valid `_advisory_probe.py` at the
checkout root, stage only that file, then run:

```bash
/usr/bin/time -f 'commit wall=%e exit=%x' ethos hook pre-commit
git restore --staged -- _advisory_probe.py
rm _advisory_probe.py
```

The fixture used a module docstring and `VALUE = 1`. Repeating with that
fixture in `src/punt_kit/` exercises the source ratchets and must fail without
a baseline; remove the fixture without updating any baseline. To measure
handoff with no start fingerprint, use a synthetic, unregistered session:

```bash
printf '%s' '{"session_id":"advisory-v520-handoff","agent_id":"advisory-v520-worker","agent_type":"gstack-implementer","stop_hook_active":false}' |
  /usr/bin/time -f 'handoff wall=%e exit=%x' ethos hook subagent-stop
```
