# GitHub Standards

Rules for repository configuration, CI/CD, branch protection, and code review across all Punt Labs projects.

---

## 1. Branch Protection

Every repository must protect `main` with a ruleset (preferred) or branch protection rule.

### Required settings

| Setting | Value | Why |
|---------|-------|-----|
| Require pull request | Yes | No direct pushes to main. Creates an audit trail. |
| Required approvals | 0 | Copilot and Cursor review as advisory (COMMENT, not APPROVE). Revisit when a project has 3+ developers. |
| Require status checks to pass | Yes | CI must pass before merge. |
| Prevent force push | Yes | Protects commit history. |
| Prevent branch deletion | Yes | main is permanent. |

### Optional settings

| Setting | Recommendation |
|---------|---------------|
| Dismiss stale reviews on new push | Yes — prevents merging after significant changes without re-review. |
| Require review from code owners | Only if CODEOWNERS file exists. |
| Require conversation resolution | Yes for repos with active review threads. |
| Restrict who can push | Not needed for small teams. Rely on PR requirement. |

### Admin bypass

Repository admins may bypass protection for emergency fixes. This should be rare and documented (e.g., a commit message noting the bypass reason).

---

## 2. CI/CD Workflows

Every repository must have at least one GitHub Actions workflow that runs on pull requests and pushes to `main`.

### By project type

| Project type | Required CI | Examples |
|-------------|-------------|---------|
| Python (application code) | Lint (ruff check, ruff format --check) + type check (mypy, pyright) + test (pytest) | Biff, Quarry, LangLearn TTS |
| Swift (iOS/macOS) | Build + unit tests + lint (SwiftLint) | Koch Trainer, Quarry Menu Bar |
| Node.js (application code) | Lint + test | Dungeon |
| Plugin (pure prompts) | Markdown lint (markdownlint-cli2) + link validation | PR/FAQ, Z Spec |
| Standards/docs | Markdown lint (markdownlint-cli2) + link validation | punt-kit, .github |
| Shell scripts (cross-cutting) | shellcheck on all `.sh` files | Any repo with shell scripts |

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

```
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

---

## 3. Code Review

### GitHub Copilot Code Review

Every repository must enable GitHub Copilot as a code reviewer. Copilot is assigned as a reviewer on PRs to provide automated feedback before human review.

#### Setup

1. Ensure GitHub Copilot is enabled for the organization (requires Copilot Business or Enterprise).
2. In repository settings > Code review > Copilot code review, enable automatic Copilot review on PRs.
3. Optionally add a `copilot-review-instructions.md` in the repo root or `.github/` to customize review focus areas.

#### Workflow

1. Developer opens a PR.
2. Copilot automatically reviews and leaves comments.
3. Developer addresses Copilot feedback.
4. Human reviewer approves (or requests changes).
5. CI passes.
6. Merge.

Copilot leaves COMMENT reviews (not APPROVE), so it does not count toward approval requirements. With required approvals set to 0, Copilot review serves as an advisory quality check alongside CI. When a project grows to 3+ developers, revisit the approval requirement — set it to 1 and require human approval.

### Review expectations

- PRs should be reviewed within 1 business day.
- Review comments should be actionable — suggest a fix, not just point out a problem.
- Nitpicks should be prefixed with "nit:" and are optional to address.

---

## 4. Required Status Checks

Branch protection must require the following status checks to pass before merge:

| Project type | Required checks |
|-------------|----------------|
| Python | `lint`, `test` |
| Swift | `build`, `test`, `swiftlint` |
| Node.js | `lint`, `test` |
| Docs/prompts | `docs` (markdown lint) |

Status check names must match the job names in the workflow files so GitHub can match them.

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
3. Add CI workflow(s) per project type (section 2)
4. Configure branch protection ruleset (section 1)
5. Enable Copilot code review (section 3)
6. Enable Dependabot and secret scanning (section 5)
7. Verify with a test PR that CI runs and protection works

### Existing repositories

Audit against the checklist in [AGENTS.md](../AGENTS.md). Create beads for each gap. Apply incrementally — branch protection and CI first, then Copilot review, then security settings.
