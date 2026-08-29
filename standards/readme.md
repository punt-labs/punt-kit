# README Standard

**Updated:** 2026-08-14

How every Punt Labs project README should be structured and written.

Reference implementations:

- [biff](https://github.com/punt-labs/biff/blob/main/README.md) — structure (CLI + plugin hybrid)
- [koch-trainer-swift](https://github.com/punt-labs/koch-trainer-swift/blob/main/README.md) — tone and competitor positioning
- [z-spec](https://github.com/punt-labs/z-spec/blob/main/README.md) — academic grounding and factual framing

## Audience

**The README is written for users.** A user is the person who installs the
tool and uses it — not the person who develops or extends it. Every section
answers a user's question: what is this, how do I install it, what can it do,
how do I drive it.

Developer content does not live in the README at all — not even a short
Development section. Quality-gate commands (lint, type-check, test) live in
`CONTRIBUTING.md` at the repo root; everything else a contributor or
integrator needs — library API guides, client code walkthroughs, internal
architecture detail, probe scripts, protocol internals — lives under `docs/`
and is linked from the Documentation section. A README with an 80-line client
code walkthrough, or a Development section listing lint/type/test commands, is
mis-addressed: move it out.

Two corollaries:

- **Document only what works.** A broken or unimplemented feature is never
  listed as something the user can use — not in a feature list, not in a
  command table, not with a caveat attached. A caveat does not rescue it: a
  reader scanning a table sees the row, not the footnote. The issue tracker
  records defects; the README describes what a user can do today.

  This is about *features presented as available*, and does not weaken
  "Be truthful about status" under [Tone](#tone). Saying a project is at
  hypothesis stage, or marking a shipped feature alpha, is required — those
  are honest statements about what exists. Listing a command that errors on
  every invocation, annotated "currently broken", is not.
- **An Architecture section, if present, tells the user-relevant story** (what
  runs where and what that means for the user), not the contributor-relevant
  one (module layout, dispatch seams). The deep version belongs in `docs/`.

## Badges

Badges appear immediately after the H1 heading (and tagline, if present).
Order is always: License, CI, then language-specific badges where
applicable (PyPI + Python for Python; Go Reference for Go). Plugin-only
projects stop at License + CI.

Go lint status is covered by the **CI badge** — golangci-lint runs in CI
as the Go lint gate (see the [Go standard](go.md)). There is no separate
Go Report Card badge: `goreportcard.com` is sunset as of 2026-07-01, and
golangci-lint is its recommended successor.

**Python projects** (published to PyPI):

```markdown
[![License](https://img.shields.io/github/license/punt-labs/{repo})](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/punt-labs/{repo}/{workflow}.yml?label=CI)]({ci-url})
[![PyPI](https://img.shields.io/pypi/v/{pypi-name})](https://pypi.org/project/{pypi-name}/)
[![Python](https://img.shields.io/pypi/pyversions/{pypi-name})](https://pypi.org/project/{pypi-name}/)
```

**Plugin-only projects** (no PyPI package):

```markdown
[![License](https://img.shields.io/github/license/punt-labs/{repo})](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/punt-labs/{repo}/docs.yml?label=CI)]({ci-url})
```

**Go projects** (published module):

```markdown
[![License](https://img.shields.io/github/license/punt-labs/{repo})](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/punt-labs/{repo}/{workflow}.yml?label=CI)]({ci-url})
[![Go Reference](https://pkg.go.dev/badge/github.com/punt-labs/{repo}.svg)](https://pkg.go.dev/github.com/punt-labs/{repo})
```

**Working Backwards badge** *(optional)*:

Projects with a PR/FAQ document add a stage-colored badge after the
standard set. Use `/prfaq:badge` to generate it.

```markdown
[![Working Backwards](https://img.shields.io/badge/Working_Backwards-hypothesis-lightgrey)](./prfaq.pdf)
```

Stages: `hypothesis` (grey), `validated` (blue), `growth` (green).

Rules:

- CI badge uses `?label=CI` for consistent display, not the workflow name
- CI badge links to the **test** workflow (not lint or docs) for Python projects
- PyPI badge uses the `punt-` prefixed package name
- No GitHub Release badge (redundant with PyPI)
- No separate Lint badge (CI covers it)
- Working Backwards badge comes last, after language-specific badges

## Tone

A README describes what a project does. It is not a pitch, a landing
page, or a blog post. Every sentence should be verifiable — a reader
should be able to check whether it is true by using the software.

### Principles

1. **Describe, don't sell.** Say what the project does and how. Let the
   reader decide whether it's useful.
2. **State facts, not opinions.** If something is an opinion or a thesis,
   present it as one ("Biff assumes the terminal is where you're already
   working"), not as established truth ("the terminal is the new center of
   gravity").
3. **Credit the method, not the tool.** When a project applies established
   research, say so and cite it. The methods have always worked; this
   project makes them accessible. Don't claim the project invented the
   insight.
4. **Be truthful about status.** Mark alpha features as alpha. Say "hypothesis
   stage" if no plugin code exists yet. Readers trust READMEs that
   acknowledge limitations.
5. **Respect competitors.** Name them, link them, say what they do well. If
   your project does something differently, describe the difference
   factually. See koch-trainer-swift's "Respect for the Ecosystem" section
   for the model.

### Avoid

| Pattern | Example | Problem |
|---------|---------|---------|
| Marketing verbs | "Unlock", "Unleash", "Supercharge" | Pitch language, not description |
| Anthropomorphizing | "understands what you mean", "reads the way you would" | Software doesn't understand or read. Say what it does technically. |
| Opinions as facts | "X hasn't caught up", "X falls apart" | State the factual gap, not a judgment |
| Implied endorsement | "Y validated the category" | Another company shipping a product doesn't validate yours |
| Buzzwords | "AI-accelerated", "next-generation" | Meaningless without specifics |
| Hyperbole | "falls apart", "game-changer", "revolutionary" | Undermines credibility |
| Vague value claims | "saves you time", "boosts productivity" | Unverifiable. Say what it does; the reader decides the value. |

### Prefer

| Instead of | Write |
|------------|-------|
| "Unlock the knowledge trapped on your hard drive" | "Local semantic search across your documents" |
| "It understands what you mean, not just what you typed" | "Retrieval is by meaning, not keyword — a query about 'margins' finds passages about profitability even if they never use that word" |
| "Brings the methodology to where builders already work" | "Implements the methodology as a Claude Code plugin" |
| "Turns product thinking into a terminal command" | "Runs Amazon's Working Backwards process as a terminal command" |
| "AI changes the equation" | "The methods are the same; the time cost is not" |

## Code Blocks

Every fenced code block in a README that shows a command to run, or file
content a reader would copy, contains exactly one line. A sequence of
commands is a sequence of one-line blocks, not one multi-line block — each
command must be independently copy-pasteable without picking up a
neighboring comment or a different command. This has no exception for
content that would read more naturally as a multi-line listing (a spec
excerpt, a config file example): split it into consecutive one-line blocks
rather than one multi-line block.

This governs a project's actual README content — Quick Start commands,
Commands/API examples, What It Looks Like listings, CONTRIBUTING.md's
quality-gate commands. It does not govern this standard's own ```markdown
fences that illustrate markdown syntax itself (a table shape, a bullet-list
shape) rather than content a reader of a real README would run or copy.

## Required Sections

Every README must have these sections in this order. Sections marked
*optional* may be omitted when not applicable. All section headings (H2 and below) use Title Case (e.g., "Quick Start", not "Quick start"). The H1 is the project name and follows its own casing.

### 1. Title + Tagline

```markdown
# project-name

> One-line description of what the project does.
```

The tagline is a blockquote. Keep it under 80 characters.

### 2. Badges

See above.

### 3. Description

One paragraph (2-4 sentences) explaining what the project is, who it's for,
and how it fits into the ecosystem. No marketing language.

### 4. Platforms *(optional)*

```markdown
**Platforms:** macOS, Linux
```

Include when platform support is not obvious (e.g., CLI tools). Omit for
pure plugins or libraries.

### 5. Quick Start

The fastest path from zero to working. For CLI tools, this is the installer:

```markdown
## Quick Start

\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/punt-labs/{repo}/{sha}/install.sh | sh
\`\`\`
```

Include a `<details>` block for manual install and another for verification.

### 6. Features *(optional)*

Bullet list of key capabilities. Keep it scannable — no paragraphs.

```markdown
## Features

- **Feature name** --- one-line description
- **Feature name** --- one-line description
```

### 7. What It Looks Like *(optional)*

Show concrete examples of the tool in use. Use fenced code blocks with
`text` language for terminal output. This section lets a reader see what
the tool actually does before installing it.

### 8. Commands / API / MCP Tools

Use the heading that matches your project type: **Commands** (CLIs and
plugins), **API** (libraries), or **MCP Tools** (MCP servers).

```markdown
## Commands

| Command | What it does |
|---------|-------------|
| `cmd foo` | Does foo |
| `cmd bar` | Does bar |
```

### 9. Setup *(optional)*

Configuration steps beyond the Quick Start. Include file formats, required
accounts, or environment variables.

### 10. Project-Specific Sections *(optional)*

Sections unique to the project (e.g., "Status Bar", "Agents Welcome" in
biff; "Standards", "Plugin Development Patterns" in punt-kit). Place these
between Setup and Documentation.

### 11. Documentation *(optional)*

Links to additional docs when they exist in a `docs/` directory. Always
link `CONTRIBUTING.md` here when the project has quality gates (virtually
every project does) — the README's only mention of it is this link.

```markdown
## Documentation

[Installing](docs/INSTALLING.md) |
[FAQ](docs/FAQ.md) |
[Contributing](CONTRIBUTING.md) |
[Changelog](CHANGELOG.md)
```

### 12. License

```markdown
## License

MIT
```

Every repo must have a `LICENSE` file in the root.

## CONTRIBUTING.md

Quality-gate commands (lint, type-check, test) go in a `CONTRIBUTING.md` file
at the repo root — never in the README, not even a short section. Match the
project's CLAUDE.md quality gates exactly:

```markdown
# Contributing

\`\`\`bash
uv sync
\`\`\`

\`\`\`bash
uv run ruff check .
\`\`\`

\`\`\`bash
uv run ruff format --check .
\`\`\`

\`\`\`bash
uv run mypy src/ tests/
\`\`\`

\`\`\`bash
uv run pyright src/ tests/
\`\`\`

\`\`\`bash
uv run pytest
\`\`\`
```

`CONTRIBUTING.md` is not bound by the README's tone rules ([Tone](#tone)) or
required-section order — it is a plain command list for contributors, not a
user-facing description of the project.

## Anti-Patterns

### Structure

- **No badge soup** — four standard badges maximum for published projects (Python or Go), two for plugin-only projects, plus optional Working Backwards badge
- **No "Table of Contents"** — the README should be short enough to not need one
- **No "Contributing" or "Development" section in README** — quality-gate commands always go in `CONTRIBUTING.md`, linked from Documentation
- **No installation instructions for dependencies** — the installer handles it
- **No version numbers in prose** — they go stale; badges stay current
- **No portfolio content** — each project describes itself, not its siblings
- **No multi-line code blocks** — every fenced block is one line; see [Code Blocks](#code-blocks)

### Tone

- **No marketing verbs in taglines** — "Unlock", "Unleash", "Supercharge", "Transform" are pitch words. Describe what it does.
- **No anthropomorphizing** — software doesn't "understand", "think", or "read the way you would". Say what it does technically: parses, indexes, retrieves, compares.
- **No opinions stated as facts** — if it's a thesis or design assumption, frame it as one. "Biff assumes X" is a fair claim. "X is the future" is not.
- **No unverifiable value claims** — "saves hours", "boosts productivity", "10x faster" require evidence. If you have the data, cite it. If you don't, describe the mechanism and let the reader judge.
- **No disparaging competitors** — name them, link them, describe what they do well. If you do something differently, state the difference. See koch-trainer-swift's "Respect for the Ecosystem" for the model.
