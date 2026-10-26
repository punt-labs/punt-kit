# Beads application mechanics verified locally

Read-only inspection on 2026-09-12. Installed binary: `bd version 1.0.4 (dev: main@77e267720368)`. Commands below describing future mutations were **not executed**. Help and queries were executed with cwd set to an actual owning repository; queries used `--readonly`.

## Repository scope is labels/prefixes over one database

`bd --readonly context --json` from Biff and punt-kit reports their distinct `cwd_repo_root`, `repo_root` and `.beads` locations, but the same backend `dolt`, mode `server`, database `beads`, the same configured hosted server. All nine checked `.beads/metadata.json` files also specify that database. Every repository's config contains a `directory.labels` mapping.

| Working directory | Issue prefix | Required repository label |
|---|---|---|
| `punt-kit` | `pkit` | `repo:pkit` |
| `biff` | `biff` | `repo:biff` |
| `beadle` | `beadle` | `repo:beadle` |
| `vox` | `vox` | `repo:vox` |
| `lux` | `lux` | `repo:lux` |
| `quarry` | `quarry` | `repo:quarry` |
| `ethos` | `ethos` | `repo:ethos` |
| `prfaq` | `prfaq` | `repo:prfaq` |
| `z-spec` | `z-spec` | `repo:z-spec` |

Evidence: read-only `bd show pkit-pjwn --json` executed **inside Biff** returns the Punt-kit issue and `repo:pkit`. Read-only `bd dep list vox-wgru --json` executed inside Vox returns the existing dependency on `lux-d84d` with `dependency_type: related`. Therefore full issue IDs are resolvable across these repositories in the current database. Their prefixes are not separate databases; repo-scoped inventory does not prevent cross-repo ID lookup.

Run every operation in the issue owner's project directory, as the user requires. Installed global `-C/--directory` also exists, but the application runner should use its process cwd explicitly. Do not use `--global` (different `beads_global` DB), `--db` overrides, `repo add/sync`, federation, prefix renaming or new initialization for this program.

**Version caveat:** Biff's checked config explicitly records that 1.0.4 `bd ready` does not honor `directory.labels`. Use explicit repository labels for ready queries, and preferably list queries too:

```bash
# Run with cwd set to biff.
bd --readonly context --json
bd --readonly list --all --limit 0 --label-any repo:biff --json
bd --readonly ready --label-any repo:biff --limit 0 --json
```

Do not derive the label from the directory name for punt-kit. Never use `ready --claim` during a read-only audit.

## Exact supported issue and dependency mechanics

These were verified using installed `create --help`, `update --help`, `comments add --help`, `dep --help`, `dep add --help`, `dep list --help`, `dep cycles --help`, `list --help`, `ready --help`, `batch --help` and `ship --help`.

| Intent | Supported command form | Constraint |
|---|---|---|
| Read before amendment | `bd --readonly show ID --json`; `bd --readonly children ID --json`; `bd --readonly dep list ID --json` | Include full current descriptions/children, not titles alone. Re-read at application time because this inventory is a snapshot. |
| Amend existing scope | `bd update ID --body-file FILE --acceptance TEXT --title TITLE` | Description is replaced by the reviewed complete body; preserve operator rulings, existing ownership, status, priority, parentage and dependencies unless the plan explicitly changes them. Always supply ID: omission targets the last touched issue. |
| Preserve reconciliation history | `bd comments add ID --file FILE` or `bd update ID --append-notes TEXT` | Record why older assumptions changed and link the plan; a comment alone is not an executable revised acceptance contract. |
| Label/map existing work | `bd update ID --add-label native-harness --set-metadata native_plan_key=KEY` | `--set-metadata` is repeatable. Preserve labels with `--add-label`, not `--set-labels`, which replaces all. One existing epic may map to several work keys: use a mapping artifact or an explicitly designed metadata value, not repeated overwriting. |
| Create new reviewed task/epic | `bd create --title TITLE --type task --body-file FILE --acceptance TEXT --parent EPIC_ID --labels repo:biff,native-harness --json` | Set type `epic` where appropriate. Create from the owner repo, use its explicit repo label, preserve existing program parentage; omit `--parent` if genuinely top level. Capture returned real ID. `--metadata @FILE` and `--spec-id VALUE` are supported. |
| Preview creation | `bd create ... --dry-run` | Help documents preview without creation. Not executed during this audit. `--readonly` may reject a create command before dry-run handling, so do not promise their combination works. |
| Reparent intentionally | `bd update CHILD_ID --parent PARENT_ID` | Existing single-parent ownership should normally remain; do not reparent every product epic beneath the fleet coordination epic. |
| Add actual blocker | `bd dep add BLOCKED_ID BLOCKER_ID --type blocks` | Direction is **dependent first, prerequisite second**. Exact help equivalence: `bd dep BLOCKER_ID --blocks BLOCKED_ID`. |
| Add same-DB cross-repo blocker | Same full-ID form above, with cwd set to the blocked issue's repo | Current cross-repo ID resolution and existing cross-prefix edge verified read-only. No new blocking edge was written or live write-tested. |
| Track without imposing order | `bd dep add PROGRAM_ID PRODUCT_ID --type tracks` | Keep product parentage; use tracks/related only for association, `blocks` only for real release prerequisites. |
| Bulk dependency wiring | `bd dep add --file FILE.jsonl` | One line per edge: `{"from":"BLOCKED_ID","to":"BLOCKER_ID","type":"blocks"}`. Also accepts `issue_id`/`depends_on_id`. Map every planning key to a real ID first. |
| Inspect both directions | `bd --readonly dep list ID --direction down --json`; `bd --readonly dep list ID --direction up --json` | Down = prerequisites; up = dependents. Multiple IDs supported. |
| Check graph | `bd --readonly dep cycles --json` | Cycle checker has no documented repo filter; interpret as database-wide and distinguish pre-existing cycles. Keep normal cycle checks on when adding edges. |

Suggested application sequence:

1. Re-read owner-repo context, current issue, children and both dependency directions. Confirm every proposed reuse/amend/split against the still-current record. Build an application manifest with existing IDs, reviewed field diffs and new-task bodies.
2. Preserve matching existing epics/tasks. Amend incomplete or stale assumptions in place. Split broad work by creating scoped children under the existing product program (`biff-00v`, relevant Vox program, etc.), with explicit acceptance and real dependencies. Closed prerequisites remain closed; current residual bugs receive new linked tasks unless a deliberate reopen is warranted.
3. Create only unmatched work, with explicit repo labels. Capture emitted IDs and store a durable `planning key -> repo -> real ID(s)` application map. A rerun first resolves that map and existing metadata/search results; it must not blindly create duplicates.
4. After all IDs exist, add blocking and tracking edges in the current shared DB. Example **shape**, not an actual edge created by this plan: a Biff task depending on a Punt-kit contract uses `bd dep add biff-REAL pkit-REAL --type blocks` in Biff. Do not put the symbolic `BIFF-*`/`KIT-*` plan keys into the Beads ID position.
5. Verify descriptions, parent/child structure, labels, dependency direction/cycles and explicitly labeled ready results. Keep application outcome and remaining unmapped keys with the plan. Creating tasks does not certify product implementation.

`backlog.json` is this program's planning schema, **not a verified `bd create --graph` input**. Installed help has a `--graph FILE` option, but does not establish that the program backlog matches its required graph schema. Do not run `bd import backlog.json` (import is JSONL issue data), `bd create --graph backlog.json`, raw SQL, or invented `bd split` syntax. `bd batch` is transactional, but its documented grammar only supports limited close/update/create/dep forms; update keys are only status, priority, title, assignee. It cannot apply the full descriptions/acceptance/metadata workflow. Prefer explicit reviewed commands and supported dependency JSONL, or implement a separately validated converter later.

## External-project capabilities are a different mechanism

Installed `dep add --help` also supports `external:<project>:<capability>`, resolved through `external_projects` configuration. `ship --help` says `bd ship CAPABILITY` finds an `export:CAPABILITY` issue, requires it closed, and adds `provides:CAPABILITY`; the external dependency resolves against a closed provider issue. Those configuration and cross-database resolution paths were not provisioned or executed here. They are unnecessary for these nine repositories sharing one database. Reserve that mechanism for a future genuinely separate project/database and verify its configuration before use; never use `ship --force` merely to make planned work appear ready.

No issue, dependency, label, config, status or database mutation was performed. A malformed help invocation (`bd --readonly create --graph --help`) was rejected by the read-only guard before any operation; subsequent conclusions use the valid `bd --readonly create --help` output.
