# Naming and Versioning Standards

How Punt Labs projects are named, versioned, and identified.

---

## General Rule

The project name is the CLI command name. The GitHub repo uses the same name.
PyPI packages use a `punt-` prefix to claim the org namespace; the CLI command
drops the prefix. Do **not** add a `-mcp` suffix — it implies the project is
only an MCP server when most of our tools are dual CLI+MCP.

| Component | Convention | Examples |
|-----------|-----------|---------|
| GitHub repo | `<org>/<name>` | `punt-labs/biff`, `punt-labs/quarry` |
| PyPI package | `punt-<name>` | `punt-biff`, `punt-quarry`, `punt-vox` |
| Go module | `github.com/punt-labs/<name>` | `github.com/punt-labs/ethos` |
| CLI command | Short, lowercase, no prefix | `biff`, `quarry`, `vox`, `ethos` |
| MCP server only (no CLI) | `<name>-mcp` | — (no current examples; avoid this pattern) |

---

## Other Components

| Component | Convention | Examples |
|-----------|-----------|---------|
| Slash command | `/<name>` or `/<name>:<subcommand>` | `/prfaq`, `/prfaq:review`, `/z check` |
| Plugin directory | Match the plugin name | `plugins/prfaq/`, `plugins/z-spec/` |
| Bead ID prefix | Auto-detected from directory name | `biff-*`, `prfaq-*`, `quarry-*` |

---

## Versioning

Projects follow **semver** (`major.minor.patch`).

- Plugin projects: version in `plugin.json`
- PyPI projects: version in `pyproject.toml` (and `manifest.json` for `.mcpb` builds — must match)
- Swift projects: version in `project.yml`
- Installers: check out the latest semver git tag
