# Repo-Local State Directory Standard

**Introduced:** 2026-07-20 · **Updated:** 2026-11-22

Where repository-bound tool data belongs, who owns it, and which data travels
with Git. The distinction is semantic: shared configuration and closed-mission
summaries are records; running-session streams and machine credentials are not.
Write frequency alone does not decide ownership or tracking.

This policy governs Punt Labs tools written in Python and Go. Third-party
tools retain their own layout. Harness
integration files follow their harness contracts rather than becoming private
tool state: for example, the host import line, `.claude/settings.json`,
`.claude/agents/`, `opencode.json`, and tool-owned CI workflows. See
[tool-enable-disable.md](tool-enable-disable.md) for integration and enablement,
and [filesystem.md](filesystem.md) for the home tree.

Implementation rules live in [Python](../lang-rules/python/python-layout.md)
and [Go](../lang-rules/go/go-layout.md). Punt's concrete compatibility inventory
and audit mechanics belong in its [layout reference](../docs/repo-layout.md),
not in this policy.

## Clauses

### PLD-1: Shared repository data has a declared root

**Applies to:** python, go

Store shared repository-bound tool data under `.punt-labs/<tool>/`, with the
tool's CLI name as the subtree name, except for the declared paths below.
Do not create root-level presence sentinels or private tool dot-directories.
One discoverable root avoids competing sources of configuration and makes
shared tool data reviewable alongside the work it describes.

| Tool | Declared shared paths | Purpose |
|------|-----------------------|---------|
| biff | `.punt-labs/biff/config.yaml` | Shared YAML configuration |
| vox | `.punt-labs/vox/vox.md` | Durable configuration |
| lux | `.punt-labs/lux.md` | Display configuration; a canonical file, not a legacy sentinel |
| ethos | `.punt-labs/ethos/`, `.punt-labs/ethos.yaml`, `.punt-labs/ethos-bundles/` | Repository records, configuration, and source bundles respectively |
| quarry | `.punt-labs/quarry/config.md` | Repository configuration |

These are storage contracts, not evidence of enablement. The committed
`enabled` marker and import contract are defined by
[tool-enable-disable.md](tool-enable-disable.md#27-the-enabled-marker).

### PLD-2: Private repository state stays local to its owning store

**Applies to:** python, go

Place private repository-bound runtime data under
`.punt-labs/local/<tool>/`. It must not enter shared history. This includes
live streams, locks, staging, retained private traces, and scratch. Reserve
`local` as the zone name, never a tool name. Static per-user overrides instead
use local-convention paths within the tool subtree as defined by PLD-4.

Resolve the owning store separately from the current checkout. In Ethos, S is
the canonical store and C is the checkout: private state belongs under
S's `.punt-labs/local/ethos/`; eligible publication targets C's record tree.
Deleting a disposable C distinct from S must not delete S's retained traces.
Deleting S itself has no such preservation guarantee. A path being inside a
repository does not make its lifetime identical to every linked worktree's.

### PLD-3: Repo-independent data belongs in the home tree

**Applies to:** python, go

Store machine- or person-scoped, repository-independent data under
`~/.punt-labs/<tool>/`, not in a repository. This includes caches, daemon
runtime, indexes, cross-repository preferences, and durable diagnostics.
See [filesystem.md](filesystem.md), [logging.md](logging.md), and
[telemetry.md](telemetry.md) for those contracts. A diagnostic that means the
same thing regardless of the triggering repository is not repository data.

### PLD-4: Naming determines the shared versus local boundary

**Applies to:** python, go

Commit tool data by default, except paths marked by the local convention:
a path segment exactly `local`, a name ending in `.local`, or a name
containing the dotted segment `.local.`. These local paths must be ignored
and absent from the index. The boundary is exact: `locales/` and
`config.locales.yaml` are shared names, not local ones.

Examples of private config are `.punt-labs/biff/config.local.yaml` and
`.punt-labs/vox/vox.local.md`. A daemon's successful deliberate change to
shared config does not make the config private. Local naming, not the identity
of the writer or its write cadence, determines whether a setting travels.

### PLD-5: Credentials never enter shared history

**Applies to:** python, go

Keep credentials out of tracked configuration. Prefer the platform secret
store or private home-tree storage with owner-only read/write permissions.
A repository-local credential is allowed
only where the tool's API explicitly supports it, in an ignored local file
excluded from Git. Biff relay credentials in config.local.yaml are such a
case; shared config.yaml is not. Ignoring a file is not protection against
copying or backing up the worktree, so repository-local storage must not be
an implicit fallback for an unsupported credential API.

### PLD-6: Live streams and published records are distinct artifacts

**Applies to:** python, go

Do not append a running-session stream to a tracked file. Keep live streams
and private trace archives in the local zone; publication produces finalized,
immutable, redacted records in the shared record tree under the tool's consent
policy. Never expose a partially written publication as a finished record.

Ethos's tracked `.punt-labs/ethos/missions.jsonl` is a summary of closed
missions, not a running-session stream or a session's sealed chunk. Preserve
its history. Per-session audit and mission-event streams are separate data.
The file extension or an append operation alone cannot establish which class
a record belongs to.

### PLD-7: Tool deployment respects ownership zones

**Applies to:** python, go

Deployments may replace only tool-vendored content. Preserve repository-owned
configuration and user-owned local data; manage the enabled marker through
the enable/disable contract, separately from vendored replacement.

| Zone | Owner | Deployment treatment |
|------|-------|----------------------|
| Vendored guides, skills, agents and inventories | Tool | Deterministic replacement |
| Shared config, including daemon-mutable config | Repository | Preserve except explicit configuration operations |
| Local-convention data | User | Preserve |
| `enabled` marker | Tool through enable/disable | Explicit activation only |

Vox's durable fields are model, notify, provider, speak and voice; its session
fields, including vibe and its cluster, belong in vox.local.md. Lux's display
configuration can change through deliberate display-mode commands and
enablement operations. Neither makes the whole config zone tool-vendored.

### PLD-8: Shared records are safe to distribute

**Applies to:** python, go

Before writing shared tool data, remove absolute paths, usernames and machine
identifiers through redaction
and scrub incidental third-party PII and profanity. Withhold data that cannot
be made safe. Private local/home data is outside this shared-content contract,
not outside the credential rule.

Declared identity fields and deliberate audit attribution are the record's
purpose, not incidental third-party PII to strip. A person's name in their own
identity record differs from personal information leaking into a mission
description about somebody else. Shared history is copied beyond the machine
that produced it, so review after commit is too late to be the privacy boundary.

### PLD-9: Replacement requires verifiable ownership

**Applies to:** python, go

Replace and prune vendored content according to the tool's shipped inventory,
persisted in the subtree as part of that inventory. Write the current set and
remove the previous-minus-current set, producing identical output for the same
tool version and repository configuration. Configuration, local data and the
activation marker are outside this replacement set.

On the first inventory-aware write, when no previous inventory exists on disk,
treat the new inventory's vendored paths as the previous set. Overwrite those
paths, naming each differing existing file in a warning so replacement is
visible. This bootstrap grandfather is a declared ownership rule, not a claim
that filenames establish historical write provenance.

Once a previous inventory exists, an occupied new path absent from it is a
collision: error, name both paths and deposit nothing. A path outside the
vendored zone must not be claimed by an inventory. In particular, a path in
the configuration zone always errors, even on bootstrap; configuration is
never grandfathered. The same protection applies to local data and markers.

### PLD-10: Relocation preserves meaning and content

**Applies to:** python, go

Before removing a legacy artifact, classify its contents and preserve them
in the appropriate shared or private destination. Convert formats where
necessary. An occupied destination is an error: name source and destination
and make no change, leaving reconciliation to the operator. Remove a pure presence
marker only after establishing the replacement enablement signal. A legacy
pathname is neither evidence of live use nor permission to discard data.

For example, root Biff TOML is not YAML and is not automatically consumed by
the YAML configuration API. A mission-summary record belongs with tracked
mission summaries, not with session streams merely because it is JSONL.
Migration must not activate a tool as a side effect of an ordinary read.

### PLD-11: Layout audit grades observed behavior

**Applies to:** python

Determine layout conformance from the repository's actual tracking, ignore
behavior and artifacts, not from the spelling of a canonical text block.
Probe every present tool independently, including local-name counterexamples.
Report tracked private data and improperly ignored shared data as failures.

Compatibility diagnostics must distinguish a known relocatable legacy
artifact (warning), a known forbidden non-migrating artifact (failure), and
an unknown prohibited artifact (failure). An absent artifact cannot inherit
another artifact's warning. Keep compatibility inventories in tool-owned
documentation/data, not in the policy. A passing partial audit must not be
represented as proof of properties it does not examine.

### PLD-12: Shared audit history is independently verifiable

**Applies to:** python, go

Keep published audit history available and verifiable from the repository
alone, without a network fetch of another repository. Published chunks must
carry the integrity and provenance evidence their publication format requires.
An opaque gitlink is not proof that hidden content meets this contract.

Private retained archives do not become public merely to make an audit pass.
Verification of a publication must respect its record mode and consent
boundary; the absence of publication does not authorize copying private data.
