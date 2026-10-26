# Acceptance: OpenCode P1 and pi P2

There are **18 active certification cells**: nine OpenCode P1 and nine pi P2. The nine Codex cells are deferred in the backlog and carry no active release obligation. All active statuses below are **planned, not certified**. The current work produced research and a plan. It did not install the proposed adapters or run live model, mailbox, audio, or display journeys.

## Common release gates

| Gate | Required evidence | Failure condition |
| --- | --- | --- |
| G01 Native distribution | Install the final versioned artifact in a clean consumer outside the source checkout, with Claude absent. Native discovery and one real operation work. | Requires Claude config/cache, repo-external assets, an editable install or a wrapper required to make the stock interactive harness behave like Claude. Intentionally supervised native worker/voice-host flows are evaluated separately. |
| G02 Scope and ownership | Independent install, registration, repo enablement and preferences; global/project duplicate test; exact update/removal diff. | Enables another harness/repo, overwrites user guidance/permissions, removes unrelated configuration. |
| G03 Public operation parity | Same input through the engine's supported CLI/API/MCP/native callers yields equivalent result, validation, authorization and error semantics. | Native path bypasses domain policy or parses human output. |
| G04 Context isolation | Two sessions in one repo, two repos, two worktrees, parent/child sessions and concurrent resume. Explicit binding is observable. | Identity, selected DB, inbox, voice preference, scene ownership or audit attribution leaks between sessions. |
| G05 Authorization and trust | Deny/missing/stale binding, disabled/untrusted hook/plugin, caller spoofing, replay, and each real side-effect entrypoint. | Model-only hooks are claimed as OS containment, or a fallback silently increases authority. |
| G06 Lifecycle | Start/resume/fork/reload/tree/compaction/cancel/normal exit/crash as available; bounded cleanup and lease expiry. | Duplicate watchers, phantom presence, stale injection, corrupt audit/capture, orphan children. |
| G07 Asynchronous delivery | Active/idle/next-turn, burst/backpressure, disconnect, retry, acceptance/consumption distinction, callback race and causal loop tests. | Lost-but-acknowledged messages, duplicate sends, unwanted wake or unbounded loops. |
| G08 Modes and hosts | Intended interactive, headless and remote modes; UI absence and disconnected frontend. | Hangs for unavailable UI, pollutes JSON protocol, plays/renders on the wrong host. |
| G09 Compatibility | Certified host releases, core/adapter/protocol skew, upgrade, rollback and native loader failure. | Unbounded latest dependency, silently ignored incompatible package, false healthy status. |
| G10 Composition | All nine packages plus an unrelated extension. Optional peers absent; no duplicate tools, native command collisions or conflicting status widgets. | A tool requires another peer unnecessarily, steals the footer/tools, or eagerly loads all manuals. |
| G11 Existing-product regression | Current Claude and standalone CLI/API journeys still work against the repaired core. | Native support forks semantics or breaks current core behavior. |
| G12 Delivery proof | CI artifacts, sanitized native session traces, exact versions, error paths and observable user outcome. | Loader success or mocked hook tests are presented as complete native support. |

Every repository's native adapter tasks include G01–G05 and G09–G12. G06–G08 apply to its declared lifecycle/media/worker behavior; a considered exemption needs a reason in its repository report. Do not attach a streaming-inbox test to a pure PRFAQ skill just for symmetry.

## Product journeys

| Tool | Required journey for each harness | Distinct debt/edge-case proof |
| --- | --- | --- |
| biff | Establish correct presence and `.plan`; list people; exchange and forward directed messages; read/ack; use wall and talk; receive while busy and idle under the [required trust/delivery policy](https://github.com/punt-labs/biff/blob/fdf49f322a58ac04d4c55200b8f22d254889c27f/docs/requirements-biffd-multihost.md). | Daemon owns state; tamper/replay/delegation revocation, intact forwarding provenance and minimum chain trust; trusted attributed injection, verified/unverified wake-only and failed-signature warning without injection; stable route to the right native session; no notification-driven self-loop. |
| beadle | Inspect scoped inbox/trust; read and search; send/reply with an attachment under contact policy; move/mark; opt-in native receive notifications, independent of autonomous execution. Separately execute an authorized email-triggered job using each backend. | CLI/MCP/native policy equality, GPG recipient selection, no shared identity override; isolated job cannot exceed declared capabilities; completion/result/mission-close are verified. |
| vox | Select provider/model/voice; speak; switch mute/notify/vibe; receive one native completion/wait/error cue; record/play/export; music controls; enter/stop supported voice mode. | Per-session state survives adapter reconnect without overwriting another session's preferences; provider/model is valid atomically; no duplicate narration; correct device host and cancellation. Native launch/steer is separately certified. |
| lux | Render scene/table, update it, receive an interaction/menu callback, inspect scoped state and tear down owned content. | Two session owners and two frontends remain isolated; lease/reconnect/dedup correct; existing Hub contract reused; human window position/z-order is respected; renderer outcome actually observed. |
| quarry | Register/sync fixture documents and ingest a URL, search with usable citations, retrieve original source, remember/learn where selected canonical commands require them, switch DB, and capture useful session context. | Explicit session/database selection; no cross-harness or truncated-ID collision; captured origin/branch/trust correct; checkpoint/recovery receipts meet the designed durability guarantee, including crash/replay; HTTP 202 is acceptance rather than indexed/durable completion; bounded task error recovery. |
| ethos | Resolve/declaratively change persona; bind current native session; show roster/roles; dispatch and inspect bounded work; evaluate independently; preserve audit/provenance through lifecycle; test public-key/delegation/revocation contracts with Biff. | Scope and constraints apply at real enforceable boundaries; child actor differs from parent; no PID-only identity; sealed records survive worktree lifecycle; honest host guard-coverage report; owner key remains outside agents and revoked delegation cannot grant owner-derived authority/trust; signature authorship and key-revocation policy remain explicit. |
| prfaq | Start/import product document, research with citations, run interactive and hive meetings with four independent reviewer contexts, preserve door rules/round-two escalation and durable human decisions, incorporate feedback once, vote, streamline, export and produce meeting playback when Vox is present. | Native questions and child workflows operate correctly; no Claude placeholders; packaged templates/reference files resolve; research data cannot rewrite process rules; optional Quarry/Lux/Vox absence has usable fallback. |
| z-spec | Produce a small Z model from code/intent; type-check; run animation and model check; produce reports/partitions/coverage; demonstrate selected refinement/proof/contract workflow and implementation comparison. | Checker setup and file boundaries independent of Claude; no-Z rejection, absent/zero/incomplete distinctions, real supported ProB census versions and B-Method check/animate; solver failure/cancel reflected honestly; proof status never inferred from generated text; reproducible artifacts and native independent review. |
| punt-kit | Load relevant standards, scaffold a fixture, run audit/PII/status, select a repo-scoped backlog, execute explicit automation dry-run and independent judgment audit. | Structured results; correct Beads cwd; no unrequested harness activation; all bundled playbook assets present; publication remains explicit and native permissions apply. |

The repository reports specify which existing capabilities are public today and which operations need implementation. The target artifact's names are not accepted as proof of current APIs. Capture the final canonical vocabulary in each release's public surface inventory.

## Host-specific contract probes

**Codex (deferred; no active probe):** prove context into MCP and CLI calls, parent/child thread identity, shared app/CLI process behavior, hook concurrency, code-mode and `write_stdin` coverage. Prove queue enqueue/start/idle/busy/ack/retry semantics and preservation of thread sandbox/approval policy. Hook async completion alone does not certify idle receive. Packaging uses the current native manifest/metadata in a stock installation. Treat CLI and desktop as separate certification rows where their behavior differs. Optional MCP UI support is not a prerequisite for Lux's own renderer.

**OpenCode:** run two sessions through one server plugin. Verify ordinary/native/MCP tool gate coverage, server `dispose`, TUI disposal, remote attach, input persistence and authorized prompt scheduling outside awaited hooks. `prompt_async` 204 is not consumption. Test experimental code-mode separately. Never rely on the declared-but-uninvoked `permission.ask` hook. Worker tests use the actual supported flags/config and resolve permission requests without a headless hang.

**Pi:** test `session_shutdown`/new runtime on switch/fork/reload and same-runtime `/tree`; use `agent_settled` for idle. Test extension direct exec/HTTP policy in addition to model `tool_call`. TUI and RPC differ even when `hasUI` is true; print/JSON must exit finitely. Native delegation uses released SDK/JSON/RPC with explicit children; no assumed stock subagent/MCP tool and no dependency on unpublished server APIs.

## Certification ledger

Each cell is a separately tracked product outcome, with core and shared prerequisites in [backlog.json](backlog.json). Passing an adjacent cell does not close it.

| Tool | OpenCode — P1 | pi — P2 |
| --- | --- | --- |
| biff | Planned: BIFF-OPENCODE | Planned: BIFF-PI |
| beadle | Planned: BEADLE-OPENCODE | Planned: BEADLE-PI |
| vox | Planned: VOX-OPENCODE | Planned: VOX-PI |
| lux | Planned: LUX-OPENCODE | Planned: LUX-PI |
| quarry | Planned: QUARRY-OPENCODE | Planned: QUARRY-PI |
| ethos | Planned: ETHOS-OPENCODE | Planned: ETHOS-PI |
| prfaq | Planned: PRFAQ-OPENCODE | Planned: PRFAQ-PI |
| z-spec | Planned: ZSPEC-OPENCODE | Planned: ZSPEC-PI |
| punt-kit | Planned: KIT-OPENCODE | Planned: KIT-PI |

The adapter keys name the primary implementation lane. Beadle cells also require the corresponding `BEADLE-WORKER-*` backend and supervisor/contract gates; inbox awareness is opt-in but is a required native capability. Vox cells also require the agreed `VOX-CALL` native voice journey. Punt cells require `KIT-AUDITOR`, manager and policy; PRFAQ cells include `PRFAQ-MEDIA` optional-peer behavior. These composite requirements are explicit in `certification_cells` and each task’s `scoped_outcomes` in the backlog. An OpenCode P1 outcome can pass while the aggregate task remains open for pi P2; it requires its own listed prerequisites and release evidence, not completion of unrelated host lanes. Independent subsets may ship with accurate sub-status without certifying the full cell.

A cell becomes certified only with its product-specific evidence, release artifact and version matrix. Record failed/blocked capabilities separately from passed operations. If a required active-host capability cannot be established, leave that cell incomplete and expose the precise blocker. Deferred Codex findings never block OpenCode or pi. `KIT-FLEET@opencode` is the P1 fleet gate; `KIT-FLEET@pi` is the P2 fleet gate.

## Evidence format and test ownership

Each product owns its acceptance runner and fixtures. Punt-kit owns shared contract samples and a fleet aggregation schema, not one simulator that pretends to be all harnesses. A run record includes repo/core/adapter/harness versions, OS/client mode, scenario ID, input fixture, expected/observed result, sanitized logs, artifact references and pass/fail/blocked status. Record whether evidence is static inspection, executable contract test, real model journey or human-observed audio/display behavior.

Use Linux and macOS where the product declares them supported; add any additional platform only with a concrete product target. Test clean installs outside the developer workspace. Use isolated mail/NATS/service fixtures and designated accounts for integration tests; live user inboxes and current sessions are not test fixtures. Paid model tests are bounded by the task's explicit test budget and produce repeatable artifacts. No implementation task closes on a fabricated “looks good” screenshot or a plan to test later.
