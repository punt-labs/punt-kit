# Agent Instructions

This project follows [Punt Labs standards](https://github.com/punt-labs/punt-kit).

## Scratch Files

Use `.tmp/` at the project root for scratch and temporary files — never `/tmp`. The `TMPDIR` environment variable is set via `.envrc` so that `tempfile` and subprocesses automatically use it. Contents are gitignored; only `.gitkeep` is tracked.

## Quality Gates

Run before every commit. Zero violations, zero errors, all tests green.

```bash
make check
```

The Makefile is the source of truth for what `check` means (`make help` lists targets).

## Beads: Dual Role

punt-kit `.beads/` tracks **both** project-specific work (punt-kit tooling, standards doc updates) and **org-wide** cross-project work (CI rollouts, security enablement, multi-repo changes). See the [parent CLAUDE.md](../CLAUDE.md#where-to-create-a-bead) for the full placement scheme.

## Plugin Lifecycle

punt-kit is both a Python package (`punt` CLI) and a Claude Code plugin
(`punt@punt-labs` on the marketplace). The plugin wraps the CLI with slash
commands (`/punt init`, `/punt audit`, `/punt reconcile`, `/punt claude2cursor`, etc.).

### Key rules

- **Never hand-edit plugin JSON config files** (`installed_plugins.json`,
  `enabledPlugins`, cache dirs). Use `claude plugin` CLI commands or the
  `/plugin` slash command instead.
- **Plugin changes require a publish cycle**: bump version in `plugin.json` →
  push → update marketplace catalog (`punt-labs/claude-plugins`) → user runs
  `/plugin update`.
- **Dev/prod isolation**: the working tree uses `name: "punt-dev"` so
  developers see both `punt:*` (marketplace) and `punt-dev:*` (local) commands
  side by side. Launch with `claude --plugin-dir .` from the repo root.
- **Can't run `claude` inside a session** — ask the user to run plugin CLI
  commands in a separate terminal when needed.
- **`/punt claude2cursor [path]`** — Write Cursor skills (and optional rules) from this plugin's commands into the workspace or the given path. Safe to run repeatedly; overwrites and cleans up obsolete artifacts.

### Developer launch

```bash
claude --plugin-dir .                       # Load local plugin alongside marketplace
```

### Marketplace publish flow

1. Bump `version` in `.claude-plugin/plugin.json`
2. Push to main
3. Update `punt-labs/claude-plugins` marketplace catalog (version + description)
4. Users pick up changes via `/plugin update`

## Claude Code CLI Reference

All `claude` subcommands below must be run from a **separate terminal** — they
cannot be invoked from within a Claude Code session.

### Plugin management (`claude plugin`)

```bash
claude plugin list [--json] [--available]        # List installed plugins
claude plugin install <name>@<marketplace> [-s user|project|local]
claude plugin uninstall <name>@<marketplace> [-s user|project|local]
claude plugin enable <name>@<marketplace> [-s user|project|local]
claude plugin disable <name>@<marketplace> [-s user|project|local]
claude plugin disable --all                      # Disable everything
claude plugin update <name>@<marketplace> [-s user|project|local|managed]
claude plugin validate <path>                    # Validate plugin structure
```

Marketplace management:

```bash
claude plugin marketplace list [--json]
claude plugin marketplace add <source>           # GitHub owner/repo, git URL, or local path
claude plugin marketplace remove <name>
claude plugin marketplace update [name]          # Update one or all marketplaces
```

Scope options: `user` (default, `~/.claude/settings.json`), `project`
(`.claude/settings.json`, version-controlled), `local`
(`.claude/settings.local.json`, gitignored).

### MCP server management (`claude mcp`)

```bash
claude mcp list                                  # List all configured MCP servers
claude mcp get <name>                            # Details for one server
claude mcp add [-t stdio|sse|http] [-s local|user|project] [-e KEY=val] <name> <cmd> [args...]
claude mcp add-json <name> '<json>' [-s scope]   # Add from JSON config
claude mcp remove <name> [-s scope]
claude mcp reset-project-choices                 # Reset .mcp.json approvals
claude mcp serve [-d]                            # Run Claude Code as an MCP server
```

### Authentication (`claude auth`)

```bash
claude auth login [--email <email>] [--sso]
claude auth logout
claude auth status [--json|--text]
```

### Other commands

```bash
claude agents [--setting-sources user,project,local]  # List configured agents
claude doctor                                    # Health check (MCP, plugins, updates)
claude update                                    # Check for and install updates
claude install [stable|latest|<version>]         # Install native build
claude setup-token                               # Set up long-lived auth token
```

### Key top-level flags

| Flag | Description |
|------|-------------|
| `--plugin-dir <path>` | Load plugin from directory (session-only, repeatable) |
| `--model <model>` | Model: `sonnet`, `opus`, or full ID |
| `-c, --continue` | Continue most recent conversation |
| `-r, --resume [id]` | Resume a session by ID or picker |
| `-p, --print` | Non-interactive mode (SDK/scripting) |
| `-w, --worktree [name]` | Start in isolated git worktree |
| `--mcp-config <path>` | Load MCP servers from JSON file |
| `--allowedTools <tools>` | Auto-allow specific tools |
| `--disallowedTools <tools>` | Remove tools from context |
| `--add-dir <dirs>` | Add working directories |
| `--system-prompt <text>` | Replace system prompt (print mode) |
| `--append-system-prompt <text>` | Append to system prompt |
| `--max-turns <n>` | Limit agentic turns (print mode) |
| `--output-format <fmt>` | Output: `text`, `json`, `stream-json` |

### Interactive slash commands (inside a session)

These are available within a running Claude Code session, not from the shell:

| Command | Description |
|---------|-------------|
| `/plugin` | Browse, install, enable, disable plugins |
| `/mcp` | View and manage MCP servers |
| `/config` | Open settings interface |
| `/model` | Switch model |
| `/permissions` | Manage permission rules |
| `/doctor` | Diagnose issues |
| `/compact` | Compact conversation context |

## Release Workflow

Releases are invoked via `/punt:auto release [version=X.Y.Z]`. This runs the
`release` playbook (`playbooks/release.yaml`) through the playbook executor,
which provides LLM-driven error diagnosis and a post-release verification step.

The playbook has two steps:

1. **`punt release`** (script) — the deterministic CLI (`src/punt_kit/release.py`)
   that executes phases 1–11. On failure the executor diagnoses the error,
   attempts a fix, and re-runs (`on_failure: diagnose`).
2. **Verify** (LLM judgment) — spot-checks that all artifacts landed correctly
   across repos (PyPI version, install-all.sh SHA, marketplace version, website
   version, org profile SHA). Prints a pass/fail checklist. Also uses
   `on_failure: diagnose` to attempt fixes if checks fail.

All main-branch changes go through PRs (zero bypass actors).

### Phase structure (`punt release`)

| Phase | Name | Description |
|-------|------|-------------|
| 1 | preflight | Verify on main, clean tree, up to date with origin/main, release scripts present (hybrid), changelog has unreleased entries, quality gates |
| 2 | bump | Create `release/vX.Y.Z` branch, bump versions (pyproject.toml / \_\_init\_\_.py / plugin.json / install.sh), stamp CHANGELOG, `uv lock` |
| 3 | build | `uv build` + `twine check` on branch |
| 4 | release-pr | Plugin swap (hybrid), push branch, create PR, wait for CI, squash-merge |
| 5 | tag | Tag main HEAD with `vX.Y.Z`, push tag |
| 6 | ci | Wait for tag-triggered `release.yml` (build → TestPyPI → test-install → PyPI) |
| 7 | github-release | Create GitHub release with changelog notes |
| 8 | pypi | Install from PyPI, run doctor, restore editable install |
| 9 | post-release | Dev plugin restore (hybrid) + README install SHA bump via PR |
| 10 | propagate | Sibling PRs: install-all.sh SHA, marketplace version+ref, org profile SHA, website version |
| 11 | verify | Check all repos (pass/fail checklist), exit non-zero on failure |

### Key assumptions

- **Sibling repos checked out**: Phase 10 (propagation) requires `../punt-kit`,
  `../claude-plugins`, and `../.github` to be checked out as siblings in the
  same parent directory, on `main`, with clean working trees. `../public-website`
  is optional (skipped if absent).
- **Push access to siblings**: The developer's SSH/HTTPS credential must allow
  `git push` on branches in all required siblings.
- **PyPI approval gate**: The `pypi` job in the release workflow requires
  manual approval in the GitHub Actions UI. Phase 6 (CI wait) blocks until
  all jobs complete, so the developer must approve the deployment during the
  release. Expect ~20 minutes for the full pipeline (build → TestPyPI →
  test-install → approve → PyPI).
- **`--resume-from <phase>`**: The CLI supports resuming from any phase. When
  resuming without an explicit version, reads from `pyproject.toml` (not
  changelog). Always pass the version explicitly when resuming from `bump` if
  Phase 2 hasn't completed.

See [DESIGN.md](DESIGN.md) DES-013, DES-014, and DES-016 for the full rationale.

## Pre-PR Checklist

- [ ] **CHANGELOG entry included in the PR diff** under `## [Unreleased]` (not retroactively on main)
- [ ] **README updated** if user-facing behavior changed (new flags, commands, defaults, config)
- [ ] **prfaq.tex updated** if the change shifts product direction or validates/invalidates a risk
- [ ] **Quality gates pass** — `make check`

## Code Review

See [Workflow standards §11 Code Review Flow](standards/workflow.md) for the full specification. Key rules inlined here:

1. **Create PR** via `mcp__github__create_pull_request`. Prefer MCP GitHub tools over `gh` CLI where possible.
2. **Request Copilot review** via `mcp__github__request_copilot_review`.
3. **Watch for CI/Copilot/Bugbot feedback without blocking your main shell** — run `gh pr checks <number> --watch` in a background task or separate session. Do not stop waiting. Copilot and Bugbot may take 1–3 minutes to post after CI completes. Do not assume silence means approval.
4. **Read all feedback** using MCP tools:
   - `mcp__github__pull_request_read` with `get_reviews` — check review verdicts
   - `mcp__github__pull_request_read` with `get_review_comments` — read inline comments
5. **Take every comment seriously.** If a reviewer flags it, you fix it. There is no such thing as "pre-existing" or "unrelated to this change" — if you can see it, you own it. If you genuinely disagree, explain why in a reply — do not silently ignore.
6. **Fix, re-push, repeat.** Each fix commit triggers a new review cycle. Expect **2–6 review cycles** before merging.
7. **Merge only when the last review cycle is uneventful** — zero new comments, all checks green. Use `mcp__github__merge_pull_request` (not `gh pr merge`, which has local side effects).

## Design Decisions

Consult [DESIGN.md](DESIGN.md) before proposing changes to settled
architecture. Log new decisions there when they involve rejected alternatives.

## Ethos & Delegation

Identity: `agent: claude` per `.punt-labs/ethos.yaml`. Sub-agent calls (`Agent(subagent_type=…)`) match ethos identity handles.

punt-kit is the *standards repo* for the entire Punt Labs org. It hosts (1) the `punt` Python CLI + plugin, (2) the canonical standards docs that all sibling repos reference, and (3) the multi-phase release playbook. Changes here ripple to ~15 sibling repos. Two distinct surfaces: the *standards* (markdown, normative) and the *tooling* (Python, executable). Within each row, the worker and evaluator must be distinct handles. Claude is the leader, never the evaluator.

| Task type | Worker | Evaluator |
|-----------|--------|-----------|
| Standards doc authoring (`standards/*.md`) | `mdm` (Pike) | `rop` (McIlroy) |
| Workflow / process / review-flow standards | `adt` (Hopper) | `mdm` |
| Python implementation (`punt` CLI, playbook executor) | `rmh` (Hettinger) | `gvr` (van Rossum) |
| Release playbook / phase logic | `adb` (Lovelace) | `rmh` |
| Plugin scaffolding / `claude2cursor` / dev/prod swap | `mdm` | `rmh` |
| CI workflows / branch protection / SHA pin propagation | `adb` | `djb` (Bernstein) |
| Cross-repo rollout / sibling PR generation | `adb` | `mdm` |
| Security review of release scripts (PyPI, signing) | `djb` | `adb` |
| `audit` / `init` / `reconcile` LLM-driven commands | `rmh` | `adt` |
| Standards doc that becomes load-bearing for sibling repos | `mdm` | `rop` + `adt` |

Standards changes are normative for ~15 repos — treat every diff as a cross-repo breaking change unless it is purely additive. Before merging anything that removes or shifts a documented rule: (1) message every affected sibling repo's owning agent via biff; (2) wait for explicit confirmation; (3) merge here only after they acknowledge the impact. This mirrors the *Cross-repo breaking changes* protocol from the org-wide CLAUDE.md (org-level scope, not in this repo). Use the `standard` pipeline for new standards or new CLI commands; use `quick` only for typos or single-section clarifications.

**Fleet reality check (required before authoring or amending any standard).** A bead records the world at filing time; the fleet moves. Before writing, survey the sibling repos via git for practice that has advanced past the standard: grep the standard's domain concepts across `../*/docs/` and implementations, sort hits by git-log recency, and list everything newer than the bead or the current standard text. The standard then generalizes the most advanced deployed reality, or explicitly supersedes it with stated rationale — one or the other, stated in the deliverable. Every standards mission contract carries this as a validation step; evaluators verify it ran (fidelity to deployed reality is a review duty). Watch first adopters especially: whoever implements a standard first (biff for the §2.4 write contract, ethos for enable/disable) runs ahead of the text — when an adoption lands, diff it against the standard and harvest corrections. Precedent: the workflow.md rewrite initially missed the operator's three-loop structure already deployed in four repos' `docs/WORKFLOW.md`; scoped-from-the-bead is scoped-from-the-past.

## Standards References

- [Python](https://github.com/punt-labs/punt-kit/blob/main/standards/python.md)
- [GitHub](https://github.com/punt-labs/punt-kit/blob/main/standards/github.md)
- [Workflow](https://github.com/punt-labs/punt-kit/blob/main/standards/workflow.md)
- [CLI](https://github.com/punt-labs/punt-kit/blob/main/standards/cli.md)
- [Shell](https://github.com/punt-labs/punt-kit/blob/main/standards/shell.md)
