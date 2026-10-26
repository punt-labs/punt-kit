# Shared architecture and required remediation

Research baseline • 2026-09-12 · Priority revision • 2026-09-13

**Active scope: OpenCode P1 and pi P2. Codex is deferred.** Shared core repairs and existing Claude compatibility remain required. Codex-specific paragraphs below retain design research for later reactivation and are not active requirements. [Decision and consequences](decisions.md).

These decisions apply to all nine repository plans. Existing settled product requirements remain constraints unless a specific amendment is identified. The user explicitly includes technical and design debt that makes native support easier and cleaner; the adapter boundary is an architectural result, not a restriction against changing core code.

## 1. Product core, native adapter, and distribution are different things

Preserve the [projection model](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/standards/architecture.md): one engine, one implementation of each capability, thin public clients. A native harness package can contain tools, lifecycle behavior, workflows and UI; it is not necessarily just an MCP distribution channel. Update that narrower wording in the current standards.

| Owner | Responsibilities | Must not own |
| --- | --- | --- |
| Tool engine/command service | Product state, domain validation, authorization/trust, durable jobs, idempotency, session preferences, artifact records | Harness prompt formatting or terminal widget behavior |
| Public client surface | CLI arguments/JSON, MCP schema/annotations, HTTP/WS transport, typed client requests/results | A second implementation of send, search, playback, identity or scene ownership |
| Native adapter | Native session context, tool registration, event translation, subscription lifetime, user/model delivery, UI and native workflow orchestration | Claude event simulation, a duplicate engine, mutable global “current session” |
| Punt-kit | Standards, schema/fixtures, package metadata/auditing, release coordination, common tests | Mandatory runtime control of every peer's process or a universal harness wrapper |

Extract common command services before adding new callers when logic currently lives in CLI/MCP/hooks. Biff's daemon extraction, Beadle's mail policy service, Vox's state relocation and Punt's structured findings are concrete required changes. Preserve already-completed Lux Hub work; finish missing client paths rather than replacing that architecture.

Shared code is warranted for repeated mechanics after validating two real adapters: validated process/JSONL clients, version negotiation, cancellation and ownership cleanup. Do not translate the active harnesses into a fictional Claude-like event model. Shared fixtures express product invariants; each adapter tests its actual native events.

## 2. Explicit context and authoritative state

Adopt a versioned logical client context, implemented through each tool's public contracts:

| Field | Meaning |
| --- | --- |
| harness and client surface | `codex`, `opencode`, `pi`, `claude`, standalone CLI or another explicit client |
| native session ID | Host's conversation identity; never a guessed PID or shared cwd |
| runtime/connection ID | One live attachment/lease; distinct even when two processes resume the same history |
| branch/head and source lineage | Host branch/leaf position, parent history and stable capture source IDs; a changing leaf is not a stable branch ID |
| actor and parent | Native agent/child identity plus optional Ethos persona/delegation mapping |
| repo/worktree | Explicit canonical execution root and worktree identity; shared repository ID where needed |
| turn/call/event ID | Correlates operations and suppresses retries; not a substitute for actor identity |
| capability/binding version | Negotiated authority/context binding and supported contract version |

This is a semantic schema, not a claim that every MCP host exports these fields. Validate available fields at the adapter boundary and reject ambiguity for stateful operations. Do not put invented authoritative IDs into prompts and hope the model copies them accurately.

The engine stores product state keyed by the appropriate scope. Repo defaults, user preferences, session overrides and device ownership are separate scopes. Session overrides must not race to rewrite a shared repo file. The adapter carries the context only it can originate and pushes it to the engine. Subscription handles and UI registration tokens remain adapter-owned; domain state and durable delivery cursors remain product-owned.

**Deferred Codex context gate:** native hooks provide session/call context, but documented automatic per-call MCP propagation is not established. Prove a supported channel in stock CLI and the intended desktop client. A candidate is synchronous native PreToolUse input enrichment backed by engine-validated bindings. Test hook failure/trust changes and all tool execution paths. This candidate is not yet an authenticated design. If it fails, the required session-aware feature gets an upstream capability task; no process-tree guessing, parent-environment mutation, shared pointer file, or wrapper becomes the release path. See [Codex research](harnesses/codex.md).

**OpenCode:** prefer native typed tools for stateful product calls, passing the actual tool callback's session context to the public CLI/API. A server plugin can host many sessions. Use existing MCP only where semantics are stateless or a verified per-call identity channel exists; never register a duplicate stateful tool set just to claim both integrations. See [OpenCode research](harnesses/opencode.md).

**Pi:** get session/runtime/branch context from the native extension APIs. New/resume/fork/reload tears down/replaces the runtime; tree navigation requires branch-sensitive refresh. Stop stale callbacks with generation tokens and abort signals. `ETHOS_SESSION` is a supported explicit CLI channel, but an extension must bind it for each owned subprocess rather than mutate the parent or rely on a once-exported shared environment. See [pi research](harnesses/pi.md).

Existing Ethos session primitives are reused and extended. Ethos is not a mandatory runtime dependency for basic operation of every tool. When enabled it supplies persona, lineage and mission contracts. Where a product explicitly requires Ethos authority, preserve that requirement: Biff's signed-author/delegation verification names Ethos as registry; unsigned messages remain possible with the prescribed unverified classification.

## 3. Domain authorization and harness permissions

Separate three claims:

1. **Engine authorization:** what the authenticated actor may do to mail, messages, files owned by the service, audio queues, scenes and missions. Every public surface enforces the same policy at the actual operation. Identity/display labels do not confer authority.
2. **Harness tool policy:** what the model may call. Native hooks/rules improve workflow enforcement, but must be tested against builtins, shell, MCP, native tools, nested/code-mode calls and subagents. A configured hook is not proof it loaded or covers every operation.
3. **OS containment:** what a process/extension/worker can access. Trusted extension code and arbitrary CLI/HTTP calls bypass model-only tool interception. High-risk worker requirements need real process/filesystem/network/credential controls.

Beadle currently exposes a concrete MCP/CLI policy mismatch; repair it before native callers use its CLI for protected mail operations. Biff's automatic message injection is gated by the existing authenticity/delivery-policy program. Keep Beadle GPG and Biff's specified Schnorr design separate. Do not introduce a new cryptographic stack merely to unify names.

For Ethos, publish a precise enforcement-coverage declaration. A plan/mission pre-tool gate cannot honestly claim universal prevention of filesystem writes when the harness does not intercept all subprocess activity. Enforce Punt-owned operations in the service; specify bounded native guard coverage for generic workspace edits; provide an isolated execution lane where stronger guarantees are required. Fail required features visibly when the necessary guard/binding is unavailable.

Retain native user authorization and scope. Never translate Claude `allowed-tools` into automatic OpenCode grants or assume pi has permission prompts. Native installation/trust is not authorization to send mail, inject a turn, launch a worker or publish a release. Conversely, do not add repeated confirmation dialogs for actions already authorized by the operator or tool policy.

## 4. Public operation and event contracts

Each repository identifies the actual operations it owns and the missing public doors required by the new callers. Keep existing operation vocabulary; coordinate genuine renames through the existing cross-surface train. Do not force REST or MCP into prompt-native products.

Minimum contract for finite operations:

- Typed arguments/results, explicit resource IDs and locations, validation independent of the harness.
- Machine-readable success and failure, documented stdout/stderr behavior and exit status, bounded output, no terminal-string parsing. Where current CLIs differ, normalize the shared command result and declare the migration.
- Request cancellation, timeout semantics and job status for long work. Cancellation must reach owned children and network operations.
- Read/write/destructive annotations and real failure propagation through MCP and native tool APIs.
- Version/capability negotiation and actionable unsupported-version errors before mutation.
- Idempotency keys for externally visible retriable operations; duplicate invocation must not duplicate mail, chat, speech, releases or scene teardown.

Long-running subscribers use public product feeds (JSONL or the product's existing authenticated streaming protocol). Define event ID, ordered sequence/cursor, type, origin, recipient scope, schema version and payload/reference. Do not promote an internal unread/status file or an unstable harness transcript to the integration protocol.

Distinguish receipt by a service, acceptance by the harness, model consumption and user-read state. An OpenCode HTTP 204 or successful `codex queue` command is not proof the message became a processed turn. Exactly-once model execution is not promised; use durable delivery states, idempotent submission where available, deduplication and explicit uncertainty after crashes. Never blindly acknowledge on an in-memory transcript transformation.

Choose notify-only, next-turn, or authorized wake from product delivery policy. External content stays attributed data. Stop self-prompt loops using causal origin IDs, one session drain, bounded batches and retry ceilings. A harness-generated response must not re-trigger the same notification indefinitely.

## 5. Guidance and workflow ownership

Maintain semantic workflow content and supporting assets as product-owned resources outside the Claude-only surface. Package neutral skill content unchanged when it actually is portable; author native invocation/orchestration separately where tool names, role APIs, questions, arguments or permissions differ. Mechanical packaging/schema generation is encouraged. A converter that rewrites Claude commands into each host's syntax is not the source of truth.

Native project guidance uses AGENTS.md or the host's explicit instruction/skill discovery. Claude `@` imports are not assumed to work in AGENTS.md. Keep user-owned guidance intact and remove only owned insertions/resources. Test progressive disclosure and install-all-nine prompt size; do not eagerly load the entire toolkit manual into every session.

Prompt-native does not mean untestable. PRFAQ and z-spec need fixed input fixtures, expected artifacts/provenance, deliberate cancellation, and native independent review/delegation. Pi has no stock subagent facility: the shared `HOST-PI-DELEGATION` component, owned by punt-kit and bundled as an optional native helper, must own a released SDK/JSON subprocess workflow with explicit lineage, limits and cancellation. Calling the same agent a “reviewer” is not independent evaluation.

Keep operator-only automation explicit. Codex implicit skill invocation can be disabled through its native metadata; OpenCode/pi frontmatter does not inherit Claude's permission semantics. Use explicit native command entrypoints and host permissions for releases, with shared playbooks owning procedure and deterministic commands owning execution.

## 6. Installation and distribution contract

Maintain independent per-product artifacts under proposed `integrations/opencode/` at P1 and `integrations/pi/` at P2; reserve `integrations/codex/` for deferred work; the existing `plugin/` remains the Claude adapter. Shared workflow assets live in a product-owned neutral location and are included in each release artifact. Paths are proposals for new work, not existing directories.

Proposed npm names follow `@punt-labs/<tool>-opencode` and `@punt-labs/<tool>-pi`; use `punt` for punt-kit's CLI-facing short name. Check registry availability before publication. On reactivation, keep Codex native package identity aligned with the product. Native user-command syntax may differ; help documents the exact spellings, and the all-nine test rejects collisions. Preserve the existing approved bare command exceptions where the host supports them and the product design still calls for them.

Separate four axes:

| Axis | Owner/action |
| --- | --- |
| Core installed on machine | Tool's existing distribution/installer; daemons only where the product requires them |
| Native package registered | Explicit selected harness and scope; use native installer/config mechanism |
| Tool enabled for repo | Owning tool writes its one committed `.punt-labs/<tool>/enabled` marker |
| Session/user preference | Owning engine stores mute/notify/poll/etc. at the intended scope |

`enable` must not detect every installed harness and activate them. A shared repo marker remains host-neutral. Integration registration chooses native host and scope explicitly; repeatable kit-manager commands delegate to each owner. Preserve the old `--no-plugin` contract until the installer standards deliberately migrate it. Do not reinterpret it silently as “disable every harness.”

Native installers should return an owned-change manifest, preserve JSONC/TOML/comments/user instructions, handle global/project duplicates, and remove only owned entries. OpenCode uses its native plugin installer or supported config with server/TUI separation; pi uses native package install/update/remove. Codex catalog/package work is deferred. No edits to another harness's cache or registry.

Release metadata ties core version, adapter version, protocol version and tested harness versions together. Validate source packages and final registry/cache installs. Upgrade, rollback and mixed-version detection must work across channels without reintroducing obsolete names. Existing Claude release/restore machinery remains a separate adapter channel; do not apply its `-dev` file convention to other native hosts by default.

## 7. Media, headless operation and remote hosts

Vox owns synthesis, playback, recording/music state and device contention. Lux owns Hub/Display rendering and scene/menu authority. Native TUI affordances are frontends to those products, not rewrites of the audio/render engine. A returned MCP audio block is not proof of audible playback; an HTML artifact is not proof of a native webview.

Distinguish engine host, harness server and user display/audio host. OpenCode server/TUI may be on different machines; pi RPC has a limited UI protocol distinct from its TUI; Codex client UI capabilities vary. Select media target explicitly and validate it. Preserve Vox’s configured voxd audio endpoint; do not silently redirect an existing daemon-based workflow to the TUI machine. Headless operation returns useful artifacts/status and never hangs waiting for an unavailable UI or plays on an unintended server.

Vox live voice launch/steer is a separate controlled-host product flow from installing Vox in an existing coding session. Use each host's supported programmatic channel and real session IDs; no tmux typing fallback. Reconcile existing voice architecture decisions and experimental modes before implementing new launch backends. Beadle workers likewise intentionally own harness jobs, but their SDK/backend use does not replace stock interactive plugin support.

## 8. Standards changes and dependency ownership

Punt-kit must amend `architecture.md`, `cli.md`, `integration.md`, `hooks.md`, `plugins.md`, `distribution.md`, `permissions.md`, `tool-enable-disable.md`, `install-cli-only.md`, `context-mgmt.md` and release standards. Retain the one-engine, one-writer, one-vocabulary principles. Replace Claude-specific universal requirements with a common invariant plus explicit host implementation rules. Resolve doctor/admin-tier contradictory wording before mechanically generating tool sets.

Freeze small shared contracts early, then refine them using real pilots. A standards change alone does not close a product task. A product can develop against a pinned draft contract while the corresponding standard is reviewed; release requires both to agree. Global program coordination belongs in punt-kit; product remediation and native packages belong in their own repositories. Preserve existing parentage and closed prerequisites in Beads, with explicit cross-repository blocking links only where delivery actually requires them.
