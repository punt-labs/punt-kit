# Design Decision Log

Decisions that shape punt-kit's architecture and standards. Consult before
proposing changes to settled decisions. See
[patterns/design-decision-log.md](patterns/design-decision-log.md) for the
format spec.

## DES-001: Plugin Dev/Prod Namespace Isolation

**Date:** 2026-02-22
**Status:** SETTLED
**Topic:** How plugin authors test local changes alongside marketplace installs

### Design

The working tree's `plugin.json` uses `name: "<project>-dev"` (e.g.
`punt-dev`). The marketplace uses `name: "<project>"` (e.g. `punt`). Developers
launch with `claude --plugin-dir .` to load both plugins simultaneously. The
`-dev` suffix at the plugin name level isolates all extension points: commands,
MCP tools, skills, agents, hooks.

Each prod command has a `-dev` variant that runs via
`uv run --directory ${CLAUDE_PLUGIN_ROOT}` against the working tree code.

At release time, `scripts/release-plugin.sh` swaps the plugin name to prod and
removes `-dev` commands. `scripts/restore-dev-plugin.sh` restores dev state
after tagging.

`punt audit` enforces: plugin name has `-dev` suffix, release/restore scripts
exist, every prod command has a `-dev` variant.

### Why

Plugin authors need to test local changes without waiting for marketplace
publish cycles. The marketplace-installed plugin and the local working tree
must coexist in the same session without name collisions.

`--plugin-dir .` is the documented, supported mechanism for loading plugins
from a local directory. CWD auto-discovery is unreliable when marketplace
plugins exist.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| CWD auto-discovery | Does not reliably load local plugins when marketplace plugin exists. Tested extensively 2026-02-22. |
| Dual manifest (`plugin-dist.json`) | Overengineered. Extra JSON files in `.claude-plugin/` are ignored — only `plugin.json` is loaded. |
| Command-level isolation only (same plugin name) | Plugin name prefixes everything (commands, MCP tools, skills). Same name = same namespace = collision. |
| `claude plugin install` from local path | Requires a marketplace directory structure. No direct local install path exists. |
| `claude plugin marketplace add` for local dir | Expects `marketplace.json`, not `plugin.json`. Wrong abstraction level. |

## DES-002: Claude CLI Over Config File Editing

**Date:** 2026-02-22
**Status:** SETTLED
**Topic:** How to manage Claude Code configuration (plugins, MCP servers, settings)

### Design

Always use `claude plugin`, `claude mcp`, and other CLI subcommands to manage
Claude Code configuration. Never hand-edit `installed_plugins.json`,
`enabledPlugins`, MCP config, or other internal JSON files.

When commands need to be run but can't be executed inside a session (nested
`claude` is not supported), ask the user to run them in a separate terminal.

### Why

Internal JSON file formats are undocumented, change between versions, and have
subtle semantics (e.g. `enabledPlugins: {}` may disable rather than enable).
The CLI commands handle these details correctly and are the supported interface.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Direct JSON editing | Fragile, format undocumented, caused multiple debugging sessions (2026-02-22). |
| Guessing at file paths and formats | Different Claude Code versions store config differently. Only the CLI knows current format. |

## DES-003: Marketplace Installs from HEAD, Not Tags

**Date:** 2026-02-27
**Status:** SETTLED
**Topic:** Why marketplace installs can silently ship dev artifacts and the systemic fix

### Root Cause

Claude Code marketplace installs clone HEAD of the default branch, not the version tag. When a marketplace entry has no `source.ref` field, `claude plugin install` resolves the `version` field for display only — the git clone targets HEAD.

This is invisible when HEAD and the tag are the same commit. It becomes a breaking defect when they diverge — which is exactly what dev/prod namespace isolation (DES-001) does. The release workflow pushes three commits in sequence:

```text
main:  ... → [release] → [prepare: name=<project>] → [restore: name=<project>-dev]
                              ↑ tag vX.Y.Z                  ↑ HEAD
```

The tag points to the prepare commit (prod name). HEAD points to the restore commit (dev name). The marketplace installs HEAD — so every user gets the dev plugin.

### Consequences of Installing the Dev Plugin

1. Plugin loads as `<project>-dev`, not `<project>`
2. Session-start hook detects dev mode, skips command deployment
3. No top-level slash commands (e.g. `/notify`, `/say`)
4. User sees only namespaced dev commands (e.g. `/tts-dev:notify`)
5. Tool permission auto-allow writes the dev pattern

The plugin technically works — MCP server starts, tools function — but the UX is wrong. The user has no idea they're running a dev build.

### Why This Wasn't Caught

1. The developer uses an editable install + `--plugin-dir .`, so the dev name is expected
2. The release script round-trip test verified the scripts work, not the installed artifact
3. No test installs from the marketplace after release — verification tests PyPI, not the plugin
4. Other projects with the same pattern hadn't cut a release since adopting it, so their HEAD happened to be correct

### Fix (Two Parts)

**Part 1: Pin `source.ref` in marketplace.json.**

Every marketplace entry must specify the release tag:

```json
{
  "name": "tts",
  "source": {
    "source": "github",
    "repo": "punt-labs/tts",
    "ref": "v0.4.0"
  },
  "version": "0.4.0"
}
```

This is required for any project where HEAD of main may diverge from the release tag — which is every project using dev/prod namespace isolation, and arguably every project where post-release commits exist.

**Part 2: Refresh the marketplace clone before plugin install.**

Pinning `source.ref` in the remote marketplace.json only helps when the local clone has the pin. Existing users whose marketplace clone predates the pin see the old marketplace.json without `source.ref` — and `claude plugin install` resolves HEAD again.

The installer must refresh the marketplace clone before running `claude plugin install`, using the supported CLI command:

```bash
claude plugin marketplace update "$MARKETPLACE_NAME" 2>/dev/null || true
```

This uses `claude plugin marketplace update` rather than operating on the clone directly, consistent with DES-002 (CLI over config file editing). New users get a fresh clone. Existing users get the latest `source.ref` pins.

### Rules

1. **Every marketplace entry MUST have `source.ref` pinned to the release tag.** The release workflow marketplace bump step must update both `version` and `ref`.
2. **Every installer MUST refresh the marketplace clone before `claude plugin install`.** Run `claude plugin marketplace update punt-labs` so existing users pick up ref pins.

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Don't push restore commit to main | Breaks the dev workflow — developer's working tree would have prod name, defeating namespace isolation |
| Tag HEAD instead of the prepare commit | Tag would include dev artifacts; marketplace clones the tag and gets dev name anyway |
| File a Claude Code bug to resolve `version` → tag | Correct long-term fix, but we can't control Claude Code's release timeline; `ref` is the available mechanism now |
| Keep main always prod-ready, dev on branches | Every feature branch would need manual plugin.json swap; error-prone, defeats the automation |
| Only pin `source.ref`, skip refresh | Existing users with stale clones never see the pin — install still resolves HEAD |

### Affected Projects

All projects with a marketplace entry and `install.sh` / CLI `install` subcommand: tts, biff, punt-kit. Pure plugins (dungeon, prfaq, z-spec) rely on `claude plugin install` directly — they need correct `source.ref` but have no installer to add a refresh step.

### Discovery Chain

1. User installed tts v0.4.0 from marketplace, saw `/tts-dev:notify` instead of `/notify`
2. Checked installed plugin cache: `name: "tts-dev"`, commit was the restore commit
3. Compared to v0.4.0 tag: correct prepare commit with `name: "tts"`
4. Confirmed: marketplace installed HEAD, not tag
5. Added `source.ref` to all marketplace entries, nuked cache, reinstalled — correct
6. Discovered stale clone problem: existing users whose clone predates the ref pin still get HEAD
7. Added `_refresh_marketplace()` to tts installer — pulls latest marketplace.json before install

## DES-004: Three-Tier Permission Scheme

**Date:** 2026-02-27
**Status:** SETTLED
**Topic:** How Claude Code agent permissions are structured across all Punt Labs projects

### Design

Agent permissions use a three-tier model: **allow** (auto-approved, no prompt),
**prompt** (user approves each time, the default), and **deny** (blocked
entirely, cannot be overridden even with explicit approval).

Permissions are split across two files based on portability:

- **`settings.json`** (checked into git) — portable permissions that apply to
  all collaborators: MCP plugin wildcards, build tool Bash commands, skill
  permissions, WebFetch domain allowlists, and deny rules.
- **`settings.local.json`** (gitignored) — machine-specific permissions tied to
  local paths: `Read`/`Edit`/`Write` with absolute or `~` paths, OS-specific
  commands (e.g. `Bash(say:*)` on macOS), temp directory access.

Deny rules cover four categories:

1. **Destructive operations** — `rm -rf /`, `rm -rf ~`, `dd`
2. **Privilege escalation** — `sudo`, `su`
3. **Network access** — `curl`, `wget`, `ssh`, `scp`, `ftp`, `tftp`, `nc`,
   `netcat`, `ncat`, `telnet`, `socat`
4. **Secrets and environment** — `Edit(.env)`, `Write(.env)`, `Edit(.envrc)`,
   `Write(.envrc)`, `Bash(direnv allow:*)`

The standard is codified in `standards/permissions.md` and enforced by
`punt audit`.

### Why

The goal is enabling safe autonomous development. An agent running `/autopilot`
(DES-005) must be able to perform routine operations — git, tests, lint, PRs —
without permission prompts, while being structurally prevented from destructive
or exfiltration-capable operations.

**Allow tier** eliminates friction for safe, reversible operations. Every tool
call that isn't explicitly allowed or denied falls into the prompt tier, which
is the safety net — the narrowest set of operations get auto-approved, not the
broadest.

**Deny tier** provides a hard floor. These aren't "things the user probably
doesn't want" — they're operations that should never happen in an automated
development context. Network tools are denied because an agent with `curl` or
`nc` can exfiltrate repository contents, secrets, or environment variables.
Allowed interpreters (e.g. `python3`, `uv run`) can still make network calls
programmatically — the deny list prevents direct invocation, not all possible
access. This is a guardrail, not a sandbox.

**File split** ensures collaborators get consistent safety rules (deny rules
travel with the repo) while allowing machine-specific path permissions to vary.
A developer on macOS with files at `/Users/alice/` doesn't pollute the shared
config that a Linux developer with `/home/bob/` needs to work.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Single `settings.json` with all permissions | Local absolute paths would differ per machine. Checking them in forces either conflicts or lowest-common-denominator paths. |
| Prompt tier for dangerous operations (no deny) | An agent can be socially engineered or hallucinate a reason to approve a destructive command. Deny removes the possibility entirely. |
| Broad deny list (deny `python3`, `uv`, etc.) | Over-restricting kills the autonomous workflow. The agent needs interpreters and build tools to function. Deny only what is categorically unsafe. |
| Per-command permission prompts during autopilot | Defeats the purpose. An autonomous loop that stops every 30 seconds for approval is not autonomous. |
| Allow `curl` for API testing | Opens exfiltration surface. Use `WebFetch` (domain-restricted, read-only) or MCP tools instead. |

### Rules

1. Every project MUST have both `settings.json` (checked in) and
   `settings.local.json` (gitignored).
2. `settings.local.json` MUST be in `.gitignore`.
3. No absolute or `~` paths in `settings.json`.
4. All deny rules from `standards/permissions.md` MUST be present in every
   project's `settings.json`.
5. All MCP plugin wildcards MUST be in `settings.json`.

## DES-005: Autopilot Command Structure

**Date:** 2026-02-27
**Status:** SETTLED
**Topic:** How the autonomous development loop is structured for safety and continuous flow

### Design

The `/autopilot` command runs a continuous bead-driven development cycle. It
picks beads from `bd ready`, implements them, opens PRs, waits for CI and
Copilot review, merges via the MCP API, and immediately continues to the next
bead without pausing for user confirmation.

Key structural decisions:

1. **Worktree-first**: On first iteration, check `/who` for other active
   sessions. If any exist, enter a worktree to avoid interfering with their
   working tree. One worktree per session — branch freely inside it for each
   PR.

2. **Blocking CI and review**: After opening a PR, the agent backgrounds
   `gh pr checks <N> --watch` (which blocks until all checks resolve) and
   requests Copilot review via the MCP tool. The agent does not proceed to
   merge until both CI passes and Copilot feedback is addressed.

3. **MCP merge, never `gh pr merge`**: Merging uses
   `mcp__github__merge_pull_request` (API-only, no local git side effects).
   `gh pr merge` attempts to checkout main locally, which fails inside a
   worktree and leaves the working tree in an inconsistent state.

4. **Command-level `allowed-tools`**: The command's YAML frontmatter declares
   `allowed-tools` — the set of tools the agent may use without per-call
   prompts during that command's execution. This is a subset of the session's
   `settings.json` allow list. The session allow list is the outer boundary;
   the command frontmatter temporarily auto-approves tools within that boundary.
   Deny rules cannot be overridden by either mechanism.

5. **Project-agnostic quality gates**: The command references "the project's
   quality gates as defined in its CLAUDE.md" rather than hardcoding specific
   linters or test commands. This lets the same command work across Python,
   Node.js, Swift, and plugin projects.

6. **Continuous flow**: After merging a PR and closing a bead, the agent
   immediately picks the next bead. It does not ask "Ready for the next bead?"
   The user interrupts when they want to stop.

### Why

The purpose of autopilot is to let an agent complete a queue of well-defined
beads while the developer is away or working on something else. Every design
choice serves either **safety** (preventing irreversible mistakes) or
**continuity** (minimizing interruptions that break the flow).

**Worktree-first** prevents a common class of accidents: two sessions modifying
the same working tree simultaneously. Git worktrees give each session an
isolated copy of the repo. The agent branches freely inside its worktree, and
cleanup is deferred to `/exit` (never from inside the worktree, which would
invalidate the session's cwd).

**Blocking on CI and Copilot** is the most important safety gate. Without it,
an agent could merge broken code or code that Copilot flagged. The
`gh pr checks --watch` command is intentionally blocking — it's not a
suggestion to check later, it's a hard gate.

**MCP merge** avoids a known failure mode. `gh pr merge` has local side effects
(attempts to checkout and pull main) that fail in worktrees and can corrupt
git state. The MCP tool is a pure API call with no local consequences.

**Command-level `allowed-tools`** creates a two-layer permission model. The
session permissions define what's possible. The command permissions define
what's frictionless. An agent running `/autopilot` can use `git`, `gh`, `bd`,
and build tools without prompts, but cannot use `curl` or `sudo` even if it
wanted to — those are denied at the session level.

**Continuous flow** is a deliberate UX choice. Asking for confirmation between
beads turns an autonomous loop into a supervised one. The beads themselves are
the user's pre-approved work items — picking them off a queue doesn't require
additional approval.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Always use worktrees (no direct branch option) | Unnecessary overhead when the agent is the only active session. Worktrees add complexity (detached HEAD, can't checkout main branch). |
| Non-blocking CI check (proceed optimistically) | Merging before CI passes can break main. The whole point of the PR workflow is gating on checks. |
| `gh pr merge` with workaround scripts | Fragile. The underlying issue is that `gh` has local side effects. Using the API directly eliminates the problem class. |
| Hardcoded quality gates per language | Breaks when a project has custom gates. Referencing CLAUDE.md means the command adapts to any project. |
| Ask user between beads | Defeats autonomous flow. The user queued the work — the agent should execute it continuously. |
| Skip Copilot review for small changes | No exemptions. Small changes can have large consequences. The review cost is low (automated, takes minutes). |

### Interaction with DES-004

The permission scheme (DES-004) and the autopilot command are co-designed. The
deny rules establish a hard safety floor that autopilot cannot breach. The
allow rules eliminate permission prompts for the operations autopilot needs. The
command's `allowed-tools` frontmatter is the final layer — it declares exactly
which allowed tools the agent will use during the loop, making the scope of
autonomous action explicit and auditable.

## DES-006: Stdin Protection in `curl | sh` Installers

**Date:** 2026-02-28
**Status:** SETTLED
**Topic:** Why `curl | sh` installers silently stop executing after certain commands

### Root Cause

When a shell script runs via `curl -fsSL ... | sh`, the shell reads the script
from stdin (the pipe). Child processes inherit the shell's stdin by default. Any
child that reads from stdin — even one byte — consumes bytes from the pipe,
starving the shell of the remaining script.

The script silently stops executing at the point where a child consumed stdin.
There is no error, no signal, no indication that the script was truncated. The
exit code is 0 if the consuming command succeeded.

### Commands That Consume Stdin

| Command | Why it reads stdin | Evidence |
|---------|-------------------|----------|
| `claude` (any subcommand) | Claude CLI checks for interactive input, reads pipe data | Confirmed: `echo \| { claude plugin list; cat; }` hangs |
| `ssh` | Reads passphrase, host key confirmation, or pipe data | Standard behavior; `-n` flag exists for this reason |
| `read` | Explicitly reads from stdin | Shell builtin |
| `cat` (no args) | Reads from stdin when no file argument | Standard behavior |

### The Failure Pattern

A typical installer runs marketplace operations (which call `claude`) before
the plugin install step:

```bash
claude plugin marketplace update "$NAME"    # ← consumes remaining script bytes
claude plugin install "$PLUGIN@$NAME"       # ← never reached
<tool> doctor                               # ← never reached
```

The marketplace update succeeds and exits 0. The shell tries to read the next
line of the script from stdin, but the pipe is exhausted. The script ends.

### Fix

Redirect stdin to `/dev/null` on every command that may consume stdin:

```bash
claude plugin marketplace update "$NAME" < /dev/null
claude plugin install "$PLUGIN@$NAME" < /dev/null
claude plugin list < /dev/null | grep -q "$PLUGIN"
ssh -n -o BatchMode=yes -T git@github.com 2>&1 | grep -q "authenticated"
```

The `< /dev/null` redirect is per-command, not global. A global redirect
(`exec < /dev/null`) would break commands that legitimately need stdin (though
install scripts typically have none).

For `ssh` specifically, the `-n` flag is equivalent to `< /dev/null` and is the
idiomatic way to prevent stdin consumption.

### Rules

1. **Every `claude` command in an install script MUST have `< /dev/null`.**
   This includes `claude plugin list`, `claude plugin install`,
   `claude plugin uninstall`, `claude plugin marketplace add`,
   `claude plugin marketplace update`, and `claude plugin marketplace list`.
2. **Every `ssh` command in an install script MUST use `-n`.**
3. **Test install scripts via `curl | sh`**, not `sh install.sh`. Direct
   execution does not reproduce the stdin consumption failure because stdin is
   a terminal, not a pipe.

### Discovery Chain

1. User ran `curl | sh` installer for tts — installed the binary but plugin
   install step never executed
2. Compared working installer (punt-kit, where SSH check came before `claude`
   commands) to broken ones (tts/biff/quarry, where `claude marketplace update`
   came first)
3. Confirmed: running `sh install.sh` directly worked fine (stdin is terminal)
4. Confirmed: `echo | { claude plugin list; cat; }` produced no output from
   `cat` — `claude` consumed the pipe
5. Applied `< /dev/null` to all `claude` and `ssh` commands across 6 repos
6. Verified: full `curl | sh` install-all now completes all steps

### Affected Projects

All projects with `install.sh`: tts, biff, quarry, punt-kit, claude-plugins.
Also `install-all.sh` in punt-kit (calls `claude` directly for pure plugin
installs).

## DES-007: Pure Plugin Release Tags

**Date:** 2026-02-28
**Status:** SETTLED
**Topic:** Why marketplace installs fail for pure plugins that use dev/prod naming without release tags

### Root Cause

DES-001 established the dev/prod namespace pattern: working tree uses
`name: "<project>-dev"`, release tags use `name: "<project>"`. DES-003
established that marketplace entries must pin `source.ref` to the release tag.

For CLI + plugin hybrids (tts, biff, punt-kit), `scripts/release-plugin.sh`
handles the name swap and tagging as part of the release workflow. Pure plugins
(dungeon, prfaq, z-spec) have no PyPI artifact and no release scripts — the
version was bumped manually but the tag was never created.

When the marketplace entry pins `source.ref: "v0.1.3"` but the tag `v0.1.3`
does not exist in the repo, `claude plugin install` fails silently. The error
is suppressed by the `2>/dev/null` in install-all.sh's pure-plugin loop.

### Fix

Pure plugins that use dev/prod naming must follow the same swap-tag-restore
pattern as hybrid projects, even without release scripts:

```bash
# 1. Swap to prod name
# Edit plugin.json: "name": "<project>"
git add .claude-plugin/plugin.json
git commit -m "chore: swap plugin name <project>-dev → <project> for release"

# 2. Tag
git tag vX.Y.Z

# 3. Restore dev name
# Edit plugin.json: "name": "<project>-dev"
git add .claude-plugin/plugin.json
git commit -m "chore: restore dev plugin state"

# 4. Push both commits and the tag
git push origin main vX.Y.Z
```

The tag points to the swap commit (prod name). HEAD points to the restore
commit (dev name). The marketplace clones at the tag and gets the correct name.

### Rules

1. **Every marketplace `source.ref` MUST point to an existing tag.** If the
   tag does not exist, the marketplace install fails silently.
2. **Pure plugins using dev/prod naming MUST create tags with the prod name.**
   The tag commit must have `plugin.json` with `name: "<project>"`, not
   `name: "<project>-dev"`.
3. **The release workflow for pure plugins is: swap → tag → restore → push.**
   This is the same as hybrid projects, minus the PyPI steps.
4. **Consider adding `scripts/release-plugin.sh` to pure plugins** if the
   project will have multiple releases. The manual swap is error-prone.

### Discovery Chain

1. `install-all.sh` reported dungeon install failure
2. Added `uninstall` before `install` (idempotency) — still failed
3. Checked dungeon repo: zero tags existed
4. Marketplace entry referenced `v0.1.3` — tag did not exist
5. Created tag with prod name at HEAD, pushed — install succeeded

## DES-008: install.sh VERSION Pinning

**Date:** 2026-03-09
**Status:** SETTLED
**Topic:** Why `install.sh` must declare `VERSION="X.Y.Z"` and how the release CLI bumps it

### Root Cause

The `punt release` CLI (Phase 2: version bump) updated `pyproject.toml`, `__init__.py`,
`plugin.json`, and `CHANGELOG.md` — but never touched `install.sh`. After a release,
`install.sh` still contained the previous version's `VERSION="X.Y.Z"` pin.

This caused two problems:

1. **install-all.sh SHA pinning installs the wrong version.** `install-all.sh` pins each
   project's `curl` URL to a specific commit SHA. The SHA points to the tag commit, which
   includes the updated `pyproject.toml` but the stale `install.sh`. Users who run
   `install-all.sh` get the old version.

2. **The "prepare plugin for release" commit has stale install.sh.** The release workflow
   creates a "prepare" commit (swap plugin name to prod), tags it, then creates a "restore"
   commit. The prepare commit bumps `plugin.json` version but not `install.sh` VERSION —
   so the tagged install script installs the wrong version.

### Fix

Added `install.sh` VERSION bump to `_phase2_version_bump()` in `release.py`:

```python
# Bump install.sh VERSION pin
content = install_sh.read_text()
new_content = re.sub(
    r'^(VERSION=")[^"]*(")',
    rf"\g<1>{version}\2",
    content, count=1, flags=re.MULTILINE,
)
```

The regex matches `VERSION="..."` and replaces the version string. Scripts without a
VERSION pin are left unchanged (the regex does not match).

### Rules

1. **Every `install.sh` that uses `uv tool install "$PACKAGE==$VERSION"` must declare
   `VERSION="X.Y.Z"` near the top.** The release CLI bumps this automatically.
2. **Scripts without a VERSION pin are non-deterministic.** They install whatever is latest
   on PyPI, which may not match the SHA pinned in `install-all.sh`. As of v0.6.0, quarry
   is the only remaining project without a VERSION pin.
3. **The release workflow verification step (Step 5b in `release.md`) checks that the
   VERSION pin at the tagged SHA matches the release version.**

### Discovery Chain

1. `install-all.sh` output showed vox installing 1.2.3 instead of 1.2.4
2. Checked vox `install.sh` at the tagged SHA — `VERSION="1.2.3"` (stale)
3. Traced to `release.py` `_phase2_version_bump()` — no install.sh handling
4. Same issue confirmed in lux: `VERSION="0.5.1"` instead of `0.5.2`
5. Fixed `release.py`, added tests, manually fixed vox and lux install.sh files
6. Updated `release.md` verification to check VERSION pins at tagged SHAs

## DES-009: Building Block Hook Ownership

**Date:** 2026-03-09
**Status:** SETTLED
**Topic:** Which plugin owns the hook reaction to a shared Claude Code event

### Design

Each building block owns its own sensory reaction to generic Claude Code
lifecycle events. Consumers add domain-specific context, not duplicate
generic reactions.

| Building block | Owns | Does NOT own |
|---------------|------|-------------|
| **Vox** | Audio reactions: Stop summary, prompt ack, subagent announce, session farewell, permission chimes | Speaking biff messages, narrating z-spec results |
| **Lux** | Display mode toggle, scene lifecycle, interaction handling | Deciding what to display — consumers call `show()` |
| **Biff** | Messaging reactions: PR announce via /wall + /write, unread message check, plan enforcement | Speaking or displaying anything — uses vox/lux as renderers |
| **Quarry** | Knowledge capture: codebase index, WebFetch ingest, compaction transcript, knowledge hints | Rendering search results visually — uses lux as renderer |

**Rule 1: Each building block reacts independently to shared events.**
PR creation is a generic Claude Code event. Vox may speak "PR created."
Biff may suggest `/wall`. Lux waits for a consumer to call `show()`.
These reactions fire in parallel and are additive.

**Rule 2: Building blocks do not call each other for generic events.**
Biff does not call vox to speak on PR creation. Vox speaks on its own
if it's enabled. This prevents duplicate announcements.

**Rule 3: Consumers add domain-specific narration and display.**
Only z-spec can say "Model check passed: 10K states, all visited" —
that's domain knowledge vox doesn't have. Only quarry can compose search
result tables for lux. Domain context flows from consumer to building
block, not the other way.

### Why

During Z specification modeling of biff, vox, quarry, and lux, we
discovered that multiple plugins hook the same Claude Code events
(e.g., PostToolUse on `create_pull_request`). Without ownership rules:

- Biff's `pr-announce.sh` suggests `/wall` + `/write`
- Vox could speak "PR created"
- If biff ALSO tried to speak via vox, we'd get duplicate announcements

The ownership model eliminates this class of bug by giving each building
block a clear lane: vox owns audio, biff owns messaging, quarry owns
knowledge, lux owns display (when asked).

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Single orchestrator for shared events | Over-couples plugins. Each plugin should work independently. |
| Consumers own all reactions (building blocks are passive) | Vox without consumers does nothing on `/vox y` — bad user experience. Building blocks need their own default behaviors. |
| Building blocks coordinate with each other | Violates integration.md: arrows are unidirectional, building blocks never know about consumers. |

### Impact

Three beads were moved from lux (building block) to their correct
consumer projects: beads board refresh → biff, PR dashboard → biff,
quarry search display → quarry. Lux retains only `lux-t1p` (display
mode toggle).

New standard bead `punt-kit-qcs` tracks updating hooks.md and
integration.md with this decision.

## DES-010: Vox vs Lux Activation Asymmetry

**Date:** 2026-03-09
**Status:** SETTLED
**Topic:** Why `/vox y` activates vox's own behavior but `/lux y` only signals consumers

### Design

Vox and lux have asymmetric activation semantics despite both being
building blocks.

**`/vox y`** means "vox, do your thing." Vox has default behaviors that
fire automatically: Stop summary speech, permission chimes, vibe signal
accumulation. A user who installs only vox and types `/vox y` gets a
working product.

**`/lux y`** means "consumers, render visually." Lux has no default
behavior — an empty display window isn't useful. Lux needs a consumer
(biff for beads board, quarry for search results, z-spec for state
diagrams) to call `show()`. The mode flag is an L3 state signal that
consumers check before rendering.

### Why

The asymmetry reflects a fundamental difference in the building blocks:

- **Audio has useful defaults.** Speaking a summary when Claude finishes
  is valuable regardless of what Claude was doing. The content is
  generic (Claude writes it), the rendering is vox's job.

- **Display has no useful defaults.** Showing an empty window, a blank
  dashboard, or a random table is not useful. The content must come from
  a domain owner who knows what data to show and how to structure it.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Symmetric: both activate own behavior | Lux has no own behavior to activate. An empty window is not a product. |
| Symmetric: both only signal consumers | `/vox y` with no reaction is confusing. Users expect voice when they enable voice. |
| Lux auto-displays a session dashboard | Requires lux to know about beads, git, biff — violates building block boundary. |

## DES-011: Formal Z Specification for Hook State Machines

**Date:** 2026-03-09
**Status:** SETTLED
**Topic:** Using Z specifications to model and verify hook integration state machines

### Design

Each Punt Labs tool with non-trivial hook state maintains a Z
specification that models its state machine as a Layer 2 extension of
the base Claude Code state machine. Specifications are type-checked with
fuzz and model-checked with probcli.

The base model (`z-spec/examples/claude-code.tex`) captures Claude
Code's session lifecycle, tool execution pipeline, subagent
coordination, and hook events. Layer 2 models extend it per tool:

| Model | File | States | Transitions | Key Property |
|-------|------|--------|-------------|-------------|
| Base | `claude-code.tex` | 329K | 1.1M | All 8 invariants hold |
| Biff | `claude-code-biff.tex` | 161K | 789K | Plan + bead before editing |
| Vox | `claude-code-vox.tex` | 11K | 48K | No infinite Stop loop |
| Quarry | `claude-code-quarry.tex` | 5K | 23K | WebFetch dedup, compaction lifecycle |
| Lux | `claude-code-lux.tex` | 10K | 56K | Scene requires display |

Each spec includes an **Implementation Validation** section that
cross-references every Z operation against its hook/script/handler,
identifying gaps.

### Why

During the first round of modeling, we found:

- **3 dead handlers in quarry** — Python handlers implemented but never
  wired to hooks.json. All three were P1 bugs (SessionStart sync,
  WebFetch capture, PreCompact transcript capture).
- **1 invariant bug in vox** — `stopHookActive` constraint was too
  strict, preventing the decision-block speak phase. Found in seconds
  by the model checker.
- **2 ghost states in the base model** — `spStarting` and `spEnding`
  declared but unreachable. Caused spurious deadlocks in model checking.
- **1 context overflow deadlock** — context-appending operations could
  deadlock when the context window was full. Fixed with truncating
  append.

These bugs are invisible to testing (the hooks don't have tests) and
to manual review (the wiring gaps span multiple files). The Z spec
catches them structurally.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Informal state diagrams | Cannot verify invariants. Box-and-arrow diagrams miss edge cases. |
| Property-based testing | Tests the implementation, not the design. We need to verify the design *before* building. |
| No formal model | The wiring bugs in quarry would have remained undiscovered. |
| Full composition (all tools in one spec) | State space explosion. Per-tool Layer 2 models keep model checking feasible (~5min per spec). |

## DES-012: Change-Driven Profile Propagation

**Date:** 2026-03-09
**Status:** SUPERSEDED by DES-013 (2026-03-12)
**Topic:** Why the public install URL went stale between punt-kit releases and the automated fix

### Root Cause

The propagation chain for the public install URL has three hops:

```text
Child release (biff, vox, lux, quarry)
  → punt-kit: /punt release bumps install-all.sh SHAs, merges PR to main
    → .github: propagate.yml updates profile README with new install-all.sh SHA
```

Hop 3 only fired when punt-kit itself released — the `.github` repo's
`propagate.yml` required a `tag` input pointing to a punt-kit release tag.
Between punt-kit releases, child project SHA bumps landed on main but the
profile README still pointed to the old punt-kit release SHA.

Result: users who followed the public install URL got stale `install-all.sh`
with old child SHAs, causing version downgrades (e.g. vox 1.2.4 → 1.2.0,
lux 0.5.2 → 0.4.0).

### Fix (Two Parts)

**Part 1: New workflow in punt-kit (`propagate-profile.yml`).**

Triggers on push to main when `install-all.sh` changes. Dispatches the
`.github` repo's `propagate.yml` with the commit SHA:

```yaml
on:
  push:
    branches: [main]
    paths: [install-all.sh]
```

This fires on every `install-all.sh` change — whether from `/punt release`
propagation PRs or manual edits. The trigger is change-driven, not
release-driven.

Both workflows use `secrets.PROPAGATE_TOKEN` (a fine-grained PAT) for
three reasons:

1. **Cross-repo dispatch**: `github.token` is scoped to the current repo
   and cannot dispatch workflows in other repos.
2. **CI triggering on PRs**: GitHub suppresses workflow triggers from events
   created by `GITHUB_TOKEN` (anti-recursion guard). If the propagation
   workflow pushes a branch and creates a PR using `GITHUB_TOKEN`, the CI
   workflows (lint, test, docs) never trigger on that PR. Auto-merge then
   blocks forever waiting for required status checks that will never arrive.
   Using a PAT for checkout (which sets git push credentials) and PR creation
   ensures CI fires normally.
3. **Cascade triggering**: The same suppression applies to merges. If a
   propagation PR auto-merges using `GITHUB_TOKEN`, the resulting push to
   main won't trigger downstream workflows like `propagate-profile.yml`.

The PAT must be configured as a repo secret (not org secret) on each repo
that runs propagation workflows. Required permissions:

| Permission | Access | Why |
|------------|--------|-----|
| Actions | Read and write | Dispatch workflows in other repos |
| Contents | Read and write | `enablePullRequestAutoMerge` GraphQL mutation requires it |
| Pull requests | Read and write | Create PRs, enable auto-merge |

**Critical:** `Contents: Write` is required for `enablePullRequestAutoMerge`
even though it appears to be a pull request operation. Without it, the mutation
returns "Resource not accessible by personal access token" with no indication
of which permission is missing.

**Part 2: Modified `.github` propagate.yml to accept SHA input.**

Added optional `sha` input alongside existing `tag` input. SHA takes
precedence when both are provided. Branch naming uses tag if available,
otherwise SHA prefix.

The tag path still works for punt-kit releases. The SHA path handles
inter-release propagation from child projects.

### Why Change-Driven, Not Release-Driven

The previous model assumed the profile only needed updating on punt-kit
releases. This was wrong — child project releases change `install-all.sh`
on main without a punt-kit release. The gap window between a child release
and the next punt-kit release could be days or weeks, during which the public
URL served stale content.

Change-driven propagation closes this gap by reacting to the actual file
change, regardless of what caused it.

### Propagation Chain (Complete)

```text
Child release (e.g. vox v1.3.0)
  → punt-kit: /punt release Phase 8 bumps install-all.sh SHA, creates PR
    → punt-kit CI: PR merges to main
      → punt-kit: propagate-profile.yml fires (install-all.sh changed)
        → .github: propagate.yml creates PR to update profile README SHA
          → .github CI: PR auto-merges
            → Public URL serves current install-all.sh
```

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Bundle profile update into `/punt release` Phase 8 | Only fires on punt-kit releases, same gap. Child releases still orphaned. |
| Cron job to sync profile SHA | Unnecessary polling. The change event is available — react to it. |
| Single workflow that does both install-all.sh bump and profile update | Mixes concerns across repos. Each repo owns its own propagation step. |
| Manual profile updates | Error-prone, already proved unreliable (the bug we're fixing). |

### Discovery Chain

1. User ran `install-all.sh` from the profile README URL — got vox 1.2.0 and lux 0.4.0 instead of 1.3.0 and 0.6.0
2. Traced profile README: SHA pointed to punt-kit v0.5.0 tag commit
3. v0.5.0 `install-all.sh` had old child SHAs — correct at release time, stale now
4. PR #50 fixed SHAs on main, but `.github` profile never updated
5. Root cause: `.github` `propagate.yml` only triggered on punt-kit release tags
6. Fix: new `propagate-profile.yml` in punt-kit, modified `propagate.yml` in `.github`
7. Propagation PRs auto-merge failed: `enablePullRequestAutoMerge` returned "Resource not accessible by personal access token"
8. Red herring: suspected org approval policy for fine-grained PATs — changing it had no effect
9. Actual root cause (two bugs):
   a. PAT missing `Contents: Read and write` — required by `enablePullRequestAutoMerge` despite being a PR operation
   b. Workflow used `GITHUB_TOKEN` for branch push and PR creation — GitHub's anti-recursion guard suppressed CI triggers, so required checks never ran and auto-merge blocked forever
10. Fix: added `Contents: Write` to PAT, switched all workflow steps to use `PROPAGATE_TOKEN`
11. Verified: `.github` PRs #20 and #21 auto-merged end-to-end (PAT enabled auto-merge → CI triggered → merge fired in ~36 seconds)

## DES-013: Local Sibling Propagation

**Date:** 2026-03-12
**Status:** SETTLED
**Topic:** Why cross-repo propagation uses local git operations instead of GitHub Actions workflows

### Problem

The GitHub Actions propagation architecture (DES-012, v0.3.0–v0.7.1) dispatched
workflows in three repos, each creating and auto-merging PRs via
`PROPAGATE_TOKEN`. This failed on every release attempt with six distinct
failure modes: secret misconfiguration, merge conflicts, stale PRs, race
conditions, silent failures, and CI trigger suppression.

### Key Insight

All propagation targets are sibling directories in the workspace. The developer
has push access to all of them. Every propagation is a deterministic text
substitution. There is no need for remote workflows, secrets, PRs, or async
coordination.

### Design

Phase 8 of `punt release` performs direct `git commit && git push` on sibling
repos. Four sub-steps in fixed order:

| Sub-step | Target | What changes |
|----------|--------|-------------|
| 8a. install-all.sh | `../punt-kit` | Project's curl SHA → tag commit SHA |
| 8b. Marketplace | `../claude-plugins` | `version` + `source.ref` in marketplace.json |
| 8c. Profile | `../.github` | install-all.sh URL SHA in profile/README.md |
| 8d. Website | `../public-website` | `version` + `installCommand` SHA in projects.json |

Before modifying any sibling: resolve path, confirm `.git` exists, confirm on
`main`, confirm clean working tree, `git pull --ff-only`. If any check fails,
the release halts.

Each sub-step is idempotent — checks for a diff before committing. Re-running
after interruption skips completed steps.

Phase 9 runs read-only verification across all repos (tag, version consistency,
changelog, sibling artifacts, PyPI).

### Workspace Assumption

All required sibling repos must be checked out as direct children of the same
parent directory. The release tool resolves siblings via `root.parent / name`.
Required siblings for a full punt-kit release: `punt-kit` (self), `claude-plugins`,
`.github`. Optional: `public-website` (skipped gracefully if absent).

### Why

The local approach eliminates every failure mode of the remote approach:

- **No secrets**: push access is the developer's existing SSH/HTTPS credential.
- **No PRs**: direct push to main means no merge conflicts, no stale PRs.
- **No async**: operations are synchronous. If it fails, it stops immediately.
- **No race conditions**: 8a completes and pushes before 8c reads the result.
- **Deterministic**: regex substitution on local files. Same input → same output.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| GitHub Actions workflows with `PROPAGATE_TOKEN` | Failed on every release. Six distinct failure modes (see DES-012 history). |
| GitHub Actions with `GITHUB_TOKEN` | Cannot dispatch cross-repo workflows. CI trigger suppression blocks auto-merge. |
| Local propagation via PRs (not direct push) | Adds unnecessary complexity. The developer has push access; the sibling is on main with a clean tree. A PR adds a review step to what is a deterministic text substitution. |
| Clone siblings on-demand (not require checkout) | Slower, requires network access, and the developer should already have siblings for development. |
| Walk up directory tree to find siblings | Over-engineered. All Punt Labs repos are direct children of the same parent. Single-level lookup is sufficient. |

### What Was Deleted

| File | Repo |
|------|------|
| `.github/workflows/propagate.yml` | punt-kit |
| `.github/workflows/propagate-profile.yml` | punt-kit |
| `.github/workflows/propagate.yml` | claude-plugins |
| `.github/workflows/propagate.yml` | .github |
| `playbooks/release.yaml` | punt-kit |
| `PROPAGATE_TOKEN` secret | all repos (manual cleanup) |

## DES-014: Resume-From Version Detection

**Date:** 2026-03-12
**Status:** SETTLED
**Topic:** How `punt release --resume-from` determines the target version without explicit input

### Design

Version auto-detection uses two strategies based on whether this is a fresh
release or a resumed one:

- **Fresh release (`start == 1`)**: Derive version from CHANGELOG.md's
  `[Unreleased]` section using `_suggest_version()`. This computes the next
  version based on the change types present (breaking → major, feature → minor,
  fix → patch).

- **Resumed release (`start > 1`)**: Read version from `pyproject.toml` on
  disk. When resuming, the on-disk state is the source of truth — it may have
  been bumped by a previous Phase 2 run.

In all cases, the user can pass the version explicitly to override auto-detection.

### Why

The two strategies have complementary failure modes when Phase 2 (version bump)
is in an ambiguous state:

| Strategy | Phase 2 already ran | Phase 2 hasn't run |
|----------|--------------------|--------------------|
| Changelog (`start <= 2`) | **Dangerous**: empty Unreleased → wrong version → propagates to siblings | Correct: suggests next version |
| Pyproject (`start == 1`) | Correct: reads bumped version | **Safe**: reads old version → Phase 2 is a no-op → user retries with explicit version |

The changelog strategy's failure (wrong version silently propagated) is
irreversible and affects multiple repos. The pyproject strategy's failure
(visible no-op) is self-correcting. The design doc examples always show
explicit versions with `--resume-from`, reinforcing that auto-detection is
a convenience for fresh releases only.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| `start <= 2` (always use changelog) | Silent wrong version when Phase 2 already ran. This was the original Bugbot finding. |
| Detect whether Phase 2 ran (compare changelog vs pyproject) | Over-engineered for an edge case. Users should pass the version explicitly when resuming. |
| Require explicit version when resuming | Too restrictive. `--resume-from propagate` (Phase 8+) is the common recovery case, and pyproject.toml reliably has the right version by then. |
