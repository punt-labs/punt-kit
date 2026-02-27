# punt-kit Vision

## The Problem

Software teams have standards. They live in wikis, READMEs, onboarding docs, and
the heads of senior engineers. They are enforced through code review, tribal
knowledge, and the occasional linter. When standards change, someone manually
updates every repo. When a new project starts, someone copies config files from
the last project and hopes they're current.

AI coding agents make this worse. An agent doesn't know your org's conventions
unless you tell it — and you have to tell it every session, in every repo.
CLAUDE.md helps, but it's a static file that someone has to maintain. There is no
feedback loop: the standards document says one thing, the repo does another, and
nobody notices until code review.

## The Insight

Standards are not documents. They are executable assertions about a codebase.
"Every README must have License, CI, PyPI, and Python badges" is a checkable
rule. "Release workflows must use `skip-existing` on TestPyPI" is a checkable
rule. "Install scripts must follow the two-phase pattern" is a checkable rule.

If standards are executable, then:

- **Auditing** is running the assertions against a repo and reporting violations.
- **Scaffolding** is generating files that satisfy the assertions from the start.
- **Rollout** is running the assertions across N repos and fixing the failures.
- **Release** is a standardized pipeline that the assertions validate.
- **Autopilot** is an agent that writes code, runs the assertions, and only
  ships when everything passes.

The entire development lifecycle becomes a loop: write standards, enforce
standards, generate from standards, release under standards, repeat.

## The Product

punt-kit is a development lifecycle engine that reads standards as data and
enforces them as code. It ships as both a CLI (`punt`) and a Claude Code plugin
(`/punt`), so the same workflows work from the terminal and from inside an AI
coding session.

### Two Separable Layers

**The engine** is general-purpose. It audits repos against standards, scaffolds
new projects from templates, manages releases, rolls out changes across repos,
and drives autonomous backlog execution. It does not hardcode any specific
convention. It reads rules from a standards directory and generates files from
templates.

**The standards pack** is a set of conventions for a specific organization.
punt-labs ships as the default pack: ruff config, badge order, install.sh
patterns, CI templates, naming rules. But the engine accepts any standards
directory — another org brings their own rules and the same engine works.

```toml
[tool.punt]
standards = "punt-labs"                              # default
# standards = "./my-standards"                       # local
# standards = "https://github.com/acme/standards"   # remote
```

This separation is the key architectural decision. It means punt-kit is not
just "our internal tooling" — it is a product that any team with codified
standards can use.

## The Commands

### Quality and Compliance

`/audit` runs all applicable checks for the detected project type. Subcommands
target individual standards:

- `/audit readme` — badges, sections, LICENSE file
- `/audit python` — ruff, mypy, pyright, pytest config
- `/audit cli` — typer + rich, naming conventions
- `/audit shell` — shellcheck, POSIX install scripts
- `/audit github` — branch protection, Copilot review, Dependabot
- `/audit ci` — workflows match templates, required status checks
- `/audit workflow` — beads initialized, branch discipline
- `/audit distribution` — trusted publishing, release pipeline
- `/audit installer` — two-phase pattern, SHA pinning
- `/audit plugins` — plugin structure, marketplace publishing
- `/audit naming` — package names, CLI commands, MCP prefixes
- `/audit node` — Node.js MCP server conventions
- `/audit pii` — email addresses, home paths, hostnames

Each audit exits 0 or 1 and prints findings with Rich formatting. The checks
are deterministic — file exists, config matches, badge format correct. For
fuzzy, LLM-powered checking, `/reconcile` already exists.

### Development Workflow

- `/preflight` — run quality gates and PII scan on staged files before commit
- `/pr` — create a PR with the standard template, assign Copilot review, watch CI
- `/status` — combined view of beads in-progress, git state, CI status,
  unreleased commits
- `/doctor` — project health check: MCP wired, plugin installed, quality gates
  pass, CI configured, beads initialized

### Release and Distribution

- `/release [patch|minor|major]` — bump version, commit, tag, push, watch the
  full pipeline (build, TestPyPI, test-install, PyPI)
- `/changelog` — generate changelog from conventional commits since last tag
- `/build` — define and verify a project's dev infrastructure (quality gates,
  CI matrix, release pipeline)

### Cross-Repo Operations

- `/rollout` — apply a standard change to N repos: detect which need the fix,
  show the delta, apply, commit, push, report. Dry-run mode previews changes
  before applying.

### Autonomous Execution

- `/autopilot` — pick work from the beads backlog, branch, implement, run
  preflight, PR, address review feedback, merge, move to the next issue.
  Guardrails: never force-push, never merge without green CI, never skip quality
  gates. Human checkpoints are configurable.

## The Development Cycle

```text
/autopilot picks from beads
  → /status: understand current state
  → code the change
  → /preflight: safe to commit?
  → /pr: open for review
  → address feedback
  → merge
  → /changelog + /release: ship it
  → /audit: still compliant?
  → next issue
```

`/rollout` sits orthogonal to this cycle — when a standard changes, it applies
the fix everywhere at once instead of waiting for each repo to catch up
organically.

## Design Principles

### Rules as Data, Not Code

Every `/audit` subcommand has a rule loader that parses the standard document
and extracts checkable assertions. The checker is generic; the rules are data.
"Badges must be License, CI, PyPI, Python" lives in `standards/readme.md`, not
in Python if-statements.

This is more work upfront than hardcoding checks. It is the right trade-off
because it means the tool scales beyond a single org.

### Deterministic Before Fuzzy

Deterministic checks (`/audit`) run first and fast. LLM-powered checks
(`/reconcile`) run second and slow. Most violations are structural — a missing
file, a wrong config value, a badge out of order. These don't need an LLM.
Reserve LLM power for the genuinely ambiguous cases.

### Guardrails Over Speed

`/autopilot` is powerful because it is conservative. It never takes destructive
actions. It never skips quality gates. It pauses and asks when uncertain. The
value is not "fast coding" — it is "methodical, standards-compliant coding that
doesn't sleep."

### Engine Owns Nothing

The engine does not decide what "good" looks like. The standards pack does. The
engine's job is to read the rules, check them, and report. This means:

- Swapping standards packs changes behavior without changing code.
- Standards packs can be versioned and released independently.
- An org can fork the punt-labs pack, change three rules, and everything works.

## Implementation Order

Ordered by daily value and dependency:

1. `/preflight` — small scope, high daily value, validates the engine pattern
2. `/audit` subcommands — break the monolithic audit into per-standard checks
3. `/release` — we do this manually every time; automate the entire pipeline
4. `/doctor` — project health checks
5. `/status` — combined view of project state
6. `/pr` — standard PR creation
7. `/changelog` — release prep
8. `/build` — configuration layer that `/audit` and `/release` reference
9. `/rollout` — cross-repo operations
10. `/autopilot` — the capstone; requires all of the above

## What This Is Not

- **Not a CI system.** punt-kit generates CI workflows and validates them. It
  does not replace GitHub Actions.
- **Not a linter.** punt-kit orchestrates linters (ruff, mypy, pyright,
  shellcheck) and validates their configuration. It does not parse code.
- **Not a package manager.** punt-kit validates distribution config and
  automates the release pipeline. It does not replace PyPI or uv.
- **Not an IDE.** punt-kit runs in the terminal as a CLI and inside Claude Code
  as slash commands. It has no GUI.

punt-kit is the glue layer — the thing that knows what "done right" looks like
for your org and enforces it at every stage of the development lifecycle.
