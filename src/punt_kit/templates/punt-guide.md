# Tracking work in a Punt Labs repo

How an agent tracks work in a Punt Labs repo. punt-kit deposits this file;
edit the source in punt-kit (`src/punt_kit/templates/punt-guide.md`), never
this copy. The normative text is `standards/workflow.md` § 4 (the backlog
loop); this file is the operating rule that section leaves to the tracker.

Two trackers exist. **Beads** is the local issue database behind the `bd`
command; one issue in it is a *bead*. **Linear** is the hosted tracker, used
from its web app or from the Linear MCP tools when your harness has them: one
team, **Punt Labs**, key `PL`, id `c1dfbb2c-985e-40cf-b004-5127646efc9d`. A
*pull* copies Linear into beads; a *push* copies beads into Linear.

## Which tracker is the record here

Run `bd config get linear.pull_label`. Output starting with `repo:` means this
repo is migrated and Linear is the tracker of record. Anything else means beads
is. `bd config get issue-prefix` cannot tell you: it prints
`issue-prefix (not set)` on migrated repos whose `.beads/config.yaml` has the key. The migrated set is
`bd config get linear.push_prefix`, read live; it is maintained nowhere else.

## Migrated repos: Linear is the record

Beads is a read-mostly local mirror. Do not use it as the record when Linear
is available. Every migrated bead stores its Linear URL in `external_ref`.

- **Plan from Linear.** `bd ready` and `bd show` are fine as local reads
  because the mirror carries the dependency graph; `bd list` and `bd ready`
  need `--label-any <the repo label>` to stay inside this repo, because the
  shared database holds every repo's beads. Refresh the mirror first:
  `bd linear sync --pull-if-stale --team c1dfbb2c-985e-40cf-b004-5127646efc9d`
  pulls only when `.beads/last_pull` is missing or older than 20 minutes, never
  twice within 5 minutes (needs `LINEAR_API_KEY`). Auto-pull (`bd prime`
  pulling on its own at session start) is not on in every repo; never assume it ran.
- **Write in Linear, not beads.** Create an issue with the mandatory repo
  label (the value `bd config get linear.pull_label` printed) plus a type
  label (`Bug`, `Feature`, `Improvement`, `Epic`); a pull imports only issues
  carrying that repo label. Edit title, description and priority there. Claim, finish
  and cancel with the states In Progress, Done and Canceled. Labels, `blocks`
  relations and projects are Linear-only.
- **Two proven facts about labels.** A push sends no labels. A pull replaces a
  bead's label set with the issue's, so a beads-only label is wiped.
- **Blocked** means a `blocks` relation in Linear plus
  `bd dep add <bead> <blocker>`: a pull imports relations only with
  `--relations` and never removes one.
- **Deferred** means state Backlog plus the `deferred` label; pick work with
  `bd ready --exclude-label deferred`.
- **Automated loops** write Linear first, then the same status to beads.
  Never beads only.
- **The one sanctioned beads-first write** is
  `bd linear sync --push --issues <bead ids> --team <id>`, which sends title,
  description, priority and state only. Then add labels in Linear, then
  `bd linear sync --pull --issues <PL ids> --team <id>`.
- **One shared cursor.** The cursor is a saved timestamp; an incremental
  pull fetches only Linear changes after it. Every non-dry-run sync, a push
  included, moves it. A push hides Linear edits made since the last pull from
  the next incremental pull. A pull skips a bead edited locally since the
  cursor, then moves the cursor past that edit, so a later pull overwrites it.
- **Never:** a bare `bd linear sync`; an unscoped `--push`;
  `bd config set linear.*` (shared by every repo); removing `issue-prefix` or
  `linear.pull_label` from `.beads/config.yaml` (an unscoped pull imports the
  whole PL team as new beads).
- **ID bridge.** Bead to Linear: `bd show <id>` prints the `external_ref`
  URL. Linear to bead: `bd list --json` and match on `external_ref`.

## Beads-only repos: beads is the record

`bd create`, `bd ready`, `bd show`, `bd update <id> --status in_progress`,
`bd close`. Labels and dependencies live in beads. To migrate, use the
workspace `linear-migrate` skill.

## Both

- T4 work (a typo, a one-line fix, a mechanical refactor with no design
  choice) needs no issue; the commit is the record.
- Work is not complete until `git push` succeeds.
- Beads mechanics: the workspace `.docs/BEADS-SETUP.md`.
- Migration and reversal: the workspace `linear-migrate`, `beads-to-linear`
  and `linear-unmigrate` skills.
