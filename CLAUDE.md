# Agent Instructions

This project follows [Punt Labs standards](https://github.com/punt-labs/punt-kit).

## Quality Gates

Run before every commit. Zero violations, zero errors, all tests green.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/ tests/
uv run pyright src/ tests/
uv run pytest
```

## Beads: Dual Role

punt-kit `.beads/` tracks **both** project-specific work (punt-kit tooling, standards doc updates) and **org-wide** cross-project work (CI rollouts, security enablement, multi-repo changes). See the [parent CLAUDE.md](../CLAUDE.md#where-to-create-a-bead) for the full placement scheme.

## Plugin Lifecycle

punt-kit is both a Python package (`punt` CLI) and a Claude Code plugin
(`punt@punt-labs` on the marketplace). The plugin wraps the CLI with slash
commands (`/punt init`, `/punt audit`, `/punt reconcile`).

### Key rules

- **Never hand-edit plugin JSON config files** (`installed_plugins.json`,
  `enabledPlugins`, cache dirs). Use `claude plugin` CLI commands or the
  `/plugin` slash command instead.
- **Plugin changes require a publish cycle**: bump version in `plugin.json` →
  push → update marketplace catalog (`punt-labs/claude-plugins`) → user runs
  `/plugin update`.
- **Dev/prod isolation**: the working tree uses `name: "punt-dev"` so
  developers see both `punt:*` (marketplace) and `punt-dev:*` (local) commands
  side by side. Launch with `claude --plugin-dir .` from the repo root.
- **Can't run `claude` inside a session** — ask the user to run plugin CLI
  commands in a separate terminal when needed.

### Developer launch

```bash
claude --plugin-dir .                       # Load local plugin alongside marketplace
```

### Plugin CLI commands (run from a separate terminal)

```bash
claude plugin list                          # See what's loaded
claude plugin validate .claude-plugin       # Validate plugin structure
```

### Marketplace publish flow

1. Bump `version` in `.claude-plugin/plugin.json`
2. Push to main
3. Update `punt-labs/claude-plugins` marketplace catalog (version + description)
4. Users pick up changes via `/plugin update`

## Standards References

- [Python](https://github.com/punt-labs/punt-kit/blob/main/standards/python.md)
- [GitHub](https://github.com/punt-labs/punt-kit/blob/main/standards/github.md)
- [Workflow](https://github.com/punt-labs/punt-kit/blob/main/standards/workflow.md)
- [CLI](https://github.com/punt-labs/punt-kit/blob/main/standards/cli.md)
- [Shell](https://github.com/punt-labs/punt-kit/blob/main/standards/shell.md)
