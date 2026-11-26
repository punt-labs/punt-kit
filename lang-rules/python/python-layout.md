---
paths:
  - "**/*.py"
---

# Python Repository Layout

**Introduced:** 2026-11-22 · **Updated:** 2026-11-24

Implements the [repository layout policy](../../standards/punt-labs-dir.md)
and [home filesystem policy](../../standards/filesystem.md).
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
Use the top-level local zone for runtime data, not an in-subtree override
path; the latter is for static settings. The name local is reserved.

## PY-PLD-3: Use the home-path authority

**Implements:** PLD-3, FS-1, FS-2, FS-3 · **Gate:** `review` (storage-boundary evaluator)

Compose the product root with `Path.home()` once in a shared paths module.
Use a resolver function if callers need home lookup at call time. Derive
cache and diagnostic paths from that authority. Review writes at the
storage boundary, including whether the product or an integration host
owns each file. Test the expected namespace with an isolated home (including
alternate entry points, if any), a cwd change and a home-resolution failure.
For diagnostics and telemetry, use the [logging rules](python-logging.md).

## PY-FS-1: Pass product-owned cache and data paths to dependencies

**Implements:** FS-4, FS-5 · **Gate:** `review` (storage-boundary evaluator)

Pass explicit `Path` values from the shared resolver to cache and store APIs
rather than relying on library defaults. Resolve a user cache override
before passing the path to download or cached-read calls. Test both a
download and subsequent cache reuse in an isolated home: assert that both
use `<root>/cache/` by default and the explicit cache override when set.
Assert that a persistent store uses `<root>/data/` by default and, if a
separate location is specified, uses that location instead.

## PY-FS-2: Check install and legacy-directory cutovers

**Implements:** FS-6, FS-7, FS-8 · **Gate:** `review` (storage-boundary evaluator)

Use `Path.mkdir(parents=True, exist_ok=True)` for directories provisioned by
the Python installer. In an isolated home, verify that a fresh install
creates the required directories. Seed the canonical root with recognizable
data and verify its contents are unchanged after reinstalling.
On a cutover, check the changelog and seed the legacy directory with
recognizable data to check that it is neither loaded nor altered.

## PY-PLD-4: Test the ignore boundary with Git

**Implements:** PLD-4 · **Gate:** `punt repo audit`; `uv run pytest tests/test_audit_layout.py tests/test_repo_gitignore.py`

Use these canonical patterns in the root ignore file:

```gitignore
.punt-labs/**/local
.punt-labs/**/local/**
.punt-labs/**/*.local
.punt-labs/**/*.local.*
```

Tooling owns this block: init writes it, rollout propagates it and audit
verifies behavior. Tools must not hand-edit it. A tool's committed ignore
file may add narrower local-convention rules, never replace the block.
The local/** line states descendant intent as defense in depth; the exact
local segment already excludes its directory and contents.

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
Use mode 0600 for credentials stored in a private home-tree file.

## PY-PLD-6: Separate stream and publication writers

**Implements:** PLD-6 · **Gate:** `review` (storage-boundary evaluator)

Give live streams and finalized records distinct path resolvers. Write a
publication to private staging and atomically expose the finalized artifact;
do not continue appending to it. Test empty streams, concurrent writers,
publication failure and consent refusal. Preserve the distinct close-summary
writer when a tool has one.
Preserve the sealing and record-mode invariants in
[the seal contract](../../docs/repo-layout.md#sealing-and-publication-contract).

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
Check that no absolute paths, usernames or machine identifiers remain outside
the declared identity/attribution fields.

## PY-PLD-9: Verify the previous inventory

**Implements:** PLD-9 · **Gate:** `review` (deployment-safety evaluator)

Ship and persist the vendored manifest, including itself in its path set.
Read the previous manifest before writing; overwrite the new set and remove
old-minus-new paths. No read-modify-merge of vendored bytes is permitted.
On bootstrap only, an absent previous manifest means previous = new for
vendored paths. Overwrite existing files there and warn with each differing
file's path. Missing is not the same as unreadable or malformed.
With a previous manifest, an occupied new path outside its set must error,
name the colliding paths and deposit nothing. Reject config, local and marker
paths from both inventories, including on bootstrap. Test repeat output,
bootstrap with changed files and named warnings, real prior inventories,
new-path collisions, pruning, and unreadable/malformed manifests.

## PY-PLD-10: Convert legacy content explicitly

**Implements:** PLD-10 · **Gate:** `review` (migration-safety evaluator)

Read and validate before creating a replacement; translate TOML to YAML rather
than renaming it. Split Vox durable/session fields through ConfigStore's field
sets rather than moving config.md to an unread filename. Detect the legacy
source before any ordinary enablement write creates its destination. Test
empty sources, unknown fields, malformed content, duplicate record IDs and
destination collisions; keep the original on failure. Do not claim a normal
config reader runs a migration merely because the audit names a destination.
An occupied destination must leave both paths unchanged and name both in the
error, even if its contents match. Do not install compatibility readers or
writers; forward integration replaces the legacy location.

## PY-PLD-11: Grade the compatibility inventory per artifact

**Implements:** PLD-11 · **Gate:** `punt repo audit`; `uv run pytest tests/test_adoption_table.py tests/test_audit_layout.py`

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
