# Pi coding agent: native harness findings and integration design

**Program status — 2026-09-13: P2: second native implementation target.** Technical observations below are the 2026-09-12 research baseline, not a new runtime certification. [Priority decision](../decisions.md).

Research date: 2026-09-12. This report is harness research; the repository investigators must reconcile the tool-specific recommendations against implementation and repo-scoped beads. No harness installation, configuration, or tool implementation was changed.

## Decision

Ship real pi packages containing TypeScript extensions, Agent Skills, and prompt templates. Register structured tools and user commands with pi's public extension API, use pi events and UI, and invoke each Punt tool through its own public CLI/library/HTTP/WS surface. Do not implement a Claude Code plugin interpreter or introduce a generic MCP bridge. This also matches the operator intent recorded by the coordinating investigator in vox `DES-067` and the existing biff native-extension/watch work (`biff-lt0v`, `biff-6vvo`). Those local references were provided by the coordinator and require final repository citation there.

The user explicitly includes all technical/design debt in Punt products that makes native support easier or cleaner in scope. Prefer repairing ownership, public APIs, storage, lifecycle, and transport boundaries in each product over perpetuating poor seams for smaller integration diffs.

Pi is particularly capable for live biff presence, native question/selection workflows, and asynchronous tool notifications. It does not give an extension an OS sandbox or guarantee that a model-only permission hook controls the extension's own process and network activity. Durable identities, send authorization, event deduplication, and service/process ownership must therefore be explicit toolkit contracts.

## Verified version and source baseline

| Evidence | Observed value | Implication |
| --- | --- | --- |
| Local `pi --version` | `0.84.4` | Installed baseline, observed without changing it. |
| Local executable target | `/home/jfreeman/.local/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js` | The workspace already has the renamed package. |
| Latest GitHub release | `v0.85.1`, published `2026-09-05T12:29:01Z` | Use this released version as initial certification target; retain 0.84.4 as a compatibility test until minimum-version policy is approved. |
| npm latest metadata | `@earendil-works/pi-coding-agent` `0.85.1`, `gitHead=d981de1229ef899957bbe968bc8dcda02a21f477` | Pin the release, not unversioned main, for production API claims. |
| Upstream main inspected | `71dca871bc80b6bc97be37f0ca3189399d651fff`, committed `2026-09-11T17:42:45Z` | Contains unreleased additions/fixes; do not quietly depend on them. |
| Repository redirect | `badlogic/pi-mono` → `earendil-works/pi` | Current package/import names differ from older pi tutorials. |
| Current package Node requirement | `>=22.19.0` | Declare/check the runtime prerequisite in package distribution and doctor output. |

Sources: [released artifact](https://github.com/earendil-works/pi/releases/tag/v0.85.1), [npm latest metadata fetched during research](https://registry.npmjs.org/@earendil-works/pi-coding-agent/latest), [release package manifest](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/package.json), [inspected main commit](https://github.com/earendil-works/pi/commit/71dca871bc80b6bc97be37f0ca3189399d651fff).

Downloaded primary evidence and local installed documentation are in `.tmp/native-harness-plan/pi-upstream/`. `release-0.85.1/` contains release-pinned versions; `installed-0.84.4/` contains local bundled docs. This cache is research material, not proposed distributable code.

The installed/release extension-document comparison showed essentially the same relevant lifecycle, tool, trust, RPC UI, and package contracts. Version 0.85.0 nevertheless fixes built-in tools ignoring `ctx.cwd` and session forks losing a compaction boundary, both relevant to the toolkit. Version 0.85.1 repairs SDK imports broken by accidentally publishing experimental dependencies in 0.85.0. Avoid 0.85.0 as a certification target. Main adds `ctx.modelRegistry.stream()/streamSimple()` and fixes direct RPC `steer`/`follow_up` bypassing `input` handlers; these are **unreleased**, so an identity/policy feature must not assume either on 0.85.1. [Release and unreleased changelog](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/coding-agent/CHANGELOG.md)

## Supported, experimental, and absent capabilities

“Supported” means documented public pi integration surface in the inspected released baseline; no promise of semver stability beyond that baseline is inferred.

| Capability | Status | Native design and limits |
| --- | --- | --- |
| TypeScript/JavaScript extensions | Supported | Public extension factory; imports pi API, TypeBox, pi TUI, and Node libraries. Async factories are supported. |
| Packages from npm/git/local paths | Supported | `package.json` `pi` manifest or convention directories; global/project install, version pins, filtering, removal and updates. |
| Agent Skills | Supported | Native `SKILL.md`, progressive disclosure, `/skill:name`, neutral `.agents/skills` discovery. |
| Prompt templates | Supported | Markdown commands expanded before model execution; appropriate for user-requested workflows, not deterministic side effects. |
| AGENTS.md | Supported | Global and cwd/ancestor context; `AGENTS.override.md` overrides same-directory context. Claude fallback exists but is unnecessary. |
| Structured model tools | Supported | `registerTool`, TypeBox schemas, cancellation, progress, custom result rendering, dynamic registration/activation. |
| User slash commands | Supported | `registerCommand`, argument completion, direct handler. No automatic ownership namespace; duplicate names gain numeric suffixes. |
| Lifecycle/compaction/context events | Supported | Session start/shutdown/replacement/tree, agent/turn/message/tool events, custom compaction, prompt/context changes. |
| Tool interception | Supported, limited boundary | `tool_call` can block model-dispatched tools; arbitrary extension code and direct CLI/HTTP are outside this gate. |
| Project trust | Supported | Project packages/extensions/config wait for trust; this is loading trust, not per-action authorization or OS isolation. |
| Notifications/status/widgets/dialogs | Supported | TUI and subsets through RPC UI requests. JSON/print have no interactive UI. |
| Custom terminal components | Supported | TUI-only components, tool and message renderers, editors; retain other extensions' UI. |
| Floating overlay UI | Experimental | Do not require it for core lux or PRFAQ acceptance. |
| Asynchronous receives/timers/processes | Extension-owned | Node APIs + session lifecycle + `sendMessage`; no built-in durable daemon or background bash manager. |
| Session tree/forks/compaction | Supported | Session UUID, branch leaf, ancestry; forks are not identical to in-file `/tree` branch navigation. |
| Subagents | Extension example, not core | Separate pi subprocesses with explicit tooling/model/abort behavior. No general stock subagent contract. |
| Core MCP client/configuration | Absent | Direct Punt transports; do not describe `.mcp.json` or Claude MCP settings as pi integration. |
| Permission popups/action policy | Not built in | Build explicit tool-owned policy and use native confirmation UI only when the actual action requires a decision. |
| OS sandbox | Not built in | Container/OS isolation or selected extension; sample sandbox only covers its configured execution path. |
| Supported programmatic hosting | Local SDK and stdio RPC | Stock interfaces, usable from JS and any process language respectively. |
| HTTP pi server / remote client / experimental plugin API | Source-only experiment | 0.85.1 deliberately excludes experimental server/client/plugin paths from published artifacts; never make these release dependencies. |
| Audio playback API | No documented first-class extension API found | Vox owns playback/backend lifecycle through its public service/CLI; pi supplies events, commands and status. |

Sources: [release extensions](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/extensions.md), [release packages](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/packages.md), [pi philosophy](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/README.md#philosophy), [release SDK](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/sdk.md), [release RPC](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/rpc.md), [0.85.1 experimental-publication correction](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/CHANGELOG.md).

## Distribution and discovery contract

Each tool should own a pi package in its own repository, for example `integrations/pi/`; npm names such as `@punt-labs/pi-biff` are proposals, not reserved or verified available names. Give packages an explicit `pi` manifest naming their extensions, skills, and prompts, and the `pi-package` keyword. Build/publish a complete artifact whose resources resolve within the package; do not make runtime loading depend on a Claude plugin cache, local symlinks into another harness, or repository source outside the tarball.

Use `pi install npm:<package>@<version>` for normal global installation and `pi install -l npm:<package>@<version>` for project scope. Native package install/remove writes the corresponding `settings.json`; trusted project startup can automatically install missing project dependencies. Treat the **pi resource load decision** and the **Punt repository enablement decision** as separate checks. A globally installed package should register discoverable commands, but should not start a mailbox watcher, playback process, or network client for a disabled/untrusted project. Respect `ctx.isProjectTrusted()` before honoring repo-controlled executable paths, endpoint overrides, or other extension configuration. Do not silently grant trust in a `project_trust` handler.

Runtime npm dependencies go in `dependencies`, because production pi package installs omit dev dependencies. Pi's bundled core packages (`@earendil-works/pi-coding-agent`, `@earendil-works/pi-ai`, `@earendil-works/pi-agent-core`, `@earendil-works/pi-tui`, `typebox`) are peers, not bundled duplicate runtimes; upstream recommends `"*"` peer ranges. Record the toolkit's narrower tested compatibility range separately, enforce it in doctor/CI, and avoid implying that upstream's peer range means untested versions are supported. Keep common adapter utilities small and ordinary libraries; installing one tool must not automatically load all nine tools. [Package contract](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/packages.md)

Use shared Agent Skills source where instructions are truly harness-neutral, with explicit per-harness presentation where needed. Native pi skill names are lowercase letters/digits/hyphens; choose stable names such as `prfaq-discover` and invoke `/skill:prfaq-discover`. A common prompt body can be packaged without reading `.claude/` at runtime. Skills describe workflows; deterministic user commands use extensions. Avoid copying Claude-only frontmatter such as `allowed-tools` as enforcement: pi documents `allowed-tools` as experimental. Native skill auto-loading is model-directed and not guaranteed, so critical setup/policy belongs in code. [Skills](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/coding-agent/docs/skills.md)

Prefer namespaced structured tools (`biff_read`, `quarry_search`) and one top-level user command with subcommands (`/biff ...`) unless the toolkit's accepted grammar requires another exact spelling. This is a recommended mapping, not a new command grammar to impose over the artifacts. Register argument completions. Pi resolves duplicate extension command names into suffixes like `/review:1`; install-all-nine tests must reject accidental collisions. Skill invocation and prompt-template expansion are different native command mechanisms; publish the actual pi invocation in help. [Command API](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/extensions.md#piregistercommandname-options)

## Tools and transport selection

A native extension is more than a prompt saying “run this CLI.” It supplies typed operations, explicit output/error behavior, lifecycle ownership, relevant native UI, and complete install/doctor/remove paths. The backend should be the smallest stable public surface the tool actually has:

1. For finite Python-backed operations, invoke the public CLI with argv and a versioned JSON output mode. `pi.exec(command, args, {cwd, signal, timeout})` uses `spawn(..., shell:false)` and returns `stdout`, `stderr`, `code`, `killed`. Pass `ctx.cwd` explicitly; shell interpolation is unnecessary. Inspect nonzero status and parse/validate the JSON envelope. Throw from `execute` to mark failures; returning `{isError:true}` inside a tool result does **not** make pi mark it failed. [Execution source](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/coding-agent/src/core/exec.ts), [tool definition/error contract](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/extensions.md#tool-definition)
2. For long-lived event delivery, own a streaming CLI JSONL child or use the tool's HTTP/WS subscription. `pi.exec` buffers output and has no stdin or incremental callback option; it is unsuitable for endless watchers or large streams. Use a bounded Node spawn client with explicit argv, streaming parser, cancellation, close handling, limits, and shutdown/process-group management. Do not assume the helper kills grandchildren. The service owns durable replay/cursor behavior; the extension owns the live subscription.
3. For services already serving HTTP/WS, use a typed direct client with authentication, bounded retries, timeout and abort. A local HTTP port is not a permission grant. Keep credentials out of command lines, prompts, session `details`, and diagnostic text. A TypeScript extension cannot directly import a Python library; do not reach into Python private modules through ad hoc scripts to simulate a public API.
4. For JS tools with a documented library API, direct imports are reasonable if they preserve the same policy and result contract. No generic transport is mandatory for every tool. A missing machine-readable public interface is a **core repository task**, not justification for adding a Claude/MCP shim.

`registerTool` supports schemas, `signal`, `onUpdate`, `details`, renderers, and post-start registration. Restrict registered/active operations according to the tool's actual capability and enablement state. `setActiveTools` manages a global active set; preserve tools owned by other extensions and never replace the whole set with one package's list. Shared command schemas can generate docs/types, but pi-native implementations should adapt results and UI. Use `StringEnum` from pi-ai where relevant for provider-compatible schemas. Bound tool output and put structured state in `details`, with a concise text result for the model. [Tool API and dynamic loading](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/extensions.md)

## Session, identity, presence, and asynchronous receive contract

Use pi's `ctx.sessionManager.getSessionId()` as the harness session UUID, plus a toolkit process/runtime instance ID and explicit repo/worktree identity. `getSessionFile()` may be undefined for ephemeral sessions; it is not a stable universal identity. Track `getLeafId()` as current branch position, not as an immutable “branch ID.” For services needing stable branch-specific state, define a toolkit-owned branch lineage key and its transitions rather than guessing from one leaf. Obtain ancestry from `getHeader().parentSession` where present. Do not mint the same live presence lease for two pi processes resuming the same session file. [Session format and public getters](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/coding-agent/docs/session-format.md)

The native lifecycle is:

| Transition | Relevant pi events | Toolkit responsibility |
| --- | --- | --- |
| Initial load | `session_start` with `startup` | Resolve trusted config/enablement, identity and capability; start eligible live connections. |
| New/resume | `session_before_switch`, old `session_shutdown`, new runtime `session_start` | Close old leases/subscriptions and rebuild against destination cwd/session. |
| Fork/clone | `session_before_fork`, old shutdown, new start with `fork` | New session identity with ancestry; do not replay external sends from copied history. |
| Reload | old shutdown, resources reloaded, start with `reload` | Idempotent teardown/reconnect; no duplicate listeners or phantom peers. |
| `/tree` | `session_before_tree`, `session_tree` | Same runtime/session file, new leaf: rebuild branch-sensitive state and reject stale branch-bound replies. |
| Compaction | before, success, failure events | Preserve durable toolkit state; distinguish actual state from model summary and aborted compaction. |
| Work/idle | `agent_start`, `agent_settled` | `agent_end` can be followed by automatic retry/compaction/follow-up; it is not definitive idle. |
| User prompt wait | `ui_prompt_start`, `ui_prompt_end` | Distinguish busy execution from native dialog wait for biff/vox status. |
| Exit | `session_shutdown` | Abort requests, stop watchers, close clients, release presence leases and clear UI. |

[Lifecycle and waiting events](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/extensions.md#events)

Factories may run for invocations that never create a session. Start no processes, sockets, watchers, or timers there. Create session-scoped resources on `session_start` or first actual use and close them in an idempotent `session_shutdown`. Extension commands that replace sessions must use `withSession` and its replacement-bound context; old closures refer to the torn-down runtime. [Long-lived resource rule and session replacement](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/extensions.md)

For biff/beadle asynchronous receive: maintain an AbortController and generation token per active runtime; capture the intended repo/session/branch for every outstanding request; drop or persist late results according to that ownership, never inject them into whichever session happens to be active. Maintain durable server-side event IDs/cursors, bounded batches, reconnect backoff, deduplication, and explicit acknowledgement semantics. Shutdown must prevent queued callbacks from sending into the old runtime. Test disconnect during reload, fork and compaction. Presence should have expiry so SIGKILL cannot leave a permanent peer.

Use `ctx.ui.notify`/`setStatus` for user-visible awareness; use `pi.sendMessage` with a typed `customType` for model-visible external content. `sendMessage` supports `steer`, `followUp`, and `nextTurn`; select a delivery policy per event, normally noninterrupting follow-up or next-turn for mail/status. `triggerTurn` is an explicit choice for an enabled receive workflow, with batching to avoid an infinite turn loop. Do not use `sendUserMessage` for incoming mail: that creates a message as if the user typed it. External content needs origin labels and must remain untrusted data. `appendEntry` stores custom state outside model context; reconstruct branch-sensitive state from the active branch, not all session entries. External side effects belong in authoritative tool storage and idempotency records, not a branch-replayable prompt. [Message/state API](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/extensions.md#pisendmessagemessage-options)

Upstream's `file-trigger.ts` demonstrates asynchronous injection, but its sample has no watcher shutdown handler; it is an illustration, not production lifecycle code to copy. [Upstream sample](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/coding-agent/examples/extensions/file-trigger.ts)

## Permissions, trust, and subagent limits

Pi's native `tool_call` handler can block a model-dispatched tool and errors in that handler fail closed. Sibling calls may be preflighted in sequence and executed concurrently; a handler cannot rely on seeing a sibling's result in the session history. Input mutation is permitted and is not revalidated afterward, so do validation inside the tool/service boundary as well. A permission extension is one cooperating layer, not hostile-extension isolation. [Tool interception guarantees](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/extensions.md#tool_call)

Crucially, an extension's `pi.exec` calls directly into process execution; direct HTTP, timers, event handlers, and user command handlers do not become separate model `tool_call` events. Put send/delegation/mutation authorization in the actual Punt action implementation and share it across user command and model tool entry points. A native dialog can obtain a required user decision in TUI or an RPC client that implements dialogs; headless execution needs an existing explicit authorization or a structured refusal, not an implied yes. Do not impose confirmations on already-authorized routine actions. [Extension exec source](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/coding-agent/src/core/extensions/loader.ts#L395), [confirmation sample](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/coding-agent/examples/extensions/permission-gate.ts)

Project trust gates loading `.pi` settings/resources/packages and project skills. It does not sandbox extensions after loading. Global or CLI extensions load before project trust, so a globally installed Punt package must explicitly respect trusted-project state before honoring repo-specific executable/service configuration. Noninteractive modes do not ask; saved trust, global defaults and explicit trust CLI options determine whether resources load. [Project trust](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/README.md#project-trust)

Pi has an example sandbox extension using `@anthropic-ai/sandbox-runtime`, but that is optional execution infrastructure, not built-in pi sandboxing, and the sample primarily replaces `bash`. Native extension Node code/HTTP/other subprocess paths do not magically inherit that restriction. Do not use a Claude hook translation, and do not claim ethos-enforced least privilege from a system prompt or active-tool list alone. [Sandbox example](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/coding-agent/examples/extensions/sandbox/index.ts)

There is no core subagent API to map Claude subagent hooks onto. Upstream's native extension example runs separate pi processes with selected tools/model/system prompt, captures JSON events, and propagates cancellation. If ethos or punt-kit supplies pi delegation, it owns the process protocol, lineage, scopes, credentials, approvals, budgets, cancellation, and results. This program selects the punt-kit-owned `HOST-PI-DELEGATION` installed helper, with optional Ethos governance; do not silently assume every pi installation has a `subagent` tool. Child AGENTS/skills/config loading and trust must be tested, not inferred from parent behavior. [Subagent example](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/coding-agent/examples/extensions/subagent/README.md)

## UI and mode behavior

Prefer independent keyed `setStatus`/`setWidget` entries so all nine packages coexist; replacing the global footer/editor is a conflict-prone optional customization. Render tool summaries natively and let expansion reveal details. PRFAQ and z-spec can use native select/input/editor/custom TUI for guided workflows; lux can expose its existing visual application with native command/status/results and optional TUI components where terminal output fits. A pi TUI component is not a browser/webview runtime.

| Run surface | Detection | Available behavior | Required fallback |
| --- | --- | --- | --- |
| Interactive | `ctx.mode === "tui"` | Full TUI, dialogs, renderers, widgets | Standard text/result output still available. |
| Stdio RPC | `ctx.mode === "rpc"`, `ctx.hasUI === true` | Dialog request/response and notifications; client must render/respond | TUI `custom()` returns undefined; footer/header/editor-component methods are no-ops. |
| JSON | `ctx.mode === "json"`, no UI | Event stream and tool results | No UI wait; machine-readable result/refusal. No debug stdout corruption. |
| Print | `ctx.mode === "print"`, no UI | Finite result | No UI wait; no unbounded background receiver keeping process alive. |

`ctx.hasUI` alone is **not** a test for a terminal. RPC dialogs block until response (or configured timeout); clients that ignore UI requests must not deadlock a required workflow. Vox playback is tool-owned process/service behavior and must have an explicit headless/remote-host policy. [Mode and custom UI contract](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/extensions.md#mode-behavior), [RPC UI limitations](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/docs/rpc.md#extension-ui-protocol)

## Tool-specific design inputs for repository plans

These are harness-informed recommendations, not claims that a particular transport or CLI already exists. Each repository plan must cite the actual implementation and name missing core work.

| Tool | Native pi integration direction | Core/API work to require if absent |
| --- | --- | --- |
| prfaq | Skills/prompt templates for product discovery; explicit commands and native question/editor UI for stages; structured artifact operations | Separate workflow text from Claude invocation/AskUserQuestion assumptions; deterministic artifact path/state contract; headless question/result protocol. |
| z-spec | Skills for specification work, native tools/commands for validation/model checking and result rendering | Stable machine-readable validator/compiler/checker results; cancellation and artifact path contract; remove Claude-only workflow/delegation coupling. |
| ethos | Per-session identity resolution and prompt/context enrichment through supported events; explicit native delegation if required | Harness-neutral identity and ancestry model, public resolution/export APIs, explicit action authorization in tool core, delegation records independent of Claude transcript files. |
| biff | TypeScript tools/commands, keyed native status, live JSONL or service receive; lifecycle-based presence, typed external messages | Watch cursor/event schema and reconnect semantics; expiry leases; session/process/branch identity; sends protected and deduplicated. Reconcile `biff-lt0v`/`biff-6vvo`. |
| beadle | Explicit mail tools and commands, native status and optional receives, drafts/preview/review where action policy calls for them | JSON send/receive/result contract; sender identity; authorization and idempotency at actual send boundary; explicit attachment/path handling. |
| vox | Native controls and response/settled/waiting events calling Vox CLI/HTTP/WS; keyed voice/playback status | Public event-to-audio entry points and cancellation; no Claude hook file parsing; playback ownership, duplicate suppression, headless policy; respect `DES-067` no-MCP intent. |
| lux | Native tools/commands for visual surfaces, direct existing service/CLI, native result rendering and optional TUI dialogs | Public authenticated presentation/control/events API, input correlation/cancellation, window ownership; do not make experimental pi overlay or server API mandatory. |
| quarry | Native retrieval/ingest/status tools and workflow skills through finite JSON CLI or existing HTTP | Explicit schema and concise search results, provenance/citation fields, repo scope, ingest cancellation/job status; no default MCP dependency. |
| punt-kit | Own package standards, compatibility/doctor checks, command-generation mappings, shared test harness and install guidance | Separate Claude-specific generators/installers from neutral manifest; validate package contents and all-nine coexistence; manage beads from explicit project cwd. |

## Acceptance suite and implementation gates

The following are planned acceptance tests, not tests executed during this research.

1. **Clean native installation:** Install a packed/published pi artifact in an isolated pi home on certified pi releases. No Claude Code installation or Claude config/cache is present. Native tools, commands, and skills are discoverable and callable.
2. **Scope/enablement:** Test global package/project disable, project install/trust denied, trusted project, nested directory, repo worktree, unrelated cwd, and two repositories concurrently. Disabled projects start no implicit receive/playback processes.
3. **Public transport parity:** Run representative operations through CLI/API and native pi tool and compare semantic results/errors. Python tools need no private module imports; stdout JSON remains valid.
4. **Tool schemas and multiple providers:** Validate required/optional parameters, enums, malformed inputs, rich results, large output bounds and provider compatibility. Inactive tool sets preserve other extensions.
5. **Native command semantics:** Direct user commands use deterministic handlers, completions and appropriate UI; skills/templates invoke the correct workflow without pretending to be hooks or MCP tools.
6. **Install/upgrade/remove:** Pinned install, upgrade, failed upgrade, downgrade policy, duplicate global/project installation, disable and remove leave no orphan watchers/config owned by the package. Python backend installation is diagnosed explicitly.
7. **Lifecycle ownership:** New, resume, fork, clone, reload, `/tree`, compaction success/failure, abort, normal exit and killed process. No duplicate peer, stale widget, leaked process, or injection into a replacement session.
8. **Asynchronous delivery:** Reconnect, duplicated/reordered events, cursor resume, offline startup, stream truncation, burst backpressure, simultaneous events, and shutdown race. Verify delivery policy and visible origin metadata.
9. **Presence fidelity:** Distinguish active work, retry/compaction, queued follow-up, true `agent_settled`, user UI wait, and expired process lease. Never rely only on `agent_end`.
10. **Branch and durable state:** Restore only active-branch view state; do not repeat external mail/chat/audio actions from replay or copied fork history. Resume the same session concurrently with distinct process leases.
11. **Cancellation:** Abort reaches finite CLI/HTTP requests and streamed subprocesses; descendants and reconnection timers terminate; partial results follow a defined contract.
12. **Action policy:** Model tool, user command, event callback, direct CLI, HTTP, and delegated child enforce the same required send/mutation authorization. Verify that pi `tool_call` interception alone does not satisfy the test.
13. **Trust:** A global extension cannot honor an untrusted repo's binary path/endpoint and cannot grant project trust itself. Explicit CLI/temporary trust is represented correctly.
14. **Mode matrix:** Interactive TUI, JSON, print and stdio RPC. RPC handles dialog requests, responses, cancel and timeout. Print/JSON exit finitely, never wait for unavailable UI, and emit no extra protocol-breaking stdout.
15. **UI coexistence:** Install all nine packages plus a sample unrelated extension. No command suffix collisions, status key collisions, stolen footer/editor, dropped tools or excessive prompt loading.
16. **Artifacts and error reporting:** Outputs are at explicit repository-relative/absolute locations with stable IDs and useful recovery errors; tool `execute` throws on actual failure rather than falsely reporting success.
17. **Vox/lux delivery:** Audio/visual ownership is correct with two sessions; user cancellation and service restart work; remote/headless mode does not unexpectedly play on the wrong host or silently hang.
18. **Delegation, if shipped:** Use actual stock pi JSON/RPC subprocess or released SDK, explicit model/tool configuration, child identity/scope and budgets, abort propagation, and result provenance. No unsupported server/plugin API required.
19. **Version canary:** Certify 0.85.1 and optionally 0.84.4, explicitly reject 0.85.0 SDK breakage, and run separate main canary without changing the supported release contract.
20. **Unreleased API restraint:** No dependency on `ctx.modelRegistry.streamSimple()` or the main-only RPC input fix until released and certified. Inspect direct RPC `steer`/`follow_up` if input interception affects ethos behavior.
21. **No MCP/Claude dependency:** Package import/dependency/config audit and execution in a clean home show no generic MCP bridge, Claude hooks parser, `CLAUDE_PLUGIN_ROOT` requirement, or Claude-only executable fallback.

## Recommended sequence

First establish the neutral capability/result/identity/policy contracts and pi package standard in punt-kit, with per-repository core fixes. Then use **quarry or another confirmed finite CLI tool** as a transport/package pilot and **biff** as the lifecycle/receive/presence pilot; the actual repository audit decides which finite CLI is ready. These two pilots exercise most common native integration infrastructure. Follow with vox and lux to test media/UI ownership, ethos to validate identity/delegation boundaries, and the remaining workflow and communication integrations. Do not block simple native skills/commands on an optional delegation package, but do not mark a tool first-class until its required lifecycle/user experience is complete.

Each implementation bead should cite its pi version/API assumptions, actual backend contract, positive end-to-end scenario, mode/lifecycle tests that matter for that tool, and the release artifact owner. The report intentionally does not create beads or modify project configuration.
