# Design: One Hardened `prfaq` Make Recipe for the Fleet

**Introduced:** 2026-11-12
**Worker:** adt · **Evaluator:** mdm
**Withdrawn:** 2026-11-14, operator ruling: the `make prfaq` recipe is owned
by the prfaq tool, not by punt-kit, and `punt seed makefile` grows no `prfaq`
section. The § 7 decisions are moot. The document stays as the record of the
measured defect (§ 2.4) and the hardened recipe (§ 3.3, § 3.4), which the prfaq
repo inherits under Linear PL-715. The one finding that outlives it is that
`punt seed makefile` skips every non-Python repo (§ 2.2), tracked as PL-1043.

This document settles where the canonical `make prfaq` recipe lives, how it
reaches every sibling Makefile, how a repo opts in, what the recipe promises
on failure, how that promise is tested, how the fleet is rolled over, and
what `punt audit` checks afterwards. It follows the shape of
[lang-rules-deploy.md](lang-rules-deploy.md): summary, fleet reality check,
mechanism, the fork and each settled question with rejected alternatives, a
`DESIGN.md` ADR draft, the implementation write-set, and the
operator-decisions list.

---

## 1. Summary

`make prfaq` in seven sibling repos is a hand copy of one recipe that exits 0
when a citation or a cross-reference is unresolved, because `pdflatex` and
`biber` both report those as warnings and the recipe trusts exit codes and
the presence of a PDF. Measured on this host on 2026-11-12 with a
three-document fixture set (one clean, one with an undefined `\cite`, one
with an undefined `\ref`): every tool invocation exits 0 for all three, every
run leaves a PDF, and only the job's `.log` and `.blg` distinguish them. The
recipe also deletes the tracked PDF before the first pass in three repos and
sweeps intermediates with root globs in six.

The canonical recipe becomes a third managed section, `prfaq`, rendered by
the existing `punt seed makefile` from a template in the installed punt-kit.
Its content is cryptd's hardened recipe generalized with the prfaq repo's
empty-list guard: build under the job name `<base>.build`, read the `.blg`
and the final `.log` instead of trusting exit codes, replace the tracked PDF
only after every check passes, and remove intermediates by explicit job name.
The section is byte-identical in every repo. A repo opts in by declaring
`TEX_FILES` in its Makefile outside the markers; a Makefile without that
declaration gets no section, whatever the repo's language. `punt audit`
re-renders the section and fails on any difference, on a `TEX_FILES`
declaration with no section, and on a `prfaq` target outside the markers.
Three fixture documents pin the failure contract with stubbed tools in every
environment and with real TeX, which CI installs (§ 3.5).

The prfaq plugin's own compile script has the same defect under its own
issue; it adopts this document's failure contract and fixtures, and neither
repo depends on the other.

---

## 2. Fleet reality check

Surveyed on 2026-11-12 against `origin/main` of every sibling under the
workspace root. Line numbers are those of each repo's `Makefile` on
`origin/main` unless stated.

### 2.1 The seven Makefiles

| Repo | Lines | Variant | Last Makefile change |
|------|-------|---------|----------------------|
| vox | 103–128 (`LATEX_ARTIFACTS` 104–105, `TEX_FILES` 107, `prfaq` 109–125, `clean-tex` 127–128) | A, verbatim from the standard | 2026-08-31 |
| punt-kit | 39–64 (`LATEX_ARTIFACTS` 40–41, `TEX_FILES` 43, `prfaq` 45–61, `clean-tex` 63–64) | A, verbatim from the standard | 2026-11-11 (not this block) |
| lux | 171–200, 205–206 (`TEX_FILES` 182 lists `prfaq.tex docs/architecture/system.tex`; globs 172–180 span `docs/` and `docs/architecture/`) | A plus directory globs | 2026-09-11 |
| biff | 80–108 (`rm -f "$$dir/$$base.pdf"` at 90; `clean-tex` 105–108 also removes `docs/*.pdf`) | A plus PDF delete before pass 1 | 2026-10-24 |
| prfaq | 1–55, 77–78 (`TEX_DIRS` wildcard 6 and 21; empty-list guard 27–31; PDF delete 35; `\|\| true` 38; log excerpt on failure 45–51; `test: prfaq` 57) | A plus wildcard, empty guard, PDF delete, log excerpt | 2026-08-30 |
| beadle | 96–129 (`TEX_FILES` 105 lists five documents; PDF delete 111; `-halt-on-error` with `\|\| exit 1` on every pass 112–123; biber keyed on `.bcf` 114; missing-biber error 115–116; biber-failure error 117–118; root-glob sweep 126) | B, partial hardening | 2026-11-11 |
| cryptd | 176–246 (`TEX_FILES` 179, `LATEX_EXTS` 184, `PDFLATEX` 193, `BIBER_PROBLEM` 194, `TEX_UNRESOLVED` 197, `prfaq` 199–239, `clean-tex` 241–246) | C, hardened | 2026-11-09, PR #114, no test |

**Variant A** is the template in `standards/makefile.md` lines 141–172,
copied verbatim into vox and punt-kit and lightly varied in lux, biff, and
prfaq. It runs `pdflatex -interaction=nonstopmode` with output discarded and
no `-halt-on-error`, runs `biber` only when a `.bib` sits beside the `.tex`
and only when `biber` is on `PATH`, discards biber's exit status with
`|| true`, and declares success when `<base>.pdf` exists. It sweeps `*.aux
*.log *.out …` at the repo root, which removes any unrelated `.log` or `.out`
there. biff, prfaq, and beadle delete the tracked PDF before pass 1, so a
failed pass 1 leaves the repo without its committed PDF.

**Variant B** (beadle) adds `-halt-on-error`, fails on a nonzero pass, keys
biber on the `.bcf` biblatex writes, and errors when biber is missing or
exits nonzero. It still reads neither the `.blg` nor the `.log`, so biber's
`WARN - I didn't find a database entry` and LaTeX's `Reference … undefined`
pass through with exit 0.

**Variant C** (cryptd) is the hardened recipe: it compiles under
`-jobname=<base>.build` so the tracked PDF is never touched until the end,
greps the `.blg` for the pattern `(WARN|ERROR) -` followed by a space (biber lines carry a
`[pid] Biber.pm:NNN>` prefix, so a `^` anchor never matches), greps the
final `.log` for `(Citation|Reference) .* undefined|There were
undefined|Rerun to get|Please \(re\)run Biber` (anchored to LaTeX's own
warning forms so body text echoed under an overfull-box warning cannot trip
it), prints the first `^!` error lines on a failed pass, warns on overfull
boxes without failing, guards the final `mv`, and removes intermediates by
explicit `<dir>/<job>.<ext>` name. Its PR carried no test. No sibling
Makefile carries a `# punt:begin` marker of any kind, and none but cryptd
carries `BIBER_PROBLEM` or `TEX_UNRESOLVED`.

### 2.2 The two repos with no `prfaq` target

quarry and ethos have a `prfaq.tex`, `prfaq.bib`, and tracked `prfaq.pdf`
but no `prfaq` target. quarry's `docs` target (lines 189–200) runs
`pdflatex -halt-on-error` three times under `set -e` with `biber … || exit
1`, so it catches a failed pass and a biber crash but reads no log: an
undefined `\ref` and a missing database entry pass. ethos's `docs-pdf`
target (lines 85–98) runs `latexmk -halt-on-error`, which reruns to
convergence but also exits 0 on unresolved references. Both are opt-in
targets outside `make check` by each repo's stated decision. They are not in
this unit's rollout; § 5.4 says how they join.

### 2.3 The plugin's compile script

`prfaq/plugin/scripts/compile_prfaq.sh` on `origin/main`:

- line 25: pass 1 with output discarded, status unchecked;
- line 28: biber keyed on a `.bib` beside the `.tex`, not on the `.bcf`;
- line 30: a biber failure is `|| echo "Warning: biber failed — citations
  may show as [?]"`;
- line 32: a missing biber is a warning;
- line 37: the final pass is unchecked;
- lines 39–40: success is `[[ -f "$DIR/$BASE.pdf" ]]`;
- lines 45–50: overfull-box warnings are reported after success;
- lines 53–55: only a missing PDF reruns pdflatex with output shown and
  exits 1.

It has the same defect as variant A and is tracked as prfaq's Linear issue
PL-715. It is called from the plugin's `streamline`, `externalize`,
`feedback`, and `import` commands and from the `prfaq` skill, always as
`bash ${CLAUDE_PLUGIN_ROOT}/scripts/compile_prfaq.sh <file.tex>`, so it runs
on an arbitrary path inside a Claude Code session, with or without a
Makefile present. § 4.2 states how the two relate.

### 2.4 The measurement

Three documents, each a one-section `article` with `biblatex` (`backend=
biber`), one `\cite`, and one `\ref`: `clean` cites a key the `.bib` has and
references its own label; `badcite` cites `missing99`; `badref` references
`sec:zz`. Under variant A's sequence on this host (TeX Live 2025, biber
2.22):

| Document | pass 1 | biber | final | PDF | `.blg` match | `.log` match |
|----------|--------|-------|-------|-----|--------------|--------------|
| clean | 0 | 0 | 0 | yes | none | none |
| badcite | 0 | 0 | 0 | yes | `WARN - I didn't find a database entry for 'missing99'` | `Citation 'missing99' … undefined`, `There were undefined references.`, `Please (re)run Biber` |
| badref | 0 | 0 | 0 | yes | none | `` Reference `sec:zz' … undefined ``, `There were undefined references.` |
| nopages (empty body) | 0 | n/a | 0 | no | n/a | `No pages of output.` |

Variant A prints its success line for the first three and, for `nopages`,
reports a compile failure only because no PDF exists at the end, with no
line saying why. Variant C, run from a copy
of cryptd's lines 179–239 on the same files, prints `./clean.pdf` and exits
0 for `clean`, and for the other two prints the matched lines followed by
`Error: badcite.tex has unresolved citations (biber); see
./badcite.build.blg` and `Error: badref.tex has unresolved references; see
./badref.build.log`, with `make` exiting 2. With `pdflatex` removed from
`PATH` it prints `Error: pdflatex is not installed; install a TeX
distribution (TeX Live or MacTeX)` and exits 2.

### 2.5 What this design generalizes and supersedes

**Generalizes** variant C, plus the prfaq repo's empty-`TEX_FILES` guard
(lines 27–31: "a gate that compiles nothing passes for the wrong reason")
and its on-failure log excerpt, which cryptd already has as `grep -A3 '^!'`.
cryptd's explanatory comments (lines 181–197) move into the template so every
repo carries the reason for each line.

**Supersedes** variants A and B, the template in `standards/makefile.md`
lines 141–172, and cryptd's hand-rolled block, which the managed section
replaces (§ 5.4). The plugin script is superseded in contract, not in code:
the prfaq repo's own issue adopts § 3.4 and the fixtures.

---

## 3. The mechanism

### 3.1 Command lines

```text
punt seed makefile           # renders standard-targets + help (Python repos) and prfaq (any repo that declares TEX_FILES)
punt seed makefile --dry-run # reports the Makefile would change, writes nothing
punt audit                   # includes the "prfaq recipe current" rows of § 3.6
make prfaq                   # the rendered target; exit 0 and the PDF path, or exit 2 and one Error: line
make clean-tex               # removes intermediates for TEX_FILES by name; never the tracked PDF
```

`punt seed makefile` is an existing subcommand; this design changes its
output in two ways. It renders a third section, `prfaq`, when the Makefile
declares `TEX_FILES`, and it renders that section for a repo of any language.
Today `_seed_file` returns with "Makefile templates only support Python —
skipping" for every non-Python repo. That sentence becomes false under this
design and is replaced: the skip line is printed only when no section
applies, and reads `No Makefile section applies: standard-targets and help
need a Python project; prfaq needs a TEX_FILES declaration — skipping`.
These are the output changes `docs/WORKFLOW.md` § "Architectural units"
names, and they are why this is a design mission.

**Output and exit status.** `seed` honors the global `--json` and `--quiet`
flags every `punt` command carries (`main_callback` in `__main__.py`), and
today prints its result through the `rich` console on stdout. The rows
below are the contract for every path this design touches; the
`--json` object is one value on stdout with the keys shown, and the exit
status is 0 on every row because a repo with nothing to render is not an
error.

| Repo | `TEX_FILES` declared | Sections rendered | Text (stdout) | `--json` | Exit |
|------|----------------------|-------------------|---------------|----------|------|
| Python | yes | `standard-targets`, `help`, `prfaq` | `Updated:` then `✓ Makefile` indented two spaces; or `No changes needed.` when the file already matches | `{"target": "makefile", "sections": ["standard-targets", "help", "prfaq"], "changed": ["Makefile"]}` (`changed` is `[]` when nothing changed) | 0 |
| Python | no | `standard-targets`, `help` | as above | `{"target": "makefile", "sections": ["standard-targets", "help"], "changed": [...]}` | 0 |
| non-Python | yes | `prfaq` | as above | `{"target": "makefile", "sections": ["prfaq"], "changed": [...]}` | 0 |
| non-Python | no | none | the skip line above, then `No changes needed.` | `{"target": "makefile", "sections": [], "changed": [], "skipped": "no section applies"}` | 0 |
| any, `--dry-run` | either | as the matching row | `~ Makefile (+N lines)` indented two spaces (or `+ Would create Makefile`), or the skip line when no section applies; then `Dry run — no files modified.` on every dry run | the matching object with `"dry_run": true` and `changed` holding what would change | 0 |

`--quiet` suppresses the text lines; the `--json` object is unaffected by
`--quiet`. The existing failure paths (`run_seed` on a non-directory, an
unknown target, an unclosed marker, an unreadable project file) keep their
`Error:` line and exit 1, and under `--json` print `{"error": "..."}` as
`_die` does. The skip line goes to stdout, as the current message does,
because it is a result, not an error. `tests/test_cli.py` pins each row:
the sections list, the text lines, the `--json` keys, and exit 0; and pins
that the retired "only support Python" sentence no longer appears for any
input.

### 3.2 The opt-in

A Makefile opts in by assigning `TEX_FILES` outside the managed markers:

```makefile
TEX_FILES = prfaq.tex
```

Detection is a line matching `^TEX_FILES\s*[:?+]?=` in any unmanaged segment
of the Makefile, read through the existing `parse_segments`. The value is
never parsed by punt; it is make's. The prfaq repo's
`TEX_FILES = $(foreach d,$(TEX_DIRS),$(wildcard $(d)/*.tex))` declares the
same way. A repo with no Makefile, or a Makefile with no such line, gets no
`prfaq` section.

### 3.3 The rendered section

The template is `src/punt_kit/templates/seed/makefile/prfaq.mk.j2`. It
takes no context, so the section is byte-identical in every repo and
`render_section("prfaq", …)` equality is the drift test. Rendered:

```makefile
# punt:begin prfaq
# Compile the LaTeX documents listed in TEX_FILES (declared outside this
# section) and replace each tracked <base>.pdf only after every check passes.
#
# pdflatex exits 0 on an unresolved citation or reference, and biber exits 0
# on a missing database entry, so this recipe reads the job's .log and .blg
# instead of trusting exit codes. Each document builds under the job name
# <base>.build: a failed build never leaves a half-resolved PDF at the tracked
# path, and the job's .log and .blg survive for diagnosis. Every removal is by
# explicit name ($dir/<job>.<ext>), never by a root glob, so an unrelated
# *.log or *.out at the repo root is never touched.
.PHONY: prfaq clean-tex

LATEX_EXTS = aux log out bbl bcf blg run.xml fls fdb_latexmk synctex.gz toc
PDFLATEX = pdflatex -interaction=nonstopmode -halt-on-error
# biber lines carry a "[pid] Biber.pm:NNN>" prefix, so no ^ anchor.
BIBER_PROBLEM = (WARN|ERROR) -
# Anchored to LaTeX's own warning forms so body text echoed under an
# overfull-box warning (e.g. "undefined behaviour") cannot trip it.
TEX_UNRESOLVED = (Citation|Reference) .* undefined|There were undefined|Rerun to get|Please \(re\)run Biber

prfaq: ## Compile TEX_FILES to PDF; fails on unresolved citations or references
	@test -n "$(strip $(TEX_FILES))" \
	  || { echo "Error: TEX_FILES is empty; declare the .tex files to compile in the Makefile" >&2; exit 1; }
	@command -v pdflatex > /dev/null 2>&1 \
	  || { echo "Error: pdflatex is not installed; install a TeX distribution (TeX Live or MacTeX)" >&2; exit 1; }
	@for f in $(TEX_FILES); do \
	  echo "Compiling $$f ..."; \
	  dir=$$(dirname "$$f"); base=$$(basename "$$f" .tex); job="$$base.build"; \
	  for ext in pdf $(LATEX_EXTS); do rm -f "$$dir/$$job.$$ext"; done; \
	  $(PDFLATEX) -output-directory="$$dir" -jobname="$$job" "$$f" > /dev/null 2>&1 \
	    || { grep -A3 '^!' "$$dir/$$job.log" >&2; \
	         echo "Error: $$f failed to compile (pdflatex pass 1); see $$dir/$$job.log" >&2; exit 1; }; \
	  if [ -f "$$dir/$$job.bcf" ]; then \
	    command -v biber > /dev/null 2>&1 \
	      || { echo "Error: $$f uses biblatex but biber is not installed" >&2; exit 1; }; \
	    (cd "$$dir" && biber "$$job") > /dev/null 2>&1 \
	      || { grep -E "$(BIBER_PROBLEM)" "$$dir/$$job.blg" >&2; \
	           echo "Error: $$f failed to process the bibliography (biber); see $$dir/$$job.blg" >&2; exit 1; }; \
	    if grep -qE "$(BIBER_PROBLEM)" "$$dir/$$job.blg"; then \
	      grep -E "$(BIBER_PROBLEM)" "$$dir/$$job.blg" >&2; \
	      echo "Error: $$f has unresolved citations (biber); see $$dir/$$job.blg" >&2; exit 1; \
	    fi; \
	    $(PDFLATEX) -output-directory="$$dir" -jobname="$$job" "$$f" > /dev/null 2>&1 \
	      || { grep -A3 '^!' "$$dir/$$job.log" >&2; \
	           echo "Error: $$f failed to compile (pdflatex pass 2, post-biber); see $$dir/$$job.log" >&2; exit 1; }; \
	  fi; \
	  $(PDFLATEX) -output-directory="$$dir" -jobname="$$job" "$$f" > /dev/null 2>&1 \
	    || { grep -A3 '^!' "$$dir/$$job.log" >&2; \
	         echo "Error: $$f failed to compile (pdflatex final pass); see $$dir/$$job.log" >&2; exit 1; }; \
	  if grep -qE "$(TEX_UNRESOLVED)" "$$dir/$$job.log"; then \
	    grep -E "$(TEX_UNRESOLVED)" "$$dir/$$job.log" >&2; \
	    echo "Error: $$f has unresolved references; see $$dir/$$job.log" >&2; exit 1; \
	  fi; \
	  overfull=$$(grep -c "Overfull \\\\hbox" "$$dir/$$job.log" 2>/dev/null || true); \
	  if [ "$${overfull:-0}" -gt 0 ]; then \
	    echo "Warning: $$overfull overfull hbox warning(s) in $$f; content extends beyond margins:" >&2; \
	    grep "Overfull \\\\hbox" "$$dir/$$job.log" >&2; \
	  fi; \
	  mv "$$dir/$$job.pdf" "$$dir/$$base.pdf" \
	    || { echo "Error: could not replace $$dir/$$base.pdf; built PDF left at $$dir/$$job.pdf" >&2; exit 1; }; \
	  echo "  $$dir/$$base.pdf"; \
	  for ext in $(LATEX_EXTS); do rm -f "$$dir/$$job.$$ext"; done; \
	done

clean-tex: ## Remove LaTeX intermediates for TEX_FILES by name (never the tracked PDF)
	@for f in $(TEX_FILES); do \
	  dir=$$(dirname "$$f"); base=$$(basename "$$f" .tex); \
	  for ext in $(LATEX_EXTS); do rm -f "$$dir/$$base.$$ext" "$$dir/$$base.build.$$ext"; done; \
	  rm -f "$$dir/$$base.build.pdf"; \
	done
# punt:end prfaq
```

Differences from cryptd's lines 179–246: the empty-`TEX_FILES` guard is
added as the first step; `TEX_FILES` itself is not inside the section;
`.PHONY: prfaq clean-tex` is inside the section so a repo's own `.PHONY`
line need not list them; the comments are consolidated. Everything else is
cryptd's text. `biber` is keyed on the `.bcf` biblatex writes, not on a
`.bib` beside the source, so a stray `.bib` triggers nothing and a document
that uses biblatex without a biber on `PATH` is an error rather than a PDF
full of `[?]`.

A repo whose old `clean-tex` did more (biff removes `docs/*.pdf`; lux sweeps
`docs/*.fuzz docs/*.mf docs/fuzz.sty`) keeps that work in its own target
under another name, outside the markers; the managed `clean-tex` removes
only what the managed `prfaq` creates.

### 3.4 The failure contract

Every failure writes exactly one `Error:` line as the last line of stderr,
preceded by the diagnostic lines named below, and exits the recipe with 1,
which `make` reports as exit status 2. Every failure leaves the tracked
`<base>.pdf` untouched and leaves `<dir>/<job>.log` (and `.blg` when biber
ran) on disk. Success writes `Compiling <f> ...` and then `<dir>/<base>.pdf` indented
by two spaces to stdout and exits 0; overfull-box warnings go to stderr and do not change
the exit status. `<f>`, `<dir>`, `<base>`, and `<job>` are the document path,
its directory, its basename without `.tex`, and `<base>.build`.

| # | Condition | Lines before the `Error:` line | `Error:` line | make exit |
|---|-----------|-------------------------------|---------------|-----------|
| 1 | `TEX_FILES` empty after `strip` | none | `Error: TEX_FILES is empty; declare the .tex files to compile in the Makefile` | 2 |
| 2 | `pdflatex` not on `PATH` | none | `Error: pdflatex is not installed; install a TeX distribution (TeX Live or MacTeX)` | 2 |
| 3 | pass 1 exits nonzero | `grep -A3 '^!' <dir>/<job>.log` | `Error: <f> failed to compile (pdflatex pass 1); see <dir>/<job>.log` | 2 |
| 4 | `<dir>/<job>.bcf` exists and `biber` not on `PATH` | none | `Error: <f> uses biblatex but biber is not installed` | 2 |
| 5 | `biber` exits nonzero | `grep -E "(WARN\|ERROR) - " <dir>/<job>.blg` | `Error: <f> failed to process the bibliography (biber); see <dir>/<job>.blg` | 2 |
| 6 | `biber` exits 0 and the `.blg` matches `BIBER_PROBLEM` | the matching `.blg` lines | `Error: <f> has unresolved citations (biber); see <dir>/<job>.blg` | 2 |
| 7 | pass 2 (post-biber) exits nonzero | `grep -A3 '^!'` | `Error: <f> failed to compile (pdflatex pass 2, post-biber); see <dir>/<job>.log` | 2 |
| 8 | final pass exits nonzero | `grep -A3 '^!'` | `Error: <f> failed to compile (pdflatex final pass); see <dir>/<job>.log` | 2 |
| 9 | final `.log` matches `TEX_UNRESOLVED` | the matching `.log` lines | `Error: <f> has unresolved references; see <dir>/<job>.log` | 2 |
| 10 | every pass exits 0 and no `<dir>/<job>.pdf` exists (`pdflatex` wrote "No pages of output"), or `mv` cannot write `<dir>/<base>.pdf` | `mv`'s own message (`mv: <dir>/<job>.pdf: No such file or directory` in the first case) | `Error: could not replace <dir>/<base>.pdf; built PDF left at <dir>/<job>.pdf` | 2 |
| 11 | every check passes | `Warning: N overfull hbox warning(s) in <f>; …` and the lines, when N > 0 | none; stdout `<dir>/<base>.pdf` indented two spaces | 0 |

Rows 2, 6, 9, 10, and 11 were observed on this host (§ 2.4; row 10 with a
document whose body is empty, so every pass exits 0 and no PDF is written).
The others follow
the same `|| { …; exit 1; }` shape and are pinned by the stub tests of
§ 3.5. A document that cites nothing never writes a `.bcf`, so rows 4–7 do
not apply to it and `TEX_FILES` with several documents stops at the first
failing one.

### 3.5 The test

Two layers, both in `tests/`, both run by `make test`.

**Fixtures.** `tests/fixtures/prfaq/` holds `clean.tex`, `clean.bib`,
`badcite.tex` (cites `missing99`), `badref.tex` (references `sec:zz`),
`pass1-error.tex` (an undefined control sequence), and `nopages.tex` (an
empty body, so every pass exits 0 and no PDF is written). `badcite.tex` and
`badref.tex` share `clean.bib`. The first three are the one-section
`article` of § 2.4.
Beside them, `tests/fixtures/prfaq/logs/` holds the `.log` and `.blg` each
document produced under real TeX on this host on 2026-11-12, the captures
the stub tools replay.

**Layer 1, hermetic (`tests/test_prfaq_recipe.py`).** The test renders the
`prfaq` section through `run_seed` into a `tmp_path` Makefile that declares
`TEX_FILES`, copies a fixture document and a pre-existing tracked PDF
(sentinel bytes) beside it, writes two stub executables `pdflatex` and
`biber` into `tmp_path/bin`, and runs `make -C tmp_path prfaq` with that
directory first on `PATH`. The stubs are shell scripts the test writes from
Python strings; they are test tooling that never ships. `pdflatex` parses
`-output-directory` and `-jobname`, copies the scenario's `.log` from
`logs/` to `<dir>/<job>.log`, writes `<dir>/<job>.pdf` and, for a biblatex
scenario, `<dir>/<job>.bcf`, and exits with the scenario's status; `biber`
copies the scenario's `.blg` and exits with its status. The scenario is one
environment variable the test sets per case. One parametrized test per row
of § 3.4 asserts the `make` exit status, the exact last stderr line, the
diagnostic lines where the row names them, that the tracked PDF's bytes are
unchanged on every failing row, and that `<job>.log` survives. Row 2 clears
`pdflatex` from the stub directory; row 4 clears `biber`; row 10 is the
`nopages` scenario, in which the stub `pdflatex` exits 0 and writes
`<job>.log` but no `<job>.pdf`, so the `mv` is the step that fails, with its
own `No such file or directory` line before the row-10 `Error:` line (real
`pdflatex` does the same for a document with no pages, § 2.4). Row 11
asserts the PDF now holds the stub's bytes and that no `<job>.*` file
remains.

This is the failing-then-passing test. On the unfixed code the `prfaq`
section does not exist, so `run_seed` renders no target and every case
fails at `make: *** No rule to make target 'prfaq'`. The implementation
mission also records the stronger proof the contract asks for: the same
test run with the template body temporarily set to `standards/makefile.md`'s
variant A, where rows 6 and 9 fail because `make` exits 0 and prints the
success line, and row 11 passes. Both outputs go in the mission result; the
variant A body does not stay in the tree.

**Layer 2, real TeX (`tests/test_prfaq_recipe_tex.py`).** The same rendered
Makefile against the real `pdflatex` and `biber` for `clean`, `badcite`, and
`badref`: exit 0 with the PDF for `clean`; exit 2 with the row 6 and row 9
`Error:` lines for the others. Its purpose is to catch a TeX Live or biber
release changing the warning text the patterns match; the captured logs in
layer 1 would go stale silently without it. It requires `pdflatex` and
`biber` on `PATH` and fails, not skips, when they are absent, with one
message naming the install (`brew install --cask mactex-no-gui` or `apt
install texlive-latex-base texlive-latex-recommended texlive-bibtex-extra
biber`). `.github/workflows/test.yml` on `origin/main` installs no TeX
(steps: checkout, setup-uv, setup-python, `uv sync --frozen`, `uv run
pytest`), so it gains one `apt-get install` step for those four packages
before the pytest step. The job name does not change, so the `test` required
status check is untouched.

### 3.6 The audit check

`punt audit`'s Makefile check gains rows keyed on the `TEX_FILES`
declaration, for a repo of any language that has a Makefile:

| Condition | Verdict | Detail |
|-----------|---------|--------|
| `TEX_FILES` declared, no `# punt:begin prfaq` section | FAIL | `prfaq recipe not seeded — run punt seed makefile` |
| section present, text differs from the installed template's rendering | FAIL | `prfaq recipe stale or hand-edited — run punt seed makefile` |
| a `prfaq:` or `clean-tex:` target outside the markers | FAIL | `hand-rolled prfaq target at line N — remove it; the managed section provides it` |
| `TEX_FILES` declared and `.gitignore` lacks a line ignoring `*.build.pdf` | FAIL | `.gitignore does not ignore *.build.pdf` |
| `TEX_FILES` not declared, no `prfaq` target | no row | |
| everything matches | PASS | `prfaq recipe current` |

The comparison is byte equality between the section in the file and
`render_section("prfaq", …)` from the installed punt-kit, the same call
`seed` makes. The third row is what catches the six legacy blocks and
cryptd's block before they are rolled over. `--fix` does not seed: a
Makefile is user-owned content, and `punt seed makefile` is the one verb
that writes it, so the detail names that verb.

### 3.7 The relationship to the plugin script

The Makefile target and `compile_prfaq.sh` are two implementations of one
operation in two execution contexts. The target is the repo's gate: it runs
from `make check` or by hand, with no plugin installed, on the documents the
Makefile declares. The script is the plugin's authoring loop: it runs inside
a Claude Code session on whatever path the skill names, from
`${CLAUDE_PLUGIN_ROOT}`, in a directory that may have no Makefile. Neither
can call the other: the Makefile cannot resolve a plugin cache path, and the
plugin cannot assume a seeded Makefile.

What they share is the contract. The prfaq repo's own issue adopts § 3.4 verbatim (same job
name, same two patterns, same `Error:` lines with the script's own exit 1,
same guarded replace) and copies the four fixture documents into prfaq's
own `tests/`. Divergence after that is a drift between a standard's template
and a tool's copy, and the prfaq repo's review catches it the same way any
standards drift is caught. No code moves between the repos, and no release
of one waits on the other.

---

## 4. The fork: where the canonical recipe lives

**Recommendation: a managed section `prfaq` rendered by the existing
`punt seed makefile` from a template shipped in the punt-kit wheel.** The
command lines are those of § 3.1; the section is § 3.3.

The governing texts, read together:

- `DESIGN.md` DES-024 says punt never writes another tool's vendored zone,
  marker, or import line. The Makefile is not prfaq's zone or anyone's: it
  is a user-owned file in which `punt seed` already owns marker-delimited
  sections, and `standards/makefile.md` already carries the `prfaq` target
  as punt-kit's template. The recipe is punt-kit's build-gate content, not
  prfaq's authoring content, so rendering it from punt is punt writing its
  own output. A deposit at `.punt-labs/prfaq/` would be punt writing another
  tool's zone and is what DES-024 forbids.
- [tool-enable-disable.md § 2.3](../../standards/tool-enable-disable.md#23-the-enable--disable-convention)
  assigns to `enable` the guide "and any other files the tool ships" and
  makes re-running the upgrade path; [§ 2.10](../../standards/tool-enable-disable.md#210-punt-follows-the-convention)
  says punt's deposited guide is not a home for repo dev-process content
  such as quality gates. A make recipe is a quality gate, so it does not
  belong in punt's deposit under `enable`; it belongs where quality gates
  already go, the Makefile, under the verb that already maintains Makefile
  content.
- `DESIGN.md` DES-027 asks for one implementation of an operation, not a
  copy per surface. Seven hand copies are what this design ends. A managed
  section is one template, rendered identically everywhere, with an exact
  drift test; the copies in the seven files are output, not sources.
- `docs/WORKFLOW.md` § "Architectural units" names a change to a
  subcommand's output format as a unit that gets a design mission and
  operator ratification. `punt seed makefile` gains a section and renders
  for non-Python repos; that is the ratification this document seeks.

**Rejected alternatives.**

| Alternative | Why rejected |
|-------------|--------------|
| (b) A shared include `.punt-labs/punt/prfaq.mk` deposited by `punt enable`, with `-include .punt-labs/punt/prfaq.mk` in each Makefile | A second import-line convention, for Makefiles, beside § 2.4's for `CLAUDE.md`, with no standard behind it; `-include` makes a missing file a silent no-op so a gate compiles nothing and passes; the recipe leaves the Makefile where make users and reviewers read it; the seed mechanism already does marker-delimited idempotent merge and needs no new deposit location. § 2.10 places quality-gate content outside punt's deposit. |
| (b′) The same include deposited at `.punt-labs/prfaq/` | punt writing another tool's zone, which DES-024 forbids outright. |
| (c) The plugin's `compile_prfaq.sh` becomes the one implementation and every `prfaq` target shells out to it | The script lives under a plugin cache path that `make` cannot resolve, is absent in CI and on any host without the plugin, and its repair is prfaq's issue on prfaq's release cadence; the Makefile gate would depend on a Claude Code plugin install. |
| Keep the template in `standards/makefile.md` and fix the text; repos re-copy by hand | Hand copies are the defect: seven variants in eight months from one template, no drift detection, and no test can prove a copy matches. |
| A `punt prfaq` subcommand that compiles documents itself | Makes the `punt` wheel a LaTeX driver; the Makefile is the gate every repo already runs and every standard names. |

---

## 5. The five questions

### 5.1 Opt-in

**Recommendation:** a `TEX_FILES` assignment in the Makefile outside the
markers (§ 3.2). It is where the seven repos already declare their
documents, where make readers look, and it keeps the section free of
per-repo context so byte equality is the drift test. A Python repo with no
`prfaq.tex` declares nothing and gets no section.

| Alternative | Why rejected |
|-------------|--------------|
| Detect `prfaq.tex` at the root | lux, beadle, and prfaq compile more than that file; quarry and ethos have `prfaq.tex` and deliberately use other targets, so detection would force the section on them. |
| `[prfaq] tex_files = […]` in `.punt-labs/punt/config.toml`, rendered into the section | Moves the document list out of the Makefile, splits one declaration across two files, and makes the section vary per repo so drift needs a renderer in `audit`. The lang-rules precedent uses `config.toml` for a selection punt itself consumes; `TEX_FILES` is consumed by make. |
| Render the section into every Python repo as `standard-targets` is today | A repo with no documents gets a target that fails with row 1 of § 3.4 on every `make prfaq` and a `clean-tex` that does nothing; Go repos (beadle, cryptd) would get nothing. |

### 5.2 The failure contract

**Recommendation:** § 3.4, with the recipe's `exit 1` surfacing as `make`
exit 2 and one `Error:` line last on stderr for every row, so each row is
pinned by status plus last line. The recipe fails, it never warns, on an
unresolved citation or reference; overfull boxes stay a warning because they
are a layout defect the author sees in the PDF, not a correctness defect
hidden under a success line.

| Alternative | Why rejected |
|-------------|--------------|
| Distinct exit codes per row (3 for pdflatex, 4 for biber, …) | `make` collapses every recipe failure to 2; the code would be observable only by running the shell loop outside make, which nothing does. The last stderr line already identifies the row. |
| Treat row 6 (biber `WARN`) as a warning and fail only on `ERROR` | `WARN - I didn't find a database entry` is exactly the bold-cite-key defect; biber classifies it as a warning and the design exists because that classification is wrong for a gate. |
| Fail on overfull boxes | Blocks every document with one long URL; the plugin's own loop treats overfull as advisory, and the two contracts should agree. |
| Show tool output instead of discarding it and grepping the log | pdflatex prints hundreds of lines per pass; the log is the same content, kept on disk, and every `Error:` line names it. |

### 5.3 The test

**Recommendation:** § 3.5: stub-tool tests for every row in every
environment, plus real-TeX tests that hard-fail without TeX, with CI
installing TeX Live and biber. The test lives in punt-kit because the
template does; a sibling's rollout PR demos `make prfaq` on its own
documents through the real entry point and does not re-test the recipe.

| Alternative | Why rejected |
|-------------|--------------|
| Real-TeX tests only, `@pytest.mark.skipif(shutil.which("pdflatex") is None)` | Skips in today's CI and on any host without TeX, so the gate passes for the wrong reason; the Python testing rule forbids a skip without a tracked fix. |
| Real-TeX tests behind a `tex` marker excluded from `make test`, run only in CI | This is the Python testing rule's default (PL-TT-1: external-tool subprocess tests are tier 3, optional in CI, behind a marker), and the design departs from it; see decision 5. Local `make check` green would stop meaning CI green on the operator's hosts, and the pattern-drift check would never run where the recipe is edited. |
| Stub-tool tests only | Captured logs go stale silently when TeX changes its warning text; the real tier is what notices. |
| Assert on `tests/test_seed.py` rendering alone (the section contains the grep patterns) | Proves the template renders, not that the recipe fails on a bad document; the bead's defect is behavioral. |
| Keep variant A in the tree as a fixture so the suite shows it passing a bad document | Encodes the bug as expected behavior; the failing run is recorded in the mission result instead. |

### 5.4 Rollout and cryptd's disposition

**Recommendation.**

1. **punt-kit**, one PR: template, seed change, audit rows, tests and
   fixtures, CI step, `standards/makefile.md`, DES-039, and punt-kit's own
   Makefile (lines 39–64 replaced by the section; `prfaq clean-tex` removed
   from line 1's `.PHONY`) and `.gitignore` (`*.build.pdf`). The demo is
   `make prfaq` on punt-kit's `prfaq.tex` and, with `badcite.tex` copied to
   the root and added to `TEX_FILES` for the demo only, the row 6 failure.
2. **Release** punt-kit so `punt seed makefile` renders the section from an
   installed wheel.
3. **Six sibling PRs**, independent, in parallel, each from a worktree via a
   workspace rollout script on the `tracker-guide-rollout.sh` pattern: run
   `punt seed makefile`, delete the hand block, remove `prfaq clean-tex`
   from the hand `.PHONY` line, add `*.build.pdf` to `.gitignore`, run
   `make prfaq` and paste the output. Per repo:

   | Repo | Delete | Keep outside the markers | `.gitignore` |
   |------|--------|--------------------------|--------------|
   | vox | 103–128 | `TEX_FILES = prfaq.tex` | add `*.build.pdf` |
   | biff | 80–108 | `TEX_FILES = prfaq.tex`; the `docs/*` sweep of `clean-tex` 107–108 moves to a `clean-docs` target | add `*.build.pdf` |
   | lux | 171–200, 205–206 | `TEX_FILES = prfaq.tex docs/architecture/system.tex`; the `docs/` sweeps of 172–180 move to `clean-docs` | add `*.build.pdf`; lines 81–87 ignore `/prfaq.aux` etc. by exact name, so add the `/prfaq.build.*` forms or widen to `/prfaq*.aux` |
   | beadle | 96–129 | `TEX_FILES` line 105 | line 170 `*.pdf` already covers `*.build.pdf`; add the explicit line anyway so the audit row reads the same everywhere |
   | prfaq | 8–12, 26–55, 77–78 | `TEX_DIRS` 6 and `TEX_FILES` 21; `test: prfaq` 57 | add `*.build.pdf` |
   | cryptd | 179–246 except `TEX_FILES` 179 | `TEX_FILES = prfaq.tex` and the comment at 177–178 | line 203 `prfaq.build.pdf` becomes `*.build.pdf` |

   The prfaq repo is the strictest consumer (`test: prfaq`, wildcard
   `TEX_FILES`, two shipped templates), so its PR is the first of the six
   to merge; the rest follow in any order.
4. **quarry and ethos** are not in this rollout. Each gets a bead in its own
   funnel: declare `TEX_FILES`, run `punt seed makefile`, and retire the
   repo's own compile loop or keep it for the non-prfaq documents. quarry's
   `docs` target passes an undefined `\ref` today (§ 2.2); the bead says so.

**cryptd's disposition:** replaced by the managed section. Its block is the
template's source, so the replacement changes the recipe only by the
empty-list guard and the moved comments, and it brings cryptd under the
audit row that every other repo gets. Leaving it would make cryptd the one
repo whose recipe the audit cannot see.

| Alternative | Why rejected |
|-------------|--------------|
| Leave cryptd's block as is, since it is already hardened | One repo outside the drift check, and the next template change (a new pattern, a new extension) does not reach it. |
| Roll the siblings before releasing punt-kit, with `uv run punt` from a checkout | A sibling PR would depend on an unreleased punt-kit; the audit row in each sibling then compares against whatever punt the host has installed. |
| One workspace PR that touches all seven Makefiles | The Makefiles live in seven independent repos with their own branch protection; there is no such PR. |
| `punt seed makefile` also edits `.gitignore` | A second file written by a Makefile verb; `.gitignore` is user-owned and the rollout PR's one-line edit is reviewed in place. |

### 5.5 The audit check

**Recommendation:** § 3.6: byte equality against the installed template,
keyed on the `TEX_FILES` declaration, with a row that catches a `prfaq`
target outside the markers and a row for the `.gitignore` line. The check
runs for any language with a Makefile, since beadle and cryptd are Go and
prfaq is a docs repo with no language.

| Alternative | Why rejected |
|-------------|--------------|
| Key on the `enabled` marker as § 2.11 keys tool checks | The section is not a tool enablement; punt's marker says nothing about whether a repo has documents to compile. `TEX_FILES` is the declaration. |
| Compare a hash recorded at seed time instead of re-rendering | Passes a stale section against its own stale hash; re-rendering from the installed template is what detects an upstream change. |
| `--fix` runs `punt seed makefile` | `seed` is a separate verb with its own `--dry-run` and output; `audit --fix` today creates mechanical files `init` creates and does not rewrite user-owned Makefile content. |
| Only check Python repos, as `_check_makefile` does today | Misses beadle, cryptd, and prfaq, three of the seven. |

---

## 6. `DESIGN.md` ADR draft

The leader lifts this section verbatim.

```markdown
## DES-039: The `prfaq` Make Recipe Is a Managed Section Rendered by `punt seed makefile`

**Date:** 2026-11-12
**Status:** SETTLED
**Topic:** Where the fleet's `make prfaq` recipe lives, how it reaches each
Makefile, and what it promises on an unresolved citation or reference

### Context

Seven sibling repos carried a hand-copied `make prfaq` recipe from
`standards/makefile.md` that trusted `pdflatex` and `biber` exit codes and
the presence of a PDF. Both tools exit 0 on an unresolved citation or
reference, so the recipe printed its success line over a PDF with bold cite
keys and `??` references. Three repos deleted the tracked PDF before the
first pass; six swept intermediates with root globs. cryptd hardened its
own copy; nothing carried the fix to the other six, and no test pinned it.

### Design

1. The recipe is a third managed section, `prfaq`, in `punt seed makefile`,
   rendered from `templates/seed/makefile/prfaq.mk.j2` with no context, so
   it is byte-identical in every repo.
2. A Makefile opts in by assigning `TEX_FILES` outside the markers. The
   section is rendered for a repo of any language that declares it;
   `standard-targets` and `help` stay Python-only.
3. The recipe builds each document under the job name `<base>.build`, fails
   on a `(WARN|ERROR) - ` line in the `.blg`, fails on an anchored
   unresolved-citation-or-reference pattern in the final `.log`, replaces
   the tracked PDF only after every check passes, and removes intermediates
   by explicit job name. Every failure ends stderr with one `Error:` line
   and exits `make` with 2; an unresolved citation or reference is a
   failure, an overfull box is a warning.
4. `punt audit` re-renders the section and fails on any difference, on a
   `TEX_FILES` declaration without the section, on a `prfaq` target outside
   the markers, and on a `.gitignore` that does not ignore `*.build.pdf`.
5. Three fixture documents (clean, undefined `\cite`, undefined `\ref`) pin
   every row of the failure contract with stubbed tools in every environment
   and with real TeX in CI, which installs TeX Live and biber.
6. The prfaq plugin's compile script adopts the same contract and fixtures
   under its own issue; the repos do not depend on each other.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| A shared make include deposited by `punt enable` | A second import-line convention with no standard; `-include` silently no-ops when missing; § 2.10 keeps quality-gate content out of punt's deposit. |
| A deposit under `.punt-labs/prfaq/` | punt writing another tool's zone (DES-024). |
| The plugin's compile script as the one implementation | Lives under a plugin cache path `make` cannot resolve; absent in CI and on plugin-less hosts. |
| Fix the standard's template text and re-copy by hand | Hand copies produced seven variants; nothing detects drift. |
| Opt in by detecting `prfaq.tex` | lux, beadle, and prfaq compile more; quarry and ethos have the file and use other targets. |
| Skip the real-TeX tests when TeX is absent | The gate passes for the wrong reason; the pattern-drift check never runs where the recipe is edited. |
| Leave cryptd's hand-rolled block | One repo outside the audit; the next template change does not reach it. |
```

---

## 7. Operator decisions

Each item deviates from a settled ADR, a standard, or the bead text, or
fixes a choice the bead left open, and is phrased for a one-word ruling.

1. **The canonical recipe is a `punt seed makefile` managed section, not a
   shared make include or the plugin's compile script.** The bead names
   those two; the contract adds the section and asks that it be settled
   against DES-024, § 2.3, § 2.10, and DES-027 (§ 4). Recommend the managed
   section. Confirm or course-correct.
2. **`punt seed makefile` renders the `prfaq` section for non-Python repos.**
   Today the subcommand skips every non-Python repo; beadle and cryptd are
   Go and the prfaq repo has no language. The change is to a subcommand's
   output, which `docs/WORKFLOW.md` names as an architectural unit, and
   `standard-targets` and `help` stay Python-only. Recommend the lift for
   the `prfaq` section alone. Confirm or course-correct.
3. **`standards/makefile.md` "Template: `prfaq` target" is replaced.** The
   section's text becomes the hardened recipe as rendered, with the
   `TEX_FILES` opt-in rule and the § 3.4 contract table, and says the
   section is rendered by `punt seed makefile`, not copied. A change that
   shifts a documented rule in a standard is a cross-repo breaking change
   under `CLAUDE.md` "Ethos & Delegation", so the sibling owners are
   messaged before merge. Recommend the replacement. Confirm or
   course-correct.
4. **cryptd's hand-rolled block is replaced by the managed section.** The
   bead treats cryptd as done ("formerly cryptd"); the design brings it
   under the audit (§ 5.4). Recommend replace. Confirm or course-correct.
5. **The real-TeX tests fail, not skip, without TeX; CI installs TeX Live
   and biber; and this departs from the Python testing rule.** Two costs,
   stated outright: every punt-kit dev host needs `pdflatex` and `biber`
   installed or `make test` fails (MacTeX or a TeX Live install, several
   hundred megabytes), and every CI run pays an `apt-get install` of
   `texlive-latex-base`, `texlive-latex-recommended`,
   `texlive-bibtex-extra`, and `biber` before pytest. The standard it
   departs from: `python-testing.md` PL-TT-1 places subprocess tests that
   need an external tool at tier 3, optional in CI, behind a pytest marker,
   so the rule's own default is the rejected alternative in § 5.3 (a `tex`
   marker outside `make test`, run in CI only). The two options:
   (a) hard-fail plus the CI step, on ethos's `fuzz` precedent, so local
   `make check` green means CI green and the pattern-drift check runs
   wherever the recipe is edited, at the cost of TeX on every dev host;
   (b) a tier-3 `tex` marker per PL-TT-1, run by CI and by `make test-tex`
   on demand, so dev hosts need no TeX and local `make check` does not
   prove the real-TeX rows. Recommend (a): the recipe's whole defect is a
   tool whose output is read instead of its exit code, and the one test
   that detects a TeX release changing that output must run where the
   recipe is edited, not only after push. Confirm or course-correct.
6. **quarry and ethos are not in this rollout.** The bead lists them among
   the eight repos sharing the recipe; neither has a `prfaq` target, and
   each has its own compile loop with its own documented reason for staying
   out of `make check`. Recommend one bead in each repo's funnel to opt in
   by declaring `TEX_FILES`, with quarry's noting that its `docs` target
   passes an undefined `\ref`. Confirm or course-correct.
7. **An unresolved citation or reference is a failure; an overfull box is a
   warning; every failure is `make` exit 2 with one `Error:` line last on
   stderr.** The bead names the patterns and not the exit or output shape;
   cryptd's block chose this shape and the contract asks for it to be
   pinned. Recommend as § 3.4. Confirm or course-correct.
8. **`punt audit --fix` does not seed the section.** The lang-rules
   precedent lets `--fix` refresh a deployed set; here the file is a
   user-owned Makefile and `punt seed makefile` is its one writer, so the
   audit row names that verb instead. Recommend no `--fix` path. Confirm or
   course-correct.
9. **The plugin script is fixed under prfaq's own issue (Linear PL-715) by
   adopting this contract, with no code shared between the repos.** The
   bead offers the script as a candidate home for the canonical recipe.
   Recommend the two-implementations-one-contract relationship of § 3.7.
   Confirm or course-correct.

---

## 8. Implementation write-set

One line per file. Paths are relative to the punt-kit root unless marked
workspace or child.

### Code

| File | Purpose |
|------|---------|
| `src/punt_kit/templates/seed/makefile/prfaq.mk.j2` | The § 3.3 recipe body between the markers; no Jinja variables. |
| `src/punt_kit/makefile_sections.py` | `MakefileSectionPlan`: given `ProjectInfo` and the Makefile's unmanaged text, decides which of `standard-targets`, `help`, and `prfaq` apply (`TEX_FILES` detection per § 3.2). |
| `src/punt_kit/seed.py` | `MAKEFILE_SECTIONS` gains `("prfaq", "makefile/prfaq.mk.j2")`; `_seed_file` uses `MakefileSectionPlan` instead of the Python-only return; the "only support Python" sentence is replaced by the § 3.1 skip line, printed only when no section applies; `run_seed` returns the sections rendered as well as the files changed so the § 3.1 `--json` object can be built. |
| `src/punt_kit/__main__.py` | `seed` emits the § 3.1 `--json` object through `_emit` and honors `--quiet`; no new flag. |
| `src/punt_kit/audit_prfaq.py` | `PrfaqRecipeAudit(info).findings`: the § 3.6 rows; re-renders through `render_section` and reads the Makefile through `parse_segments`. |
| `src/punt_kit/audit.py` | Registers `PrfaqRecipeAudit` in the checks tuple; `_check_makefile`'s Python-only return no longer gates it. |
| `.github/workflows/test.yml` | One `apt-get install` step for TeX Live and biber before `uv run pytest`. |
| `Makefile` | Lines 39–64 replaced by the rendered section; `prfaq clean-tex` removed from line 1's `.PHONY`; `TEX_FILES = prfaq.tex` kept outside the markers. |
| `.gitignore` | `*.build.pdf`. |

### Tests and fixtures

| File | Purpose |
|------|---------|
| `tests/fixtures/prfaq/clean.tex`, `clean.bib` | The clean document of § 2.4: one `\cite` the `.bib` resolves, one `\ref` to its own label. |
| `tests/fixtures/prfaq/badcite.tex` | Cites `missing99`; shares `clean.bib`. |
| `tests/fixtures/prfaq/badref.tex` | References `sec:zz`; shares `clean.bib`. |
| `tests/fixtures/prfaq/pass1-error.tex` | An undefined control sequence, for rows 3, 7, and 8. |
| `tests/fixtures/prfaq/nopages.tex` | An empty document body: every pass exits 0 and no PDF is written, for row 10. |
| `tests/fixtures/prfaq/logs/*.log`, `*.blg` | The real `.log` and `.blg` each document produced on 2026-11-12, replayed by the stubs: `clean`, `badcite`, `badref`, `pass1-error`, `nopages`, and a `biber-crash.blg` with an `ERROR -` line for row 5. |
| `tests/test_prfaq_recipe.py` | Layer 1: one parametrized case per § 3.4 row with stub `pdflatex` and `biber`; row 10 via the `nopages` scenario (stub exits 0, writes the `.log`, no `.pdf`); asserts exit status, last stderr line, diagnostic lines, untouched tracked PDF, surviving `<job>.log`. |
| `tests/test_prfaq_recipe_tex.py` | Layer 2: `clean`, `badcite`, `badref` under real TeX; fails with the install message when `pdflatex` or `biber` is absent. |
| `tests/test_seed.py` | Section rendered iff `TEX_FILES` declared; non-Python repo with `TEX_FILES` gets `prfaq` only; Python repo without it gets the two existing sections only; idempotent; the prfaq repo's `foreach`/`wildcard` form is detected. |
| `tests/test_audit.py` | Each § 3.6 row, including the hand-rolled-target row against a copy of vox's lines 103–128. |
| `tests/test_cli.py` | Every row of the § 3.1 output table: the four repo-by-declaration cases and `--dry-run`, each for text and `--json`, exit 0; the retired "only support Python" sentence appears for no input; `--quiet` suppresses the text lines. |

### Docs and standards

| File | Purpose |
|------|---------|
| `standards/makefile.md` | "Template: `prfaq` target" replaced per decision 3; the target table row at line 37 says the section is seeded. |
| `DESIGN.md` | DES-039 from § 6. |
| `README.md` | The `punt seed` row at line 40 names the `prfaq` section and the `TEX_FILES` opt-in. |
| `CHANGELOG.md` | Added: the `prfaq` managed section, the audit rows, the fixtures; Changed: `punt seed makefile` renders for non-Python repos that declare `TEX_FILES`; Fixed: `make prfaq` fails on unresolved citations and references. |

### Workspace repo

| File | Purpose |
|------|---------|
| `.bin/prfaq-recipe-rollout.sh` | Per child: worktree, `punt seed makefile`, delete the hand block, edit `.PHONY` and `.gitignore`, run `make prfaq`, open the PR; the `tracker-guide-rollout.sh` pattern. |
| `.bin/README.md` | Its catalog row. |

### Child repos (one PR each, after the punt-kit release)

| File | Purpose |
|------|---------|
| vox, biff, lux, beadle, prfaq, cryptd `Makefile` | Hand block out, section in, `.PHONY` edit, `TEX_FILES` kept; biff and lux move their `docs/` sweeps to `clean-docs` (§ 5.4 table). |
| the same six `.gitignore` | `*.build.pdf`; lux's exact-name `/prfaq.*` lines gain the `.build` forms; cryptd's `prfaq.build.pdf` widens. |
| quarry, ethos | No change in this unit; one bead each (decision 6). |

### Out of this write-set

| File | Purpose |
|------|---------|
| `prfaq/plugin/scripts/compile_prfaq.sh` | The prfaq repo's own issue adopts § 3.4 and copies the four fixture documents. |
