# Decisions and scope history

Updated: 2026-09-13

This document separates operator decisions from engineering recommendations and unresolved implementation choices. Research observations are dated September 12; the priority decision below is September 13. A planned remedy is not proof that a feature works.

## Accepted operator direction

| Decision | Source/date | Consequence |
| --- | --- | --- |
| Native first-class support; no Claude compatibility shim | Initial planning request, 2026-09-12 | Use each host's actual loader, tools, lifecycle, UI and delegation. Keep one product engine behind public contracts. |
| Core technical/design debt is in remediation scope | Operator clarification, 2026-09-12 | Repair policy, state ownership, command contracts and product design where needed; adapter-only scope is explicitly insufficient. |
| OpenCode is P1 | Operator direction, 2026-09-13 | First implementation reference, first complete product releases and first nine-product fleet gate. |
| pi coding agent is P2 | Operator direction, 2026-09-13 | Native extensions/direct APIs and independent review support follow the validated shared contracts; pi does not gate OpenCode. |
| Codex may be dropped for now | Operator direction, 2026-09-13 | Defer all Codex-only probes, packages, capture experiments, workers, voice connectors and certification. Retain dated research; no active dependency may require it. |
| Work is a documented metaplan | Current request | Produce research, rationale, scope/dependencies and execution guidance. Integration implementation and bulk application of the proposed backlog are separate work. |

Priority here means program sequencing. It does not overwrite an existing bug's severity, Beads priority, ownership or status. A shared authorization defect can be urgent independently of which adapter exposed it.

## Execution recommendations within that direction

Use a finite Punt operation and an OpenCode Lux interaction as the first complete slices. Punt exposes packaging/resource/result-contract defects cheaply; Lux exposes session, lifecycle, callback and TUI behavior on an already mature core. Start Beadle, Biff, Vox and Ethos remediation in parallel so early pilots do not defer the critical path.

Develop OpenCode against its real contextual native tool API and keep state in the product service. Then make pi consume that service through its own native extension. Do not implement an OpenCode-shaped domain engine or generate pi code by translating OpenCode event payloads.

Ship independent host outcomes. Shared metadata, persona, auditor, media and release work may have an aggregate task spanning P1/P2, but their OpenCode outcome is evaluated using only OpenCode and shared prerequisites. Pi-specific helper/package work is P2. P2 exploration can follow proved P1 contracts when capacity permits; it does not delay the P1 release gate.

Retain separate tracks for interactive Beadle clients versus contained unattended workers, and finite Vox audio versus controlled voice sessions. Partial delivery can be useful, but the full product cell stays incomplete until its declared worker/voice journey is certified for that host.

## Design questions to resolve during implementation

These are bounded tasks, not permission to reopen settled operator choices:

- Biff daemon IPC, stable-address/lease/ack protocol and envelope design, within biff-00v's fixed signing/trust requirements.
- Vox session/default/device ownership and reconciliation of ratified versus proposed voice paths; preserve the already-ratified provider/model value object and NullModel.
- Quarry authoritative session-to-target selection versus immutable explicit targets, within the current one-daemon-per-database topology; native capture checkpoint/recovery guarantees and the outstanding canonical naming table.
- Beadle signed WorkerSpec migration and actual containment/grant enforcement. Preserve GPG semantics and reject unsupported grants instead of silently widening them.
- Native asset ownership, capability/compatibility declarations and the smallest useful shared TypeScript utilities, tested on two real products before generalizing.
- Each host's actual enforcement coverage. Domain authorization, model-tool interception and OS containment are different claims and require different evidence.

Existing designs and operator rulings named in the repository reports remain constraints. Implementation should record a concrete recommendation and alternatives in the owning design record when resolving a real fork.

## Deferred Codex research

The original audit ranked Codex highest in capability uncertainty for session-aware tools. It identified native plugin support and plausible native routes, but did not prove authoritative per-call session binding, exact-thread idle queue delivery or full native capture fidelity. Deferring Codex removes those experiments and their shipping dependencies from the current critical path; it does not imply that native Codex support is impossible.

The [Codex dossier](harnesses/codex.md), deferred repository sections, 14 deferred task records and nine deferred cells retain that research. The [original backlog](evidence/backlog-2026-09-12.json) preserves the prior three-host graph. Deferred tasks are not closed, certified, canceled in Beads or silently deleted.

Reactivation requires new operator prioritization, a fresh version/source audit, and revalidation of the previously unproven native capabilities. Assess the then-current repaired services rather than rerunning the original core work. Restore only real dependencies and authorize concrete native acceptance journeys; no Claude shim is a fallback completion path.
