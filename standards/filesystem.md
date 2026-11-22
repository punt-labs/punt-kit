# Filesystem Standards

**Updated:** 2026-11-19

Standards for home directory layout across all Punt Labs projects. Reference implementations: **biff** and **vox**.

---

## Core Principle

**One namespace; location keyed by the kind of data.** All Punt Labs state
lives under a `.punt-labs/<tool>/` namespace, and no tool creates its own
top-level dot-directory — at `$HOME` or at a repo root. Which `.punt-labs/`
root a file lands in is decided by **what kind of data it is**, not by a
one-root-wins rule:

| Kind of data | Root | Committed? |
|--------------|------|-----------|
| **(a)** Repo config and first-class repo-bound data — team-shareable | `<repo>/.punt-labs/<tool>/` | Yes |
| **(b)** Repo-bound per-user/per-machine static overrides, and ephemeral per-checkout live state (locks, pre-seal live streams, trace, scratch) | `<repo>/.punt-labs/local/<tool>/`, or a local-convention path within the tool root | No (gitignored) |
| **(c)** Durable diagnostic logs, daemon runtime, caches, and global/machine-scoped config — repo-independent | `~/.punt-labs/<tool>/` | N/A (outside any repo) |

This document governs the **home tree (c)** — `~/.punt-labs/<tool>/`. The
repo tree, rows (a) and (b), is governed by
[punt-labs-dir.md](punt-labs-dir.md); durable logs under (c) are detailed in
[logging.md](logging.md). The namespace keeps `$HOME` and every repo root
clean, and makes it obvious which files belong to which org.

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
| `logs/` | Rotating log files (see [logging.md](logging.md)) | `~/.punt-labs/vox/logs/vox.log` |
| `cache/` | Content-addressed or ephemeral cache | `~/.punt-labs/vox/cache/` |
| `data/` | Persistent user data (databases, indexes) | `~/.punt-labs/quarry/data/lancedb/` |
| `sessions/` | Per-Claude-Code-session state, one directory per `session_id` (see [mcp-caller-identity.md](mcp-caller-identity.md) § 4.2) | `~/.punt-labs/lux/sessions/<session_id>/handle` |

The reserved home-tree file `~/.punt-labs/<tool>/telemetry.db` holds local
usage capture, separate from `logs/` (see [telemetry.md](telemetry.md)). Its
directory is `0700`; the database and sidecars are `0600`, created privately
before SQLite opens them. The shared per-install telemetry salt also lives
under `~/.punt-labs/` at `0600`, never in a repo.

---

## Per-Project Activation

Per-project enablement uses the tool's committed subtree
`<repo>/.punt-labs/<tool>/` — **not a repo-root sentinel file**. Inside that
subtree:

- `config.yaml` (or `config.md`) — tracked shared team config (roster,
  database name, poll interval), the same for everyone working the repo;
- `config.local.yaml` — gitignored per-user override, carrying a local-convention
  name ([punt-labs-dir.md PLD-4](punt-labs-dir.md#pld-4-naming-determines-the-shared-versus-local-boundary));
- `enabled` — the marker file, written by `<tool> enable` and deleted by
  `<tool> disable`
  ([tool-enable-disable.md § 2.7](tool-enable-disable.md#27-the-enabled-marker)).

Shared roots and declared tool-specific exceptions are defined by
[PLD-1](punt-labs-dir.md#pld-1-shared-repository-data-has-a-declared-root).
Private repository state belongs to the owning store's local zone under
[PLD-2](punt-labs-dir.md#pld-2-private-repository-state-stays-local-to-its-owning-store),
not to this home tree. Linked checkouts and canonical stores can differ.
Harness integration paths follow their harness contract.

Preserve legacy contents according to
[PLD-10](punt-labs-dir.md#pld-10-relocation-preserves-meaning-and-content),
classifying shared mission summaries separately from private session streams.
Concrete legacy paths and conversions belong to
[punt's compatibility reference](../docs/repo-layout.md#compatibility-inventory),
not a second placement table here.

---

## Migration

When adopting this standard from a legacy dot-directory (e.g., `~/.biff/` → `~/.punt-labs/biff/`):

- **No automatic migration.** The `install` command creates the new directory. The old directory is not read, moved, or deleted.
- **Clean break.** Document the change in CHANGELOG as a breaking change. Users who need old data can move it manually.
- **Installer handles creation.** `<tool> install` creates `~/.punt-labs/<tool>/` and required subdirectories via `mkdir -p`.

The legacy dot-directory each tool breaks from, and its target:

| Tool | Legacy path | Target path |
|------|------------|-------------|
| biff | `~/.biff/` | `~/.punt-labs/biff/` |
| quarry | `~/.quarry/` | `~/.punt-labs/quarry/` |
| vox | `~/.punt-vox/` | `~/.punt-labs/vox/` |

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
