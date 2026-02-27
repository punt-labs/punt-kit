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

The installer must `git pull` the marketplace clone before running `claude plugin install`:

```python
def _refresh_marketplace() -> StepResult:
    if not MARKETPLACE_CLONE.is_dir():
        return StepResult("Marketplace refresh", True, "not yet cloned")
    git = shutil.which("git")
    if not git:
        return StepResult("Marketplace refresh", False, "git not found")
    result = subprocess.run(
        [git, "-C", str(MARKETPLACE_CLONE), "pull", "--ff-only"],
        capture_output=True, text=True, check=False,
    )
    ...
```

New users (no clone yet) skip this — `claude plugin install` clones fresh. Existing users get the latest `source.ref` pins.

### Rules

1. **Every marketplace entry MUST have `source.ref` pinned to the release tag.** The release workflow marketplace bump step must update both `version` and `ref`.
2. **Every installer MUST refresh the marketplace clone before `claude plugin install`.** Run `git pull --ff-only` on `~/.claude/plugins/marketplaces/punt-labs/` so existing users pick up ref pins.

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
