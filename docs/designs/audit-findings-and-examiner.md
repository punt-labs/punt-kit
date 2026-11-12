# Design: A Findings Type for `punt audit`, and the Standards Examiner

**Introduced:** 2026-11-12
**Worker:** adt · **Evaluator:** mdm

This document settles two things the audit-engine epic (pkit-fp5x) orders as
one unit: the `Finding` class that replaces the `(status, label, detail)`
tuple every `punt audit` check returns, and the judgment examiner that
`punt audit --standard <name>` runs against one named standard. It follows
the shape of [lang-rules-deploy.md](lang-rules-deploy.md) and
[prfaq-make-recipe.md](prfaq-make-recipe.md): problem and fleet reality
check, the findings type, the harness, independence, the failure contract,
the tests, the operator decisions, a `DESIGN.md` ADR draft, and the
implementation write-set in waves.

The operator's rulings of 2026-08-02, recorded as DES-023
(`DESIGN.md:1322-1374`), are the frame and are not redesigned here: one
standard per run; audit-only at both ends; remediation by different hands;
one engagement, one report; a deterministic-only exit code; one shared
harness prompt with the standard as its reference. Every choice below sits
inside that frame, and where a ruling leaves a choice open the choice is
made and its alternatives recorded in § 7.

---

## 1. Problem

### 1.1 The tuple

Every check in `punt audit` returns a list of three-string tuples. The alias
is `type _Findings = list[tuple[str, str, str]]` (`src/punt_kit/audit.py:34`)
with the comment "One audit finding: (status, label, detail)"; the three
class-based modules each re-declare the same shape under `TYPE_CHECKING` as
`Finding = tuple[str, str, str]` (`src/punt_kit/audit_layout.py:28`,
`src/punt_kit/audit_permissions.py:16`, `src/punt_kit/audit_github.py:17`).
The first element is not a status: it is a rich markup string,
`"[green]✓[/green]"` (`src/punt_kit/audit_verdict.py:4-7`), chosen so that
`run_audit` can print it without translation
(`src/punt_kit/audit.py:105`). The tuple is assembled for one consumer, the
terminal, and that consumer's needs leaked into the data:

- **Severity is a glyph.** `status == PASS` compares a string against a
  markup literal (`src/punt_kit/audit.py:108-113`). A consumer that wants to
  know whether a finding failed has to know the markup.
- **Rule identity is absent.** No element says which standard or which
  section a finding enforces. `audit_layout.py` smuggles the section into the
  detail text (`"§ 8"`, `"§ 9.4"` at `src/punt_kit/audit_layout.py:379-384`,
  `394-397`); every other module names nothing. The epic's judgment examiner
  must tag each finding with its standard section (DES-023 rule 3), and the
  tuple has nowhere to put it.
- **Location is prose.** A finding that names a file does so inside the
  detail string, in whatever form the check chose: `(.gitignore:{number})`
  (`src/punt_kit/audit_layout.py:423`), `"Missing lint.yml"`
  (`src/punt_kit/audit.py:147`), `str(_relpath(py_typed, info.root))`
  (`src/punt_kit/audit.py:355`). Nothing can sort, group, or link findings
  by file.
- **Remedy is prose.** `"Missing — run punt audit --fix"`
  (`src/punt_kit/audit.py:279`), `" — run punt init"`
  (`src/punt_kit/audit_permissions.py:185`): the remedy is appended to the
  detail with an em dash, and a consumer that wants to offer the fix has to
  split on punctuation.
- **Examiner type does not exist.** Every finding is deterministic today;
  the examiner the epic adds produces findings that are not pass/fail per
  rule, and the tuple cannot say which examiner produced a row.
- **Markup escaping is a producer duty.** Because the detail is printed as
  markup, four sites call `rich.markup.escape` on it
  (`src/punt_kit/audit.py:71,133,587,690`), `audit_layout.py` escapes every
  detail in one sweep (`src/punt_kit/audit_layout.py:172`), and the other
  two modules escape nothing. A `[abc]` glob in a finding from
  `audit_permissions.py` or `audit_github.py` would be eaten as markup. The
  data carries a rendering concern, inconsistently.

The epic names three consumers that need the same thing first: the judgment
examiner (pkit-zmca), the MCP server (pkit-1up8), and the REST surface
(pkit-mud6). Each would otherwise parse rendered terminal text or invent its
own serialisation of the tuple. The epic's ordering is forced: the findings
type is the first task inside pkit-zmca because the examiner cannot be
built without it.

### 1.2 Fleet reality check

Surveyed on 2026-11-12 against `origin/main` of punt-kit (every citation
below is to that ref) and against the sibling checkouts under the workspace
root.

**The five audit modules and the findings flow.**

| Module | Role | Producers |
|--------|------|-----------|
| `src/punt_kit/audit.py` | Entry point `run_audit` (line 56); registers every check in one tuple (lines 80-97); collects (line 98); renders and counts (lines 101-118); decides the exit code (lines 120-121). | 14 `_check_*` functions (lines 136, 193, 258, 285, 344, 370, 389, 400, 414, 470, 582, 601, 635, 682); 13 are registered directly, and `_check_plugin_dev_suffix` (line 582) is called from `_check_plugin_dev_isolation` (line 504). |
| `src/punt_kit/audit_verdict.py` | The four markers `PASS`, `FAIL`, `FIXED`, `INFO` (lines 4-7), each a rich markup string. | none |
| `src/punt_kit/audit_layout.py` | `LayoutAudit(info).findings` (line 155); declares a fifth marker `WARN` (line 30). | 9 finding methods (lines 251, 284, 292, 343, 364, 388, 401, 435, 450). |
| `src/punt_kit/audit_permissions.py` | `PermissionsAudit(info).findings` (line 32). | 3 producers (lines 32, 110, 195). |
| `src/punt_kit/audit_github.py` | `GithubSettingsAudit(info.root).findings` (line 41); `_gh_json` returns a union of `object` and `Finding` (line 129) and callers test `isinstance(listing, tuple)` to tell a finding from a response (line 100). | 4 producers (lines 41, 60, 92, 167). |

The flow end to end: `run_audit` builds `checks`, a tuple of 16 zero-argument
callables (lines 80-97), 13 `functools.partial` wrappers over module
functions plus the three bound `.findings` methods. Each runs under
`_guarded` (lines 124-133), which catches `ReleaseError` alone and turns an
unreadable file into one `FAIL` tuple labelled "Project files are readable"
so the other checks still run. The flat list is printed one row per tuple
(lines 104-107): the marker, the label, then the detail on a dim second line
when non-empty. Three counters tally `PASS`, `FAIL`, and `FIXED` (lines
108-113); `INFO` and `WARN` rows print and are counted nowhere, and `WARN`
is not imported into `audit.py` at all. The summary prints the three counts
(lines 115-118). The exit code is `SystemExit(1)` when `failures > 0` (lines
120-121); two earlier exits cover a path that is not a directory (line 64)
and a `detect` that raises (line 72).

**Status markers in use: five.** `PASS`, `FAIL`, `FIXED`, `INFO`
(`audit_verdict.py:4-7`) and `WARN` (`audit_layout.py:30`). `WARN` is used
at `audit_layout.py:370, 383, 398, 448, 467`. `FIXED` is produced by three
checks under `--fix` (`audit.py:276, 359, 384`).

**Check count.** 16 registered callables; 69 tuple literals with a constant
label across the four producer modules, 45 distinct constant labels, plus
f-string labels (`f"{filename} exists"` at `audit.py:271`,
`f"GitHub settings ({exc})"` at `audit_github.py:55`). The epic's "~50
existing checks" is this population.

**Consumers that read rendered audit output today.** No Makefile, CI
workflow, or shell script in any sibling repo invokes `punt audit`; a grep
over the workspace for the string in `Makefile`, `*.yml`, `*.yaml`, `*.sh`,
`*.py`, and `*.go` outside punt-kit returns nothing, and no sibling's
`CLAUDE.md` mentions it. Every reader is one of these:

| Reader | How it reads | Citation |
|--------|--------------|----------|
| `/punt:audit` and `/punt-dev:audit` | Runs the CLI and tells the model to "Report the output to the user. Summarize the pass/fail results." | `plugin/commands/audit.md:17-24`, `plugin/commands/audit-dev.md:23` |
| `/punt:reconcile` | Runs `punt audit <project-path>` as step 1 and reports its output before the LLM reconciliation. | `plugin/commands/reconcile.md:31-40` |
| `standards-rollout` playbook | An LLM step: "Use punt audit if applicable, or manually inspect." | `plugin/playbooks/standards-rollout.yaml:36-46` |
| The test suites | `capsys` captures stdout and asserts substrings of rendered rows. | `tests/test_audit_layout.py:716-777`, `tests/test_audit_unreadable.py:22-44`, `tests/test_audit.py` (52 `run_audit` calls) |

`punt audit` has no `--json` path: the `audit` command passes only `path` and
`fix` (`src/punt_kit/__main__.py:82-89`), and the global `_json_output` flag
(`src/punt_kit/__main__.py:18`) is never consulted by `run_audit`, so
`punt --json audit` prints the same rich text. The CLI standard requires
every command to honour `--json` (`standards/cli.md:379-383`).

**The ruling text.** DES-023 (`DESIGN.md:1322-1374`) records the four rules
and the shared-harness decision verbatim, with five rejected alternatives.
`docs/sprint-plan.md:53-66` places the findings type as the first task inside
pkit-zmca and states the exit: `punt audit --standard <name>` runs against a
live standard, emits typed findings, and re-audits after remediation to sign
off.

**The corpus.** 33 standards under `standards/*.md` on `origin/main`, from
1.5 KB (`naming.md`) to 69 KB (`punt-labs-dir.md`); 17 are under 15 KB and
the five largest (`punt-labs-dir.md`, `workflow.md`, `tool-enable-disable.md`,
`pr-review.md`, `hooks.md`) are 32 KB to 69 KB. The wheel ships
`src/punt_kit` and nothing else (`tests/test_packaging.py:57-65`), so no
installed `punt` carries the corpus; every reader of a standard today reaches
it through the sibling checkout (`plugin/commands/reconcile.md:28-30`, the
`SiblingRepo` resolution the release uses at
`src/punt_kit/phases/phase01_preflight.py:161`) or GitHub.

**The headless agent surface.** `docs/WORKFLOW.md:22` already drives the
plugin through `claude -p --plugin-dir plugin "<command>"` for the demo gate;
the installed `claude` on this host accepts `--print` with
`--output-format json`, `--json-schema <schema>` for structured output,
`--tools <names>` to restrict the built-in tool set, `--max-turns`, and
`--no-session-persistence` (`claude --help`, 2026-11-12). ethos's end-to-end
suite drives `claude --print ... --output-format json` against a mock
upstream (`../ethos/docs/testing-strategy.tex:696-803`).

**What this design generalizes.** The three class-based modules already
follow the shape the findings type needs: a `@final` class with `__slots__`,
a `__new__` returning `Self`, and one `findings()` method
(`audit_layout.py:142-155`, `audit_permissions.py:19-32`,
`audit_github.py:28-41`). `_guarded` already centralizes one cross-cutting
concern (an unreadable file). The design keeps both: every producer stays a
callable returning a list, and the one place that touches every finding
stays `run_audit`.

**What this design supersedes.** The tuple alias and its three re-declarations;
the markup-string markers as the severity vocabulary; per-producer markup
escaping; and `audit_github.py`'s union return of a response or a finding
with its `isinstance(..., tuple)` discrimination, which the class makes
unambiguous.

---
