# Development Workflow

This file is punt-kit's instantiation of the org workflow standard,
[standards/workflow.md](../standards/workflow.md). The standard owns the
frame: the three nested loops (backlog, PR, mission), their pseudocode, the
Z doorway schemas, tiers, branch and commit discipline, and the invariants.
The PR loop's review sequence, `merge_gate`, and the shape of `verified_ok`
are owned by [standards/pr-review.md](../standards/pr-review.md). Nothing in
either standard is repeated here.

This file supplies the four things the standard leaves to each repo: the
verification, the worker/evaluator table, the formal classes, and what the
backlog ranks mean for punt-kit.

## Verification

punt-kit ships two surfaces, and each has one entry point:

| Surface | Entry point | Install step before driving it |
|---|---|---|
| The `punt` CLI (`src/punt_kit/`) | The installed wheel: run `punt <subcommand>` from `PATH` | `make build`, then `uv tool install --force dist/*.whl` |
| The plugin (`plugin/`: commands, skills, agents, hooks, playbooks) | A dev session: `claude --plugin-dir plugin` from the repo root, then the command, skill, agent, or hook as a user would invoke it | None; the dev session loads `plugin/` directly |

`gstack-qa` drives both. For each changed surface it writes the expected
outcome first, installs or launches as the table says, records
expected-versus-actual, and certifies the commit SHA it exercised. The
certification happens before the PR opens and again after any push that
changes a non-exempt file.

**Human-judged exception: none.** punt-kit produces no audio and no rendered
output that only a human can judge; every behavior it ships is text on a
terminal, a file on disk, or a GitHub object, all of which `gstack-qa` can
read. An internal change that `gstack-qa` certifies does not wait on the
operator.

A plugin command, skill, agent, hook, or playbook under `plugin/` is behavior
even when it is Markdown or YAML, because Claude Code executes it. A change
there is never docs-only and is re-certified after every edit.

### `verify_exempt`

A file is `verify_exempt` when it matches one of these and is not under
`plugin/`:

- `*.md` outside `plugin/`
- `docs/`
- `standards/` (the `.tex` models included: a model is checked by `fuzz` and
  `probcli`, not driven)
- `lang-rules/`
- `patterns/`
- `tests/`
- `.github/` other than `.github/workflows/`
- `.pr_agent.toml` (the next Qodo review on the PR is its check)

A file under `.github/workflows/` is behavior. For a change there the pre-PR
certification is `gstack-qa` running the changed job's commands locally (the
same steps the YAML runs), and the run named below is the post-open
re-certification the PR description names:

| Workflow | Verifying run |
|---|---|
| `docs.yml`, `lint.yml`, `test.yml` (trigger: `pull_request`) | The run on the PR head; the PR description names it |
| `release.yml` (trigger: tag push `v*`; publishes to PyPI on any run) | `verify_exempt`: it cannot run before merge. Its build job runs locally first (`uv build`, then `uvx twine check dist/*`); the full run is the next tagged release, which the leader checks after merge |
| `biff-notify.yml` (trigger: `workflow_run` on completed Docs, Lint, Release, Test; skips PR-sourced events) | `verify_exempt`: it cannot run before merge. The verifying run is its first `workflow_run` on `main` after the merge, which the leader checks |

A PR that changes a workflow names the run that exercises it, and for the
two exempt workflows the leader checks the named post-merge run; a failure
there is a finding, fixed in a fix PR on the spot.

A docs-only PR (every changed file `verify_exempt`) is verified by
`npx markdownlint-cli2` on each changed file with zero findings and a
read-through of the rendered text; no QA certification is needed.

## Worker/evaluator table

The table lives in [CLAUDE.md](../CLAUDE.md) under "Ethos & Delegation" and
is not repeated here. It stays there because it is consulted at every mission
dispatch, and `CLAUDE.md` is loaded into every session while this file is
read on demand; the two paragraphs around it (the cross-repo breaking-change
protocol for standards diffs and the fleet reality check) are rules that bind
the same dispatch and belong beside it.

The mission-dispatchable workers for punt-kit are the handles in that table.
`gstack-qa` is the QA agent for the verification above and is never a mission
worker or evaluator.

## Formal classes

Each class has a model checked by `fuzz` (type-check) and `probcli`
(model-check) and kept beside the standard or code it describes.

1. **The PR review state machine.** `standards/pr-review.md`'s review
   markers, Qodo sessions and the outage fallback, findings and `answered`,
   rulings, escalations, `merge_gate` (machine A), and the Bugbot run,
   rerun, window, and ruling behavior (machine B). Models:
   `standards/pr-review-model.tex` and
   `standards/pr-review-model-bugbot.tex`; the check commands and cardinality
   bounds are in each file's header.
2. **The `punt release` phase sequence.** `src/punt_kit/release.py`, phases
   1 through 11, and `--resume-from`. It is a formal class because it is a
   sequential state machine with irreversible transitions (tag push, PyPI
   publish, sibling-repo PRs) and re-entry at any phase, so a wrong
   `--resume-from` precondition can re-run or skip an irreversible step.
   Model: `standards/release-model.tex`, written with the first change in
   this class and kept beside the other two.

## Backlog ordering for punt-kit

The sort is the standard's. What each rank means here:

1. **Security severity.** A Dependabot high or critical on the `punt`
   package; a release-pipeline credential (`release.yml` must stay on OIDC
   trusted publishing, no `PYPI_TOKEN`); a stale or wrong `install.sh` SHA
   pin that sibling repos and the org profile consume.
2. **Broken user journeys.** A `punt release` phase that fails or leaves a
   sibling repo on a propagation branch; `punt init`, `punt audit`, or
   `punt reconcile` failing against a sibling repo; a plugin command that
   fails after `/plugin update` from the marketplace; a standard that
   contradicts what the fleet runs (see the fleet reality check in
   `CLAUDE.md`).
3. **Active epic continuity.** A standards rewrite in flight across sibling
   repos keeps its claim until every affected repo has acknowledged it.
4. **Debt that blocks throughput.** Release phases without a failure
   harness; standards text that duplicates another standard; plugin
   surfaces that reach outside `plugin/` at runtime.
5. **Features.** New `punt` subcommands, new standards, new plugin commands
   or playbooks.

punt-kit's beads also hold org-wide cross-repo work (CI rollouts, security
enablement, multi-repo changes); those rank by the same sort, with the
affected-repo count as the tiebreaker inside a rank.
