# Testing

punt-kit follows the Punt Labs [testing standard](standards/testing.md) and
its [Python mapping](lang-rules/python/python-testing.md). This file records
how each tier and test kind applies here, and every deviation.

## Setup

Provision Python 3.13, Git and uv, then run `uv sync --frozen`. Run
`make hooks` to activate the local gates. It refuses to overwrite other Git
hooks and leaves linked worktrees without these test commands unaffected. If
the repo already has a custom pre-commit hook, invoke `.githooks/pre-commit`
from it. To chain a custom pre-push hook, move it aside and replace the
installed pre-push entry point with an executable wrapper:

```bash
#!/usr/bin/env bash
chain=/path/to/custom-hook
if [[ -x .githooks/pre-push ]]; then
  exec .githooks/pre-push --chain "$chain" "$@"
fi
printf '%s\n' 'punt-kit pre-push gate not present in this worktree; skipping it.' >&2
exec "$chain" "$@"
```

Point `/path/to/custom-hook` at the hook you moved. Both hooks then receive
the same list of refs. The hook targets use system temporary storage rather
than the checkout's `.tmp`.

## Triggers and budgets

| Tier | Runner and selector | Budget | Failure |
| --- | --- | --- | --- |
| Pre-commit | Local hook: `make test-changed` tests the staged index, selecting tests by staged path and source imports. Shared files, tooling, standards and source with indirect consumers fall back to the default suite. | <30 s for typical small changes | Stops commit |
| Pre-push | Local hook: `make test-push` runs the default suite on the pushed commit. | <3 min | Stops push |
| PR | GitHub Actions: Docs, Lint, Ratchet and Test. Test runs the default suite with branch coverage (`make coverage-ci`) and the installed-wheel smoke (`make smoke-candidate`). | 10 min job timeouts | Required checks block merge |
| Merge to main | The same workflows run on the main commit. | Same as PR | Red main triggers CI triage; Biff notifies |
| Nightly | `nightly.yml` on upstream `main` only, Ubuntu and macOS: `make test-nightly` lists quarantines (and rejects invalid ones), runs the default suite with coverage and the installed-wheel smoke. | 30 min job timeout | Biff wall to the team; not a PR check |
| Release candidate | `release.yml` `candidate-smoke`: the exact wheel `build` produced for the tag, installed in a clean venv, runs `scripts/smoke-release.sh candidate`. | 10 min job timeout | Blocks the `pypi` job |
| Post-release | `release.yml` `published-smoke`: `punt-kit==<tag>` from production PyPI, byte-compared with the candidate wheel, runs the same operations. | 10 min job timeout, retries for index propagation | Fails the release run; `punt release run` phase `ci` stops; Biff notifies |

## Test kinds

| Kind | Selector | Applies |
| --- | --- | --- |
| Unit and component | `make test` (pytest default selection: everything except `quarantine`) | Yes. Command layers run in-process through Typer's `CliRunner`. |
| Subprocess | Part of the default suite: tests that run real `git`, shell and Python children against temporary repositories. | Yes. Credential-free and local. |
| End-to-end | `make smoke-candidate` installs the built wheel and drives the installed `punt` binary: `punt repo init`, `punt repo audit` and `punt --json status` on a scaffolded project. | Yes |
| Domain | `make lint` runs `tools/check_standards.py`, which checks every standard and rule file for clause IDs, `Applies to:` lines and links. | Yes |
| Live | `uv run python tools/record_gh_fixtures.py --check` replays the recorded read-only `gh` commands and compares response shapes. Needs an authenticated `gh`. | Yes, manual. |
| Agent | The plugin under `plugin/` needs a real Claude Code session. | Manual only; see [Deviations](#deviations) |

## Isolation

`tests/conftest.py` points `GIT_CONFIG_GLOBAL` at a test-owned config and
sets `GIT_CONFIG_NOSYSTEM`, so a developer's `url.<base>.insteadOf` rewrites,
signing and hooks cannot change what the tests or their `git` children see.
Tests use `tmp_path` and `monkeypatch`; none need credentials or a network.
The release smoke runs with a private `HOME`, Git config and venv.

## Coverage

`make coverage` and `make coverage-ci` measure branch coverage of `punt_kit`
for the default suite, including Python child processes started by it
(`[tool.coverage.run] patch = ["subprocess"]`). The installed-wheel smoke
is not instrumented and is not counted. Test CI on `main` keeps
`coverage.xml` as the `coverage-<sha>` artifact for 90 days.

## Quarantine

Mark a flaky test with
`@pytest.mark.quarantine(issue="PL-123", owner="name", reason="...", expires="YYYY-MM-DD")`.
Collection fails unless the issue is a Linear `PL-` key, owner and reason are
set, and the expiry is today or within 14 days. The default selection skips
quarantined tests; `make test-quarantine` lists them and
`make test-quarantine-run` runs only them. There are no quarantines.

The 14 skips in the default run are `test_gh_fixture_contracts` cases that do
not apply to hand-authored fixtures; each states that reason.

## Deviations

Tracked in [PL-1480](https://linear.app/punt-labs/issue/PL-1480), owned by
the punt-kit maintainers, expiring 2026-12-07.

| Clause | Scope | Reason |
| --- | --- | --- |
| TST-2, TST-6, TST-7, TST-8 | Agent kind | The plugin's slash commands and `auto` playbook skill are verified by hand with `claude -p --plugin-dir plugin` ([docs/WORKFLOW.md](docs/WORKFLOW.md)), not by a trusted automated agent job on Nightly, the candidate or the published plugin. |
| TST-2 | Subprocess kind | Subprocess tests run inside the default suite; there is no marker to select them alone. |
| TST-6 | Live kind | `record_gh_fixtures.py --check` is run by hand, not on a schedule: it needs a token that can read rulesets and branch protection, and `gh_api_rules_branches_governed.json` has drifted from the live ruleset and must be re-recorded first. |
