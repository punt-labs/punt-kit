# Plugin Development

How to work on the `punt@punt-labs` Claude Code plugin from a punt-kit
checkout. For setup and quality gates, see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Run the Local Plugin

From the repository root, start Claude Code with the plugin loaded from the
working tree:

```bash
claude --plugin-dir plugin
```

Pass `plugin`, not `.`. The marketplace installs the `plugin/` directory, so a
session started with `--plugin-dir .` sets `${CLAUDE_PLUGIN_ROOT}` (the
plugin's root directory) differently from a real install.

In the working tree the plugin is named `punt-dev`, so its commands appear as
`/punt-dev:*` next to the marketplace plugin's `/punt:*` commands. Each command
in `plugin/commands/` has a `-dev` copy (`init.md` and `init-dev.md`, and so
on). The `-dev` commands run the checkout's code with
`uv run --project "${CLAUDE_PLUGIN_ROOT}/.." punt …` instead of the installed
`punt` binary. Releases strip the `-dev` commands and rename the plugin to
`punt`.

To check a plugin change without an interactive session, run a command
headlessly, for example:

```bash
claude -p --plugin-dir plugin "/punt-dev:audit --help"
```

## What the Plugin Contains

| Path | Contents |
|------|----------|
| `plugin/.claude-plugin/plugin.json` | The plugin manifest. It declares no MCP servers; the commands call the `punt` CLI installed from PyPI |
| `plugin/commands/` | Slash commands, in `name.md` and `name-dev.md` pairs |
| `plugin/skills/` | The `auto` skill, which runs playbooks, and the `issue-review` skill |
| `plugin/playbooks/` | The playbook YAML files that `/punt:auto` loads from `${CLAUDE_PLUGIN_ROOT}/playbooks/` |

The plugin does not contain the `punt` program. Users install it separately
from PyPI (the README's Quick Start does both).

## What a Marketplace Install Copies

The marketplace entry uses a `git-subdir` source, which is a cone-mode sparse
checkout of `plugin/`. Cone mode excludes directories but not files at the
repository root. So `src/`, `tests/`, `standards/`, `lang-rules/`, `patterns/`,
`docs/`, `scripts/`, `tools/`, and `.punt-labs/` never reach an
installed plugin, but root files such as `README.md`, `DESIGN.md`,
`CHANGELOG.md`, `AGENTS.md`, and `prfaq.*` do. See DES-025 and DES-028 in
[DESIGN.md](../DESIGN.md).

Two rules follow:

- A command or skill may refer only to paths under `${CLAUDE_PLUGIN_ROOT}` or
  in the user's project. A path elsewhere in this repository does not exist in
  an installed plugin. The `-dev` commands are the one exception, and they are
  never released.
- Do not describe a repository-root file as excluded from the install.

## Publishing a Plugin Change

A plugin change reaches users only after a release: bump the version in
`plugin.json`, push, update the catalog in
[punt-labs/claude-plugins](https://github.com/punt-labs/claude-plugins), and
have users run `/plugin update`. `punt release run` runs these steps; see the
release section of [CLAUDE.md](../CLAUDE.md).
