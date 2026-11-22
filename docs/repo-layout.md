# Punt layout audit and compatibility reference

The [layout policy](../standards/punt-labs-dir.md) owns the required end state.
This document describes punt-kit's concrete audit inventory and compatibility
behavior. It is not an org adoption table. A row does not establish that a
tool's current enable command implements a migration.

## Ignore behavior

The canonical patterns are in
[PY-PLD-4](../lang-rules/python/python-layout.md#py-pld-4-test-the-ignore-boundary-with-git).
`punt audit` uses Git probes for verdicts; textual block comparison only
explains failures. The probe sets cover every present tool and every live
compatibility path independently, even when the corresponding tool is absent.

Tool-shipped ignore files must be committed. A named compatibility exclude
is accepted only while its concrete path remains in the inventory below.
Remove an exclude in the same change that removes its inventory path, after
preserving the data and updating the writer. The two inventories must not drift.

```gitignore
.punt-labs/quarry/captures/
.punt-labs/vox/ephemeral/
```

These are punt's compatibility excludes, not permission for new tools to put
private data in shared paths. Quarry's capture writer uses the first path;
the second protects older Vox output. Vox's runtime configuration is vox.md
plus vox.local.md, not config.md. Its installer has a separate compatibility
path from `.vox/config.md` to `.punt-labs/vox/config.md`; that intermediate
filename is not read by the runtime configuration API.

## Compatibility inventory

`src/punt_kit/adoption_table.py` mirrors these tables, with a policy clause ID
in each row's `section` field. Tests parse this document and compare every row.
The warning is an operator-facing preservation task, not a promise that a
read or an `enable` invocation will perform it. Biff reads YAML only; its root
TOML requires validated conversion rather than a filesystem rename.

### PLD-10 Root sentinels

| Legacy | Destination | Rule |
|--------|-------------|------|
| `.biff` | `.punt-labs/biff/config.yaml` | Convert TOML settings to YAML; route private credentials to config.local.yaml through the supported API. |
| `.quarry.toml` | `.punt-labs/quarry/config.md` | No migration: a stray, not a Quarry presence marker. |
| `.vox/config.md` | `.punt-labs/vox/vox.md` | Preserve durable settings and split session fields into vox.local.md; do not merely rename a mixed file. |
| `.lux/config.md` | `.punt-labs/lux.md` | Preserve display settings at Lux's canonical bare file. |
| `.biff` / `.vox` / `.lux` | — | Delete only a content-free presence marker after explicit enablement; settings-bearing rows take precedence. |
| `.ethos/missions.jsonl` | `.punt-labs/ethos/missions.jsonl` | Preserve tracked close-summary history; validate records and resolve duplicate IDs without losing conflicting content. |

Classify contents before selecting a destination. Unknown files in a root
directory are not authorization to purge the directory. Refuse unresolved
collisions before creating a destination as part of ordinary enablement.

### Bare-file classification

`.punt-labs/lux.md` and `.punt-labs/ethos.yaml` are canonical shared files.
Other bare files fail unless explicitly declared by policy and implemented in
the audit. An ignored canonical file fails the shared-data check; it is not
a migration warning. The reserved local zone must be a directory.

### PLD-12 Registry gitlinks

| Legacy | Destination | Rule |
|--------|-------------|------|
| `.punt-labs/ethos` gitlink | `.punt-labs/ethos/` | Vendor the intended shared record history before claiming it is independently auditable. |

Any tool-root gitlink warns even if no inventory row names it. Hidden content
is not traversed. Do not infer seal-manifest integrity from this warning or
from a layout pass: LayoutAudit checks tracking/ignore/path properties, not
publication-format manifests or consent correctness. Those require the
publication review gate in PY-PLD-12 or GO-PLD-12.

### PLD-2 Live-state compatibility paths

| Artifact | Live path | Destination | Rule |
|----------|-----------|-------------|------|
| quarry captures/ | `.punt-labs/quarry/captures/` | `~/.punt-labs/quarry/captures/` | Relocate to the home tree if machine-scoped, otherwise use a repo-local local-convention path. |
| vox ephemeral/ | `.punt-labs/vox/ephemeral/` | `~/.punt-labs/vox/` | Relocate machine-scoped output or use a repo-local local-convention path. |
| ethos live logs | — | `.punt-labs/local/ethos/` | Resolve the canonical store; this row has no legacy live path for the layout audit to probe. |

The ethos row neither warns nor creates an ignore exemption: it has no
observed compatibility path. Private retained traces under the canonical
store must not be copied into a checkout merely to satisfy a layout check.

## Grades and diagnostics

- A present, named migrating root artifact warns; a present named
  non-migrating artifact fails; an unnamed prohibited artifact fails.
- A tracked live compatibility path warns. Only its inventoried path may
  supply the corresponding compatibility ignore exemption.
- A stale compatibility exclude fails even if its tool is absent.
- Dangling root symlinks count as occupied, not absent.
- Canonical bare files are not obsolete and must not be ignored.
- Audit messages cite PLD clause IDs; absent artifacts do not borrow a
  sibling artifact's migration state.

## Publication and lock implementation references

Ethos's `internal/layout/policy.go` is the concrete authority for S/C roots,
private trace archives and domain-qualified hashed lock paths. Its
`internal/mission/trace.go` owns tracked close summaries. Its
`docs/storage-layout.md` and `docs/audit-seal.md` describe publication
formats, manifests, atomic staging, ordering, redaction and integrity checks.
Do not replicate those algorithms or a version-based compliance guess in
the language-neutral policy. Review a publication's actual format and bytes.
