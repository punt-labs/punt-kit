# README Standard

How every Punt Labs project README should be structured and written.

Reference implementations:

- [biff](https://github.com/punt-labs/biff/blob/main/README.md) — structure (CLI + plugin hybrid)
- [koch-trainer-swift](https://github.com/punt-labs/koch-trainer-swift/blob/main/README.md) — tone and competitor positioning
- [z-spec](https://github.com/punt-labs/z-spec/blob/main/README.md) — academic grounding and factual framing

## Badges

Badges appear immediately after the H1 heading (and tagline, if present).
Order is always: License, CI, then language-specific badges where
applicable (PyPI + Python for Python; Go Reference + Go Report Card
for Go). Plugin-only projects stop at License + CI.

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
[![Go Report Card](https://goreportcard.com/badge/github.com/punt-labs/{repo})](https://goreportcard.com/report/github.com/punt-labs/{repo})
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
4. **Be honest about status.** Mark alpha features as alpha. Say "hypothesis
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
between Setup and Development.

### 11. Documentation *(optional)*

Links to additional docs when they exist in a `docs/` directory.

```markdown
## Documentation

[Installing](docs/INSTALLING.md) |
[FAQ](docs/FAQ.md) |
[Changelog](CHANGELOG.md)
```

### 12. Development

Quality gate commands for contributors. Match the project's CLAUDE.md
quality gates exactly.

```markdown
## Development

\`\`\`bash
uv sync                        # Install dependencies
uv run ruff check .            # Lint
uv run ruff format --check .   # Check formatting
uv run mypy src/ tests/        # Type check (mypy)
uv run pyright src/ tests/     # Type check (pyright)
uv run pytest                  # Test
\`\`\`
```

### 13. License

```markdown
## License

MIT
```

Every repo must have a `LICENSE` file in the root.

## Anti-Patterns

### Structure

- **No badge soup** — four standard badges maximum for published projects (Python or Go), two for plugin-only projects, plus optional Working Backwards badge
- **No "Table of Contents"** — the README should be short enough to not need one
- **No "Contributing" section in README** — link to `CONTRIBUTING.md` if it exists
- **No installation instructions for dependencies** — the installer handles it
- **No version numbers in prose** — they go stale; badges stay current
- **No portfolio content** — each project describes itself, not its siblings

### Tone

- **No marketing verbs in taglines** — "Unlock", "Unleash", "Supercharge", "Transform" are pitch words. Describe what it does.
- **No anthropomorphizing** — software doesn't "understand", "think", or "read the way you would". Say what it does technically: parses, indexes, retrieves, compares.
- **No opinions stated as facts** — if it's a thesis or design assumption, frame it as one. "Biff assumes X" is honest. "X is the future" is not.
- **No unverifiable value claims** — "saves hours", "boosts productivity", "10x faster" require evidence. If you have the data, cite it. If you don't, describe the mechanism and let the reader judge.
- **No disparaging competitors** — name them, link them, describe what they do well. If you do something differently, state the difference. See koch-trainer-swift's "Respect for the Ecosystem" for the model.
