# Design: Punt Labs Development Workflow

**Status:** SUPERSEDED — the `dev.yaml` playbook this proposed was never
built. The problem it names was solved instead by the three-loop workflow
standard ([standards/workflow.md](../standards/workflow.md)) with ethos
missions as the delegation mechanism, and by the review sequence in
[standards/pr-review.md](../standards/pr-review.md). Several principles
survived into those documents (delegation-always, postconditions as truth,
demo before ship); the playbook encoding did not. Preserved as a historical
design record.

## Problem

Three systems compete to control the development flow:

1. **CLAUDE.md lifecycle** — 27 numbered steps the model is supposed to internalize. Works after fresh load, degrades after compaction. No hard gates — the model can skip steps. No delegation structure — one agent does everything.

2. **`/feature-dev`** (Anthropic) — 7-phase prompt-driven state machine with hard gates. Reliable but generic: no beads, no biff, no standards enforcement, no shipping pipeline. Stops too often (user gates at phases 3, 4, 5, 6).

3. **`/punt:auto autopilot`** — bead-driven loop with 13 LLM steps. Right intent but every step is `type: llm` with loose guidance. No specialist delegation, no parallel agents, no competing architectures. No demo step — features ship without being shown working. The model is still doing everything.

None of these achieve what we need: a reliable, ecosystem-aware, team-structured workflow that ships code with minimal user intervention.

## Design

### Core Idea

A **playbook** (`dev.yaml`) that encodes the Punt Labs lifecycle as a state machine. The COO agent (main session) is the executor. It never writes code — it delegates to specialist sub-agents, reviews their output, demos the result, and drives the shipping pipeline. Hard gates exist only where the user's judgment is irreplaceable.

### Principles

1. **The COO delegates, always.** Code exploration → sub-agent. Architecture → sub-agent. Implementation → specialist agent (bwk, rmh). Review → reviewer agents. The main agent coordinates, never implements. All delegated agents run on `opus` with max effort, fast output, and auto mode — set `/model opus[1m]`, `/effort max`, and `/fast` at the start of every sub-agent prompt, and pass `mode: "auto"` on the Agent tool call. Sub-agents inherit the parent's auto mode automatically (auto overrides any per-agent `permissionMode`), but passing it explicitly is belt-and-suspenders. The executor model is irrelevant; the specialists need Opus 1M context at full effort with fast output and zero permission prompts for autonomous execution.

2. **Gates are proportional to risk.** T3 (tasks/bugs): zero user gates — fully autonomous. T2 (features): one gate — spec confirmation after recon. T1 (epics): two gates — spec + architecture choice. The user sets the tier; the workflow respects it.

3. **Postconditions are truth.** Every phase has a machine-verifiable postcondition. `make check` exit code, `git log` output, PR merge status, `/z-spec:check` pass. Not "the model thinks it's done."

4. **Ecosystem integration is built in.** Beads for tracking. Biff for coordination. Quarry for prior knowledge. Z-spec for formal specification. Beadle for recap. Standards for quality. These aren't optional add-ons — they're phases in the playbook.

5. **Formal specs are the backbone.** For stateful features (T1/T2), the spec phase produces a Z specification — not prose. Z specs are type-checked (`/z-spec:check`), model-checked (`/z-spec:test`), and used to generate test cases (`/z-spec:partition`), runtime contracts (`/z-spec:contracts`), and refinement verification (`/z-spec:refine`). The spec is a living artifact that flows through the entire lifecycle: spec → tests → code → verification. This closes the loop — the specialist can't "interpret" the spec differently because Z is unambiguous.

6. **Demo before ship.** Code that passes tests but hasn't been demonstrated working is not done. The workflow includes an explicit Demo phase where the feature is built, installed, and exercised as the user would see it — before creating a PR. Python projects build and install a wheel. Go projects `make install`. CLI changes run with representative arguments. The demo is evidence, not assertion.

7. **The playbook is the source of truth, not CLAUDE.md.** CLAUDE.md describes principles and standards. The playbook encodes the workflow. After compaction, `bd prime` and the playbook schema restore the exact state.

---

### Phase Structure

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│   CLAIM → RECON → SPEC → IMPLEMENT → VERIFY → DEMO → SHIP → CLOSE     │
│                          ▲         │                                     │
│                          └─────────┘                                     │
│                          (review loop)                                   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

| Phase | Type | What | Gate | Postcondition |
|-------|------|------|------|---------------|
| **1. Claim** | script + llm | Find/create bead, set model/effort/fast, announce via biff, check for active agents | None | `bd show <id>` status = in_progress |
| **2. Recon** | llm (sub-agents) | Quarry search for prior work. 2-3 code-explorer agents in parallel. Read identified files. Check punt-kit standards. | None | `.tmp/dev-recon.md` written |
| **3. Spec** | llm | COO writes the spec. Stateful features → Z specification, type-checked and model-checked. Stateless → prose with acceptance criteria. Route to specialist. | **T1/T2: user confirms spec** | `.tmp/dev-spec.md` or `.tmp/dev-spec.tex` exists. Z specs pass `/z-spec:check`. |
| **4. Implement** | llm (specialist sub-agent) | Specialist receives spec + partition tests + file list. Tests first, then code. `make check`. Background or team mode. | None | `make check` exits 0, `git diff` shows changes |
| **5. Verify** | llm (reviewer sub-agents) | Code review (3 parallel agents) + formal verification (Z-specced features). All findings fixed. | None | All findings fixed. Refinement verified. `.tmp/dev-verify.md` written. |
| **6. Demo** | llm | Build, install, and exercise the feature as the user would see it. Paste output as evidence. | None | Demo output captured in `.tmp/dev-demo.md` |
| **7. Ship** | script + llm | commit-push-pr → request-review → wait-ci → wait-copilot → address-feedback → merge. 6 sub-steps. | None | PR merged, all checks green |
| **8. Close** | script + llm | Close bead. Email recap (with demo evidence). Delete branch. Pull main. | None | `bd show <id>` status = closed |

### Phase Details

#### Phase 1: Claim

```yaml
- id: claim
  type: llm
  context: |
    0. **Set model and effort** — before any work:
       `/model opus[1m]`, `/effort max`, `/fast`.
       The COO runs at full capability from the start.
    1. Check `bd ready` for available work. If a bead ID was provided
       as argument, use that instead.
    2. `bd update <id> --status=in_progress`
    3. **Biff coordination** — biff is the team presence and messaging
       system. Before touching files:
       a. `/who` — list active agents across all repos. Check if
          anyone else is working in this repo.
       b. If others are active in this repo: `EnterWorktree` to
          isolate your work. Never modify tracked files in a repo
          with another active agent.
       c. `/plan <bead-id>: <title>` — set your working status.
          This is visible to all agents via `/who` and `/finger`.
          Other agents use this to avoid conflicts and to know
          what you're doing.
    4. Create feature branch: `git checkout -b <prefix>/<bead-id> main`
    5. Classify tier:
       - Bead has "epic" type or touches 3+ repos → T1
       - Bead touches multiple files, has design ambiguity → T2
       - Otherwise → T3

    Write phase output to `.tmp/dev-claim.md`: bead ID, tier,
    branch name, specialist routing decision.
  postcondition:
    check: bd show ${bead_id} --json | grep -q '"status":"in_progress"'
```

#### Phase 2: Recon

```yaml
- id: recon
  type: llm
  context: |
    Launch in parallel:
    1. Quarry search: `/find` for prior work related to this bead's
       domain. Check memory-claude collection for relevant procedures.
    2. Code-explorer agent: "Find all code related to <feature area>.
       Return the 10 most important files with file:line references."
    3. Code-explorer agent: "Find the test patterns and conventions
       used in this project. Return examples of similar test files."
    4. Read applicable punt-kit standards for this project type.

    Merge results. Build a file list for the specialist.
    Do NOT read implementation files yourself — the specialist will.

    Write phase output to `.tmp/dev-recon.md`: file list, quarry
    findings, standards applicable, explorer summaries.
  postcondition:
    check: test -f .tmp/dev-recon.md
```

#### Phase 3: Spec

```yaml
- id: spec
  type: llm
  context: |
    Write a specification for the specialist agent. Two formats
    depending on whether the feature involves state:

    **Stateful features** (entities, transitions, modes, counters,
    permissions, session lifecycle, anything with invariants):

    1. Write a Z specification in `.tmp/dev-spec.tex`:
       - State schemas with invariants
       - Init schema
       - Operations with preconditions and effects
       - Use `/z-spec:code2model` conventions (ProB-compatible,
         bounded integers, flat schemas)
    2. Type-check: `/z-spec:check .tmp/dev-spec.tex`
       Must pass — iterate until clean.
    3. Model-check: `/z-spec:test .tmp/dev-spec.tex`
       Animate all operations. Fix any unreachable states or
       invariant violations.
    4. Generate partition tests: `/z-spec:partition .tmp/dev-spec.tex`
       These test cases go to the specialist alongside the spec.
    5. Optionally: `/z-spec:contracts .tmp/dev-spec.tex <language>`
       to generate runtime assertion functions the specialist can
       embed directly.

    The Z spec IS the specification. It is unambiguous, type-checked,
    and model-checked before any code is written. The specialist
    implements against it; `/z-spec:refine` verifies the implementation
    matches in Phase 5.

    **Stateless features** (CLI flags, output formatting, config
    changes, documentation, pure functions without state):

    Write prose spec in `.tmp/dev-spec.md`:
    - What to build (from bead description + recon findings)
    - Acceptance criteria (testable)
    - Key files from recon

    **Both formats include:**
    - Specialist routing (see Specialist Routing Table below)
    - Standards to follow (from punt-kit standards read in recon)
    - Key files from recon (the specialist reads these)
    - CHANGELOG requirement: if user-facing, specialist must update
      CHANGELOG.md under ## [Unreleased]

    **Gates:**
    - T1/T2: present the spec (Z or prose) to the user. For Z specs,
      show the rendered schemas and the model-check results. WAIT
      for confirmation. This is the discovery checkpoint — "I explored
      the codebase, here's what I found affects this work, here's
      the formal model of what needs to happen."
    - T3: proceed immediately. No user gate.
  postcondition:
    check: test -f .tmp/dev-spec.tex || test -f .tmp/dev-spec.md
```

#### Phase 3a: Architecture (T1 Only)

```yaml
- id: architecture  # T1 only — skip for T2/T3
  type: llm
  context: |
    Launch 2-3 code-architect agents with different mandates:
    1. Minimal changes: smallest diff, maximum reuse of existing code
    2. Clean architecture: best maintainability, elegant abstractions
    3. Pragmatic balance: speed + quality trade-off

    Each receives the spec + recon file list.

    Present all approaches with trade-offs. Recommend one.
    WAIT for user to choose. Then update `.tmp/dev-spec.md` or
    `.tmp/dev-spec.tex` with the chosen approach before delegating
    to the specialist.

    Write architecture decision to `.tmp/dev-architecture.md`.
```

#### Phase 4: Implement

```yaml
- id: implement
  type: llm
  context: |
    Two execution modes based on spec decomposability:

    **Mode A: Single specialist (default)**

    When the spec is a single coherent unit of work — one module, one
    feature, one bug fix — delegate to a single specialist sub-agent
    running in the background.

    1. Launch the specialist via Agent tool with
       `run_in_background: true`, `mode: "auto"`.
       Include in the prompt: `/model opus[1m]`, `/effort max`, `/fast`.
    2. The COO remains responsive to the user while the specialist works.
    3. The specialist receives:
       - The spec from Phase 3 (read `.tmp/dev-spec.md` or `.tmp/dev-spec.tex`)
       - The file list from Phase 2 (read `.tmp/dev-recon.md`)
       - Partition test cases if Z-specced
       - Instruction: "Write failing tests first, then implementation.
         Run `make check` after each change. Iterate until green.
         Update CHANGELOG.md if user-facing.
         Return when `make check` passes and all acceptance criteria met."
    4. When the specialist completes, verify `make check` in main session.
    5. If it fails, send findings back via SendMessage with a fix spec.
       Loop until green. Max 3 rounds. After 3 rounds, surface the
       consolidated errors to the user.

    **Mode B: Agent team (parallel decomposition)**

    Only when: (a) bead is an epic with enumerated sub-tasks, or
    (b) user explicitly requests parallelism.

    1. Decompose the spec into independent work units. Each unit must
       be able to pass `make check` independently (no cross-unit
       compilation dependencies within a single phase).
    2. Create a team via TeamCreate. Spawn one specialist teammate
       per work unit. Each teammate:
       - Gets its own spec slice + relevant file list
       - Works in isolation (teammates load CLAUDE.md independently)
       - Runs with `/model opus[1m]`, `/effort max`, `/fast`, auto mode
       - Writes tests + implementation for its unit
       - Reports completion via task status
    3. The COO monitors via TaskGet, stays responsive to the user.
    4. When all teammates complete, the COO:
       - Runs `make check` in the main session (integration gate)
       - If integration fails, diagnoses which unit broke, sends
         fix spec to that teammate via SendMessage
       - Loops until `make check` passes. Max 3 rounds.
    5. Clean up: TeamDelete after integration passes.

    **Choosing the mode:**

    - Default → Mode A
    - T3 beads → always Mode A
    - T1 epics with enumerated sub-tasks → Mode B
    - User explicitly requests parallel → Mode B
    - When in doubt → Mode A (simpler, less coordination overhead)

    In both modes, the COO never writes code. The COO writes specs,
    delegates, reviews results, and drives convergence.
  postcondition:
    check: make check
```

#### Phase 5: Verify

```yaml
- id: verify
  type: llm
  context: |
    Two verification tracks run in parallel:

    **Track A: Code review (all features)**

    Launch 3 reviewer agents in parallel on `git diff main...HEAD`:

    1. code-reviewer: bugs, logic errors, project conventions.
       Confidence threshold ≥ 80. Return only high-priority findings.
    2. silent-failure-hunter: inadequate error handling, swallowed
       exceptions, inappropriate fallbacks.
    3. Security review (djb-style): input validation, credential
       handling, trust boundaries.

    **Track B: Formal verification (Z-specced features only)**

    If `.tmp/dev-spec.tex` exists (stateful feature with Z spec):

    1. `/z-spec:refine .tmp/dev-spec.tex <language>`
       Verify the implementation refines the spec via abstraction
       function and commutativity checks. If refinement fails, the
       implementation diverges from the spec — this is a bug, not
       a review comment.
    2. `/z-spec:audit .tmp/dev-spec.tex`
       Audit test coverage against spec constraints. Identify any
       invariants or operations not exercised by the test suite.
    3. `/z-spec:oracle .tmp/dev-spec.tex <language>` (T1 only)
       Property-based testing using the Z spec as oracle. Generates
       random valid inputs and checks the implementation matches
       the spec's expected outputs.

    **Consolidate all findings (both tracks):**

    - Fix: delegate to specialist. No exceptions, no overrides.
    - Noise (confidence < 80, false positive): discard with reason.
    - Refinement failures are always fix-tier — the code doesn't
      match the spec.

    Write a fix spec and send back to the specialist (Phase 4
    re-entry). Loop until clean.
    Do NOT fix code yourself — delegate fixes to the specialist.

    Write phase output to `.tmp/dev-verify.md`: findings, fixes
    applied, final status.
  postcondition:
    check: make check
```

#### Phase 6: Demo

```yaml
- id: demo
  type: llm
  context: |
    The feature must be demonstrated working before shipping.
    Tests passing is necessary but not sufficient — the user needs
    to see the actual behavior.

    **By project type:**

    - **Python CLI/library**: build a wheel (`make build` or
      `uv build`), install it (`uv tool install --force dist/*.whl`
      or `uv pip install dist/*.whl`), then run the tool or call
      the function with representative arguments. Paste the output.
    - **Go CLI**: `make install` (or `go install ./cmd/...`), then
      run the binary with representative arguments. Paste the output.
    - **Plugin (prompts/hooks)**: plugins reload automatically.
      Invoke the changed command or skill directly. Paste the output.
    - **MCP server**: requires a Claude restart. Ask the user to
      restart and confirm. Do not skip — ask and wait.
    - **Bug fix**: reproduce the original failure first (show it
      breaks on main or prior state), then show it no longer occurs.
    - **Config/docs only**: no demo needed — skip this phase.

    **Demo output must include:**
    1. The exact command(s) run
    2. The actual output (pasted, not summarized)
    3. Confirmation that the output matches expected behavior

    Write demo evidence to `.tmp/dev-demo.md`. This is included
    in the PR body and the recap email.

    If the demo reveals a bug, write a fix spec and re-enter Phase 4.
    Do not proceed to Ship with a broken demo.
  postcondition:
    check: test -f .tmp/dev-demo.md
```

#### Phase 7: Ship

Split into 6 sub-steps per autopilot.yaml pattern:

```yaml
- id: commit-push-pr
  type: llm
  context: |
    1. Stage files by name (not `git add -A`). Include the Z spec
       (`.tmp/dev-spec.tex`) in the commit if one was written.
    2. Commit with conventional format: type(scope): description.
    3. Push with -u.
    4. Create PR via mcp__github__create_pull_request.
       Title under 70 chars. Body includes:
       - Summary bullets
       - Test plan
       - Demo evidence (from `.tmp/dev-demo.md`)
       - Z spec summary if applicable

- id: request-review
  type: llm
  context: |
    Request Copilot review via mcp__github__request_copilot_review.

- id: wait-ci
  type: llm
  context: |
    Run `gh pr checks <number> --watch` in background.
    Wait for all checks to resolve.
  on_failure: diagnose

- id: wait-copilot
  type: llm
  context: |
    CI passing does NOT mean Copilot has reviewed — those are
    independent. Poll until the review appears:

      gh pr view <number> --json reviews \
        --jq '.reviews[] | select(.author.login == "copilot-pull-request-reviewer") | .submittedAt'

    If empty, wait 60 seconds and poll again. Keep polling for at
    least 15 minutes. Do not invent theories about why the review
    is absent. If no review after 15 minutes, ask the user whether
    to continue waiting or merge without review.

- id: address-feedback
  type: llm
  context: |
    Read ALL review comments via mcp__github__pull_request_read
    (get_reviews + get_review_comments).

    Address every finding:
    - 0 issues: proceed to merge
    - Any issues: write a fix spec, delegate to specialist,
      re-push, re-run quality gates, wait for CI again.
    - Repeat review cycle. Expect 2-6 rounds.

    After each fix round, re-request Copilot review and wait again.
    Do not merge until the latest review cycle is uneventful —
    zero new comments, all checks green.

- id: merge
  type: llm
  context: |
    Merge via mcp__github__merge_pull_request (squash).
    Then update local state:
    - In a worktree: git fetch origin main && git checkout origin/main
    - On main directly: git checkout main && git pull
  postcondition:
    check: gh pr view ${pr_number} --json state --jq '.state' | grep -q MERGED
```

#### Phase 8: Close

```yaml
- id: close
  type: llm
  context: |
    1. `bd close <id>`
    2. Send recap email to jim@punt-labs.com via beadle:
       Subject: [<repo>] PR #N merged: <title>
       Body: bead ID, PR link, 1-paragraph summary, key decisions,
       demo evidence (from `.tmp/dev-demo.md`).
    3. Delete feature branch locally and remotely.
    4. Switch to main, pull latest.
    5. If in a worktree: ExitWorktree.
    6. Clean up `.tmp/dev-*.md` and `.tmp/dev-*.tex` artifacts.
```

---

### Tier Behavior

| Aspect | T1 (Epic) | T2 (Feature) | T3 (Task/Bug) |
|--------|-----------|--------------|----------------|
| Recon depth | 3 explorers + quarry + standards | 2 explorers + quarry | 1 explorer (or skip if obvious) |
| Spec gate | User confirms spec | User confirms spec | No gate — auto-proceed |
| Spec format | Z spec (stateful) or prose | Z spec (stateful) or prose | Prose (bead description) |
| Architecture | 2-3 competing approaches, user chooses | None — specialist decides | Specialist decides |
| Implement mode | Mode B if sub-tasks, else Mode A | Mode A | Mode A |
| Review depth | 3 reviewers + Z refine + Z oracle | 3 reviewers + Z refine | code-reviewer only |
| Demo | Full demo with build/install | Full demo with build/install | Demo or skip if trivial |
| Recap email | Full with design decisions + demo | Standard with demo | Brief or skip |

---

### Specialist Routing

The spec phase determines which specialist to delegate to. Routing
is **dynamic** — the COO reads the project's language and domain from
the files involved, then queries the ethos team roster (`/ethos:team`)
to find the specialist whose talents match. Agent names are NOT
hardcoded in the playbook.

**Routing logic:**

1. Identify the primary language/domain of the change from recon
   (file extensions, build system, project type).
2. Query the team roster for agents with matching talents
   (e.g., talent `engineering` + role `go-specialist`).
3. Pick the best match. If ambiguous, prefer the specialist whose
   role description most closely matches the domain.

**Examples** (current team, for illustration — not hardcoded):

| Signal | Specialist example |
|--------|--------------------|
| `.go` files, `go.mod` | Go specialist (currently bwk) |
| `.py` files, `pyproject.toml` | Python specialist (currently rmh) |
| CLI design, help text | CLI specialist (currently mdm) |
| CI/CD, deployment | Infra engineer (currently adb) |
| Security review (Phase 5) | Security engineer (currently djb) |
| ML inference, ONNX | ML specialist (currently kpz) |

When a bead spans multiple domains (e.g., Go library + Python CLI
wrapper), use Mode B with one specialist per domain.

The routing decision is written to `.tmp/dev-claim.md` in Phase 1
and refined in Phase 3 after recon reveals the actual files involved.

---

### Artifact Handoff

Each phase writes its output to `.tmp/dev-<phase>.md` (or `.tex`
for Z specs). The next phase reads from these files, not from
context. This survives compaction and enables resume-from-phase.

| Phase | Output File | Contents |
|-------|------------|----------|
| Claim | `.tmp/dev-claim.md` | Bead ID, tier, branch, specialist |
| Recon | `.tmp/dev-recon.md` | File list, quarry findings, standards |
| Spec | `.tmp/dev-spec.md` or `.tmp/dev-spec.tex` | Specification |
| Architecture | `.tmp/dev-architecture.md` | Chosen approach (T1 only) |
| Verify | `.tmp/dev-verify.md` | Findings, fixes, final status |
| Demo | `.tmp/dev-demo.md` | Commands run, output, pass/fail |

On restart or compaction recovery, the executor reads existing
`.tmp/dev-*.md` files to determine which phases have completed
and resumes from the first phase whose output file is missing.

---

### Composition with autopilot.yaml

`dev.yaml` is `mode: once` — it processes a single bead. `autopilot.yaml`
is `mode: loop` — it selects beads and iterates. They compose:

autopilot's `implement` through `close-bead` steps are replaced with
a single step that invokes the dev playbook:

```yaml
- id: run-dev
  type: llm
  context: |
    Run `/punt:auto dev bead_id=${claimed_id}`. This executes the
    full dev workflow (recon → spec → implement → verify → demo →
    ship → close) for the claimed bead. When it completes, the
    bead is closed, the PR is merged, and the loop continues.
```

This fixes autopilot's current gap: no code review, no demo, no
Z-spec integration. All of that comes from dev.yaml automatically.

`dev.yaml` does NOT replace `autopilot.yaml`. Their modes differ
(`once` vs `loop`), their parameters differ (dev needs `bead_id`,
autopilot selects automatically), and keeping them separate lets
users run dev on a single known bead without autopilot's selection.

---

### CLAUDE.md Changes

Once the playbook is reliable, the CLAUDE.md lifecycle section changes:

**Keep:**

- Principles (action bias, coherent autonomy, end-to-end ownership)
- Standards references (all punt-kit/standards/*.md links)
- Communication rules (banned patterns, calibrated confidence)
- Tool usage rules (one command per Bash call, .tmp/ for scratch)
- Invariants (no pre-existing excuse, git safety)
- Team and delegation table
- Biff, beadle, quarry, z-spec tool sections

**Remove:**

- The 27 numbered lifecycle steps (Phases 1-7 with sub-steps)
- Duplicate workflow descriptions

**Add:**

```markdown
## Development Workflow

For all code changes, use `/punt:auto dev` (or `/punt:auto dev bead_id=<id>`).
This runs the dev playbook which handles: bead claiming, codebase recon,
Z-spec or prose specification, specialist delegation, code review, demo
verification, PR lifecycle, and bead closure.

For autonomous bead processing, use `/punt:auto autopilot` which loops
through available beads using the dev workflow for each.

For releases, use `/punt:auto release`.
```

---

### Implementation Plan (v1)

v1 uses `type: llm` for all steps. No schema extensions (`type: agent`,
`type: parallel`, `when:` conditionals). The agent-launching and
tier-conditional logic is encoded in the LLM context prose. This ships
faster and lets us learn from real runs before committing to schema
changes.

1. **Write `dev.yaml`** in `punt-kit/playbooks/`. All steps are `type: llm`
   or `type: script`. Agent delegation happens via the Agent tool within
   LLM steps.

2. **Add `bead_id` parameter** (optional). When provided, skip `bd ready`
   and use the given bead. When absent, fall back to `bd ready`.

3. **Test on a real T3 bead** — pick a small bead, run `/punt:auto dev`,
   observe what breaks.

4. **Iterate** — fix executor gaps exposed by real runs. Add T2 support
   (Z-spec, user gate). Add T1 support (architecture phase).

5. **Update autopilot.yaml** — replace inner loop with dev invocation.

6. **Slim CLAUDE.md** — once dev.yaml is proven reliable on 5+ beads.

### Schema Extensions (v2, after v1 is proven)

Once we've run the workflow enough to know the right abstractions:

- `type: agent` — first-class agent delegation with lifecycle management
- `type: parallel` — fan-out with join semantics and per-agent failure handling
- `when:` conditionals — tier-gated phases evaluated against computed variables
- Resume-from-phase support — read `.tmp/dev-*.md` artifacts to determine entry point
