# OpenCode native harness research

**Program status — 2026-09-13: P1: primary native implementation target.** Technical observations below are the 2026-09-12 research baseline, not a new runtime certification. [Priority decision](../decisions.md).

Research date: 2026-09-12. Scope: harness contracts and implications for Punt Labs, not an audit of Punt repository implementations. Recommendations below require the repository audit to select the final interfaces. No installed configuration was changed; no model invocation or integration runtime test was performed.

## Baseline and evidence

- Installed executable: `/home/jfreeman/.opencode/bin/opencode`; `opencode --version` returned **1.18.27**. Local `opencode --help`, `opencode run --help`, and `opencode plugin --help` were executed.
- Latest official release returned by GitHub releases API: **v1.18.30**, published 2026-09-09T03:34:27Z, commit **3104c1428ec91f809e5ab86631300de41eb6952e**. [Release](https://github.com/anomalyco/opencode/releases/tag/v1.18.30), [immutable source](https://github.com/anomalyco/opencode/tree/3104c1428ec91f809e5ab86631300de41eb6952e).
- Installed-version tag commit: **4b7e19e315cca414121ba1d61523fef74bb3ae8b**. The `packages/plugin/src/index.ts` and `packages/plugin/src/tui.ts` interfaces were fetched at both releases and are byte-identical. Runtime internals were audited primarily at v1.18.30; identical types do not establish identical behavior.
- Development branch was observed at **95daf90670b7c039c436c85537da5fbfe2205b41**, but is not the proposed support baseline.
- Official live documentation was fetched through web access, and selected release-pinned upstream sources were downloaded to `.tmp/native-harness-plan/opencode-source/`. Live documentation is not revision-pinned; source wins where it is more precise. In particular the documentation omits meaningful shipping TUI and lifecycle features.

**Recommendation:** initially certify 1.18.30 and retain 1.18.27 as an explicit compatibility test candidate. Declare an `engines.opencode` range only after executable contract tests pass. Do not write an unbounded “works with OpenCode” claim against moving `dev` or `latest`.

## Native architecture

OpenCode supports first-class integration in its ordinary CLI/TUI: server plugins receive an SDK client, repository context and Bun shell, return hooks and custom tools, and are loaded from project/global config. MCP is also a built-in transport. A separate TUI plugin API provides actual native presentation. The SDK controls the same server architecture used by the stock frontend; it is useful inside plugins as well as for independently supervised workers. None of these require executing Claude Code or translating Claude hook payloads. [Plugin documentation](https://opencode.ai/docs/plugins/), [server architecture](https://opencode.ai/docs/server/), [SDK](https://opencode.ai/docs/sdk/).

Use four independently warranted pieces per product:

1. Product core, CLI/HTTP/MCP operations and durable state owned by that product.
2. Server plugin only for session identity, event adaptation, lifecycle, policy gates, inbox delivery or custom tools requiring live session context.
3. Native command/skill/agent assets for model-mediated workflows.
4. Optional TUI entrypoint for direct user actions, presentation and local media. Every server operation must remain usable when no TUI is connected.

A thin OpenCode adapter is a native integration. A thin adapter to an existing Claude hook script is technical debt. Extract reusable behavior into an ordinary API and rewrite the adapter against OpenCode contracts. Do not force all nine products to publish plugins if a native skill plus existing MCP is the complete product experience; conversely MCP registration alone is inadequate for a product whose expected behavior depends on lifecycle or notifications.

## Capability matrix

Legend: **D** documented public mechanism; **S** shipping public source/API, less completely documented; **E** explicitly experimental; **L** limitation or no verified public mechanism. “Shipping” does not mean exercised end to end in this research.

| Capability | Status and exact mechanism | Planning consequence |
| --- | --- | --- |
| Server extensions | D/S: async JS/TS plugin returning `Hooks`; local files or npm package; SDK client and repo context | Native home for Biff/Beadle lifecycle and Ethos gates |
| Product tools | D: plugin `tool` map or `.opencode/tools/`; Zod schemas; tools can invoke any language | Python products need no TS rewrite of core business logic |
| MCP | D/S: local stdio; remote Streamable HTTP with SSE fallback; OAuth and headers | Prefer existing product MCP for model operations if semantics fit |
| Resources/templates | S: actual list/read resource tools and resource templates in session tool layer | Quarry need not flatten all resources into custom search tools |
| Commands | D: `.opencode/commands/*.md` or `command` config; arguments, model, agent, subtask | Workflow prompts are native, but are model-mediated |
| Skills | D: `.opencode/skills`, `.agents/skills`, global equivalents; lazy native `skill` tool | Share clean skill content, render harness-specific frontmatter/discovery |
| Instructions | D: `AGENTS.md`, explicit config `instructions`; optional legacy discovery | Generate AGENTS/native config, avoid dependence on CLAUDE.md fallback |
| Enforce before tool | D/S: awaited `tool.execute.before`; throw rejects that invocation | Suitable policy gate after coverage tests; not a system sandbox |
| Permission hook | L: `permission.ask` declared in Hooks, but audited current permission engine does not invoke it | Do not use it as enforcement until a contract test demonstrates it |
| Permission rules | D: per tool/pattern `allow/ask/deny`; per-agent and per-session | Explicit worker policy, preserve user policy, no blanket auto-approval |
| Session identity | D/S: hook `sessionID/callID`; custom tool `sessionID/messageID/agent/directory/worktree`; session parentID via SDK | Pass explicit immutable context to cores; one process may serve many sessions |
| Session events | D: created, updated, deleted, status, idle, error, compacted, message events | Session resume/switch is not “created”; idle is not shutdown |
| Server cleanup | S: `dispose(): Promise<void>` invoked by instance finalizer | Stop watches/timers/children; still use leases for crashes |
| TUI cleanup | S: `lifecycle.signal`, `onDispose`, scoped registration cleanup | Client cleanup separate from server/session end |
| Passive inbox/context delivery | D/S: `chat.message` mutable parts; `session.prompt({noReply:true})` persists input without starting a loop | Stable alternatives exist to experimental transcript transform |
| Wake existing session | D/S: `session.promptAsync` / `/prompt_async`; session-scoped standard prompt | Native wake possible; requires routing, idempotency and reentrancy handling |
| Change every model request/history | E: `experimental.chat.messages.transform`, `experimental.chat.system.transform` | Optional version-gated enhancement, not required inbox delivery path |
| Compaction customization | E: `experimental.session.compacting`; post-compaction autocontinue hook also experimental | Durable product state external to summary; compact references only |
| Native TUI UI | S: slots, custom routes, dialogs, keymap commands, prompt controls, read-only session state | Biff unread counts, Ethos identity and Lux controls can be truly native |
| Notifications/sounds | D/S: SDK toast; TUI attention notify and soundboard | Respect frontend attention preferences; backend cannot assume local sound device |
| Rich audio/MCP Apps webview | L: no verified generic embedded webview or playable arbitrary MCP audio part | Lux renderer remains owned external surface; Vox media returns artifacts/URLs plus native controls |
| Subagents | D/S: named primary/subagents, task tool, child sessions; source has background task mode | Native delegation possible, retain parent lineage and child permission policy |
| Durable scheduler | L: plugin process can watch/timer, no verified persistent plugin scheduling API | Product/service owns durable schedules, delivery cursor and restart recovery |
| Hard job dollars/tokens budget | L: no verified native per-job hard budget API; agent `steps` documented | Beadle supervisor must enforce runtime/cost ceilings and cancellation |

Sources: [server plugin contract](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/plugin/src/index.ts), [tool contract](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/plugin/src/tool.ts), [TUI contract](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/plugin/src/tui.ts), [session tool wiring](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/tools.ts), [permission engine](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/permission/index.ts), [MCP implementation](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/mcp/index.ts).

## Lifecycle, gates and identity: details that affect correctness

Server plugin inputs include `project`, `directory`, `worktree`, SDK `client`, `serverUrl`, and Bun `$`. Initialization is attached to a directory/instance, not necessarily one conversation. Product presence must be keyed by harness + project/worktree + session, with parent session identity when appropriate. Query SDK session metadata where a hook lacks the agent or parentID; never use PID or CWD alone as an agent identity. [Input and hook types](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/plugin/src/index.ts#L57).

The plugin runtime awaits named hooks in sequence. `tool.execute.before` precedes builtin/custom tool execution and ordinary MCP calls. Throwing rejects execution. However hook ordering means a later plugin can mutate arguments after an earlier policy check; validation should be repeated by product cores at actual side effects. The host's permission rules remain necessary. The experimental code-mode path returns before ordinary MCP wrapping, so test code-mode explicitly before claiming universal MCP gate coverage. Direct external CLI/HTTP clients, plugin initialization side effects and arbitrary trusted plugin code are outside a model-tool hook's jurisdiction. Do not characterize the hook as an OS sandbox. [Gate call sites](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/tools.ts#L101), [code-mode branch](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/tools.ts#L388).

Two important source findings: generic `event` callbacks are started without awaiting their promises; a plugin must catch failures and serialize its own work. Plugin load/config errors are logged and ignored. Ethos cannot infer that a configured plugin is enforcing policy: doctor/handshake and integration acceptance tests must verify successful activation, while product authorization belongs in the core. Server `dispose` is now explicitly invoked by a finalizer. A crashed process cannot guarantee disposal; presence and job ownership need expiring leases. [Runtime: errors, event dispatch, disposal, hook sequencing](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/plugin/index.ts#L230).

`session.idle` is emitted whenever status becomes idle; it is neither a permanent close event nor permission to disconnect the user's inbox. Session creation does not fire on every resume. Use first-seen session context, persisted session registrations and SDK reconciliation; UI route change can update presentation without changing server ownership. [Status implementation](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/status.ts).

## Biff/Beadle inbox: stable delivery and reentrancy

Amend the existing Biff OpenCode design rather than blindly implement its experimental-transform proposal. A durable product watch API, such as the existing proposed JSONL watcher, is appropriate: stream semantic events with IDs, repository/session recipient and reconnect cursor; the OpenCode plugin adapts delivery policy. Parent reports existing beads `biff-bhfj` and `biff-6vvo`; this research has not itself queried those repo-scoped beads.

Recommended modes:

- **Notify only:** TUI unread state/toast, no model wake. Do not consume the message merely because it was shown.
- **Next user turn:** `chat.message` appends bounded inbox context to the real incoming message, recording product event IDs for acknowledgement. The hook runs before persistence; avoid recursively calling prompt from it.
- **Persist without wake:** `session.prompt` with `noReply:true` records a normal input message and returns without starting the inference loop. This provides transcript-backed context but is not a system-role injection or necessarily an invisible message. Make provenance clear.
- **Authorized wake:** schedule `promptAsync` outside awaited hooks against a known live session. It starts or joins session processing; it is not a separate harness or terminal keystroke injection. Do not wake every session in a shared directory.

Source sequence: `prompt()` creates and persists a user message, returns early on `noReply`, otherwise calls a coordinated loop. A busy runner's `ensureRunning()` waits for its existing run rather than rejecting with a busy error or starting concurrent inference. The existing model loop rereads messages on subsequent iterations. Consequently, awaiting ordinary `session.prompt()` from an awaited tool/message hook can deadlock the run that must finish to resolve that request. `promptAsync` forks the prompt operation and returns HTTP 204; 204 is scheduling acceptance, not proof of persisted/model-consumed delivery. Use a per-session drain lock, event deduplication, causal origin markers, bounded batches, and explicit acknowledgement after observable acceptance. Test arrivals at the final loop iteration: not every race is resolved merely by observing “busy.” Never acknowledge an inbox item on an experimental in-memory transform alone. [Prompt and loop implementation](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/prompt.ts#L1048), [runner coordination](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/effect/runner.ts#L125), [async endpoint](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts#L311).

Compaction must preserve pointers and durable state, not serve as the inbox database. `experimental.session.compacting` can add a concise checkpoint, but Biff unread/ack state, Beadle job state, Quarry checkpoints and Ethos identity must be reconstructible when that optional hook is absent. [Compaction contract](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/plugin/src/index.ts#L314).

## Native TUI and media

The release exports `@opencode-ai/plugin/tui`. It has native slots including `session_prompt_right`, `sidebar_content`, `sidebar_footer` and `app_bottom`; dialog prompt/confirm/select; custom routes; read-only session state and SDK client; keymap command registration; toast; attention notifications; sound packs; cancellation and disposal. This is stronger than a toast-only or external-terminal integration. Use `api.keymap.registerLayer` for current commands; older `api.command` is deprecated. [TUI API](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/plugin/src/tui.ts#L457), [implemented runtime scoping](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/plugin/tui/runtime.ts#L390).

Distribution can use one npm package with separate `./server` and `./tui` exports; each module has the corresponding native module shape. The loaders resolve the appropriate entrypoint; a server-only main entrypoint is supported. A TUI module should own local UI/media and server module should own product events. This distinction matters when attaching a local TUI to a remote server: playing sound on the server is usually wrong. Server disposal is not the same as client disconnect. [Entrypoint resolution and compatibility](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/plugin/shared.ts#L111).

For Vox, use native attention for named notification sounds when it fits; arbitrary speech/music playback is a Vox client capability, not established by the host's attention feature. The ordinary MCP result conversion handles text/image/resources and does not demonstrate handling of arbitrary audio content or generic resource-link content. Return a text artifact path/URL alongside media; route playback through an explicit local Vox component and verify remote/SSH behavior. For Lux, TUI can show status/controls and links to a Lux-owned renderer. Do not promise a stock OpenCode embedded HTML/webview/MCP Apps renderer without a separate demonstrated API. Source-only TUI findings should be treated as a version-pinned support lane, not an undocumented hack. [Result conversion](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/tools.ts#L430).

## Workflows, discovery and configuration

Workflow instructions belong in native skills/commands/agents. OpenCode skills accept a limited frontmatter schema and lowercase hyphenated names; unknown keys are ignored. Claude fields such as allowed-tools or disable-model-invocation do not become OpenCode policy. Use permission configuration and native TUI direct commands where a deterministic user operation must avoid inference. Prompt command templates may expand shell substitutions and file references; treat them as trusted executable workflow material and keep external email/message text in data arguments. [Skills](https://opencode.ai/docs/skills/), [commands](https://opencode.ai/docs/commands/), [custom tools](https://opencode.ai/docs/custom-tools/).

Config is merged, not wholesale replaced. Precedence increases through remote organizational defaults, global config, `OPENCODE_CONFIG`, project config, `.opencode` directories, inline config, then managed settings. Native runtime config is `opencode.json/jsonc`; TUI config is separately `tui.json/jsonc`. Skills may live in `.agents/skills` when shared without harness-specific assumptions; `.opencode/skills` is also native. AGENTS.md and explicit instruction paths should carry shared engineering rules. Do not silently read a parent toolkit policy as enablement of every tool in every sibling repository. [Configuration](https://opencode.ai/docs/config/), [rules](https://opencode.ai/docs/rules/).

Installation/update/removal recommendation:

1. Publish versioned per-product npm adapters where needed; include `engines.opencode`, distinct server/TUI entrypoints and a clear core compatibility range. Use release-pinned package specs in certified deployments.
2. Prefer the shipping `opencode plugin <module>` installer (`--global`, `--force` verified in installed help). Verify which runtime/TUI config entries it adds in an isolated acceptance fixture. Manual config registration remains documented and supported. No equivalent removal CLI was established in this research.
3. Product `install/init/enable/disable/uninstall/doctor` must preserve unrelated JSONC/comments, report effective scope, avoid duplicate local/npm registrations and expose exact owned changes. Separate global availability from repository activation. Remove only owned config/assets; do not delete shared OpenCode cache, sessions or user credentials.
4. Inspect resolved config with `opencode debug config` in tests, sanitized before logs. Detect a global adapter plus local copy and mismatched core/plugin versions. Unpinned npm packages resolve latest, so updater behavior must be explicit.
5. Package manager install is not semantic enablement. A globally installed lifecycle plugin should check product repo enablement before opening network connections or registering presence. Native tool disclosure should match repo/agent enablement too.

Sources: [public plugin installation](https://opencode.ai/docs/plugins/), [package resolution](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/plugin/shared.ts), local CLI help execution.

## Beadle headless workers: correct the stale CLI assumptions

The parent identified existing `beadle-tmo` claims that need correction:

- `opencode run [message..]` is real. It also reads piped stdin. **`-p` means password**, not print/prompt.
- No `--allowedTools` or `--excludedTools` exists in the inspected installed run help. Use native permission config/session policy.
- Noninteractive run is **not automatically approving by default**: `--auto` defaults false; current code rejects permission requests unless auto mode is selected. However most unspecified permissions default allow, so auto-rejection alone is not a safe worker policy.
- `--agent` can select a named profile; a named agent is not required to supply a system instruction when using the SDK, whose prompt supports `system`, `agent`, model and structured output format.
- `--pure` disables external plugins. Do not turn it on while depending on Ethos plugin enforcement; core authorization and controlled worker policy must remain effective independently.

Local `opencode run --help` and [run implementation](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/cli/cmd/run.ts#L416), [auto-rejection](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/cli/cmd/run.ts#L801), [SDK prompt schema](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/prompt.ts#L1498).

Preferred managed worker contract: Beadle's harness-neutral job supervisor starts or connects to a controlled OpenCode server with an isolated work directory and explicit config, creates a **new** session with permissions and tracked job ID, sends the email task as untrusted task data with a controlled system instruction/profile, subscribes to events, validates the final output schema and records usage/artifacts. Use no ambient “continue last” behavior. SDK `createSession`/prompt/abort are native automation. Restrict or supervise subagents and inherit job authorization into child sessions. A CLI backend with `run --format json --agent ...` is a valid simpler alternative if the same cancellation, isolation and result semantics are implemented; do not parse formatted human output. Never interpolate raw message text into a shell command.

Stock headless run denies question/plan-enter/plan-exit on new sessions and handles outstanding permission asks itself. A custom SDK worker client must implement its own denial/review path; a bare server will wait for replies. Observe errors and structured completion, not merely process exit or the first text event. No verified native hard dollar/token budget exists: configure agent `steps`, enforce wall-clock/concurrency/usage ceilings in the supervisor, and call `session.abort`; terminate worker process only if graceful cancellation fails. Step limits are not a strict billing cap. Scope authentication and worktree cleanup to the job rather than inherit arbitrary user project plugins/config. [Agent steps](https://opencode.ai/docs/agents/#max-steps), [server API](https://opencode.ai/docs/server/), [run session creation](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/cli/cmd/run.ts#L429), [background child cancellation](https://github.com/anomalyco/opencode/blob/3104c1428ec91f809e5ab86631300de41eb6952e/packages/opencode/src/session/run-state.ts#L128).

## Product implications to reconcile with repository audits

| Product | Best native starting point | Core debt to investigate/remediate |
| --- | --- | --- |
| prfaq | Native skills + commands; scoped reviewer agent/task when needed; CLI artifact operations | Workflow content coupled to Claude tool names/frontmatter; deterministic artifact state hidden inside prompts |
| z-spec | Native skills/commands + CLI/formal check tools; pre-tool gate only for enforceable invariants | Solver/checker setup hidden in Claude hooks; proof/check results lacking a reusable machine contract |
| ethos | Native identity/session plugin + enforcement hooks + optional TUI identity/status; canonical API/MCP operations | Process-global identity, Claude session IDs, unchecked plugin activation, authorization enforced only by prompts |
| biff | Native server watcher/SDK delivery + TUI unread/presence/direct commands; existing MCP/CLI for operations | Claude poll hooks/transcripts; lack of replay cursors, acknowledgment semantics, session-safe identities |
| beadle | Native inbox integration plus separately managed OpenCode SDK/CLI worker backend | Mail domain coupled to Claude spawning flags; job lifecycle/config/permissions encoded in harness-specific code |
| vox | Product media API/MCP with server events and local TUI presentation/control where needed | Parsing assistant transcript as speech API; server-side playback assumptions; no structured media artifact contract |
| lux | Native tool/MCP + TUI controls/status/renderer launch link; Lux owns its renderer | Claude-only display hooks, renderer tied to one client's filesystem/localhost, implicit UI lifecycle |
| quarry | Existing MCP tools/resources + native retrieval/ingestion skills and explicit repository config | Shared mutable session state, opaque errors, compaction-as-storage, transport/tool naming conflated with grammar |
| punt-kit | Native integration standards, generators, installer ownership and compatibility probes | Claude scaffolds as canonical source; duplicated per-harness grammar/config rewriting; stale beads assumptions |

Do not preserve technical debt just to keep adapters small. The core APIs, lifecycle model, configuration ownership, artifact delivery, worker supervisor and workflow representation should be repaired where required, then adapters should be straightforward.

## Release-blocking acceptance scenarios

1. **Stock experience:** install from published artifact into isolated project/global scopes; start ordinary `opencode`; discover expected operations and workflows; no Claude installation, env var, hook runtime or manifest is required.
2. **Ownership:** repeated install/update/uninstall preserves unrelated JSONC/TUI config, plugins, credentials, AGENTS.md and sessions; no duplicated tools/events; repo disable works with global plugin installed.
3. **Tool contract:** malformed args, core timeout, missing binary, cancellation, permission denial and transport outage yield actionable bounded results; tool names remain unique across all nine products. MCP stdio and remote transports tested separately where offered.
4. **Enforcement:** denied builtin/custom/MCP operations do not reach product side effects; test parallel tool calls, shell/code-mode, child sessions and plugin load failure. Confirm `permission.ask` separately before ever depending on it. Doctor detects absent gates.
5. **Inbox:** two sessions and two worktrees receive only their own events; test active inference, idle, next-turn, reconnect, replay, duplicates, compaction, resume, final-loop race, and noReply. Confirm no self-prompt recursion, unbounded wake loop or acknowledged-but-lost message.
6. **Lifecycle:** plugin disposal closes watchers/children/timers; TUI disconnect does not mark server session gone; crash leaves expiring presence; restarting reconstructs durable state.
7. **TUI:** native status/commands/dialogs work in supported TUI release; server/headless functions without frontend; remote attach directs audio and renderer launch to the user-side component; unsupported media still exposes a useful artifact.
8. **Workflow:** native skills load with valid names and actual commands/tools; Claude frontmatter does not silently grant permissions; model choice isn't hardcoded unless product semantics demand it; child session lineage is correct.
9. **Workers:** fresh email job uses fresh scoped session, no continue-last; deny/ask policy cannot silently approve, SDK asks cannot hang, child work obeys restrictions; structured output is validated; timeout/abort kills owned descendants and records completion/error and usage.
10. **Version contract:** run against certified minimum and latest supported releases; include server hooks, TUI exports, plugin installer, permissions, async prompts, compaction optionality, core/plugin skew. Experimental features fail explicitly or degrade to a documented stable path.

The report proposes acceptance tests; it does not claim they have run. The actual research checks were installed CLI/version/help inspection, current official documentation fetches, pinned-source inspection and installed/current public-interface comparison.
