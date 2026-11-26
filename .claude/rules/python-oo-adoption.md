---
paths:
  - "**/*.py"
---

# OO Standards Adoption

**Updated:** 2026-11-18

## PL-OA-1: Ratchet — Every Commit Improves OO Quality

**Statement**: The OO Python rules (PY-CC, PY-EN, PY-TS, PY-IC, PY-OP, PY-DP,
PY-EH, PY-OO, PY-CS) represent the target standard. Existing code does not yet
fully comply. The rule is: every commit must improve compliance, never regress.

When you touch a file:

1. Record the baseline: `make check-oo` scores touched files against the
   committed `.oo-baseline.json`; `uv run oo-ratchet oo <file>` runs the
   same scoring directly
2. Make your change
3. Re-run the scoring — no metric may worsen
4. If you can improve a metric while making your change, do so
5. After the code passes, `make update-oo` rewrites `.oo-baseline.json` and
   appends to `.oo-audit.jsonl`; stage both in the same commit as the source
   they measure

The baseline is never edited by hand and the ratchet is never suppressed. You
are not required to fix an entire file in one pass. You are required to leave
every file better than you found it.

**Criterion**:

- Pass: OO score does not regress on any touched file; at least one metric improves
- Fail: OO score worsens on a touched file; or opportunity to improve was ignored

**Tooling**:

- `make check-oo` — score touched files against the committed baseline
- `make update-oo` — rewrite the baseline after the code passes
- `uv run oo-ratchet oo <file>` — direct scoring, before and after a change
- `uv run oo-ratchet oo <directory> --threshold` — per-file breakdown

## PL-OA-2: The punt-oo-ratchet Package Is Required

**Statement**: Every Python project depends on the dev package
[`punt-oo-ratchet`](https://pypi.org/project/punt-oo-ratchet/), the canonical
implementation of the OO, coupling/cohesion, and suppression-count gates.
It requires Python 3.13+ and has no runtime dependencies. Do not copy its
implementation into the consumer's `tools/` directory. Existing baseline
and audit filenames are compatible with the extracted package.

Install the PyPI release (source: [`python-oo-ratchet`](https://github.com/punt-labs/python-oo-ratchet)):

```bash
uv add --dev "punt-oo-ratchet==0.4.0"   # exact reviewed release
```

Commit `pyproject.toml` and `uv.lock`; CI installs with `uv sync --frozen`.

### Makefile wiring

Replace `src/pkg/` with the project's source directory:

```make
SRC := src/pkg/
OO_BASE ?=
COUPLING_BASE ?=
SUPPRESSION_BASE ?=

.PHONY: check check-oo update-oo report check-coupling update-coupling check-suppressions update-suppressions
check: lint type test check-oo check-coupling check-suppressions

check-oo:
	uv run oo-ratchet oo $(SRC) --check $(OO_BASE)
update-oo:
	uv run oo-ratchet oo $(SRC) --update $(OO_BASE)
report:
	uv run oo-ratchet oo $(SRC) --threshold
check-coupling:
	uv run oo-ratchet coupling $(SRC) --check $(COUPLING_BASE)
update-coupling:
	uv run oo-ratchet coupling $(SRC) --update $(COUPLING_BASE)
check-suppressions:
	uv run oo-ratchet suppressions $(SRC) --check $(SUPPRESSION_BASE)
update-suppressions:
	uv run oo-ratchet suppressions $(SRC) --update
```

### Initial baselines

Only for a repo without baselines, seed from its current source:

```bash
uv run oo-ratchet oo src/pkg/ --rebaseline
uv run oo-ratchet coupling src/pkg/ --rebaseline
uv run oo-ratchet suppressions src/pkg/ --update
```

Commit `.oo-baseline.json`, `.oo-audit.jsonl`,
`.oo-coupling-baseline.json`, `.oo-coupling-audit.jsonl`,
`.suppression-baseline.json`, and `.suppression-audit.jsonl` together.
OO and coupling baselines map repo-relative paths to metric dictionaries;
suppression baselines contain total, category, and per-file counts. Audits
are JSON Lines. Normal changes use the update targets, not `--rebaseline`.
Never hand-edit a baseline to bypass a regression. Suppression checks rescan
source at the comparison base; the count snapshot supports updates and audit.

### CI wiring

Run on `pull_request` and `push` to `main`. Checkout must use
`fetch-depth: 0`; install Python 3.13+ and run `uv sync --frozen` first.
Use the package's merge-base comparison and post-merge tripwire steps:

```yaml
- name: Ratchets (PR, merge-base compare)
  if: github.event_name == 'pull_request'
  env:
    HEAD_REF: ${{ github.head_ref }}
    BASE_REF: ${{ github.base_ref }}
  run: |
    git fetch --no-tags origin "${BASE_REF}"
    BASE="$(git merge-base "origin/${BASE_REF}" HEAD)"
    OO_ARGS="--base-ref ${BASE} --require-base"
    case "${HEAD_REF}" in
      release/*|post-release/*) OO_ARGS="${OO_ARGS} --allow-no-improvement" ;;
    esac
    make check-oo OO_BASE="${OO_ARGS}"
    make check-coupling COUPLING_BASE="--base-ref ${BASE} --require-base"
    make check-suppressions SUPPRESSION_BASE="--base-ref ${BASE} --require-base"
- name: Ratchets (main, post-merge tripwire)
  if: github.event_name == 'push'
  run: |
    make check-oo OO_BASE="--base-ref HEAD~1 --require-base --allow-no-improvement --tripwire"
    make check-coupling COUPLING_BASE="--base-ref HEAD~1 --require-base --tripwire"
    make check-suppressions SUPPRESSION_BASE="--base-ref HEAD~1 --require-base --tripwire"
```

The OO/coupling gates bootstrap when both the merge base and `origin/main`
lack their baseline, even with `--require-base`; an unresolvable base fails.
Once main has baselines, a pre-adoption branch must rebase instead of
bootstrapping. `--tripwire` handles the one-time adoption merge on main.
Suppression comparisons already work on pre-adoption source via a live rescan.
See punt-kit's [workflow](../../.github/workflows/ratchet.yml) for a complete
consumer configuration and the package README for gate-specific flags.

**Metrics and thresholds**:

| Metric | Target | What it catches |
|--------|--------|----------------|
| method_ratio | >= 0.80 | Procedural modules (functions not in classes) |
| encapsulation_ratio | == 1.0 | Public attributes (missing _ prefix) |
| avg_params | <= 4.0 | Parameter bloat (should be an object) |
| max_complexity | <= 10 | God functions (worst single function) |
| avg_complexity | <= 5.0 | Sustained complexity (many moderately-complex functions) |
| module_size | <= 300 | God modules |
| classes_per_module | <= 3 | Unfocused modules |
| class_to_func_ratio | >= 0.5 | Procedural code disguised as a module |
| init_violations | == 0 | **init** used instead of **new** |
| public_attr_violations | == 0 | self.name without underscore |
| future_annotations | == 1 | Missing from **future** import annotations |

**Criterion**:

- Pass: the pinned package installs and all three ratchets run in `make check`
  and CI
- Fail: package missing, embedded tooling used instead, or a gate bypassed

## PL-OA-3: Apply the Refactoring Protocol for Legacy Code

**Statement**: When working on a file that violates OO standards, follow
the refactoring protocol in `python-refactoring-protocol.md`. Key principle:
one transformation per step, tests pass at each step, score improves at
each step. Never big-bang rewrite.

The refactoring protocol applies when:

- You are asked to improve OO quality of existing code
- You touch a file with low OO scores and have scope to improve it
- A code review flags OO violations in code you changed

The refactoring protocol does NOT apply when:

- You are writing new code (write it correctly from the start)
- The change is a one-line bug fix with no reasonable OO improvement nearby
