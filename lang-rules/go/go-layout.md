---
paths:
  - "**/*.go"
---

# Go Repository Layout

**Introduced:** 2026-11-22

Implements the [repository layout policy](../../standards/punt-labs-dir.md).
The storage-boundary evaluator reviews the consuming tool's tests for these
acceptance cases; this file does not imply that punt-kit executes Go tests.

## GO-PLD-1: Centralize shared path resolution

**Implements:** PLD-1 · **Gate:** `review` (storage-boundary evaluator)

Use `filepath.Join` behind a tool-owned resolver. In Ethos use the established
layout policy and config/bundle resolvers, including ethos.yaml and
ethos-bundles; do not invent a second config location. Test canonical paths,
nested cwd, absent data and invalid path inputs.

## GO-PLD-2: Preserve the store and checkout distinction

**Implements:** PLD-2 · **Gate:** `review` (storage-boundary evaluator)

Resolve S and C before constructing `layout.Policy`. Use LocalRoot for private
data, TraceArchiveRoot for retained traces and CheckoutRecordRoot only for
eligible publication. Use domain-qualified `LockPath` for repository locks,
not an assumed sibling `.lock` filename. Test linked worktrees, invalid roots,
and removal of C while S remains. Never test deletion of S as a preservation
guarantee. Surface lock/path errors without a tracked fallback.
Use the top-level local zone for runtime data; in-subtree local-convention
paths are static overrides. The local zone name is never a tool name.

## GO-PLD-3: Resolve machine data independently of cwd

**Implements:** PLD-3 · **Gate:** `review` (storage-boundary evaluator)

Use the tool's home resolver, with errors propagated, for machine-scoped
profiles, caches and diagnostics. For example mcp-proxy profiles resolve
under the home tree. Test cwd independence, empty configuration and home
resolution/permission errors.
Keep durable diagnostics in logs/ and telemetry in telemetry.db with a 0700
directory and 0600 database and sidecars, separate from logs.

## GO-PLD-4: Verify Git behavior for local names

**Implements:** PLD-4 · **Gate:** `review` (storage-boundary evaluator)

Exercise the actual root ignore file through Git in temporary test repos.
Cover exact local segments, suffix/interior dotted forms, shared counterexamples
and deny-all repositories. Reject tracked local paths, and commit any ignore
file the tool ships. Punt's canonical pattern spelling and compatibility
inventory are in its [layout reference](../../docs/repo-layout.md); do not
duplicate a second pattern generator inside every tool.
The canonical block is tooling-owned, not hand-edited by a tool; additive
narrower local rules are allowed only in a committed tool ignore file.

## GO-PLD-5: Keep secrets out of shared configuration

**Implements:** PLD-5 · **Gate:** `review` (storage-boundary evaluator)

Use explicit credential sources rather than serializing secrets with shared
config. Test shared rejection, supported private credential sources and errors
reading the selected source. A repo-local source requires an explicitly
supporting API and an ignored, untracked destination; do not infer permission
from another tool's API.
Use mode 0600 for private home-tree credential files.

## GO-PLD-6: Distinguish close summaries from session streams

**Implements:** PLD-6 · **Gate:** `review` (storage-boundary evaluator)

Use separate Ethos summary and stream APIs. The close-summary writer appends
to the tracked missions.jsonl; local per-session audit/mission-event writers
must not target it. Finalize publication from private staging with atomic
filesystem operations. Test close summaries, empty streams, concurrent sessions,
failed finalization and record-mode consent.
Preserve the full sealing and record-mode invariants in
[the seal contract](../../docs/repo-layout.md#sealing-and-publication-contract).

## GO-PLD-7: Preserve non-vendored zones

**Implements:** PLD-7 · **Gate:** `review` (storage-boundary evaluator)

Keep shared config and local overlays out of the vendored file writer.
Exercise enable, disable and upgrade with modified config, private data and
a dormant subtree. Activation changes must use the marker API, not directory
presence or config-file existence.

## GO-PLD-8: Check bytes before the shared write

**Implements:** PLD-8 · **Gate:** `review` (privacy evaluator)

Pass records through the tool's redactor and sink guard before persistence.
Use typed record metadata to distinguish declared identity/attribution from
incidental PII. Test empty records, machine paths, third-party information,
declared identity fields and guard failure. Keep originals private when a
publication is withheld.
Replace home and repo prefixes with `~` and `<repo>`; leave no absolute paths,
usernames or machine identifiers outside declared identity/attribution fields.

## GO-PLD-9: Apply the persisted inventory and bootstrap rule

**Implements:** PLD-9 · **Gate:** `review` (deployment-safety evaluator)

Ship and persist a vendored manifest that includes itself. Read the previous
manifest before writing exactly the new set and pruning previous-minus-new;
never read-modify-merge vendored output. On first manifest-aware deployment,
an absent prior manifest means previous = new for vendored paths. Overwrite
those files and warn by path for differing existing content. Do not treat a
manifest read/parse error as absence. On later writes, an occupied new path
outside the previous set is an error naming both paths, with no deposit.
Reject config, local and marker paths from inventories unconditionally:
bootstrap never grandfathers configuration. Test bootstrap overwrite/warnings,
repeat output, old-minus-new pruning, new collisions, protected-zone paths
and manifest errors.

## GO-PLD-10: Validate before relocating

**Implements:** PLD-10 · **Gate:** `review` (migration-safety evaluator)

Classify source records with the tool's schema, then validate and write the
destination before retiring the source. Preserve mission summaries in the
shared summary history; do not classify every JSONL as a private trace.
Detect source/destination collisions before normal enablement creates files.
Test malformed/empty input, duplicate IDs, conflicting destinations and failed
writes; retain originals on failure and report what was not moved.
An occupied destination always errors and names both paths without changing
either, even if contents match. Use forward integration, not a compatibility
reader or writer at the old location.

## GO-PLD-12: Verify published provenance without a network dependency

**Implements:** PLD-12 · **Gate:** `review` (audit-integrity evaluator)

Check the publication format's manifests, hashes and provenance against the
repository's bytes. Test valid, absent, missing-manifest and corrupted
publications and gitlinks concealing the history. Respect the record-mode
boundary: retained private archives are not shared records to copy in order
to satisfy a verifier.
