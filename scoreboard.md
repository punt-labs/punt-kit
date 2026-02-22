# Punt Labs Standards Scoreboard

> **Regenerate**: Run this document as a prompt against the punt-labs workspace.
> It will re-survey all projects and produce an updated scoreboard.

## Instructions for Regeneration

Survey every project directory under the punt-labs workspace. For each project,
check the criteria below by reading actual files (not from memory). Report only
facts. Use the main branch for each repo. Produce the tables in the Results
section with updated dates and data.

### Projects to Survey

**Python CLI+MCP**: punt-kit, biff, quarry, langlearn-tts, langlearn,
langlearn-anki, langlearn-imagegen, langlearn-types

**Swift**: quarry-menubar, koch-trainer-swift

**Claude Code Plugins**: prfaq, dungeon, z-spec

**Org Infrastructure**: .github, claude-plugins

### Criteria

For each project, check:

| # | Criterion | How to Check | Applies To |
|---|-----------|-------------|------------|
| 1 | CLAUDE.md | File exists in project root | All |
| 2 | .biff | File exists in project root | All |
| 3 | .markdownlint.jsonc | File exists in project root | All |
| 4 | .markdownlint-cli2.jsonc | File exists in project root | All |
| 5 | CHANGELOG.md | File exists in project root | All except org infra |
| 6 | docs.yml | .github/workflows/docs.yml exists | All |
| 7 | lint CI | .github/workflows/lint.yml or ci.yml with lint job | Python, Swift |
| 8 | test CI | .github/workflows/test.yml or ci.yml with test job | Python, Swift |
| 9 | release.yml | .github/workflows/release.yml exists | Python, Swift |
| 10 | install.sh | File exists, shebang is `#!/bin/sh` | Python CLI+MCP, Plugins |
| 11 | SHA-pinned curl | README curl URL uses commit SHA, not branch name | Projects with install.sh |
| 12 | pyright config | `[tool.pyright]` in pyproject.toml | Python |
| 13 | mypy config | `[tool.mypy]` in pyproject.toml | Python |
| 14 | ruff config | `[tool.ruff]` in pyproject.toml | Python |
| 15 | Plugin on marketplace | Listed in claude-plugins marketplace.json | Plugins |

### Legend

| Symbol | Meaning |
|--------|---------|
| Y | Compliant |
| ~ | Partial (exists but non-standard) |
| - | Missing (should exist) |
| . | Not applicable to this project type |

---

## Results

**Last updated**: 2026-02-21

### Project Files

| Project | CLAUDE.md | .biff | mdlint | mdlint-cli2 | CHANGELOG |
|---------|:---------:|:-----:|:------:|:-----------:|:---------:|
| punt-kit | Y | Y | Y | Y | Y |
| biff | Y | Y | Y | Y | Y |
| quarry | Y | Y | Y | Y | Y |
| langlearn-tts | Y | Y | Y | Y | Y |
| langlearn | Y | - | Y | Y | Y |
| langlearn-anki | Y | - | Y | Y | Y |
| langlearn-imagegen | Y | - | Y | Y | Y |
| langlearn-types | Y | - | Y | Y | Y |
| quarry-menubar | Y | Y | Y | Y | Y |
| koch-trainer-swift | Y | Y | Y | Y | Y |
| prfaq | Y | Y | Y | Y | Y |
| dungeon | Y | Y | Y | Y | Y |
| z-spec | Y | Y | Y | Y | Y |
| .github | Y | Y | Y | Y | . |
| claude-plugins | Y | Y | Y | Y | . |

### CI Workflows

| Project | docs | lint | test | release |
|---------|:----:|:----:|:----:|:-------:|
| punt-kit | Y | Y | Y | Y |
| biff | Y | Y | Y | Y |
| quarry | Y | Y | Y | Y |
| langlearn-tts | Y | ~ | ~ | Y |
| langlearn | Y | Y | Y | - |
| langlearn-anki | Y | Y | Y | - |
| langlearn-imagegen | Y | Y | Y | - |
| langlearn-types | Y | Y | Y | - |
| quarry-menubar | Y | ~ | ~ | - |
| koch-trainer-swift | Y | ~ | ~ | - |
| prfaq | Y | . | . | . |
| dungeon | Y | . | . | . |
| z-spec | Y | . | . | . |
| .github | Y | . | . | . |
| claude-plugins | Y | . | . | . |

`~` = combined ci.yml with separate lint/test jobs (functional but not split per standard)

### Quality Gates (Python only)

| Project | ruff | mypy | pyright | pytest |
|---------|:----:|:----:|:-------:|:------:|
| punt-kit | Y | Y | Y | Y |
| biff | Y | Y | Y | Y |
| quarry | Y | Y | Y | Y |
| langlearn-tts | Y | Y | Y | Y |
| langlearn | Y | Y | Y | Y |
| langlearn-anki | Y | Y | Y | Y |
| langlearn-imagegen | Y | Y | Y | Y |
| langlearn-types | Y | Y | Y | Y |

### Distribution

| Project | install.sh | POSIX sh | SHA-pinned | On marketplace |
|---------|:----------:|:--------:|:----------:|:--------------:|
| punt-kit | . | . | . | Y (punt) |
| biff | Y | Y | Y | Y (biff) |
| quarry | Y | Y | Y | . |
| langlearn-tts | Y | Y | Y | . |
| langlearn | - | - | - | . |
| langlearn-anki | - | - | - | . |
| langlearn-imagegen | - | - | - | . |
| langlearn-types | . | . | . | . |
| quarry-menubar | . | . | . | . |
| koch-trainer-swift | . | . | . | . |
| prfaq | Y | Y | Y | Y (prfaq) |
| dungeon | Y | Y | Y | Y (dungeon) |
| z-spec | . | . | . | - |
| .github | . | . | . | . |
| claude-plugins | Y | Y | Y | . |

### Open Issues

| ID | Repo | Priority | Title |
|----|------|:--------:|-------|
| punt-kit-8wd | punt-kit | P2 | Add release.yml to langlearn projects |
| punt-kit-18i | punt-kit | P2 | Add install.sh to langlearn projects |
| punt-kit-zud | punt-kit | P2 | Investigate langlearn CI path dependency resolution |
| punt-kit-t2a | punt-kit | P3 | Add .biff to langlearn projects |
| punt-kit-4ob | punt-kit | P3 | Pin action SHAs consistently across langlearn CI |
| punt-kit-3vr | punt-kit | P3 | Automated TestPyPI + PyPI release workflow (template) |
| langlearn-a8t | langlearn | P3 | Evaluate langlearn-types CLI/MCP surface |
| langlearn-anki-5eo | langlearn-anki | P3 | Pin setup-uv action to v7.3.0 |

### Blockers

| Blocker | Impact | Workaround |
|---------|--------|------------|
| PyPI org prefix approval pending | All `punt-*` packages not on PyPI | install.sh uses git URLs |
| z-spec not on marketplace | Has plugin.json but not in catalog | Publish when ready |

---

## Scoring Summary

| Category | Compliant | Partial | Missing | N/A |
|----------|:---------:|:-------:|:-------:|:---:|
| Project files (5 items x 15 repos) | 67 | 0 | 4 | 4 |
| CI workflows (4 items x 15 repos) | 27 | 6 | 8 | 19 |
| Quality gates (4 items x 8 repos) | 32 | 0 | 0 | 0 |
| Distribution (4 items x 15 repos) | 18 | 0 | 6 | 36 |

**Overall**: 144 compliant, 6 partial, 18 missing, 59 N/A out of 227 checks.
All missing items are tracked in open beads.
