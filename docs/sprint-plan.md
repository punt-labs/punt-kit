# Sprint plan — drive punt-kit buglist to zero

Filed 2026-08-30 from operator direction: fix release engine bugs (weekly pain), then strengthen standards auditing/enforcement, then review standards rot, then decompose. `claude2cursor` is already gone (DES-021); no action. OO ratchet tooling moves to its own external repo — punt-kit's standards depend on it but do not embed it (see `pkit-kmos` update 2026-08-30).

## Scope

29 open beads at start of sprint — 28 pre-existing plus `pkit-ptvc` (standards rot review) filed today. 3 in-progress meta-epics (`pkit-k29q` product rethink, `pkit-a8w9` CLAUDE.md redesign, `pkit-r94d` playbook DSL) run underneath the sprints below.

## Sequence

Operator ratified release-first: **A is the entry point**. From there, the dependency graph — not a strict linear order — determines what runs when:

- **A** ships independently.
- **D** (standards rot) runs concurrently with **A** because it does not touch `release.py`; its edits are confined to `standards/`, `lang-rules/`, and a survey report under `docs/`.
- **B** (kit-manager) starts once **A** frees attention; it does not depend on **A**.
- **C** (standards enforcement) is deferred until **D** finishes so the LLM examiner enforces a fresh corpus, not a rotted one; **C** also depends on **B**'s `.punt-labs/<tool>/` declaration.
- **E** (playbook DSL) can start any time after **A** since it is orthogonal to standards work.

Read as a graph: **A ‖ D**, then **B**, then **C** (needs both B and D), with **E** floating after A.

### Sprint A — Release-engine reliability

Goal: eliminate every manual intervention `punt release` requires today. Uses shared synthetic-`gh`-output test harness (deliverable of epic `pkit-f85t`).

| Bead | P | Kind |
|------|---|------|
| `pkit-f85t.1` | P1 | `_get_project_version` has no plugin-only branch |
| `pkit-f85t.2` | P1 | Phase 6 waits for `release.yml` that plugin-only projects lack |
| `pkit-f85t.3` | P2 | Phase 11 profile-SHA check false-positive for marketplace-only plugins |
| `pkit-f85t.4` | P1 | `_wait_for_required_checks` has no fallback when branch protection absent |
| `pkit-fwql` | P1 | README-SHA guard fails at tag time (phase-order circularity) |
| `pkit-hsyi` | P1 | `--no-verify` in fleet release scripts (biff/quarry/vox/lux) |
| `pkit-3zu8` | P2 | Auto-update bundled template version pins in bump phase |
| `pkit-zqj5` | P2 | Org `.github/release.yml` on deprecated `PYPI_TOKEN`; move to OIDC |
| `pkit-i6gj` | P2 | Decompose 2437-line `release.py` into `phases/` package |

Exit: next release runs zero-touch on a plugin-only project and a hybrid project.

### Sprint B — Kit-manager foundation

Goal: `punt` becomes a kit manager for the repo it points at. Unblocks Sprint C.

| Bead | P | Kind |
|------|---|------|
| `pkit-qv4` | P1 | Rewrite filesystem.md to describe `.punt-labs/<tool>/` (already deployed) |
| `pkit-pjwn` | P1 | `punt enable/install/status` verbs; includes `punt enable` for punt itself in punt-kit |
| `pkit-s00b` | P2 | Fleet rollout: strip org duplicates + `punt auto claude` across ~15 repos |

`pkit-qv4` is de facto implemented across siblings; scope is the doc rewrite plus enabling `punt` itself in punt-kit through `pkit-pjwn`.

Exit: `punt enable`, `punt install <tool>`, `punt enable <tool>`, `punt status` work; punt-kit itself has `.punt-labs/punt/` with a committed marker.

### Sprint C — Standards enforcement

Goal: `punt audit` gains a judgment examiner scoped to declared kit. Deferred until after Sprint D so the examiner enforces a fresh corpus, not a rotted one.

| Bead | P | Kind |
|------|---|------|
| Findings type | — | First task inside `pkit-zmca`; not a separate bead |
| `pkit-zmca` | P1 | LLM judgment examiner, one standard per run |
| `pkit-mb8k` | P2 | Scope audit to declared kit (unblocked by `pkit-qv4`) |
| `pkit-jsxe` | P4 | Audit check for tracked bd runtime artifacts |

`pkit-mud6` and `pkit-1up8` (REST and MCP surfaces) stay P3, deferred until a consumer asks.

Exit: `punt audit --standard <name>` runs against a live standard, emits typed findings, re-audits after remediation to sign off.

### Sprint D — Standards rot review (interactive)

Goal: careful, interactive review of all 29 standards against deployed fleet reality. Runs in parallel with Sprint A because it does not touch `release.py`.

Epic: `pkit-ptvc` (filed 2026-08-30). Members already scoped: `pkit-qv4` (filesystem.md), `pkit-n6y8` (agent-engineering.md). Additional standards get sub-beads as the survey identifies drift — no preemptive 27-stub filing.

Method per standard (one session, operator-in-the-loop):

1. Cross-check standard concepts against sibling repo practice (grep + `git log` recency).
2. List drift: what's newer than the standard, what supersedes it, what's obsolete.
3. Decide: rewrite, supersede with rationale, or delete.
4. One PR per standard for reviewability.

Priority order (staleness × load-bearing):

1. `filesystem.md` (`pkit-qv4`) — known-wrong, blocker for Sprints B and C
2. `agent-engineering.md` (`pkit-n6y8`)
3. `github.md`, `naming.md` — untouched since March
4. `python.md`, `oo.md`, `lang-rules/python/python-oo-adoption.md` — update OO ratchet references to point at the new external repo (see `pkit-kmos`)
5. `c.md`, `pharo.md`, `swift.md` — untouched since July 19
6. Sweep the remaining 20 for drift

Exit: fleet cross-check report at `docs/standards-rot-survey-<date>.md`; every standard either verified fresh, updated, or deleted with rationale.

### Sprint E — Playbook DSL

Goal: prompt state-machine DSL lands. PR-loop is the first machine.

| Bead | P | Kind |
|------|---|------|
| `pkit-r94d` | P1 | Design (in progress) |
| `pkit-445i` | P2 | Implementation: SCHEMA.md, executor SKILL.md, pr-loop.yaml, helpers |

Design goes to operator for ratification before dispatch.

### Long tail (opportunistic)

Ride along with other sprints:

- `pkit-59sm` P2 — feature-usage logging (informs next round's cut-or-keep)
- `pkit-a4a` P2 — cross-project hook integration test via fake Claude spawn
- `pkit-8r6` P3 — `punt doctor` "(optional)" cosmetic
- `pkit-rwq` P3 — standardize on `importlib.metadata.version()`
- `pkit-oamm` P4 — time-box or drop the spec-media experiment

### Cancelled / already done

- **claude2cursor** — already removed in DES-021. No action. CHANGELOG and DESIGN.md history stay.
- **`pkit-kmos` reframed 2026-08-30**: OO ratchet tooling moves to its own repo, not to punt-kit. `python.md` and the OO adoption lang-rule remain the standards home and reference the external repo. This bead now covers filing the new repo, migrating the tooling out of `lux/tools/`, and pointing the standards references at the new location. Handled inside Sprint D so the standards changes land together.

## What is not in this plan

- `pkit-k29q` (product rethink) stays open as the operator's decision surface — it does not close until the sprints below finish.
- `pkit-a8w9` (CLAUDE.md architecture) closes when `pkit-s00b` closes.
- `pkit-52xz` (kit-manager epic) closes when Sprint B closes.
- `pkit-f85t` (release engine epic) closes when Sprint A closes.
- `pkit-fp5x` (audit engine epic) closes when Sprint C closes.

## Buglist ledger

Zeroing target: 29 open beads → 0 (28 pre-existing plus `pkit-ptvc` filed today). Excluding P3/P4 opportunistic and the three in-progress meta-epics, the concrete work is 21 beads across Sprints A–E. `pkit-ptvc` will add N sub-beads discovered during Sprint D.
