# Punt layout audit and compatibility reference

The [layout policy](../standards/punt-labs-dir.md) owns the required end state.
This document describes punt-kit's concrete audit inventory and compatibility
behavior. It is not an org adoption table. A row does not establish that a
tool's current enable command implements a migration.

## Ignore behavior

The canonical patterns are in
[PY-PLD-4](../lang-rules/python/python-layout.md#py-pld-4-test-the-ignore-boundary-with-git).
`punt repo audit` uses Git probes for verdicts; textual block comparison only
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
directory are not authorization to purge the directory. An occupied migration
destination always errors, names source and destination, and changes neither.
Detect the legacy source before ordinary enablement creates its destination.
Operator-directed reconciliation is separate from an automatic relocation.
Retire the old location through forward integration, not compatibility readers
or writers. Pure presence markers are removed only once the subtree and its
enabled marker exist; settings must be preserved first.

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

## Vendored deployment contract

The vendored manifest is shipped and persisted in the subtree, includes itself,
and is distinct from a seal manifest. Read the previous inventory before any
replacement. Write exactly the current set and delete previous-minus-current
paths; do not read-modify-merge vendored bytes. The same tool version and repo
configuration must produce identical output.

On the first manifest-aware write, no previous manifest on disk means the
effective previous set is the new manifest's vendored set. Overwrite those
paths, warning with the name of each existing file whose bytes differ. This
bootstrap grandfather keeps pre-manifest deployments upgradable; it does not
assert that historical authorship can be inferred from a pathname.

After a previous manifest has been persisted, an occupied new-manifest path
absent from that previous set is a collision: error, name both paths and
deposit nothing. Configuration, local data and the enabled marker are outside
the vendored set, including on bootstrap. A manifest cannot claim a config
path: the config-zone carve-out is unconditional, not grandfathered.
An unreadable or malformed manifest is not an absent manifest.

## Sealing and publication contract

The seal implementation preserves the ethos audit-seal invariants; the seal
manifest declares each managed stream explicitly, never by a directory glob.
It is not the vendored deployment manifest. The implementation authority is
Ethos's docs/audit-seal.md invariant block, not a pinned section number.

- Live appends use the session lock and strictly monotonic timestamps:
  ts = max(now, last_ts + 1ns). Seed the floor from the full sealed watermark,
  including sealed chunks, verified quarantine-marker bounds and the frozen
  legacy file's maximum, not just the latest valid chunk.
- Seal at deliberate lifecycle points: pre-commit is primary, mission close
  secondary. Write each chunk once with temp-and-rename; never append to or
  rewrite a chunk. Use no growing tracked audit.jsonl and no merge driver.
- Within a branch lineage, chunk timestamp ranges are disjoint and contiguous.
  A branch rewind may overlap merged history; resolve overlaps at read time.
- Sealing is lossless: every complete live line enters at least one chunk
  after a following seal. Duplicate copies of a (session, ts) line have
  identical bytes. There is no seq field.
- Read the union of chunks and the live tail beyond the watermark. Deduplicate
  post-discipline lines on (session, ts); never deduplicate frozen legacy lines.
  Legacy timestamps precede all post-upgrade timestamps and the pools do not mix.
- A chunk that does not parse whole or whose final timestamp disagrees with
  its filename errors with its name, never disappears silently. Salvage it on
  the next tool run; bypassing verification is not recovery.
- In every Ethos record mode, seal into the owning store's local trace tier.
  Only record: full publishes eligible session chunks into the checkout's
  tracked .punt-labs/ethos/sessions/ tree, adding them at pre-commit. Record:
  blame publishes no trace-tier chunks; blame-tier mission records and closed
  mission exports remain tracked in both modes.
- Vendor a gitlinked record tree before relying on tracked publication. A
  gitlink defers each publication, never local sealing or completion. There is
  no publication spool implied by this rule. Removing a disposable checkout
  distinct from the canonical store does not remove the store's sealed traces.

## Audit probe and grading contract

The root ignore block is tooling-owned: punt repo init writes it, workspace rollout
propagates it, and punt repo audit verifies behavior. Tools may add narrower
local-convention rules in their own committed ignore files, but must not edit
the canonical block. The local/** pattern is defense in depth; local segment
matching already excludes its descendants. Deny-all re-inclusions precede the
four exclusions. All listed compatibility live paths receive excludes in both
normal and deny-all repositories, one row per artifact, never per tool.

For every present tool directory, excluding the reserved local zone and
gitlinks, probe shared CLAUDE.md and config.yaml as not ignored; local/x,
foo.local and config.local.yaml as ignored; and locales/en.yaml and
config.locales.yaml as not ignored. Probe each inventoried live path itself
as ignored, independently of whether its tool is present. Probe the reserved
top-level `local/<tool>/x` path as ignored;
its name must be a directory when occupied. Evaluate Git behavior, including
later overrides, not the presence of canonical text. Include empty directories
and report offending ignore lines as diagnostics rather than verdicts.

Tracked local-convention paths fail. Ignored shared paths fail except the
explicit inventoried compatibility live paths; do not re-fail a sanctioned
live-path exemption in the shared-path check. An exclude for a path no longer
in the inventory fails even if the path or tool is absent. Grade each artifact
by its own row, never a sibling artifact's state. A warning does not escalate
merely with time. The Ethos live-log row is audit-silent because it has no live
path; a tool-root gitlink always warns and its hidden contents are not probed.
The bare-file scan uses the worktree, not only the index, including ignored
and untracked strays. Tool-shipped ignore files must themselves be tracked.

Keep best-effort secret scanning and punt repo scan-pii separate from layout verdicts:
neither is proof of absence or a substitute for writer-side protection. PII
scanning targets tracked .punt-labs content for absolute home paths, email
addresses and .local hostnames. Declared identity fields and explicitly
supported ignored local credentials retain their policy exceptions. Review,
not a static attempt to infer write cadence, catches undeclared live streams.

The canonical-block rollout uses the workspace meta-repo's single-template
pattern, like .bin/envrc-canonical-rollout.sh, not release-process phase 10's
fixed-artifact propagation. Remove each compatibility exclusion in the same
change that relocates its row's live path; generate the list from concrete
inventory paths, never infer it from prose or a tool-wide migration status.
