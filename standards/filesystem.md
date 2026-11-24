# Filesystem Standards

**Updated:** 2026-11-24

The home tree gives each Punt Labs product one place for its
repository-independent files. [Repository layout (PLD)](punt-labs-dir.md)
governs shared and private repository paths, including the boundary with the
home tree and repository migration.

## Clauses

### FS-1: Keep product-owned machine state in the home tree

**Applies to:** python, go

Use `~/.punt-labs/<tool>/` for product-owned machine- or user-scoped state,
including global configuration and daemon runtime. Do not create a separate
top-level dot-directory for that state.

Host- or platform-managed files stay where their owner expects them. This
includes Claude Code plugins, commands and registrations; OS-managed service
registrations and native preference stores; and standard locations for
binaries and shell completions. User documents and export destinations are
not internal state. A library's choice of default path does not make a
cache it populates on the product's behalf host-managed (FS-4).

### FS-2: Give each product one stable namespace

**Applies to:** python, go

Use one stable `<tool>` for the product's home root across its CLI, daemon
and integrations.
Default to the primary CLI name. For a product without a CLI, or one whose
product namespace differs from its primary CLI name, declare the namespace
explicitly. The declared namespace for `beadle-email` is `beadle`; use
`~/.punt-labs/beadle/` without a rename or migration. This clause does not
change repository paths.

### FS-3: Resolve product-owned home paths centrally

**Applies to:** python, go

Define the product's home root once and derive owned subpaths from that
authority. Resolve the root independently of the working directory. An
unavailable home directory must not produce a fallback into the checkout.

### FS-4: Put owned caches in the product cache directory

**Applies to:** python, go

Default to `cache/` inside the product home root, including for artifacts
the product explicitly downloads through a dependency, such as model
weights. Honor explicit user cache-location overrides. This does not move
independent caches owned and populated by another application.

### FS-5: Put persistent user stores in the product data directory

**Applies to:** python, go

Use `data/` inside the home root for persistent user stores such as
databases and indexes. A store with a separately specified location uses
that location instead.

[LOG-7](logging.md#log-7-log-location) specifies durable diagnostics in
`logs/`; [TEL-5](telemetry.md#tel-5-salted-identifiers) and
[TEL-6](telemetry.md#tel-6-private-local-store) specify the shared salt and
private telemetry store. Reserve `sessions/` for per-Claude-Code-session
state as described in [MCP caller identity §4.2](mcp-caller-identity.md#42-lifecycle).

### FS-6: Do not migrate superseded home directories automatically

**Applies to:** python, go

When replacing a legacy home directory with the canonical root, do not
automatically read, move or delete the superseded directory. The user
decides whether to preserve its data.

### FS-7: Document breaking home-path cutovers

**Applies to:** python, go

When replacing a legacy home directory with the canonical root, record
the old and new paths as a breaking change in the product changelog.
Describe what data users can move manually.

### FS-8: Provision the home tree on install

**Applies to:** python, go

The supported installer creates the canonical home root and required
subdirectories. Repeating installation must not discard existing data.

## Per-Project Activation

See [Tool enablement §2.7](tool-enable-disable.md#27-the-enabled-marker) for
activation markers and [Repository layout (PLD)](punt-labs-dir.md) for the
placement of repository settings.
