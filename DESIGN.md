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
