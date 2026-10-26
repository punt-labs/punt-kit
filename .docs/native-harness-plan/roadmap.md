# Execution roadmap: OpenCode P1, pi P2

Updated: 2026-09-13 · Research baseline: 2026-09-12

[The strategy](strategy.md) explains the comparative complexity and native choices. This document names the execution gates. [backlog.json](backlog.json) is the machine-readable task/dependency record. Its keys are planning identifiers, not Beads IDs; current repository-scoped records must be reconciled before implementation.

P1 delivers all nine products natively in OpenCode. P2 delivers all nine in pi. Codex-only probes, adapters, worker backends, voice connectors and certification are deferred; they are absent from active dependency closures. Shared core repairs and existing Claude compatibility remain required.

## Milestones and priority semantics

| Milestone | Work and evidence | Completion gate |
| --- | --- | --- |
| P1 foundations and first slices | Freeze small context/results/install contracts; prove native OpenCode tool/session/TUI/delivery behavior; complete finite Punt and a Lux interaction slice. | The relevant KIT/HOST/LUX task acceptance and actual installed OpenCode journeys. This is useful partial delivery, not certification of all nine. |
| P1 OpenCode products | Nine independent native packages and complete declared journeys, including OpenCode Beadle workers, Vox voice mode and independent reviews. | Selected `opencode` outcome of each product release, then `KIT-FLEET@opencode`. Pi is not a prerequisite. |
| P2 pi products | Released native extension/package APIs over repaired cores; real pi delegation where needed; pi workers/voice and all-nine composition. | Selected `pi` outcome of each product release, then `KIT-FLEET@pi`. |
| Active program complete | Both active fleet outcomes, required shared remediation and mixed OpenCode/pi composition. | `KIT-FLEET` aggregate. No Codex completion is required. |

P1/P2 are sequencing priorities rather than automatic changes to existing Beads severity. Shared task aggregates may span both hosts; evaluate their scoped outcome to decide whether an OpenCode release is complete. P2 can start bounded development against proved P1 contracts when capacity permits, but pi-only work never gates P1. Avoid artificial dependencies on finishing an unrelated product or the entire OpenCode fleet.

Sizes in repository work tables describe complexity: M is a bounded component, L spans interfaces/lifecycle, XL changes a state machine, migration or execution boundary. Decompose L/XL packages into reviewable tasks. Do not turn these relative sizes into ungrounded calendar promises.

## P1 step 1: establish the native reference and cheap complete slices

`KIT-STD` defines explicit context/lifetime, typed operation/event results, install/register/enable/preferences, and compatibility/evidence contracts. Pin the first versions; refine them with real products. `KIT-RESULT` repairs deterministic JSON results. `KIT-CONTENT` packages shared assets. `KIT-OPENCODE` then supplies a small native audit/status operation that works outside the source checkout, including a structured failure and removal without damaging user configuration.

`HOST-OPENCODE` proves the runtime assumptions before every product copies them:

| Experiment | Required evidence | Failure response |
| --- | --- | --- |
| Native package/discovery | Maintained npm server/TUI package, exact version, owned installation/update/removal, commands/skills and one typed operation. | Fix the native distribution path; no Claude cache or undeclared checkout resources. |
| Session and actor context | Two sessions, two worktrees and child roles through one server; correct context reaches the product service. | Repair binding/isolation before stateful tool release. A display name is not authorization. |
| Delivery and scheduling | Persisted noReply input, authorized wake, idle/busy/final-loop race, retries and consumption evidence; one owned serialized event drain. | Fix supported scheduling or explicitly block the required feature. Do not rely on experimental transcript transforms or a successful HTTP 204 alone. |
| Gates and activation | Actual covered before-tool denial, native permissions, untrusted/failed plugin load, ordinary/native/MCP and relevant code-mode paths. | Publish accurate coverage, enforce product authorization at the core, and diagnose unavailable required guards. The uninvoked permission.ask hook is not a gate. |
| Server/TUI/remote lifetime | Native slots/keymaps/dialogs, attach/detach, server dispose, reconnect, absent UI and explicit media destination. | Correct ownership and cleanup; a remote server must not silently change the selected audio/display host. |

Use `LUX-CONTEXT`, `LUX-LIFETIME`, `LUX-ENABLE`, `LUX-CLIENT` and `LUX-OPENCODE` for the first substantial lifecycle/interaction slice. Reuse the existing Hub and leases. Render, inspect, click, reconnect and remove one owner while a second remains active. Observe the renderer and the native TUI; successful HTTP alone does not prove the journey.

## P1 step 2: start the large core repairs in parallel

| Track | Work packages | Ordering and existing work |
| --- | --- | --- |
| Ethos identity/governance | ETHOS-CONTEXT, SERVICE, GOVERNANCE, PERSONAS; separately AUTHORITY | Reuse explicit sessions; fix current path/binding/invariant defects. Authority is P1 because BIFF-AUTH needs keys, scoped delegation and revocation. |
| Biff messaging | BIFF-DESIGN → CORE; EVENTS and SETUP; AUTH → POLICY | Reuse biff-00v. Claude M4 parity gates daemon M1; signatures/delegation and recipient policy gate automatic content injection. Biff is not a prerequisite for unrelated products. |
| Beadle interactive mail | BEADLE-MAIL → SESSION → RECEIVE; SETUP | Fix CLI/MCP policy parity before exposing new agent callers. Account routing, durable arrival identifiers and watch state remain separate from autonomous execution. |
| Vox audio | VOX-DESIGN → STATE → CONTRACT; ENABLE | Reuse vox-zugu, including provider/model value object and NullModel. Put lifecycle-event decisions, recap limits and duplicate suppression in the engine. |
| Quarry knowledge | QUARRY-DESIGN → CONTEXT/SURFACE → CAPTURE/TASKS/ENABLE | Reuse naming/enablement work, preserve immediate acceptance by default, and define actual capture recovery guarantees. Explicit-target retrieval can be an earlier partial release. |
| PRFAQ workflows | PRFAQ-CLI → MEETING; RESEARCH | Package actual helpers, durable meeting/reducer records, source capabilities and native independent role contracts. No manufactured HTTP/MCP service. |
| Z-spec verification | ZSPEC-CORRECTNESS, EXECUTION, CONTEXT, BMETHOD, WORKFLOWS | Preserve the shared command layer. Empty/incomplete/unsupported results cannot pass; native cancellation must reach real solvers. Lux client/lifetime contracts govern optional display. |
| Punt infrastructure | KIT-MANAGER, POLICY, CONTENT, CONFORMANCE; OpenCode outcomes of AUDITOR/RELEASE | Separate core install, explicit registration, repo enablement and preference. Full pi-specific outcomes can remain pending while OpenCode ships. |

Implement state/schema migrations with compatibility for existing clients, deliberate default/session scopes, idempotence and crash recovery. Preserve mature services rather than replacing them for symmetry. An authorization bypass is a defect to fix, not a behavior to preserve for compatibility.

## P1 step 3: complete native product behavior and controlled execution

Each `*-OPENCODE` lane implements native discovery, tools/workflows, permissions, session/child lineage, subscription/UI lifecycle and install/remove. Product reports specify its public transport. Stateful tools use actual native callback context; they cannot infer the current conversation from a shared MCP environment.

Biff must exchange and forward messages with provenance, classify trust, deliver appropriately while busy and idle, and recover from retry/reconnect without wrong-recipient or lost-but-acknowledged delivery. Biff's four-level policy is product-owned; source content cannot silently become authorization. Beadle inbox notification observes its own contact/read policy and never enables executing jobs as a side effect.

PRFAQ, Z-spec, Ethos and Punt judgment workflows require actual independent native child sessions, evidence, cancellation and human decisions where specified. No fictitious reviewer or synthetic user answer can satisfy acceptance. Missing peers and headless interaction have explicit usable outcomes.

Two additional P1 tracks remain separate from interactive tool registration:

- **Beadle OpenCode workers:** `BEADLE-WORKER-CONTRACT` → `BEADLE-SUPERVISOR` → `BEADLE-WORKER-OPENCODE`. Version signed recipes/grants, implement real containment and credential scope, claim jobs durably, validate results and finalize Ethos missions. Test a harmless signed mail→real backend→result→mission close→reply journey and failure/cancel cases. Use actual OpenCode flags and explicit native permissions.
- **Vox OpenCode voice:** the OpenCode scoped outcome of `VOX-CALL` reconciles existing voice decisions and proves supported launch/attach/steer/interrupt with explicit session, credential/read and device scope. Finite speech can ship earlier. Historical pi experiments remain evidence; they do not make pi a P1 prerequisite.

`BEADLE-TRANSPORT` repairs the existing custom-WS credential/framing gap. It can proceed independently of native stdio/direct-CLI clients, but remains a required shared product remediation before the complete fleet milestone.

## P1 step 4: certify OpenCode independently

The selected OpenCode release outcome for each repository covers final artifacts, compatibility, migration, doctor, owned cleanup, actual product journeys and existing Claude/core regression. `KIT-RELEASE@opencode` verifies the native channel. `KIT-CONFORMANCE` supplies evidence fixtures. `KIT-FLEET@opencode` requires all nine OpenCode release outcomes and all-nine composition.

Install from final packages outside development checkouts. Run all nine with an unrelated extension; check command/tool/widget collisions and progressive prompt load; exercise concurrent sessions/worktrees, missing peers, wrong versions, reconnect and removal while other clients remain active. Observe audio, rendering, consumed messages and independent reviewers where required. No pi helper, package, worker or voice outcome may appear in the transitive P1 prerequisite closure.

## P2: implement and certify native pi on the corrected services

Start `HOST-PI` with a finite Punt package operation and real released lifecycle/mode tests. Derive session/runtime/branch context from the extension API; clean up on runtime replacement; handle same-runtime tree navigation separately; use agent_settled for idle; generation-check late callbacks. TUI, RPC and JSON/print have different contracts. Use direct product CLI/HTTP/WS APIs rather than a generic MCP bridge.

Implement the nine `*-PI` adapters using the shared domain contracts. Reuse schemas, result validation and bounded transport utilities where proved useful, while independently authoring native events/UI/workflows. Validate one stateful and one streaming/media client early, then expand across products.

`HOST-PI-DELEGATION` is an early P2 prerequisite for independent Ethos/PRFAQ/Z-spec/Punt workflows. Ship a versioned helper that resolves in a clean consumer, launches actual independent children, controls discovery/grants/output/time, records lineage, cancels cleanly and validates results. It is not a required running service for unrelated tools and does not claim to supply an OS sandbox.

Complete `BEADLE-WORKER-PI` under the contained Beadle supervisor and `VOX-CALL@pi` under its controlled-host contract. Both use released native capabilities. Certify every selected pi product release outcome and `KIT-FLEET@pi`; then verify mixed OpenCode/pi sessions against shared daemons, including ownership, defaults, capture IDs and teardown. Full active-program completion requires both fleets and shared remediation, with Codex still deferred.

## Maintenance and revalidation

Pin a minimum/certified host matrix and repeat affected canaries when a harness changes. Re-read current source and repo-scoped Beads before taking a task; September 12 statuses are snapshots. Record scope amendments in product design records and a real key-to-Beads-ID application map. Keep planned, partial, blocked and certified states distinct.

Codex reactivation is a separate priority decision governed by [decisions.md](decisions.md). The former Codex-first risk probes are historical research, not the first tasks of this roadmap.
