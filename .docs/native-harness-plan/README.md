# Native OpenCode and pi support for the Punt Labs toolkit

Updated: 2026-09-13 · OpenCode P1 · pi P2 · Codex deferred

Build native, first-class OpenCode support for all nine Punt Labs products first, then native pi coding-agent support on the same repaired product foundations. Technical and design debt that makes this cleaner is part of the implementation scope. Existing Claude integrations remain a regression requirement.

The operator selected this priority order on September 13. The research below was performed on September 12 across four toolkit artifacts, nine codebases and 2,419 repository-scoped Beads records. This is an evidence-backed execution plan, not a report that the integrations have shipped.

**Start with [Strategy, complexity and execution rationale](strategy.md).** It explains the harness comparison, product rankings, two-axis complexity matrix, architecture findings and recommended first work. Then use the [roadmap](roadmap.md) and [assignable backlog](backlog.json).

## What is documented here

| Document | Purpose |
| --- | --- |
| [Strategy and complexity](strategy.md) | The cohesive writeup: why OpenCode first, where the engineering effort is, and how to execute |
| [Decisions](decisions.md) | Operator direction, what is settled, what remains a design question, and Codex reactivation conditions |
| [Shared architecture](architecture.md) | Product services, explicit context, native adapters, authorization, package ownership and distribution |
| [Execution roadmap](roadmap.md) | P1/P2 milestones, pilots, parallel core repairs, worker/voice tracks and release gates |
| [Bead reconciliation](beads.md) | Existing work to reuse/amend/split and the actual supported repo-scoped Beads mechanics |
| [Machine-readable backlog](backlog.json) | 98 researched work packages: **84 active**, **14 Codex-only deferred**, and **231 active aggregate dependencies** |
| [Acceptance matrix](acceptance.md) | Nine OpenCode P1 cells and nine pi P2 cells, with independently evaluated product/release outcomes |
| [Validation record](validation.md) | Checks actually performed, research limitations and concurrent source changes |
| [Source design files](sources/) | The target-state design inputs: [command surface](sources/command-surface.html), [command spec](sources/pl-command-spec.html), [lexicon](sources/pl-lexicon.html) and the [generator](sources/gen_spec.py) for the command spec |

The [original artifact inventory](evidence/original-artifacts.json), [initial source baseline](evidence/source-baseline.json), [closing source observation](evidence/end-baseline.json) and [referenced Beads records](evidence/referenced-beads.json) preserve the audit evidence. The [original September 12 backlog](evidence/backlog-2026-09-12.json) preserves the former three-harness program; it is historical, not the current execution graph.

## Per-product research and design

Every repository report describes the actual shipped surfaces, source-level debt, native integration choices, existing-bead disposition and concrete acceptance journeys. Its Codex sections are retained as visibly deferred research.

| Product | Report | Principal remediation and integration work |
| --- | --- | --- |
| Biff | [Biff audit and plan](repos/biff.md) | Daemon-owned sessions/presence/inbox, signed authorship/delegations, trust-controlled delivery, replayable receive |
| Beadle | [Beadle audit and plan](repos/beadle.md) | Shared mail authorization, explicit accounts/sessions, durable receiver; separately, signed worker contracts and contained native backends |
| Vox | [Vox audit and plan](repos/vox.md) | Move session state into voxd, implement the ratified provider/model value object and NullModel, neutral events and native audio/voice control |
| Lux | [Lux audit and plan](repos/lux.md) | Extend the existing Hub identity/client/lease foundation; fix callback ownership, activation and native interactive lifecycle |
| Quarry | [Quarry audit and plan](repos/quarry.md) | Explicit session/database targets, coherent public command schemas, native capture provenance/checkpoints and recovery |
| Ethos | [Ethos audit and plan](repos/ethos.md) | Native context, governance/admission, durable audit, persona assets and the authority registry needed by Biff |
| PRFAQ | [PRFAQ audit and plan](repos/prfaq.md) | Package deterministic helpers; durable meeting records; real independent review and native questions/decisions |
| Z-spec | [Z-spec audit and plan](repos/z-spec.md) | Truthful solver outcomes, complete command/abort contracts, native review workflows and scoped Lux ownership |
| Punt-kit | [Punt-kit audit and plan](repos/punt-kit.md) | Structured findings, native package metadata, explicit kit-manager registration, standards/auditor/release infrastructure |

The artifact's 378-operation target vocabulary is not an implementation inventory. PRFAQ currently has no product MCP/HTTP service; Punt-kit has no daemon; Biff HTTP is MCP rather than REST; Beadle's WebSocket is a custom MCP transport; Quarry's current MCP is a stdio client of its HTTP daemon. These distinctions determine the appropriate native adapter rather than forcing every product into one packaging template.

## Harness baselines and native choices

These are **dated research baselines and certification candidates**, not claims about the latest release or completed live tests. Revalidate exact versions when implementation starts.

| Priority | Harness | Observed / proposed baseline | Native approach |
| --- | --- | --- | --- |
| P1 | [OpenCode research](harnesses/opencode.md) | Installed 1.18.27; initial certification candidate 1.18.30, with a 1.18.27 compatibility candidate to test separately | Native npm server/TUI extensions, contextual tools, commands/skills and independent delegation. Use per-call session context for stateful public API/CLI operations. |
| P2 | [pi research](harnesses/pi.md) | Installed 0.84.4; initial certification candidate 0.85.1, with a 0.84.4 compatibility candidate to test separately | Native packages and TypeScript extensions using direct CLI/HTTP/WS APIs; native lifecycle/UI and a released, packaged independent-child supervisor where required. |
| Deferred | [Codex research](harnesses/codex.md) | Observed 0.154.0 | Preserve findings and possible native designs. No package, context, queue, capture, worker or voice implementation is required by P1/P2. |

Primary source entry points are the [OpenCode release-pinned plugin source](https://github.com/anomalyco/opencode/tree/3104c1428ec91f809e5ab86631300de41eb6952e/packages/plugin) and [pi 0.85.1 release](https://github.com/earendil-works/pi/releases/tag/v0.85.1); the harness dossiers cite the individual APIs and source locations behind each finding.

## What first-class means

A user installs the selected harness's own package, enables a product in the intended repository, discovers its native tools/workflows and completes the product's actual journeys. Resume, compaction, cancellation, concurrent worktrees, upgrade, disable and removal work deliberately. Services remain authoritative for product state and authorization. Native adapters own host context, subscriptions, interactions and presentation.

Calling a stable public CLI or HTTP/WS API from a native extension is a first-class integration. An MCP declaration alone does not complete a product that also needs ongoing inbox delivery, identity, audio, visuals or capture. Independent reviewers must actually run in separate contexts. Prompt-native products need complete authored workflows and reliable artifacts, not a daemon added for symmetry.

P1 completes when all nine OpenCode product outcomes and OpenCode fleet composition pass. Pi cannot block that milestone. P2 completes the equivalent nine pi outcomes using the corrected shared services. Product-wide aggregate tasks may span both priorities, but their host-specific outcomes have explicit independent prerequisites. Codex is excluded from both milestones and from the active fleet-completion gate.
