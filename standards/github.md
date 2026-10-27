# GitHub Standards

**Updated:** 2026-10-26

Rules for repository configuration, CI/CD, branch protection, and code review across all Punt Labs projects.

---

## 1. Branch Protection

Every repository must protect `main` with a ruleset (preferred) or branch protection rule.

### Required settings

| Setting | Value | Why |
|---------|-------|-----|
| Require pull request | Yes | No direct pushes to main. Creates an audit trail. |
| Required approvals | 0 | Qodo, Bugbot, and Copilot review as advisory (COMMENT, not APPROVE). Revisit when a project has 3+ developers. |
| Require conversation resolution | Yes | Unresolved review comments block merge. |
| Require status checks to pass | Yes | CI must pass before merge. |
| Prevent force push | Yes | Protects commit history. |
| Prevent branch deletion | Yes | main is permanent. |
| Bypass actors | None | No admin override. Zero bypass actors on every ruleset. |

### Optional settings

| Setting | Recommendation |
|---------|---------------|
| Dismiss stale reviews on new push | Yes — prevents merging after significant changes without re-review. |
| Require review from code owners | Only if CODEOWNERS file exists. |
| Restrict who can push | Not needed for small teams. Rely on PR requirement. |

### No bypass

Rulesets must have **zero bypass actors**. No admin override, no emergency exception. Every change to main goes through a pull request — no exceptions. If a fix is urgent, the PR can be minimal, but it still goes through the gate.

---

## 2. CI/CD Workflows

Every repository must have at least one GitHub Actions workflow that runs on pull requests and pushes to `main`.

### By project type

| Project type | Required CI | Examples |
|-------------|-------------|---------|
| Python (application code) | Lint (ruff check, ruff format --check) + type check (mypy, pyright) + test (pytest) | punt-kit, Biff, Quarry, LangLearn TTS |
| Swift (iOS/macOS) | Build + unit tests + lint (SwiftLint) | Koch Trainer, Quarry Menu Bar |
| Plugin (pure prompts) | Markdown lint (markdownlint-cli2) | Dungeon, Feature Forge, PR/FAQ, Z Spec |
| Standards/docs | Markdown lint (markdownlint-cli2) | punt-kit, .github |
| Shell scripts (cross-cutting) | shellcheck on all `.sh` files | Any repo with shell scripts |

**All repos** also run a `docs.yml` workflow with markdownlint-cli2. This is in addition to any project-type-specific CI.

### Workflow naming convention

| Workflow | Filename | Triggers |
|----------|----------|----------|
| Lint + type check | `lint.yml` | push to main, pull_request to main |
| Tests | `test.yml` | push to main, pull_request to main |
| Build (compiled languages) | `build.yml` | push to main, pull_request to main |
| Markdown validation | `docs.yml` | push to main, pull_request to main |
| Release / publish | `release.yml` | tag push (`v*`) or manual dispatch |
| Manual / special | descriptive name | workflow_dispatch |

### Release workflow (`release.yml`)

Python projects must have a `release.yml` that publishes to PyPI via TestPyPI gate:

```text
Trigger: tag push (v*) or workflow_dispatch

Pipeline: build → testpypi → test-install → pypi
```

| Job | Environment | Permissions | What it does |
|-----|-------------|-------------|-------------|
| `build` | — | — | `uv build` + `uvx twine check dist/*`, uploads artifact |
| `testpypi` | `testpypi` | `id-token: write` | Publishes to TestPyPI via trusted publishing |
| `test-install` | — | — | Installs from TestPyPI, verifies CLI entry point |
| `pypi` | `release` | `id-token: write` | Publishes to production PyPI via trusted publishing |

**Trusted publishing (OIDC):** Uses `pypa/gh-action-pypi-publish` with `id-token: write` permission. No `PYPI_TOKEN` secret needed. Requires one-time setup of trusted publishers on pypi.org and test.pypi.org (see [Python standards](python.md#trusted-publishing-setup-one-time-per-package)).

**Required GitHub environments:** `testpypi` and `release` (no protection rules for solo dev; add approval gates when team grows).

### Workflow standards

- Pin action versions to full SHA, not tags: `actions/checkout@<sha>` not `actions/checkout@v4`. Tags are mutable.
- Use `uv` for Python dependency installation (not `pip`).
- Cache dependencies where possible (`actions/cache` or tool-specific caching).
- Set timeout for jobs (default: 10 minutes for lint, 20 minutes for tests).
- Use matrix strategy for multi-version testing only when the project supports multiple Python/Node versions.

### Markdownlint configuration

Every repo has two config files at the root:

**`.markdownlint.jsonc`** — rule configuration (org standard):

```json
{
  "MD013": false,
  "MD060": false,
  "MD024": { "siblings_only": true },
  "MD033": { "allowed_elements": ["img", "p"] }
}
```

**`.markdownlint-cli2.jsonc`** — CLI configuration with ignore patterns:

```json
{
  "ignores": [".beads/", ".claude/", ".venv/", ".tmp/"]
}
```

Use `.tmp/` so scratch and CI temp output (e.g. pytest `.tmp/`) are not linted. Add project-specific paths (e.g. `research/`, `session.md`) as needed.

Add project-specific overrides in `.markdownlint-cli2.jsonc` when certain directories need relaxed rules (e.g., test fixtures, generated files). Use the `overrides` array:

```json
{
  "ignores": [".beads/", ".claude/", ".venv/"],
  "overrides": [
    {
      "files": ["tests/fixtures/*.md"],
      "config": { "MD025": false }
    }
  ]
}
```

---

## 3. Code Review

### PR review bots: Qodo and Bugbot

Qodo and Bugbot are the default remote reviewers. Their sequencing, round cap, and merge conditions are owned by the [PR and Review standard](pr-review.md); this section covers only the repository configuration they need.

- **Qodo** reads `.pr_agent.toml` from the default branch. Start from the punt-kit template (`src/punt_kit/templates/pr_agent.toml`), fill its `{{PLACEHOLDER}}` values, and merge it to `main` before the first PR that should use it. In the Qodo portal, set "Review every push" to Disable (the portal default is Enable); the config reviews once, on open.
- **Bugbot** is configured in the Cursor dashboard to review each PR once, on open.

Both leave COMMENT reviews (not APPROVE), so they do not count toward approval requirements. With required approvals set to 0, they serve as an advisory quality check alongside CI; Qodo's High findings post as threads that block merge through the conversation-resolution rule in section 1. When a project grows to 3+ developers, revisit the approval requirement — set it to 1 and require human approval.

### GitHub Copilot Code Review

Copilot is on request only. It is not a default reviewer, and repository rulesets carry no `copilot_code_review` rule (as of 2026-10-26). A repo may request one Copilot review per PR, at open, per its `docs/WORKFLOW.md`; its findings are handled like any other.

Rulesets keep `required_review_thread_resolution` and the required status checks (section 4). Do not add `copilot_code_review` to a ruleset: it makes Copilot review automatically, outside the bounded review loop in [PR and Review](pr-review.md).

### Review expectations

- PRs should be reviewed within 1 business day.
- Review comments should be actionable — suggest a fix, not just point out a problem.
- Nitpicks should be prefixed with "nit:" and are optional to address.

---

## 4. Required Status Checks

Branch protection must require the following status checks to pass before merge:

| Project type | Required checks |
|-------------|----------------|
| Python | `lint`, `test`, `docs` |
| Swift | `Build and Unit Tests`, `Lint`, `docs` |
| Plugin / docs | `docs` |

Status check names must match the job names in the workflow files so GitHub can match them. Every repo requires the `docs` check (markdownlint).

---

## 5. Repository Settings

### General

| Setting | Value |
|---------|-------|
| Default branch | `main` |
| Allow merge commits | Yes |
| Allow squash merging | Yes (default) |
| Allow rebase merging | Yes |
| Auto-delete head branches | Yes — clean up after merge |
| Allow auto-merge | Yes — enables merge when CI passes |

### Security

| Setting | Value |
|---------|-------|
| Dependabot alerts | Enabled |
| Dependabot security updates | Enabled |
| Secret scanning | Enabled |
| Push protection | Enabled — blocks commits containing secrets |

---

## 6. Applying These Standards

### New repositories

Use this checklist when creating a new repo:

1. Create with `main` as default branch
2. Add `.gitignore` appropriate for the language
3. Add `.markdownlint.jsonc` and `.markdownlint-cli2.jsonc` (org standard, section 2)
4. Add CI workflow(s) per project type, including `docs.yml` (section 2)
5. Configure branch protection ruleset with required status checks (sections 1, 4)
6. Add `.pr_agent.toml` from the template and configure Qodo and Bugbot (section 3); do not enable Copilot code review
7. Enable Dependabot and secret scanning (section 5)
8. Enable auto-merge and auto-delete head branches (section 5)
9. Verify with a test PR that CI runs and protection works

### Existing repositories

Audit against the checklist in [AGENTS.md](../AGENTS.md). Create beads for each gap. Apply incrementally — branch protection and CI first, then the review bots, then security settings.
