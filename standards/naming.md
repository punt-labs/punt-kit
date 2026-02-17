# Naming and Versioning Standards

How Punt Labs projects are named, versioned, and identified.

---

## General Rule

The project name is the CLI command name. That same name is used for the GitHub repo, the PyPI package, and the local directory. Do **not** add a `-mcp` suffix — it implies the project is only an MCP server when most of our tools are dual CLI+MCP.

| Component | Convention | Examples |
|-----------|-----------|---------|
| GitHub repo | `<org>/<name>` | `punt-labs/biff`, `punt-labs/quarry` |
| PyPI package | `<name>` (matches CLI) | `biff`, `quarry`, `langlearn-tts` |
| MCP server only (no CLI) | `<name>-mcp` | — (no current examples; avoid this pattern) |

---

## Other Components

| Component | Convention | Examples |
|-----------|-----------|---------|
| CLI command | Short, lowercase, no prefix | `biff`, `quarry`, `langlearn-tts` |
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
