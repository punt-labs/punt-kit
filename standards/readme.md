# README Standard

How every Punt Labs project README should be structured. Use
[biff's README](https://github.com/punt-labs/biff/blob/main/README.md) as the
reference implementation.

## Badges

Badges appear immediately after the H1 heading (and tagline, if present).
Order is always: License, CI, PyPI, Python.

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

Rules:

- CI badge uses `?label=CI` for consistent display, not the workflow name
- CI badge links to the **test** workflow (not lint or docs) for Python projects
- PyPI badge uses the `punt-` prefixed package name
- No GitHub Release badge (redundant with PyPI)
- No separate Lint badge (CI covers it)

## Required Sections

Every README must have these sections in this order. Sections marked
*optional* may be omitted when not applicable.

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
`text` language for terminal output. This section sells the project to
someone scrolling the README.

### 8. Commands / API

Table of commands (for CLIs/plugins) or API surface (for libraries/MCP
servers).

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

- **No badge soup** — four badges maximum for Python projects, two for plugins
- **No "Table of Contents"** — the README should be short enough to not need one
- **No "Contributing" section in README** — link to `CONTRIBUTING.md` if it exists
- **No installation instructions for dependencies** — the installer handles it
- **No version numbers in prose** — they go stale; badges stay current
- **No portfolio content** — each project describes itself, not its siblings
