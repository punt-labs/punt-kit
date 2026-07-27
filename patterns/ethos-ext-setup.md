# Ethos Extension Setup

How tools write session context into ethos identity extension files during
install.

---

## Problem

A tool needs to inject instructions into the agent's context at every session
start and after context compaction. The instructions are tool-specific (memory
commands, search tips, behavioral guidance) but must be delivered through ethos,
which owns session context emission.

Without a standard mechanism, tools either hardcode knowledge into ethos (tight
coupling) or rely on ad-hoc hook output (lost after compaction).

## Forces

- **One-way dependency.** Ethos provides identity. Tools consume identity.
  Ethos must not contain tool-specific code.
- **Survives compaction.** Instructions delivered only at session start
  disappear when context is compacted. They must be re-injected.
- **Idempotent.** Running install twice must not duplicate instructions.
- **Non-destructive.** Users may hand-author YAML with comments. The install
  must not destroy existing content.
- **Batch resilience.** Multiple identities may exist. A malformed file for
  one identity must not abort the rest.
- **Diagnosable.** Missing configuration (no `memory_collection`, no
  `session_context`) must be surfaced, not silently skipped.

## Solution

### Extension file location

```text
~/.punt-labs/ethos/identities/<handle>.ext/<tool>.yaml
```

Each tool owns its YAML file inside the identity's `.ext/` directory. The
file contains tool-specific config keys and a `session_context` key.

### session_context

The `session_context` value is a YAML literal block scalar (`|`) containing
markdown instructions. Ethos emits it verbatim at session start and before
context compaction — no parsing, no tool-specific code in ethos.

```yaml
memory_collection: memory-claude
session_context: |
  ## Memory

  You have persistent memory stored in quarry.
  Collection: "memory-claude"

  To recall: /find <query>
  To persist: /remember <content>
```

### Install logic

During `<tool> install`:

1. Scan `~/.punt-labs/ethos/identities/` for `*.ext/` directories.
2. For each, check for `<tool>.yaml`.
3. If the file exists and has tool config but no `session_context`:
   - Extract config values via `yaml.safe_load` (parse only).
   - **Append** the `session_context` block as raw text — do not
     re-serialize the file through `yaml.dump`.
4. If `session_context` already exists: skip (idempotent).
5. If the file has no tool config: skip (tool not configured for this
   identity).
6. If the file is malformed: log the error, continue to the next identity.

### Raw-append, not round-trip

```python
# Read to detect keys
raw = path.read_text(encoding="utf-8")
data = yaml.safe_load(raw) or {}
if "session_context" in data:
    return "already_set"

# Append without re-serializing
fragment = f"\nsession_context: |\n{indented_body}\n"
with path.open("a", encoding="utf-8") as fh:
    fh.write(fragment)
```

This preserves comments, blank lines, and key ordering in the original file.
`yaml.dump` destroys all three.

### Three-way classification

The install step returns one of three outcomes per identity:

| Result | Meaning |
|--------|---------|
| `updated` | `session_context` written |
| `already_set` | `session_context` was already present |
| `not_configured` | Required config key absent — tool not set up for this identity |

The `not_configured` case is surfaced in install output so users know their
config is incomplete.

### Per-identity exception handling

```python
for ext_dir in sorted(identities_dir.iterdir()):
    try:
        result = write_session_context(quarry_yaml, handle)
        # classify result...
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"{handle}: {exc}")
```

Failed identities are reported but do not abort processing of subsequent
identities.

## Consequences

- **Tools own their instructions.** Adding a new tool's session context
  requires zero ethos code changes.
- **Compaction-safe.** Instructions survive context compaction because ethos
  re-emits them from the extension file.
- **Comment-safe.** Raw-append preserves hand-authored YAML formatting.
- **Diagnosable.** Install output distinguishes updated, already set, no
  config, and failed identities.
- **Extra install step.** Tools that need session context must add a step
  to their install flow.

## Related Patterns

- [Two-Phase Install](two-phase-install.md) — ethos ext setup is Phase 2b
- [Doctor Checks](doctor-checks.md) — validate `session_context` presence
- [CLAUDE.md `@`-import Includes](claude-md-import-includes.md) — complementary
  mechanism for global agent context

## Known Uses

- **quarry v1.8.1** — `quarry install` step 7/7 writes memory instructions
  into `<handle>.ext/quarry.yaml`. See quarry DES-019.
