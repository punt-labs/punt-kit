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

## 2. The findings type

### 2.1 Modules and classes

Three modules, each under the three-class limit, all in `src/punt_kit/`:

| Module | Classes | Role |
|--------|---------|------|
| `audit_verdict.py` | `Severity`, `Examiner` | The two closed vocabularies. The four markup strings it holds today move to the renderer. |
| `audit_finding.py` | `Rule`, `Location`, `Finding` | The value objects every producer returns. |
| `audit_report.py` | `Report`, `TerminalRenderer` | The collection with its counts, exit code, and JSON form; the one terminal consumer. |

`Severity` and `Examiner` are `StrEnum` classes, the form `Tier` already
takes (`src/punt_kit/permission_rules.py:24,43`), so each value is its own
JSON string with no translation:

```python
class Severity(StrEnum):
    PASS = "pass"
    INFO = "info"
    WARN = "warn"
    FAIL = "fail"
    FIXED = "fixed"


class Examiner(StrEnum):
    DETERMINISTIC = "deterministic"
    JUDGMENT = "judgment"
```

`Rule`, `Location`, and `Finding` are `@final` classes with a tuple
`__slots__`, a `__new__` returning `Self`, underscore-prefixed attributes,
read-only properties, and `from __future__ import annotations` at the top
of the module, the shape `LayoutAudit` already has
(`src/punt_kit/audit_layout.py:142-153`). `Finding` has no setter and no
mutating method; two findings are equal when every field is equal, and
`__hash__` pairs `__eq__` so a set of findings deduplicates.

```python
@final
class Rule:
    """Which standard, and which section of it, a finding enforces."""

    __slots__ = ("_section", "_standard")

    _standard: str  # the stem of standards/<stem>.md
    _section: str  # "8", "9.4", "2.11"; "" when the standard numbers no section

    def __new__(cls, standard: str, section: str = "") -> Self: ...


@final
class Location:
    """A path relative to the project root, and a 1-based line when known."""

    __slots__ = ("_line", "_path")

    _path: str
    _line: int  # 0 when the finding names a whole file

    def __new__(cls, path: str, line: int = 0) -> Self: ...


@final
class Finding:
    """One audit finding: what was examined, by whom, and what was found."""

    __slots__ = (
        "_examiner", "_label", "_location", "_message",
        "_remedy", "_rule", "_severity",
    )

    _severity: Severity
    _rule: Rule
    _label: str  # the check's name, the row header the terminal prints today
    _message: str  # what was found; "" when the label says it all
    _remedy: str  # what to run or edit; "" when there is nothing to do
    # Absence is the contract: a finding about the repository as a whole
    # (a ruleset, a missing tool) names no file.
    _location: Location | None
    _examiner: Examiner

    def __new__(
        cls,
        severity: Severity,
        rule: Rule,
        label: str,
        *,
        message: str = "",
        remedy: str = "",
        location: Location | None = None,
        examiner: Examiner = Examiner.DETERMINISTIC,
    ) -> Self: ...
```

Three positional parameters and four keyword-only ones keep the
constructor inside the four-positional limit. `__new__` validates at the
boundary: a `label` that is empty raises `ValueError`; a `FIXED` severity
with `Examiner.JUDGMENT` raises `ValueError`, because the judgment examiner
never edits (DES-023 rule 1) and so can never report a fix. The one
`| None` in the type carries its justification comment as PY-TS-14
requires; the alternative, a `Location` null object, is recorded in § 7.

Five class-method constructors are the migration vocabulary, one per
severity, each taking `(rule, label, message="", remedy="",
location=None)`: `Finding.passed`, `Finding.info`, `Finding.warned`,
`Finding.failed`, `Finding.fixed`. A producer line today reads
`(FAIL, "CHANGELOG.md exists", "Missing — run punt audit --fix")`
(`src/punt_kit/audit.py:386`); after migration it reads
`Finding.failed(_RULE, "CHANGELOG.md exists", "Missing", remedy="run punt audit --fix")`.

### 2.2 How the five markers map

| Today | `Severity` | Counted in the summary | Affects exit code |
|-------|-----------|------------------------|-------------------|
| `PASS` (`audit_verdict.py:4`) | `PASS` | yes, as `passed` | no |
| `FAIL` (`audit_verdict.py:5`) | `FAIL` | yes, as `failed` | yes, when `examiner` is `DETERMINISTIC` |
| `FIXED` (`audit_verdict.py:6`) | `FIXED` | yes, as `fixed` | no |
| `INFO` (`audit_verdict.py:7`) | `INFO` | yes, as `info` (new) | no |
| `WARN` (`audit_layout.py:30`) | `WARN` | yes, as `warned` (new) | no |

`WARN` joins the shared vocabulary; `audit_layout.py` stops declaring its
own marker. The summary line keeps its first three counts in the same order
and words (`N passed, N failed[, N fixed]`) and appends `, N warned` and
`, N info` only when those counts are non-zero, so a project with no
warnings or info rows prints the line it prints today.

### 2.3 The report and its exit code

`Report` is built once from the producers' lists and is the only object
`run_audit` reasons about:

```python
@final
class Report:
    __slots__ = ("_findings", "_language", "_project", "_project_type")

    def __new__(cls, project: ProjectInfo, findings: Sequence[Finding]) -> Self: ...

    @property
    def findings(self) -> tuple[Finding, ...]: ...
    def count(self, severity: Severity) -> int: ...
    @property
    def exit_code(self) -> int:
        """1 when any deterministic finding is FAIL; else 0. Judgment never counts."""
    def to_json(self) -> dict[str, object]: ...  # wire boundary; see § 2.5
```

The exit rule is the operator's ruling made executable: `exit_code` reads
`severity is FAIL and examiner is DETERMINISTIC`, and no flag, option, or
environment variable reaches it. `run_audit` ends with
`raise SystemExit(report.exit_code)` when the code is non-zero, replacing
the `failures > 0` test at `src/punt_kit/audit.py:120-121`. The two early
exits for a bad path and a failed `detect` (`audit.py:64,72`) stay as they
are; they happen before any finding exists.

### 2.4 The terminal renderer, one consumer among several

`TerminalRenderer` owns the five glyphs (the four strings now at
`audit_verdict.py:4-7` plus `WARN`'s), the `Console(emoji=False)` at
`audit.py:31`, and the single `rich.markup.escape` call. It prints, for
each finding, the glyph and the label on one line and the detail on a dim
second line when the detail is non-empty, where the detail is `message`,
then an em dash and `remedy` when `remedy` is non-empty. The five producer-side
`escape` calls (`audit.py:71,133,587,690`, `audit_layout.py:172`) are
deleted; the renderer escapes every label, message, and remedy once, so a
`[abc]` glob from any producer survives. The four labels written as raw
strings with pre-escaped brackets (`audit.py:214-251`) lose their
backslashes, since the renderer now escapes them.

The rendered rows for every existing check are byte-identical to today's
output: the glyph, the label, the dim detail, and the summary line do not
change for a report with no `WARN`, `INFO`, or judgment row, and a `WARN`
or `INFO` row prints exactly as it prints today. The snapshot tests of
§ 6 pin this. A judgment row is new output and renders with its rule after
the label: `✗ README names a feature that errors on use  [readme § Audience · judgment]`.

The other consumers the epic names each read `Report`, never the terminal:
`Report.to_json()` for `punt --json audit` and the REST surface (pkit-mud6),
`Report.findings` for the MCP server (pkit-1up8), and `Report.findings`
filtered by `examiner` for the remediation hand-off of § 4.

### 2.5 The JSON shape and its stability

`punt --json audit [--standard <name>]` prints one object on stdout and
nothing else, honouring the global flag the CLI standard requires
(`standards/cli.md:379-383`) and that `audit` ignores today
(`src/punt_kit/__main__.py:82-89`):

```json
{
  "version": 1,
  "project": "punt-kit",
  "language": "python",
  "project_type": "package",
  "standard": "readme",
  "summary": {"passed": 41, "failed": 2, "fixed": 0, "warned": 1, "info": 3},
  "exit_code": 1,
  "findings": [
    {
      "severity": "fail",
      "examiner": "deterministic",
      "standard": "github",
      "section": "",
      "label": "CI docs workflow exists",
      "message": "Missing docs.yml",
      "remedy": "",
      "location": {"path": ".github/workflows/docs.yml", "line": 0}
    },
    {
      "severity": "warn",
      "examiner": "judgment",
      "standard": "readme",
      "section": "Audience",
      "label": "README lists a Development section",
      "message": "Lines 88-104 give lint and test commands; the standard sends those to CONTRIBUTING.md.",
      "remedy": "Move the section to CONTRIBUTING.md and link it from Documentation.",
      "location": {"path": "README.md", "line": 88}
    }
  ]
}
```

`standard` at the top level is the `--standard` argument, or `null` when
the run had no judgment examiner. `location` is `null` when the finding
names no file. Every key is present on every finding; absence is `""`,
`0`, or `null`, never a missing key.

The stability promise: `version` is `1`; within version 1 a key is never
removed or renamed and a value's type never changes; new keys may be added
to any object; the `severity` and `examiner` vocabularies are the closed
sets of § 2.1 and a new value is a version bump. A consumer pins on
`version` and ignores keys it does not know. The REST and MCP surfaces, if
built, serialize `Report.to_json()` and add nothing of their own; that is
the whole point of the epic's ordering.

### 2.6 Migration of the existing checks

Direct rewrite, module by module, no adapter. The reasons:

1. **An adapter keeps the tuple alive.** A `Finding.from_tuple` shim would
   let every producer keep returning `(status, label, detail)`, so no
   producer would ever name its rule, split its remedy, or give a
   location; the type would exist and carry nothing. PL-PP-1 forbids the
   shim outright.
2. **The rewrite is mechanical and bounded.** 69 tuple literals across four
   modules, each becoming one class-method call with the same label and the
   same message, plus a `Rule` constant per module or per check. The three
   class-based modules change their return annotation from
   `list[Finding]` (the tuple alias) to `list[Finding]` (the class) and
   drop the `TYPE_CHECKING` alias at `audit_layout.py:28`,
   `audit_permissions.py:16`, and `audit_github.py:17`.
3. **The tests already pin the rows.** The 52 `run_audit` tests in
   `tests/test_audit.py` and the rendering tests in
   `tests/test_audit_layout.py:716-777` read stdout, so a rewrite that
   changes a row fails before it merges. The tests that compare tuples
   directly (`tests/test_audit_layout.py:290,363` through the
   `_findings_for` helper at line 70, `tests/test_audit_permissions.py`,
   `tests/test_audit_github.py`) are rewritten in the same commit as their
   module to compare `Finding` values, and `_findings_for` returns
   `list[Finding]`.

Each module's rewrite is one commit and one mission, and the four run in
parallel once `audit_finding.py`, `audit_verdict.py`, and
`audit_report.py` exist (§ 9, wave 2). Rule assignment follows the module
docstrings that already name a standard: `audit_layout.py:1` names
`punt-labs-dir.md § 8`; `audit_permissions.py:1` and the `permissions.md`
§ 1 reference at `audit_permissions.py:196`; `_check_makefile` names
`makefile.md` (`audit.py:415`); `_check_plugin_dev_isolation` names
`plugins.md` (`audit.py:507-508`). A check whose docstring names no
standard is assigned one by the implementing mission from the standard
that states the rule (`github.md` for the CI and ruleset checks,
`python.md` for the tool-config checks), and a check that enforces punt's
own scaffolding convention rather than a published standard
(`_check_beads`, `_check_claude_md`, `_check_plugin_version_sync`) carries
the stem `punt`, meaning "what `punt init` writes" (§ 7, item 12).

---

## 3. The harness: `punt audit --standard <name>`

### 3.1 The command line

```text
punt audit [PATH] [--fix] [--standard NAME]
punt --json audit [PATH] [--standard NAME]
```

`--standard` takes exactly one name and may be given once. `NAME` is the
stem of a file under the corpus directory: `readme` for
`standards/readme.md`, `punt-labs-dir` for `standards/punt-labs-dir.md`.
The name is matched exactly after lowercasing; `readme.md` and
`standards/readme.md` are accepted and reduced to the stem, so a shell
completion of the path works. An unknown name is a usage error: exit 2,
one line on stderr naming the given value, then the sorted list of valid
stems, one per line, and no audit runs. `--standard` given twice, or with a
comma-joined value, is the same usage error with the one-standard-per-run
rule stated in the message. `--standard` with `--fix` is accepted: `--fix`
acts on the deterministic checks as today, and the examiner runs after
`--fix` has written its files, so the judgment reads the fixed tree.

The corpus directory is resolved in this order and the first hit wins:
`PUNT_STANDARDS_DIR` when set and a directory; `<project>/../punt-kit/standards`
when the project's parent holds a punt-kit checkout, the sibling convention
`SiblingRepo.resolve` already uses for the release
(`src/punt_kit/phases/shared/siblings.py:62-70`) and `reconcile.md:28-30`
documents; and `<project>/standards` when the project is punt-kit itself.
No hit is the "standard missing" row of § 5. The corpus does not ship in
the wheel (§ 7, item 8): `src/punt_kit` is the whole package
(`tests/test_packaging.py:57-65`), and a copy inside it would be a second
source for the thing it audits against.

### 3.2 What the agent is given

One prompt, the same for every standard, assembled by `AuditExaminer` in
`src/punt_kit/audit_examiner.py` from three parts:

1. **The harness prompt.** The package data file
   `src/punt_kit/templates/examiner-prompt.md`, beside the other templates
   (`src/punt_kit/audit.py:36`). It states the role (an auditor reading one
   standard against one repository), the two prohibitions (write nothing;
   run nothing that writes), the reading procedure (read the standard
   first, then the files it governs, then compare), the findings
   discipline (each finding cites a section of the standard and a file
   and line; a conforming area is reported as a `pass` row naming the
   section, so silence never reads as compliance), the severity rules of
   § 3.4, and the output contract: a JSON object matching the schema, and
   nothing else. It lives in the wheel, not under `plugin/`, because the
   wheel is what runs on an installed `punt` with no plugin, and
   `CLAUDE.md:65-70` forbids the plugin surface from reaching outside
   `plugin/` at runtime; the slash command stays the thin wrapper it is
   today (`plugin/commands/audit.md:17-24`) and passes `--standard`
   through in `$ARGUMENTS`.
2. **The standard, whole.** The full text of `standards/<name>.md`,
   fenced, with its path and its `git log -1 --format=%H` when the corpus
   is a checkout, so the report can say which revision was audited. The
   largest standard is 69 KB (§ 1.2), under a fifth of the context the
   headless session has; one standard per run is the ruling, and sections
   are not sliced (§ 7, item 9).
3. **The project brief.** The `ProjectInfo` fields the deterministic
   audit already prints (`language`, `project_type`), the project root
   as the working directory, and the deterministic findings of this same
   run as JSON, so the examiner does not re-report what a deterministic
   check already failed.

### 3.3 How the agent runs and what it returns

`AuditExaminer` runs one headless session:

```text
claude --print --output-format json --json-schema <schema>
       --tools "Read,Grep,Glob" --max-turns 40 --no-session-persistence
       --permission-prompts none --add-dir <project>
```

The tool list is the read-only three; `Bash`, `Edit`, and `Write` are not
in it, so the auditor cannot edit by construction and not only by
instruction. `--json-schema` is the findings schema of § 2.5's `findings`
array wrapped in an object with a `findings` key; the result's
`structured_output` is the only part of the session's JSON that is read.
The session's `is_error`, `num_turns`, and `total_cost_usd` go into the
`INFO` row of § 3.5. `--max-turns` and a wall-clock timeout of 600 seconds
bound the run; both are constants in `audit_examiner.py`, not flags
(§ 7, item 13).

The returned object is parsed by `FindingSchema.parse` in
`src/punt_kit/audit_finding.py`, the wire-boundary method that takes
`dict[str, object]` and returns a `Finding` or raises `ReleaseError` naming
the offending key, the same discipline `JsonFile.parse_object` uses
(`src/punt_kit/phases/shared/json_file.py:46-53`). Parsing is total:
every finding in the array is parsed or the whole array is rejected, so a
report never carries half of an examiner's output. Free prose from the
agent is unreachable: a session that returns text instead of the schema
fails `--json-schema` validation on the harness side and reaches
`AuditExaminer` as a malformed result (§ 5).

Every finding the parser builds is forced to `examiner=Examiner.JUDGMENT`
and `rule.standard=<name>`, whatever the agent wrote in those fields; the
agent chooses `section`, `severity` (from `pass`, `info`, `warn`, `fail`;
`fixed` is rejected), `label`, `message`, `remedy`, and `location`. A
`location.path` outside the project root is rejected.

### 3.4 Severity rules for judgment findings

The harness prompt states them, and `FindingSchema.parse` cannot check
them, so the evaluator of each implementation mission reads a sample:

| The agent found | Severity |
|-----------------|----------|
| A rule the standard states with "must", "never", "required", or an imperative, and the repository breaks it at a cited line | `fail` |
| A rule the standard states with "should" or "prefer", broken at a cited line | `warn` |
| An area the standard governs and the repository conforms to, named by section | `pass` |
| Something the standard does not cover, or a question the auditor could not settle from the files | `info` |

### 3.5 Merging and the report

`run_audit` appends the judgment findings to the deterministic ones in
one `Report`; the renderer prints them after the last deterministic row
under a one-line heading naming the standard and the corpus revision, each
row carrying its `[<standard> § <section> · judgment]` tag (§ 2.4). The
run ends with one `INFO` row from the harness itself, labelled
`Examiner: <name>`, whose message gives the turn count, the cost, and the
elapsed seconds, so a run with zero judgment findings still shows that the
examiner ran and what it cost. The summary line counts judgment rows in
`passed`, `failed`, `warned`, and `info` like any other.

`Report.exit_code` ignores every judgment finding (§ 2.3). A run whose only
`fail` rows are judgment rows exits 0, prints them in red, and says so in
the summary: `exit 0 — judgment findings do not affect the exit code`.

---

## 4. Independence

### 4.1 Who may not do what

| Party | May | May not |
|-------|-----|---------|
| The examiner (the headless session of § 3.3) | Read the standard, read the repository, return findings | Edit, write, run a command, be given `Bash`, be re-run by the fixer, certify its own second opinion as the fixer's |
| The fixer (§ 4.2) | Edit the repository to resolve findings, commit on its branch | Run `punt audit --standard` to sign off, mark a finding resolved, edit the standard |
| The leader (the human or the COO session driving the loop) | Run the audit, dispatch the fixer, run the re-audit, read both reports | Fix anything itself and then sign off on that fix |

### 4.2 The remediation hand-off

`punt audit --standard <name> --handoff` writes the judgment findings with
`severity` in `{fail, warn}` to one file, `.tmp/audit/<name>-<utc-stamp>.json`
in the project, and prints its path; it is the § 2.5 object filtered to
those rows. Nothing else is automatic. The hand-off itself is one of two
mechanisms, chosen by the presence of `.punt-labs/ethos/enabled` in the
project, the marker tool-enable-disable.md § 2.7 defines
(`standards/tool-enable-disable.md:275-291`):

- **Ethos enabled.** The leader writes a mission contract whose
  `inputs.files` names the hand-off file, whose write-set is the files the
  findings locate, and whose success criterion is "every finding in the
  hand-off resolved; the worker runs no audit". `ethos mission create` is
  the dispatch, exactly as `docs/WORKFLOW.md` prescribes for any delegated
  change; the mission's own evaluator reviews the fix. The design generates
  nothing: a contract is an audit record the leader authors
  (`ethos mission create --help`), and a generated contract would carry a
  write-set the generator cannot judge.
- **Ethos absent.** The leader spawns one typed sub-agent
  (`Agent(subagent_type=<specialist for the repo's language>,
  run_in_background=true)`), the delegation form `standards/workflow.md:838`
  reserves for a bare spawn, with the hand-off file as its brief and the
  same two sentences: resolve every finding; run no audit.

In both forms the fixer never sees the harness prompt and never invokes
`punt audit --standard`; its brief is the findings file.

### 4.3 The sign-off

The sign-off is a second `punt audit --standard <name>` run by the leader
after the fixer's commit lands on the branch, with the project tree at that
commit. The re-audit is a fresh session; nothing from the first run is
passed in but the same three parts of § 3.2, so the examiner cannot be
told what was "fixed". Sign-off is the re-audit's report having zero
judgment rows at `fail` and zero at `warn`; the `pass` rows it prints are
the attestation, section by section. A re-audit that fails again produces
a new hand-off and a new mission; the same fixer may be dispatched again,
and still never runs the audit.

The leader's independence from the fix is the one condition the tool
cannot check, so the harness records who ran each audit: the `INFO` row of
§ 3.5 includes the `ethos whoami` handle when `ethos` is on `PATH` and the
OS user otherwise, and the hand-off file carries the same. A PR that
cites a sign-off cites that row.

---

## 5. The failure contract

Every row below is for `punt audit --standard <name>`; the deterministic
checks run to completion in every case and their exit code stands.

| Condition | What the user sees | Judgment rows | Exit code |
|-----------|--------------------|---------------|-----------|
| `NAME` is not a stem in the corpus | One `Error:` line on stderr with the given name and the sorted list of stems; nothing else runs | none; the audit does not start | 2 |
| No corpus directory resolves (§ 3.1) | The deterministic report, then one `FAIL` row `Examiner: <name>` with message "standards directory not found" and a remedy naming `PUNT_STANDARDS_DIR` and the sibling path | none | deterministic result, plus 1 for this `FAIL`: the harness row is deterministic, so a run that asked for an examiner and got none fails |
| `claude` is not on `PATH` | The deterministic report, then one `FAIL` row `Examiner: <name>` with message "claude not found on PATH" | none | deterministic result plus this `FAIL`, as above |
| The session exceeds 600 s or `--max-turns` | One `FAIL` row `Examiner: <name>` with the elapsed time and the turn count; partial output is discarded | none | deterministic result plus this `FAIL` |
| The session exits non-zero or `is_error` is true | One `FAIL` row with the session's error text, cut to 300 characters as `OperationalFailure.detail` does (`src/punt_kit/phases/shared/errors.py:55-69`) | none | deterministic result plus this `FAIL` |
| The result is not JSON, has no `structured_output`, or a finding fails `FindingSchema.parse` | One `FAIL` row naming the first offending key or the parse error; the raw result is written to `.tmp/audit/<name>-<stamp>.raw.json` and the row names it | none; a partial array is never merged | deterministic result plus this `FAIL` |
| The agent returns an empty `findings` array | One `WARN` row `Examiner: <name>` with message "returned no findings and no pass rows"; the prompt requires a `pass` row per governed section, so an empty array means the examiner did not audit | none | deterministic result; a `WARN` does not change it |
| The agent returns only `pass` rows | The rows print; the `INFO` row says so | the `pass` rows | deterministic result |
| The project has no `.claude/` directory | The deterministic checks run as today (the permissions check reports its missing `settings.json`, `audit_permissions.py:38-45`); the examiner runs, because it reads the standard and the tree and needs no `.claude/` | as returned | deterministic result |
| The project is not a git repository | As today for the layout and GitHub checks; the examiner runs without a corpus revision and the heading says `revision unknown` | as returned | deterministic result |
| `--fix` and `--standard` together | `--fix` writes first; the examiner reads the fixed tree | as returned | deterministic result |

The `FAIL` rows the harness itself emits carry `examiner=DETERMINISTIC`
and `rule=Rule("punt")`: they report that the tool could not do what it
was asked, which is a property of the run and not an opinion about the
repository, and the operator's ruling that judgment never moves the exit
code is about the agent's opinions, not the tool's own failures (§ 7,
item 14).

---
