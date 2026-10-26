# Validation record

Research audit: 2026-09-12. Priority/documentation revision: 2026-09-13. This package proposes implementation; it does not certify native integrations.

## Evidence reviewed

- All **four original files**, now published verbatim in [`sources/`](sources/) (`gen_spec.py` differs from its recorded hash only in its output path), recorded with hashes in [the original artifact inventory](evidence/original-artifacts.json). The 378-operation target vocabulary was treated as intended design, not shipped-API evidence.
- All nine codebases during the September 12 audit: entry points, commands/services, transports, plugins/workflows, install/release paths, relevant designs and tests. [Repository dossiers](README.md#per-product-research-and-design) cite the evidence for remediation and native choices.
- **2,419 repo-scoped Beads records** from successful read-only queries executed in each owning directory. [Referenced records](evidence/referenced-beads.json) retain descriptions/status/dependency history. These remain September 12 observations; the priority revision does not claim a new fleet-wide issue audit or mutate the proposed implementation backlog into live Beads.
- Installed Codex 0.154.0 help/features and generated protocol schemas, OpenCode 1.18.27 and pi 0.84.4 evidence, and fetched official/release-pinned upstream sources for the proposed baselines. [Harness dossiers](README.md#harness-baselines-and-native-choices) distinguish installed, released, experimental and unproven behavior. Codex is now deferred.
- Beads 1.0.4 help, repo context and cross-repo ID lookup as observed September 12. [Application mechanics](evidence/beads-application.md) records supported syntax and explicit repository labels. The custom backlog is not a verified Beads import schema.

Product source citations now use GitHub permalinks to the audit revisions so the published research is navigable without nine sibling checkouts. [The source-reference index](evidence/source-links.json) preserves their former workspace paths. Working-tree-only observations are explicitly identified in the dossiers; a baseline permalink is not a claim that an uncommitted change exists in that commit. No new live API/solver/media/worker certification is inferred from this citation update.

## Checks on the revised program

The latest [machine validation record](evidence/validation-results.json) contains exact counts and results. Validation covers:

- JSON syntax, unique work-package keys, dependency/specification references and dated existing-bead status agreement with saved evidence.
- **98 researched tasks: 84 active and 14 deferred**, **18 active certification cells and nine deferred Codex cells**, and **231 active aggregate edges**.
- Acyclic aggregate and expanded scoped-outcome graphs; no active task or outcome depends on deferred Codex work.
- The complete P1 OpenCode milestone closure contains no pi-only task or outcome. Both P1/P2 retain all nine matching product releases, their required Beadle worker/contract/supervisor and Vox voice outcome. Active fleet aggregation excludes Codex.
- Local document/evidence destinations, task-to-repository line references and the recorded pinned source targets. Historical snapshots remain explicitly dated rather than being rewritten to look current.
- Markdown lint under Punt-kit's existing configuration: `markdownlint-cli2 'docs/native-harness-plan/**/*.md'` from the punt-kit directory.

Independent reviews checked the priority graph and prose separately. Corrections included stale three-adapter acceptance, active Codex instructions, ambiguous compatibility-test wording, a pi helper named without its scoped auditor outcome, persona-renderer ownership and the mixed Beadle backend row. The [strategy](strategy.md) explicitly labels complexity scores and work sizes as engineering judgment, not measured effort or schedule commitments.

## Repository quality gates and preservation

The completed package was copied by itself into an isolated documentation checkout based on Punt-kit `f1ad6a35168b19bb20932535f4fd90e15d9ae840`. `make check` passed: Ruff lint/format and shellcheck, mypy, pyright, and **688 pytest tests passed with 14 skipped**. These are the existing Punt-kit regression checks, not live native-harness acceptance. The original checkout’s user edits, agent files and four original artifacts were not staged into this documentation change.

## Historical source movement and practical limits

The [initial baseline](evidence/source-baseline.json) and [closing observation](evidence/end-baseline.json) record preexisting changes. Lux advanced during the original audit: menu-id consolidation landed and was reverted, a coupling-checker fix landed, and uncommitted identity/roster work followed. The dossier records those observations without changing their Beads status. Re-read affected source and live issues before implementation. The [original backlog](evidence/backlog-2026-09-12.json) and [original validation result](evidence/validation-2026-09-12.json) preserve the former 27-cell program; they are not current delivery requirements.

No live model-driven harness journey, mail job, renderer interaction, audio playback, ingestion, solver run or unattended worker execution was performed for this planning deliverable. Product behavior tests were inspected during research; documentation validation cannot establish consumed turns, full capture fidelity, audible/painted output, independent reviewers or OS containment. Those remain explicit implementation acceptance gates.

The September 13 changes document priorities, rationale, active/deferred scope and release dependencies. They do not implement integrations, change live harness registration or apply the 98 proposed work packages to Beads. The plan directory is the deliverable; existing product/user edits and the four original artifacts are preserved. Workspace research caches and editing helpers remain under ignored `.tmp/native-harness-plan`.
