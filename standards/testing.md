# Testing

**Introduced:** 2026-11-22

Run the fastest useful checks first, then test what can break at process,
platform, provider and distribution boundaries. [vox's testing guide](https://github.com/punt-labs/vox/blob/main/TESTING.md)
is the reference implementation, not a cross-repo inventory of test kinds.

This standard defines when tests run and what they prove. [CI](ci.md) owns
required checks and supported-platform matrices, [Makefile](makefile.md)
owns common commands, [Workflow](workflow.md) owns change-level
verification, and [Release Process](release-process.md) owns publication.
For test timing and release test evidence, this standard supersedes the
numbered tiers and version-only release checks in the legacy [Python
standard](python.md). The test kinds remain useful selectors. The
required status checks in [CI §8](ci.md#8-every-leg-is-a-required-check)
apply to PR legs; scheduled and release runs have their own gates below.

## Clauses

### TST-1: Assign each suite to the earliest suitable trigger

**Applies to:** c, go, pharo, python, rust, swift

Use the tier names below. Assign suites to the earliest trigger at which they
provide reliable evidence within budget. Measure wall-clock gate time, not
the sum of parallel jobs. Local budgets assume a provisioned checkout;
measure Pre-commit on a typical small change. A budget overrun is a defect
for the gate owner to track and fix; do not remove required evidence to
meet a budget.

Pre-commit is the automated hook, not a replacement for the quality
gates required before committing under [Workflow](workflow.md).

| Tier | Trigger and runner | Budget | Gate |
|---|---|---|---|
| Pre-commit | Before a local commit | <30 s | Run a relevant subset; failure stops commit. |
| Pre-push | Before a local push | <3 min | Run the default suite and fast local boundary checks; failure stops push. |
| PR | On the proposed change in CI | <10 min | Run required checks per [CI](ci.md#5-what-the-pipeline-must-contain); failure blocks merge. |
| Merge to main | On the actual main commit in CI | PR budget for the repeated suite | Repeat required PR checks and publish any successful coverage reference keyed by commit; handle red main per [CI](ci.md#7-broken-main-revert-first). |
| Nightly | Scheduled against main in trusted CI | ≤1 h | Broader checks; notify an owner on failure. Not a PR status check. |
| Release candidate | After building the candidate, before production promotion, in trusted release CI | Document a bounded timeout | Automated installed-candidate checks; failure blocks promotion. |
| Post-release | Immediately after publication, in release CI | <2 min | Published-version smoke; failure triggers release triage. |

### TST-2: Select tests by kind independently of the trigger

**Applies to:** c, go, pharo, python, rust, swift

Give suites explicit, discoverable selections. A **unit** test exercises
behavior in process; local component tests can also run in the default
suite with external boundaries substituted. A **subprocess** test crosses
a real local process boundary. An **e2e** test drives a shipped entry point
through a complete user path, using the installed artifact when testing
packaging. A **live** test calls a real external service. An **agent** test
drives a real agent harness and asserts an observable outcome, not just an
exit status or narrative. Kinds can overlap. Repos may add domain kinds
such as vox's **speech round trip**, and selectors like slow or quarantined
that describe execution rather than kind.

This matrix shows normal placements; a dash means no default placement.
Only applicable kinds are required. Every maintained, non-quarantined
suite runs in at least one CI tier.

| Tier | unit | subprocess | e2e | Domain-specific | live | agent |
|---|---|---|---|---|---|---|
| Pre-commit | Changed subset | If fast | — | If fast and relevant | — | — |
| Pre-push | Default suite | Fast local | — | If fast | — | — |
| PR | Full default | Required contracts | Install and exercise the PR build | Core operation | — | — |
| Merge to main | As in PR | As in PR | As in PR | As in PR | — | — |
| Nightly | As needed | Broader cases | Broader paths | Broader cases | Applicable providers | Applicable harnesses |
| Release candidate | As needed | Candidate contracts | Installed candidate | Release-critical flows | Release-critical providers | Release-critical harnesses |
| Post-release | — | — | Published smoke | One real operation | If needed | — |

### TST-3: Publish reproducible entry points

**Applies to:** c, go, pharo, python, rust, swift

Use the default test and quality-gate entry points from [Makefile](makefile.md).
Document a runnable command or workflow for each applicable tier and suite,
including selectors, prerequisites, runner, budget and blocking behavior.
Local gates and CI should invoke the same underlying suite where they make
the same claim. Required invocations fail on test failures or errors, missing
required prerequisites and unexpectedly empty selections. Docs-only projects
can use document validation as the default test; projects that do not ship
software have no installed-artifact or release tests to run.

### TST-4: Isolate credential-free runs from ambient state

**Applies to:** c, go, pharo, python, rust, swift

Pre-commit through Merge to main must not depend on external runtime
services, provider keys, user configuration or a developer's running daemon.
Provision tools and dependencies separately. Use temporary state, explicit
fixtures, synthetic credentials and test-owned local processes or simulators.
Fake external dependencies at their boundary and drive the real product code
above it. Clean up children and test state even on failure; parallel cases
must not share mutable resources unless the test is about sharing.

### TST-5: Measure coverage where the product code runs

**Applies to:** c, go, pharo, python, rust, swift

Exercise new behavior and regressions under the existing [CI](ci.md#5-what-the-pipeline-must-contain)
and [Workflow](workflow.md) test policies. Report coverage for credential-free
suites, with line and branch results where supported. State what the report
includes and excludes. Instrument the child or installed artifact if claiming
coverage from it; measuring the test driver is not measuring a separate
process. Do not set a universal percentage floor. If the project uses a
no-regression ratchet, compare head with the exact merge base under equivalent
instrumentation and selection rules; missing or invalid evidence must not pass.

### TST-6: Keep live execution explicit and trusted

**Applies to:** c, go, pharo, python, rust, swift

Run live and real-agent suites by explicit selection in trusted jobs or
authorized local runs. Never expose secrets to untrusted PR code. Use scoped
test credentials from a secret store or short-lived identity, test resources
and synthetic data. Do not persist credentials or private payloads in logs
or artifacts. Paid providers are allowed. Bound requests, duration and side
effects. A missing required credential or unavailable provider is a failed
or explicitly incomplete run, not a green check.

### TST-7: Prove the installed candidate before promotion

**Applies to:** c, go, pharo, python, rust, swift

Install the exact candidate in a clean environment. Drive its entry points
and release-critical workflows, including applicable live and agent cases.
Reuse Nightly suites where they can target that artifact. Promote the tested
artifact, not a later rebuild. A staging install check required by [CI](ci.md)
still applies. Automated success is the test gate; this standard does not
require manual installed-candidate signoff and does not remove separate
publication approval or change-level human verification.

### TST-8: Verify the published distribution

**Applies to:** c, go, pharo, python, rust, swift

Use the production distribution path to install the exact released version in
a clean environment. Assert a representative real operation and the version
or artifact identity; an existence check alone does not count. Report version,
channel and result. Failure must fail release verification and alert the
release owner to triage recovery; it cannot undo publication.

### TST-9: Make quarantines temporary and visible

**Applies to:** c, go, pharo, python, rust, swift

Follow the [CI flake policy](ci.md#6-flaky-tests-zero-tolerance). Quarantines
must be visible and separately selectable, with a tracked issue, named owner
and a fix-or-remove deadline within 14 days. Diagnose failures before reruns;
retries must not erase failed evidence. Review quarantines daily and restore
fixed tests to their normal gate.

### TST-10: Document the project's conformance

**Applies to:** c, go, pharo, python, rust, swift

Link to this standard from the project test guide or agent instructions.
Document why any tier or kind does not apply. Track progress, audit findings
and deviations in the project and Linear, not in standards or language
rules. Record the scope, reason, owner and expiry of each deviation.
