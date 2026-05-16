# Workflow Standards

How Punt Labs teams track work, develop code, and collaborate.

---

## 1. Issue Tracking

All projects use **beads** (`bd`) for issue tracking.

### Setup

Every repo must have beads initialized (`bd init`). The `.beads/` directory is committed to git.

### Workflow

- `bd create "title"` to create issues with `--type` (task, bug, feature, spike) and `--priority` (1-5)
- `bd ready` to find available work
- `bd update <id> --status in_progress` before starting
- `bd close <id>` when complete
- Work is not complete until `git push` succeeds

### Issue Quality

Issues must have:

- A clear title in imperative form
- A description with enough context for another engineer (or agent) to act on
- Correct type and priority
- Dependencies declared (`--blocks`, `--blocked-by`) when applicable

---

## 2. Branch Discipline

All code changes go on feature branches. Never commit directly to main. Branch protection rulesets enforce this — there are zero bypass actors.

```bash
git checkout -b feat/short-description main
```

### Branch prefixes

| Prefix | Use |
|--------|-----|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code improvements |
| `docs/` | Documentation only |
| `release/` | Release version bumps |
| `chore/` | Maintenance and housekeeping |

### Commits

One logical change per commit. Quality gates pass before every commit. Commit
messages follow Conventional Commits format: `type(scope): description`.

---

## 3. Development Loop

Every code change follows two nested loops. The inner loop governs a single
mission. The outer loop governs the full feature before it becomes a PR. Both
loops apply to every change — there is no scope below which either is skipped.

### Pseudocode

```python
def test():
    make_test()                   # run test suite against installed artifact;
                                  # write missing tests first if changed code
                                  # has no coverage
    exercise_manually()           # write expected output first, compare actual;
                                  # cover one failure mode, one boundary condition;
                                  # paste actual output


def fix_findings_via_ethos(findings):
    for finding in findings:
        # The finding IS the spec — design step collapsed, not skipped.
        # COO reviews the finding before delegating; that review is the design step.
        implement_via_ethos(spec=finding)


def inner_loop(mission):
    design_via_ethos()            # specialist produces write set + approach;
                                  # COO reviews: what changes, how it leaves
                                  # the system better, what was decided and why
    implement_via_ethos()         # specialist executes the write set
    make_check()                  # zero exceptions
    make_build()                  # build wheel
    make_install()                # install from built wheel — not dev install,
                                  # not uv run from source
    test()                        # make_test() + exercise_manually() — see above
    code_reviewer()               # on mission diff
    silent_failure_hunter()       # on mission diff
    fix_findings_via_ethos(findings)
    rerun_agents_until_clean()    # exit when both return zero findings
    commit()
    push()                        # push to remote branch / update draft PR


def outer_loop(feature):
    branch()                      # create feature branch
    open_draft_pr()               # draft so CI runs on every push

    for mission in feature.missions:
        inner_loop(mission)       # repeat for each mission; no limit

    make_check()                  # on full accumulated diff
    code_reviewer()               # on full diff — catches cross-mission issues
    silent_failure_hunter()       # on full diff
    fix_findings_via_ethos(findings)
    human_ide_review()            # only human review in the process;
                                  # all findings resolved before proceeding
    make_build()                  # build wheel
    make_install()                # install from built wheel
    exercise_end_to_end()         # complete user-facing workflow; paste output
    rerun_agents_until_clean()
    mark_pr_ready()               # convert draft to ready for remote review
```

### Design (`design_via_ethos`)

Before any code is written for a mission, the approach is decided via a design
mission delegated to the right ethos specialist. The specialist produces a write
set and approach; the COO reviews it before implementation begins.

The design brief must answer:

1. What this mission changes
2. How it leaves the system better — structural improvement, not just feature
   delivery: OO quality, coupling, cohesion, naming, module boundaries
3. What approach was chosen and why

If the design reveals a non-obvious decision with rejected alternatives worth
recording for future readers, write a `DESIGN.md` ADR entry. The commit message
is sufficient for most changes.

If a specialist hits a decision point mid-implementation, they stop and surface
it. `implement_via_ethos` does not resume until `design_via_ethos` reruns for
that decision.

### Implementation (`implement_via_ethos`)

Delegated to the right ethos specialist for the domain — never bare `Agent()`.
The specialist's personality, expertise, and writing style are load-bearing.
The design mission and implementation mission may use different specialists;
the same worker/evaluator pairing constraints apply to both.

### Finding fixes (`fix_findings_via_ethos`)

Review agents find issues; ethos specialists fix them. The finding itself is the
spec — design is collapsed to the COO reviewing the finding before delegating.
The same domain specialist that would implement the area handles the fix. Fixing
a finding in Python provider code goes to `rmh` or `gvr`, not a generic agent.

To dismiss a finding as inapplicable: document (a) the exact finding text,
(b) the specific reason it does not apply, (c) the code reference.
"Pre-existing," "by design," and "intentional" are not reasons.

### Install and test

`make_build()` builds the wheel. `make_install()` installs from that wheel —
not a dev install, not `uv run` from source. `test()` = `make_test()` (automated
suite against the installed wheel) + `exercise_manually()` (expected vs actual,
one failure mode, one boundary, paste output). See [PR and Review Standard](pr-review.md)
for project-type-specific install commands. `make check` passing is necessary
but not sufficient — it does not verify the installed artifact.

---

## 4. Remote Review

Remote review (Copilot, Bugbot) is **automated-only**. There is no human
reviewer in this phase — human review happens locally via IDE in the outer loop
before `mark_pr_ready()`. Remote review is a second opinion on already-clean
code, not the primary quality signal.

1. **Request Copilot review** via `mcp__github__request_copilot_review`
2. **Watch** — `gh pr checks <number> --watch` in a background task. If Bugbot
   remains `in_progress` more than 6 minutes after CI, treat as clean.
3. **Read all feedback** via `mcp__github__pull_request_read`
4. **Address every finding** — code fix, or documented dismissal (exact finding,
   specific reason, code reference). Re-request review after each push.
5. **Resolve all threads** before merging
6. **Merge** via `mcp__github__merge_pull_request` when the last cycle is clean

Expect 2–6 remote cycles, with the goal of driving toward 1–2 as inner and
outer loop quality improves.

---

## 5. PR Boundaries

See [PR and Review Standard](pr-review.md) for the full specification.

One PR = one complete, locally-verified unit of work, defined by rollback
granularity. Prohibited split reasons: "the diff is large," "separate concern,"
"I'll clean it up in a follow-on PR." Valid split reasons: independent rollback
capability, sequential dependency, independently shippable blast radius.

---

## 6. Test Coverage

Test coverage is a quality goal. The goal is coverage of behavior that matters —
critical paths, data transformations, error paths, and anything hard to reverse.

- Critical paths: covered
- Edge cases on critical paths: covered
- Data transformations: tested with realistic inputs including malformed ones
- New code: tests land in the same commit as the code
- Bug fixes: the test that would have caught the bug lands before the fix

Coverage percentage is a useful proxy but not the target itself. A codebase
with 95% coverage on trivial getters and 0% on error handling is worse than one
with 70% on paths that actually matter.

---

## 7. CHANGELOG Discipline

CHANGELOG entries are written **in the PR branch, before merge** — not
retroactively on main.

- Entries go under `## [Unreleased]`
- Categories: Added, Changed, Fixed, Removed (omit empty groups)
- Internal-only changes (CI config, dev tooling, test-only) do not get entries

---

## 8. Session Close

Before ending any session:

```bash
git status
git add <files>
git commit -m "..."
git push
```

Work is **not** complete until `git push` succeeds.

---

## 9. Work Recap

After merging a PR, send a recap email to <jim@punt-labs.com> via beadle.

- **Subject**: `[repo-name] PR #N merged: <title>`
- **Required**: bead ID, PR link, 1-paragraph summary of what changed, why,
  and how it left the system better
- **Include when relevant**: design decisions made, test coverage notes,
  follow-up work created

---

## 10. Design Decision Logs

Use `DESIGN.md` at the repo root. Write an ADR entry when a decision is
non-obvious, has rejected alternatives worth recording, or would confuse a
future reader. Consult the log before proposing changes to settled architecture.
Do not revisit a settled decision without new evidence.

---

## 11. Cross-Project Integration

Integrations must be optional, graceful (falls back silently when absent), and
one-way (A uses B; B does not know about A).

When a change affects a package consumed by other projects:

1. Producer runs `make build` and notifies consumer via biff
2. Consumer installs from the built wheel and runs `make check`
3. Both proceed with independent PRs
