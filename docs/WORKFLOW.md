# Development Workflow

This file is punt-kit's instantiation of the org workflow standard,
[standards/workflow.md](../standards/workflow.md). The standard owns the
frame: the three nested loops (backlog, PR, mission), their pseudocode, the
Z doorway schemas, tiers, branch and commit discipline, and the invariants.
The PR loop's review sequence, `merge_gate`, and the shape of `verified_ok`
are owned by [standards/pr-review.md](../standards/pr-review.md). Nothing in
either standard is repeated here.

This file supplies what the standard leaves to each repo: the verification,
the worker/evaluator table, the standing worker contract, the architectural
units, the formal classes, and what the backlog ranks mean for punt-kit.

## Verification

punt-kit ships three artifacts, each with one entry point:

| Artifact | Entry point | Install step before driving it |
|---|---|---|
| The `punt` CLI (`src/punt_kit/`) | The installed wheel: run `punt <subcommand>` from `PATH` | `make build`, then `uv tool install --force dist/*.whl` |
| The plugin (`plugin/`: commands, skills, agents, hooks, playbooks) | A headless session from the repo root: `claude -p --plugin-dir plugin "<the command as a user would type it>"`, for example `claude -p --plugin-dir plugin "/punt-dev:audit --help"` | None; the session loads `plugin/` directly |
| The installer (`install.sh`) | `sh install.sh`, as the README's `curl … \| sh` line runs it; it takes no arguments | A clean `uv tool` state: `uv tool uninstall punt-kit` first |

The interactive `claude` cannot start inside a session (`CLAUDE.md`,
"Claude Code CLI Reference"); the headless `-p` form can, and it executes
plugin commands, so `gstack-qa` drives all three. For each changed artifact
it writes the expected outcome first, installs or launches as the table
says, records expected-versus-actual, and certifies the commit SHA it
exercised. The certification happens before the PR opens and again after
any push that changes a non-exempt file.

**Human-judged exception: none.** punt-kit produces no audio and no rendered
output that only a human can judge; every behavior it ships is text on a
terminal, a file on disk, or a GitHub object, all of which `gstack-qa` can
read. An internal change that `gstack-qa` certifies does not wait on the
operator.

A plugin command, skill, agent, hook, or playbook under `plugin/` is behavior
even when it is Markdown or YAML, because Claude Code executes it. A change
there is never docs-only and is re-certified after every edit.

A script under `scripts/` is behavior. `release-plugin.sh` and
`restore-dev-plugin.sh` are run by `punt release` phases 4 and 9;
`audit-all.sh` is run by hand (`bash scripts/audit-all.sh [--fix]`). Because
`punt release` performs irreversible steps, a change to any of the three is
certified by invoking the script directly against a scratch checkout under
`.tmp/`, expected output written first.

### `verify_exempt`

A file is `verify_exempt` when it matches one of these and is not under
`plugin/` or `.github/workflows/`:

- `*.md` outside `plugin/`
- `docs/`
- `standards/` (the `.tex` models included: a model is checked by `fuzz` and
  `probcli`, not driven)
- `lang-rules/`
- `patterns/`
- `tests/`
- `.github/` other than `.github/workflows/`
- `.pr_agent.toml` (the next Qodo review on the PR is its check)

A file under `.github/workflows/` is behavior and is never exempt. For a
change there the pre-PR certification is `gstack-qa` running the changed
job's commands locally (the same steps the YAML runs) and certifying the
head; the run named below is the CI re-certification — on the PR head for
`docs.yml`, `lint.yml`, and `test.yml`, after merge for the other two — that the PR
description names:

| Workflow | Pre-PR certification | Named run |
|---|---|---|
| `docs.yml`, `lint.yml`, `test.yml` (trigger: `pull_request`, and `push` to `main`) | The job's commands run locally | The run on the PR head |
| `release.yml` (trigger: tag push `v*` or `workflow_dispatch`; publishes to PyPI on any run) | The build job: `uv build`, then `uvx twine check dist/*` | The next tagged release; the leader checks it after merge |
| `biff-notify.yml` (trigger: `workflow_run` on completed Docs, Lint, Release, Test; its one job runs only when the upstream run failed on a `push` or `workflow_dispatch` event) | The `if:` filter evaluated by hand against a failing and a passing upstream event, and the `biff wall` command it runs executed locally with a `QA test of biff-notify` message and `--duration 1m`, never the workflow's own `CI failed` text | Its first `workflow_run` whose upstream failed on a `push` or `workflow_dispatch` event; until one occurs the post-merge run has not happened, and the leader records that |

A failure in a named post-merge run is a finding, fixed in a fix PR on the
spot.

A docs-only PR (every changed file `verify_exempt`) is verified by
`npx markdownlint-cli2` on each changed `.md` with zero findings and a
read-through of the rendered text, and on each changed `.tex` by `fuzz -t`
plus `probcli` as the file's header or the companion `.md` it names
prescribes (a `*_buggy.tex` passes when `probcli` reports the violation it
was built to show); no QA certification is needed.

## Worker/evaluator table

The table lives in [CLAUDE.md](../CLAUDE.md) under "Ethos & Delegation",
beside the two rules that bind the same dispatch (standards diffs are
cross-repo breaking changes; the fleet reality check), and is not repeated
here.

The mission-dispatchable workers for punt-kit are the handles in that table.
`gstack-qa` is the QA agent for the verification above and is never a mission
worker or evaluator.

## The standing worker contract

Every implementation mission in punt-kit carries this block verbatim in its
contract. punt-kit has no ratchet gate (`make check` runs ruff, mypy,
pyright, shellcheck, and pytest; there is no `check-oo`, baseline file, or
update target), so the ratchet clauses of the standard's reference block
name nothing here and the block reads:

> **Goal.** Good design, stated as responsibilities: which unit (type,
> module, or package) owns what, who depends on what.
> `standards/python.md` says what good design means in Python; for a plugin
> command, skill, or playbook, `standards/plugins.md`. A change that moves a
> number without improving responsibilities — a grab-bag unit, a bundle of
> collaborators handed out for callers to reach through, a second facade
> forwarding to the first — is rejected even when the gate goes green.
>
> **Forbidden.** Restoring any file from git (`git show REV:path > path`,
> `checkout --`, `restore`, `reset`, `stash`), `rm`, `clean`, or switching
> branches. Pushing, or touching a PR. Piping a gate through `head`,
> `tail`, or `grep`. Suppressions (`# noqa`, `# type: ignore`, `xfail`,
> `--no-verify`).
>
> **On any test or type regression: stop.** Do not delete or skip the test,
> do not commit. Report the design and the failure to the leader, who
> decides.
>
> **Evidence, not claims.** Run `make check` with output saved to a file
> under `.tmp/`; cite the file and its final summary line. Commit only after
> that file shows exit 0. The evaluator and the leader re-run it; a report
> that disagrees with their run rejects the work.

## Architectural units

A unit in one of these classes gets a design mission before any
implementation mission, and the operator ratifies the design:

- A new `punt` subcommand, or a change to a subcommand's arguments or
  output format.
- A new standard under `standards/`, or a change that removes or shifts a
  documented rule in one (a cross-repo breaking change; `CLAUDE.md`,
  "Ethos & Delegation").
- A change to the plugin's layout: what `plugin/` contains, how a command
  resolves `${CLAUDE_PLUGIN_ROOT}`, or the dev/prod command pairing.
- A change to the `punt release` phase sequence or its `--resume-from`
  contract (also a formal class, below).

## Formal classes

Each class has a model, or acquires one with its first change, checked by
`fuzz` (type-check) and `probcli` (model-check) and kept beside the standard
or code it describes.

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
   The first change in this class writes its model at
   `standards/release-model.tex`, beside the other two.

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
   commands, skills, or hooks that reach outside `plugin/` at runtime.
5. **Features.** New `punt` subcommands, new standards, new plugin commands
   or playbooks.

punt-kit's beads also hold org-wide cross-repo work (CI rollouts, security
enablement, multi-repo changes); those rank by the same sort, with the
affected-repo count as the tiebreaker inside a rank.
