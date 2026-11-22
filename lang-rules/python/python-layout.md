---
paths:
  - "**/*.py"
---

# Python Repository Layout

**Introduced:** 2026-11-22

Implements the [repository layout policy](../../standards/punt-labs-dir.md).
Review gates below mean the storage-boundary evaluator checks the named
acceptance cases in the consuming tool; they do not claim punt-kit supplies
runtime tests for every tool.

## PY-PLD-1: Resolve declared shared paths

**Implements:** PLD-1 · **Gate:** `review` (storage-boundary evaluator)

Centralize `pathlib.Path` resolution rather than constructing alternate roots
in each entry point. Test the declared canonical path from a nested working
directory, a missing config, and a malformed config. Keep legacy discovery
out of normal readers. Use Biff's YAML API, Vox's ConfigStore and Lux's
ConfigManager as tool-specific path authorities, not a uniform config filename.

## PY-PLD-2: Resolve the private store before writing

**Implements:** PLD-2 · **Gate:** `review` (storage-boundary evaluator)

Pass the resolved store root to private writers. Test a main checkout, a
linked checkout whose store is elsewhere, and a missing or invalid store.
Keep temporary publication bytes local until finalization. Never silently
fall back to a tracked directory on a path or permission error.

## PY-PLD-3: Use the home-path authority

**Implements:** PLD-3 · **Gate:** `review` (storage-boundary evaluator)

Use the tool's home resolver for caches and diagnostics. Test that changing
cwd does not change machine-scoped paths and that an unavailable home root
produces a visible error rather than a repo-local fallback.

## PY-PLD-4: Test the ignore boundary with Git

**Implements:** PLD-4 · **Gate:** `punt audit`; `uv run pytest tests/test_audit_layout.py tests/test_repo_gitignore.py`

Use these canonical patterns in the root ignore file:

```gitignore
.punt-labs/**/local
.punt-labs/**/local/**
.punt-labs/**/*.local
.punt-labs/**/*.local.*
```

In a deny-all repository, precede them with directory and descendant
re-inclusions, in that order:

```gitignore
!.punt-labs/
!.punt-labs/**
```

Use `git check-ignore` probes and `git ls-files`, not substring matching.
Probe each tool's shared guide/config, local directory, `.local` suffix,
`.local.` interior segment and the `locales` counterexamples; also probe
the reserved local zone. Test normal and deny-all repos, empty directories,
tracked local files, and patterns overridden later in the ignore file.
Commit tool-shipped ignore files. Keep compatibility excludes and their
lifecycles in [punt's layout reference](../../docs/repo-layout.md).

## PY-PLD-5: Route credentials through the explicit API

**Implements:** PLD-5 · **Gate:** `review` (storage-boundary evaluator)

Reject credentials in shared config. For an API supporting local credentials,
require explicit local selection and verify the destination is ignored and
untracked. Test shared rejection, explicit local success, and a force-tracked
or unignored destination. Do not add a repo-local credential fallback to an
API that does not support one.

## PY-PLD-6: Separate stream and publication writers

**Implements:** PLD-6 · **Gate:** `review` (storage-boundary evaluator)

Give live streams and finalized records distinct path resolvers. Write a
publication to private staging and atomically expose the finalized artifact;
do not continue appending to it. Test empty streams, concurrent writers,
publication failure and consent refusal. Preserve the distinct close-summary
writer when a tool has one.

## PY-PLD-7: Keep configuration out of vendored replacement

**Implements:** PLD-7 · **Gate:** `review` (storage-boundary evaluator)

Use an explicit vendored inventory. Exercise repeat deployment with modified
shared config, local overrides and a disabled marker. A deployment must not
turn an ordinary setting change into a wholesale overwrite of the config
file. Vox's durable/session field routing and Lux's display-mode API are
configuration operations, not permission to replace the subtree.

## PY-PLD-8: Guard the shared-content sink

**Implements:** PLD-8 · **Gate:** `review` (privacy evaluator)

Apply redaction and content checks before the shared write. Replace the home
prefix with `~` and the repository prefix with `<repo>`; reject unresolved
sensitive values. Test incidental third-party information, deliberate identity
fields, an empty record, and a scrubber failure. Do not use a later review
or ignore rule as a substitute for the write boundary.

## PY-PLD-9: Verify the previous inventory

**Implements:** PLD-9 · **Gate:** `review` (deployment-safety evaluator)

Compare old and new inventories before replacement or pruning. On bootstrap,
require a known legacy inventory or verified content identity; otherwise fail
on occupied paths. Test new files, identical known copies, locally changed
copies, unknown collisions, absent manifests and unreadable manifests. Preserve
all config and local-convention data regardless of inventory membership.

## PY-PLD-10: Convert legacy content explicitly

**Implements:** PLD-10 · **Gate:** `review` (migration-safety evaluator)

Read and validate before creating a replacement; translate TOML to YAML rather
than renaming it. Split Vox durable/session fields through ConfigStore's field
sets rather than moving config.md to an unread filename. Detect the legacy
source before any ordinary enablement write creates its destination. Test
empty sources, unknown fields, malformed content, duplicate record IDs and
destination collisions; keep the original on failure. Do not claim a normal
config reader runs a migration merely because the audit names a destination.

## PY-PLD-11: Grade the compatibility inventory per artifact

**Implements:** PLD-11 · **Gate:** `punt audit`; `uv run pytest tests/test_adoption_table.py tests/test_audit_layout.py`

Read concrete paths from `adoption_table.py` and keep its inventory in sync
with [the tool reference](../../docs/repo-layout.md). A row with migrates=False
fails even when named. Distinguish absent, occupied, malformed and unreadable
artifacts; include dangling symlinks in presence checks. Test every row,
unknown bare files, mixed warning/failure cases and both canonical bare-file
exceptions. Gitignore text is a diagnostic, never the behavioral verdict.

## PY-PLD-12: Review publication integrity independently

**Implements:** PLD-12 · **Gate:** `review` (audit-integrity evaluator)

Validate the publication format's manifest, hashes and record provenance
before accepting shared chunks. Test a valid publication, no published data,
a missing/unreadable manifest, corruption and a gitlink hiding the record
tree. Review privacy/consent separately from integrity. Do not interpret
LayoutAudit's gitlink warning as seal-manifest verification.
