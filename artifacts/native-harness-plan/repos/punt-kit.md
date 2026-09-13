# Punt-kit: native harness plan

**Priority update — 2026-09-13:** OpenCode is P1; pi is P2. Codex designs and task rows below are deferred research, including workers and controlled voice backends. They impose no active dependency or release gate. Research/source and Beads observations remain dated 2026-09-12. See [the scope decision](../decisions.md) and the [active roadmap](../roadmap.md).

Baseline: `main` at `1ebc0a766423a8b6513feac902e6bb9e45fe867e`, inspected 2026-09-12. Existing untracked `artifacts/` and changes to local agent files predate this work. This report proposes changes; it does not report them implemented.

## What exists

Punt-kit is a Python CLI, standards corpus, scaffolding/audit/release tool, and a Claude plugin containing prompt workflows and playbooks. It has no MCP server or HTTP daemon. The CLI actually registers `init`, `audit`, `pii`, `release`, `seed`, `version`, `doctor`, and `status`; the artifact's `enablement` is target state. `auto`, `reconcile`, and backlog review execute as agent workflows. A daemon or MCP server is not a prerequisite for bringing these workflows to another harness.

The engine principle already exists in [architecture.md](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/standards/architecture.md): one engine, thin clients, explicit client context, one vocabulary. Implementation gaps are concrete:

- [detect.py](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/src/punt_kit/detect.py), `PLUGIN_MANIFEST_CANDIDATES`, `ProjectInfo.plugin_root`, and `detect` recognize Claude manifests and `CLAUDE.md`. One `plugin_manifest` property cannot describe a Python product plus multiple native integration packages and its existing Claude plugin.
- [CLI entry point](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/src/punt_kit/__main__.py), lines 74–116, delegates `init`, `audit`, and `pii` without passing the global JSON setting. [audit.py](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/src/punt_kit/audit.py), lines 29–96, renders Rich output and raises `SystemExit`; [pii.py](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/src/punt_kit/pii.py), `run_pii`, does likewise. A declared global `--json` does not make these operations a machine contract.
- [init.py](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/src/punt_kit/init.py), lines 183–189, creates guidance, Claude permissions, and ignore entries while scaffolding. `_init_permissions` seeds broad Claude-specific tool names. [seed.py](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/src/punt_kit/seed.py) also treats settings as Claude settings. Harness registration, repo policy, and scaffolding are mixed.
- [phase10_propagate.py](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/src/punt_kit/phases/phase10_propagate.py) and [phase11_verify.py](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/src/punt_kit/phases/phase11_verify.py) model the Claude marketplace and its source pins. There is no registry-artifact verification for OpenCode or pi, or native Codex package verification.
- [plugin/commands/auto.md](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/plugin/commands/auto.md) grants Claude tool names; [plugin/skills/auto/SKILL.md](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/plugin/skills/auto/SKILL.md) resolves Claude plugin paths. [reconcile.md](https://github.com/punt-labs/punt-kit/blob/1ebc0a766423a8b6513feac902e6bb9e45fe867e/plugin/commands/reconcile.md) references repository standards and templates that the installed `plugin/` subtree does not necessarily contain. Every native package must pass an install-outside-checkout test.
- DESIGN DES-021 says the Cursor converter was removed, yet `plugin/commands/claude2cursor.md` and its twin are present at this checkout. Resolve this observed code/design drift under the existing product rethink; do not use the converter as the source of the native integrations.

## Mandatory remediation

Make callable audit, PII, initialization, and seed operations return typed results. Keep rendering and exit handling in CLI adapters. Give JSON callers structured findings, changes, diagnostics, exit semantics, and cancellation; retain CLI behavior for humans. Machine clients must never parse terminal glyphs or model-generated prose to decide whether a release passed. Separate deterministic audit failures from judgment findings as already specified in `pkit-zmca`.

Replace the single-plugin model with product metadata plus a collection of harness packages. Extend detection, audit, build, version checks, install, and release verification together. Each package declares its core compatibility range, harness baseline, assets, commands/skills, and capabilities. Metadata generation is appropriate; generating native workflows by rewriting Claude prompts is not.

Complete `pkit-pjwn`: init scaffolds user-owned project files once; enable installs maintained guidance and activates punt's own marker; per-tool dispatch calls the owning tool. Add explicit harness selection for integration registration. Installation of a package must not turn on another harness or enable a repo. Preserve unrelated TOML/JSONC/comments/config and record owned assets so removal is exact. `punt status` should report installed core × registered harness × repo enabled × capabilities, not infer support from executable presence.

Publish harness-neutral guidance and playbooks as real distribution resources. Author native invocation wrappers around these resources. Use AGENTS.md/native instructions or skills according to each host's documented loader; writing Claude `@` imports into AGENTS.md is not an implementation. Keep operator-only release automation explicitly invoked. Skill autodiscovery must not turn a release/publish workflow into an automatic model action.

Punt-kit owns shared specifications and conformance fixtures: native lifecycle contracts, explicit session binding, command/result schemas, capability declarations, install ownership, optional-peer behavior, release matrix, and source provenance. It should not become a runtime broker that every independent tool must contact. Shared TypeScript utilities, if justified after two adapters, should handle transport/validation/cleanup only and ship with the individual packages.

## Native integrations and deferred Codex research

| Harness | Design | Product-specific behavior |
|---|---|---|
| Codex [deferred] | Native Agent Plugin package with skills, bundled references/playbooks, and supported OpenAI extension metadata where needed. Use the actual `punt` CLI for deterministic operations; no fake MCP service. | Explicitly invoked automation skill calls `punt release` and performs the judgment portions from the shared workflow. Project guidance loads through native instructions/skills. Native approval handling governs publishing steps. |
| OpenCode | Maintained npm package with native commands/skills. Register typed tools over the corrected CLI JSON results where they improve deterministic discovery. Package-level lifecycle code is minimal. | `punt audit` findings can be rendered as native output/UI without reparsing prose. Use native task/subagent capabilities for independent audit and remediation. Native permissions distinguish inspection, edits, and publication. |
| pi | Native pi package: skills/prompts plus a small TypeScript extension for explicit commands and typed CLI tools. No MCP bridge. | `registerCommand` supplies explicit automation entry points; `registerTool` exposes audit/PII/status after JSON fixes. Headless mode returns structured results without TUI calls. Require an independent evaluator invocation for judgment audits; do not imply pi has built-in subagents. |

Both active targets share one playbook/schema and standard reference corpus. Native harness orchestration is independently authored and tested. `bead-review` runs `bd` in the selected project's directory, including when the workspace contains multiple repos. Release pipeline tools remain CLI-admin operations with explicit invocation and harness permissions.

## Work packages and existing beads

| Key | Existing bead disposition | Scope, dependencies, and acceptance | Size |
|---|---|---|---|
| KIT-STD | New org coordination epic/tasks | Amend architecture, CLI, integration, hooks, plugins/distribution, permissions, enablement, context and release standards to distinguish core semantics from harness mechanics. Reconcile conflicting doctor/admin guidance and target artifact drift. Complete before adapter designs freeze. | L |
| KIT-RESULT | Reuse findings-type work assigned to `pkit-zmca` by `pkit-fp5x`; add sibling JSON tasks for init/pii/seed | Extract typed results and full JSON handling for audit/init/pii/seed; test successful and failing commands, non-TTY mode and cancellation. No harness dependency. | M |
| KIT-MANAGER | Reuse/amend `pkit-pjwn` (open), preserve its parent `pkit-52xz`; `pkit-qv4` is a closed prerequisite | Add explicit native registration and own-resource lifecycle to the existing kit-manager design. Validate install/register/enable as separate actions; disabling a tool preserves its data and another harness's registration. | L |
| KIT-POLICY | Reuse/amend `pkit-mb8k` (open) | Audit only declared tool/harness policy; add native package checks. Depends on KIT-STD and KIT-MANAGER's policy schema, not on every toolkit implementation. | M |
| KIT-CONTENT | Extend `pkit-k29q` (in progress); reference `pkit-s00b` (open) | Resolve converter/reconcile drift; ship shared reference assets and native wrappers; keep existing declared operator-only triggers. Validate package paths from clean external consumer dirs. | L |
| KIT-CODEX [deferred] | New native package task | Codex skills/package/guidance; depends KIT-STD, KIT-RESULT, KIT-CONTENT and Codex packaging proof. Install/invoke/update/remove in stock Codex without Claude installed. | M |
| KIT-OPENCODE | New native package task | Commands/skills and typed operations with native permission declarations; same core dependencies, own OpenCode packaging proof. | M |
| KIT-PI | New native package task | pi package and explicit commands/tools; same core dependencies, own pi packaging proof. | M |
| KIT-AUDITOR | Reuse `pkit-zmca` (open) | One-standard judgment workflow and separate evaluator in independently completed OpenCode P1 and pi P2 outcomes. Preserve deterministic-only exit status. Does not block initial deterministic audit support. | L |
| KIT-RELEASE | New shared release-channel task | Extend product/package metadata, builds, pins, publication, rollback and external-install verification for OpenCode and pi native npm channels. Pilot one tool before fleet propagation. | L |
| KIT-CONFORMANCE | New shared test-assets task | Version-pinned loader, lifecycle, identity, permission, package and product journey fixtures. Each repo runs its own acceptance; master matrix tracks 18 active outcomes and retains nine deferred Codex rows. | L |

`pkit-s00b` already says its old `punt auto claude` half is dead. Keep only relevant guidance ownership cleanup; do not resurrect the removed command. `pkit-k29q` is broad and in progress: attach implementation to the appropriate child scopes instead of replacing it with a second product rethink.

## Acceptance and rollout

Start in a consumer repo outside the Punt workspace, with Claude absent. Install just punt core and one selected native package. Discover its commands/skills; run audit and PII in read-only mode; inspect structured failures; run a scaffold change with reviewable output; load one bundled playbook. Update and remove the package without losing user instructions. Repeat for both active harnesses and preserve the Claude regression path.

Exercise explicit automation invocation versus a casual mention of a release; unsupported or denied publishing permissions must stop the publish action. Test two project roots with distinct beads so backlog review never reads the sibling tracker by accident. Execute release dry-run and resume/failure fixtures without live publication. Verify native artifacts from the tagged packages, not just source trees.

The smallest pilot is KIT-RESULT plus a deterministic native operation; full kit-manager, standards-auditor, and release-channel work then becomes shared infrastructure for the rest of the fleet. None of these tasks requires adding a punt daemon or manufacturing an MCP server solely for symmetry.

Additional dependency reconciliation: `pkit-s00b` prerequisites `pkit-k4fg` and `pkit-umqs` are closed. `pkit-fp5x` explicitly makes MCP (`pkit-1up8`) and REST (`pkit-mud6`) optional; native support does not require them. Its findings type is already assigned as the first task inside `pkit-zmca`. Split that work into an independently schedulable child if needed, preserving ownership and one representation rather than creating a duplicate. Initial typed results/JSON need not wait for the judgment examiner.
