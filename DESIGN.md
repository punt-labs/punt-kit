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
