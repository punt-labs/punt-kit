# CI Standards

What continuous integration must prove before a merge, for every Punt Labs
repository. The floor is set by operator ruling (2026-08-30); the rest is
grounded in the published CI literature, cited inline. Where common practice
and the evidence disagree, section 11 says so explicitly.

Reference implementation: z-spec's `.github/workflows/test.yml` + `lint.yml`.

---

## 1. The floor: every supported OS (operator ruling)

Two absolute rules. They are Punt Labs policy, not literature-derived — the
canonical CI sources are silent on platform matrices (see §11), so these are
cited to the operator, and they bind regardless of what any external source
says.

**Rule 1: The installer must work on each supported OS.**
**Rule 2: The software must work on each supported OS.**

### Criteria

- Pass: every OS named in the README (or implied by the installer's own
  platform branches) has CI legs for BOTH the installer and the software
  test suite, via a matrix.
- Fail: an OS is claimed but has no leg; the installer is matrixed but the
  test suite is not (or vice versa).

"Supported" is defined by what the repo ships: if `install.sh` carries a
`Darwin` branch, macOS is supported and must be tested.

## 2. CI runs what ships, never a parallel copy

If a repo has an install script, CI executes **that script** — never a
second inline copy of its steps that drifts from the shipped one.

- Pass: the workflow invokes `./install.sh` (or the repo's equivalent).
- Fail: the workflow contains its own clone/configure/build/install
  sequence that also exists in the install script.

Origin: z-spec shipped a sudo-free installer whose CI built the same tool
via a separate, untested script for weeks. The shipped path had zero
coverage while CI stayed green.

## 3. Verify through the installed artifact doing real work

Resolving a binary on PATH is not evidence it functions. After installing,
CI must run at least one real operation through the installed artifact and
check its exit code — the tool's own doctor/status command plus one genuine
domain operation (z-spec: `doctor` + `check` + `test` on a real spec).

- Pass: post-install steps run real commands and fail the job on nonzero.
- Fail: verification is `command -v`, `--version`, or file-existence only.

## 4. Commit-stage speed budget: 10 minutes, hard

The full PR-blocking pipeline completes in **under 10 minutes wall clock,
targeting 5**. This is the strongest cross-source consensus number in the
CI literature: Fowler's "ten minute build" [1], Humble & Farley's "under 5
minutes, ceiling 10" [3], and DORA's Accelerate-sourced "a few minutes,
upper limit about 10" [4] independently agree.

- Independent jobs run in parallel; matrix legs run in parallel. A slow
  pipeline is fixed by parallelizing or moving work to a later stage, not
  by deleting tests.
- Order checks fastest-first within a job so failures surface early [2], [3].
- Each repo names its long pole (the slowest leg) in its CI docs so
  slowness has an owner. Exceeding the budget files a bead.

## 5. What the pipeline must contain

| Layer | Requirement |
|-------|-------------|
| Lint/static | Everything `make check` runs locally, identically in CI. CI checking less than the local gate is a fail. |
| Unit tests | The full default suite. Tests deselected by default must run somewhere in CI or be deleted. |
| Quality ratchets | OO/coupling/suppression vs. merge-base, where the repo has them; post-merge tripwire on main. |
| Installed-artifact | Build the wheel/binary, install it, drive it as a subprocess — entry points, packaging, data files. In-process tests cannot see these faults. |
| Domain gate | The product's core function exercised for real (z-spec: the spec corpus type-checks and model-checks; lux: rendering; vox: synthesis). |
| Installer | Per §1–§3, matrixed per OS, including dependency-availability legs where install behavior branches on an optional dependency (z-spec: TeX present/absent). |

The shape follows the test pyramid [2] and Google's size/scope split
(roughly 80% unit / 15% integration / 5% system) [6]: many small fast
tests, few large slow ones. The inverted shape ("ice-cream cone") is an
anti-pattern [2].

## 6. Flaky tests: zero tolerance

A pass must mean releasable; a fail must mean a real defect. DORA's
guidance is literal: "don't tolerate flaky tests" [5]. Fowler: "99.9%
green is still red" [1].

- A test observed to flake is fixed or quarantined **the same day** it is
  identified; a quarantined test gets a bead and does not silently return.
- Retrying a failed job to get a green run without diagnosing the failure
  is prohibited. Re-run only after reading the logs and classifying the
  failure (real defect / infrastructure / flake), and record the class.

## 7. Broken main: revert first

A red main is the top priority for whoever merged. The default remedy is
reverting the offending commit, not debugging in place on mainline [1], [4].
Nobody merges onto a broken main except the fix or the revert.

## 8. Every leg is a required check

Every CI leg the pipeline runs is a required status check in the branch
ruleset. An advisory leg is a leg that can silently fail forever.

- Pass: the ruleset's `required_status_checks` lists every job and matrix
  leg by exact name; adding a leg to the workflow and to the ruleset is
  one change.
- Fail: any test leg that can be red while the PR merges. (Found in the
  wild: z-spec's ruleset required only `docs` — every real gate was
  advisory — until 2026-08-30.)

External advisory reviewers (Bugbot) may stay unrequired with a bounded
grace policy, per the org workflow's merge gate.

## 9. Security hardening (machine-checkable)

GitHub's own hardening guide [7] and OpenSSF Scorecard's checks [8] mirror
each other exactly; this section is verifiable by running Scorecard.

- Third-party actions pinned to full-length commit SHAs, never mutable
  tags.
- Top-level workflow `permissions:` read-only; write permissions declared
  per-job where needed.
- Untrusted input (`github.event.*`, `github.head_ref`) never interpolated
  into `run:` bodies — pass through `env:` and quote.
- `pull_request_target` and secret-bearing `workflow_run` triggers never
  check out or execute untrusted PR code; widening such a filter requires
  an explicit head-repository check.

## 10. Release pipelines: staged promotion, gates seen failing

- Tag-triggered releases promote through stages: build → staging registry
  (TestPyPI) → install-from-staging smoke test → production. A staging
  failure blocks production [3].
- **A new gate is not trusted until it has been observed failing.** Before
  a new CI check ships, run it once against a deliberately broken input
  and record where that was done (PR description). A check that has never
  been seen red proves nothing. (Promoted from z-spec's TESTING.md, where
  this rule surfaced a model-check gate that could not fail.)
- Repos that ship installers or binaries should state a SLSA level target
  for their release pipeline [9]; SLSA is a single-framework ladder, cited
  as such, and L1–L2 (hosted build, signed provenance) is the sensible
  ceiling for this org today.

## 11. What this standard deliberately does NOT require

Stated explicitly so these do not creep back in under an unearned "best
practice" label.

- **No code-coverage percentage gate.** DORA does not validate coverage %
  as a performance predictor [4], [5]; Google frames its own internal bands
  as "a floor, not a ceiling" [6]. Chasing a number rewards trivial
  assertions. The enforced alternative is a **test policy**: new
  functionality ships with tests, per the OpenSSF Best Practices Badge
  criterion [10], and reviewers hold that line.
- **No appeal to authority for the OS matrix.** Per-OS testing appears
  nowhere in the canonical CI literature [1], [3], [4] — §1 is operator
  policy driven by what we ship, and is cited as exactly that.
- **No monolithic blocking mega-suite.** The literature's model is staged
  and parallel, fast things first [1], [2], [3]; a single serial job that runs
  everything before every merge is the anti-pattern, even though it is
  common. Parallel jobs inside the §4 budget are the required shape.

---

## References

1. Fowler, "Continuous Integration" —
   <https://martinfowler.com/articles/continuousIntegration.html>
2. Fowler (Vocke), "The Practical Test Pyramid" —
   <https://martinfowler.com/articles/practical-test-pyramid.html>
3. Humble & Farley, *Continuous Delivery*, ch. 7 (commit stage);
   <https://continuousdelivery.com/implementing/patterns/>;
   <https://martinfowler.com/bliki/DeploymentPipeline.html>
4. DORA, "Continuous integration" capability —
   <https://dora.dev/capabilities/continuous-integration/>
5. DORA, "Test automation" capability —
   <https://dora.dev/capabilities/test-automation/>
6. Winters, Manshreck & Wright, *Software Engineering at Google*,
   ch. 11–12 — <https://abseil.io/resources/swe-book>
7. GitHub, "Security hardening for GitHub Actions" —
   <https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions>
8. OpenSSF Scorecard checks —
   <https://github.com/ossf/scorecard/blob/main/docs/checks.md>
9. SLSA v1.0 levels — <https://slsa.dev/spec/v1.0/levels>
10. OpenSSF Best Practices Badge criteria —
    <https://www.bestpractices.dev/en/criteria/0>

Note on evidence strength: DORA/Accelerate findings are strong practitioner
research, not fully peer-reviewed causal proof; the 5–10 minute budget and
flakiness stance are held by three independent sources and are the safest
claims here. Farley's later per-stage confidence model and Google's coverage
bands are single-source opinions and are deliberately not normative above.
