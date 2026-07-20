# Filesystem Standards

Standards for home directory layout across all Punt Labs projects. Role models: **biff** (reference implementation) and **vox** (early adopter of namespaced paths).

---

## Core Principle

**One namespace, one root.** All Punt Labs tools store user data under `~/.punt-labs/<tool>/`. No tool creates its own top-level dot-directory. This keeps `$HOME` clean and makes it obvious which files belong to which org.

---

## Directory Root

```text
~/.punt-labs/
├── biff/
├── quarry/
├── vox/
├── langlearn/
└── punt/
```

Each tool owns `~/.punt-labs/<tool>/` and may create any structure beneath it. The `<tool>` name matches the CLI binary name (see [cli.md](cli.md) §Command Layers).

### Resolution

Each tool defines a single root constant or function in one central module. All subdirectory paths derive from it — no scattered `Path.home()` calls.

```python
# In src/biff/_stdlib.py (or equivalent central module)
BIFF_DATA_DIR = Path.home() / ".punt-labs" / "biff"
```

For code that needs test mockability (where tests patch `Path.home()`), use a function instead:

```python
def biff_data_dir() -> Path:
    return Path.home() / ".punt-labs" / "biff"
```

Both patterns are valid. The constant is simpler for module-level declarations; the function is necessary when tests mock `Path.home()` at runtime. A tool may use both — constant for imports, function for mockable call sites.

---

## Common Subdirectories

Tools are free to create any subdirectory structure. The following names are reserved conventions — use them when applicable, skip them when not.

| Subdirectory | Purpose | Example |
|-------------|---------|---------|
| `logs/` | Rotating log files (see [logging.md](logging.md)) | `~/.punt-labs/vox/logs/tts.log` |
| `cache/` | Content-addressed or ephemeral cache | `~/.punt-labs/vox/cache/` |
| `data/` | Persistent user data (databases, indexes) | `~/.punt-labs/quarry/data/lancedb/` |

---

## Per-Project Activation

Per-project enablement uses the marker file `.punt-labs/<tool>/enabled` inside
the tool's committed vendored subtree `<repo>/.punt-labs/<tool>/`, written by
`<tool> enable` and deleted by `<tool> disable`
([tool-enable-disable.md § 2.7](tool-enable-disable.md#27-the-enabled-marker)).
This supersedes the bare repo-root sentinel dotfile (`.biff`, `.quarry.toml`)
as the enabled signal. These paths are **not** under `~/.punt-labs/` — they
live in the project directory and are committed to version control.

---

## Migration

When adopting this standard from a legacy dot-directory (e.g., `~/.biff/` → `~/.punt-labs/biff/`):

- **No automatic migration.** The `install` command creates the new directory. The old directory is not read, moved, or deleted.
- **Clean break.** Document the change in CHANGELOG as a breaking change. Users who need old data can move it manually.
- **Installer handles creation.** `<tool> install` creates `~/.punt-labs/<tool>/` and required subdirectories via `mkdir -p`.

---

## What Does NOT Live Here

| Item | Location | Reason |
|------|----------|--------|
| Claude Code plugin files | `~/.claude/plugins/` | Owned by Claude Code |
| Claude Code commands | `~/.claude/commands/` | Owned by Claude Code |
| MCP server registration | `~/.claude/settings.json` | Owned by Claude Code |
| Status line config | `~/.claude/settings.json` | Owned by Claude Code |
| Shell completions | `~/.zfunc/`, `~/.bash_completion.d/` | Shell convention |
| Binaries | `~/.local/bin/` | XDG/FHS convention |

---

## Adoption Status

| Tool | Legacy path | Target path | Status |
|------|------------|-------------|--------|
| biff | `~/.biff/` | `~/.punt-labs/biff/` | Migrating |
| quarry | `~/.quarry/` | `~/.punt-labs/quarry/` | Planned |
| vox | `~/.punt-vox/` | `~/.punt-labs/vox/` | Planned |
| punt | — | `~/.punt-labs/punt/` | N/A |
