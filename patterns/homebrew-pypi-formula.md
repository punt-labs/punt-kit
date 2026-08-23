# Homebrew Formula for a PyPI-Published Python CLI

## Problem

Punt Labs tools that publish to PyPI as pure-Python CLIs (biff, quarry — and
any future one) also want to ship via `punt-labs/homebrew-tap`, so users who
prefer `brew install` over `uv tool install`/`pip install` have a first-class
path. Homebrew's own packaging policy forbids a formula that just shells out
to `pip install <package>` at install time — every dependency has to be
declared and built from source inside the formula's own sandboxed virtualenv,
with no ambient network dependency resolution.

## Forces

- Homebrew formulas must be reproducible: no ambient `pip` dependency
  resolution against the live PyPI index at install time.
- `Language::Python::Virtualenv` is Homebrew's standard mixin for this case —
  it still uses `pip` internally, but only to *install* dependencies that are
  already pinned as `resource` blocks (fixed url + sha256), never to resolve
  or fetch new ones from the network.
- Discovering a formula's system-level build dependencies (a C library, a
  Rust toolchain) has no static signal — it only surfaces as a build failure
  during `brew install --build-from-source`, and `brew style`/`brew audit`
  catch only some of it.
- The tool's own PyPI dependency *tree* can itself be incompatible with this
  model, independent of any missing `depends_on` line (see Consequences).
- Once a formula exists and builds, bumping it for a new release is a
  narrower, far more mechanical problem than creating it the first time.

## Solution

Use Homebrew's `Language::Python::Virtualenv` mixin: the formula's `resource`
blocks pin the tool's full dependency tree to fixed PyPI sdist URLs + sha256
hashes, generated via `brew update-python-resources`. `virtualenv_install_with_resources`
still uses `pip` to install those pinned resources into the formula's own
venv — the discipline is that `pip` never resolves or fetches from the live
index, only installs exactly what the `resource` blocks already pinned.

This does **not** apply to tools that ship as compiled binaries (e.g. `ethos`,
a Go binary distributed via per-platform GitHub release tarballs). Those use a
different formula shape entirely — `on_macos`/`on_linux` blocks with
`url`/`sha256` per platform, no virtualenv, no resources. See
`punt-labs/homebrew-tap/Formula/ethos.rb` for that pattern; it is unrelated to
this one.

### Two problems, two different levels of automatability

**Steady-state: bumping an already-working formula for a new release.**
Mechanical and safely automatable. The tool's own dependency *set* rarely
changes between patch/minor releases — only versions and hashes move. This is
a good CI candidate.

**First-time onboarding: writing a new formula for a tool that's never had
one.** Not mechanical. Discovering which system-level `depends_on` lines a
formula needs (a C library, a Rust toolchain) only surfaces as a build
failure during `brew install --build-from-source` — there is no static way to
know in advance. `brew style`/`brew audit` catch some missing declarations
(e.g. `FormulaAudit/ResourceRequiresDependencies` for `pynacl`→`libsodium`),
but a Rust-toolchain requirement (needed to compile a dependency like
`cryptography`, `pydantic-core`, or `rpds-py` from source) only shows up as a
raw pip build failure with no formula-linter signal at all. This step wants a
human or an agent reading build output and iterating, not a script.

**Automate the first, treat the second as a one-time task per tool.**

### Steady-state recipe (the automatable part)

Given an existing `Formula/<name>.rb` with `include
Language::Python::Virtualenv`, a `url`/`sha256` pinned to a PyPI sdist, and
already-correct `depends_on` lines:

```bash
# 1. Tap must be locally registered (brew tap punt-labs/tap, one-time per machine/runner)

# 2. Fetch the new sdist URL + sha256 from PyPI, update the formula's url/sha256/version fields.
#    (PyPI JSON API: https://pypi.org/pypi/<package>/<version>/json — "urls" array,
#    packagetype == "sdist" entry has "url" and "digests.sha256".)

# 3. Regenerate every resource block from the new release's dependency tree.
#    --ignore-main-package-cooldown is required if the release is < 24h old —
#    brew's default cooldown filter (--uploaded-prior-to=P1D) otherwise silently
#    excludes the just-published version's own metadata.
brew update-python-resources <name> --ignore-main-package-cooldown

# 4. Style-fix (mostly dependency-ordering; safe to auto-apply).
brew style --fix <name>

# 5. Non-interactive correctness gate — this is the step that actually proves
#    the bump didn't break anything. Must build from source, not from a
#    cached bottle, since resource pins changed.
brew install --build-from-source <name>
brew test <name>

# 6. Commit, push, open PR against punt-labs/homebrew-tap.
```

Step 5 is the load-bearing verification step — treat a failure here as a hard
stop, not a warning. If it fails after a dependency-tree change (a transitive
dependency swapped its own build backend, e.g. started requiring Rust when it
didn't before), that's a signal the formula needs a `depends_on` addition —
which pushes this specific release back into the "needs a human/agent" bucket
even for a tool that was previously steady-state. Don't auto-merge past a
failed step 5.

### First-time onboarding recipe (what actually happened for biff)

1. Scaffold `Formula/<name>.rb`: `desc`, `homepage`, `url`/`sha256` from
   PyPI's sdist entry, `license`, `include Language::Python::Virtualenv`, a
   `def install; virtualenv_install_with_resources; end`, and a `test do`
   block that runs the tool's own version/help command.
2. Run `brew update-python-resources <name> --ignore-main-package-cooldown`
   to generate every resource block.
3. `brew style <name>` — fix every `FormulaAudit/ResourceRequiresDependencies`
   finding by adding the named `depends_on` (Homebrew's linter names the
   missing system library directly, e.g. "Add depends_on lines above for
   libsodium").
4. `brew install --build-from-source <name>`. If it fails on a Rust-based
   wheel build (`maturin`, `setuptools-rust`), the missing declaration is
   `depends_on "rust" => :build` — Homebrew's resource-install model always
   builds from sdist, never installs prebuilt wheels, so any dependency with
   a compiled extension needs its build toolchain declared explicitly. This
   failure mode has no formula-linter signal; you only find it by attempting
   the build.
5. Fix `brew style`'s `FormulaAudit/DependencyOrder` complaints — build-time
   deps (`=> :build`) sort before runtime deps, and `brew style --fix` will
   reorder them for you once you've added the right set.
6. Re-run step 4 until it succeeds. `brew test <name>` to confirm the
   formula's own smoke test passes against the installed binary.
7. Commit, PR, done — from here the tool is in the steady-state bucket for
   every future release.

### Known failure mode: wheel-only dependencies break the recipe entirely (quarry, 2026-08-23)

The second real-world test of this recipe, on `quarry`, did not reach the
build/test gate at all — `brew update-python-resources` refused outright:

```text
Error: lancedb exists on PyPI but lacks a suitable source distribution
Error: Unable to resolve some dependencies. Please update the resources for "quarry" manually.
```

This is a different and more fundamental problem than anything the recipe
above anticipates. `Language::Python::Virtualenv` resource blocks build every
dependency from its **sdist** inside the formula's venv — the whole model
assumes a source distribution exists to build from. Some PyPI packages,
typically Rust-core packages published via `maturin`, ship **wheel-only**
with no sdist at all: `pip install` works fine against a prebuilt wheel, but
there is nothing for Homebrew's resource-block model to build from source.
`brew update-python-resources` hard-refuses the moment it hits one; there is
no `depends_on` line that fixes this, because the gap isn't a missing system
library — it's the dependency having no buildable form.

Verified directly against PyPI JSON metadata for quarry's tree:

- `lancedb` (0.37.1): wheel-only, zero sdist entries.
- `pylance` (10.0.0, lancedb's own sub-dependency): same shape.
- `onnxruntime` (1.29.0): also wheel-only.

A second, independent gap compounds this: even where a wheel exists, PyPI's
wheel matrix for these packages has **no macOS x86_64 (Intel) build** at the
versions quarry pins — only macOS arm64, manylinux aarch64/x86_64, and
Windows. Hand-authoring a `resource` block that points directly at a wheel
URL (technically possible — pip can install a `.whl` resource) still cannot
close this gap, because the artifact simply doesn't exist for that platform.
This is upstream's platform matrix, not a formula-authoring problem.

**Do not treat this as a step-5-build-failure needing one more `depends_on`.**
It is a pattern-level incompatibility: `Language::Python::Virtualenv` fits
pure-Python dependency trees (`biff`'s were all sdist-buildable, including
the three Rust-based ones that only needed `depends_on "rust" => :build`).
It does not fit a tree containing wheel-only, platform-incomplete ML/Rust
packages. Recognizing which case you're in only happens by running
`brew update-python-resources` and reading whether the failure names a
missing library (fixable, stays in the normal recipe) or refuses to resolve
a package's source distribution at all (stop — this is the case below).

When this happens, the options are a genuine fork requiring an operator
decision, not something an agent should pick unilaterally:

1. Restrict the formula to the platforms that have full wheel coverage
   (e.g. `depends_on arch: :arm64` on macOS, refuse Intel) — ships a
   formula that works, but not everywhere.
2. Pin to older releases of the wheel-only dependency that still shipped an
   sdist or broader wheel coverage — likely stale/unsupported upstream.
3. Hand-roll wheel installation outside `virtualenv_install_with_resources`
   — non-standard for this tap, higher maintenance burden per release.
4. Don't ship a Homebrew formula for this tool — ML/Rust-heavy dependency
   trees may not fit this distribution channel the way pure-Python CLIs do.

`quarry.rb` remains an unfinished scaffold pending that decision — see
`quarry-dbsn` for the specific finding and escalation.

## Consequences

- Every steady-state release bump is a fully non-interactive, CI-verifiable
  operation — `brew update-python-resources`, `brew install
  --build-from-source`, and `brew test` either all pass or the bump doesn't
  ship.
- First-time onboarding cannot be fully scripted: system `depends_on`
  discovery requires reading a real build failure. Budget for a human or
  agent iteration loop, not a one-shot script, when adding a new tool.
- Not every PyPI-published Python CLI is a candidate. A dependency tree with
  wheel-only, platform-incomplete packages (common in ML/Rust-heavy stacks)
  defeats the sdist-only resource model entirely and needs an explicit
  operator decision, not an automated workaround.
- Where this plugs into `punt release`: Phase 10 (Propagate) already opens
  PRs against sibling repos (`.github`, `claude-plugins`, `public-website`)
  in the same shape this needs — local edit → push branch → open PR → wait
  for CI → squash-merge. Adding `punt-labs/homebrew-tap` as a propagation
  target, gated on "does this repo have a `Formula/<name>.rb` already," fits
  that existing model directly — but only run the *steady-state* recipe
  automatically. If the build/test gate fails, stop and surface it rather
  than trying to auto-fix `depends_on` lines or auto-select one of the
  wheel-only escape hatches above.

## Related Patterns

- [Two-Phase Install](two-phase-install.md) — the install-time counterpart:
  once a Homebrew formula exists, it becomes a third install path alongside
  `uv tool install` and the bootstrap script, all converging on the same
  `<tool> doctor` verification.

## Known Uses

- **biff** (`punt-biff` 1.16.0) — first tool proven end-to-end:
  `punt-labs/homebrew-tap` PR #33. 61 resource stanzas, three requiring a
  from-source Rust compile (`pydantic-core`, `cryptography`, `rpds-py`), full
  build succeeded in ~17 minutes.
- **quarry** — second real-world test; hit the wheel-only failure mode
  above. `Formula/quarry.rb` remains an unfinished scaffold (`sha256
  "PLACEHOLDER"`, no resource blocks) pending an operator decision — see
  `quarry-dbsn`.
