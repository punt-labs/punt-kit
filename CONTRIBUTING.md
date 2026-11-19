# Contributing to punt-kit

punt-kit is a Python package (the `punt` CLI) and a Claude Code plugin. This
guide covers setting up a checkout and running the checks a change must pass.
[CLAUDE.md](CLAUDE.md) and [docs/WORKFLOW.md](docs/WORKFLOW.md) hold the full
development rules; [docs/development.md](docs/development.md) covers working on
the plugin.

## Prerequisites

- [uv](https://docs.astral.sh/uv/)
- Python 3.13 or later (uv can install it)
- [ShellCheck](https://www.shellcheck.net/), used by `make lint`
- [markdownlint-cli2](https://github.com/DavidAnson/markdownlint-cli2), used by the documentation check
- `pdflatex` and `biber`, only if you edit `prfaq.tex`

## Setup

Clone the repository:

```bash
git clone https://github.com/punt-labs/punt-kit.git
```

Install the package and its development tools (pytest, ruff, mypy, pyright)
into `.venv`:

```bash
uv sync
```

Put scratch files in `.tmp/` at the repository root, not `/tmp`. Its contents
are gitignored, and `make clean` deletes them.

## Quality Gates

Every commit must pass all quality gates:

```bash
make check
```

`make check` runs these targets, which you can also run on their own.

Check Python formatting, comments, and public docstrings; run ShellCheck on
`install.sh` and `scripts/*.sh`:

```bash
make lint
```

Type check with mypy and pyright:

```bash
make type
```

Run the tests:

```bash
make test
```

Fix formatting and auto-fixable lint findings:

```bash
make format
```

CI also lints every Markdown file. Run the same check locally:

```bash
markdownlint-cli2 "**/*.md"
```

Build and verify the [Python API reference](docs/api-reference/index.md):

```bash
make build-api-docs
```

Open `.tmp/api-site/index.html` to read the generated reference.

After editing `prfaq.tex`, rebuild the PDF and commit both files:

```bash
make prfaq
```

Build and check the wheel and sdist:

```bash
make build
```

## Making a Change

1. Create a branch from `main`. Nothing reaches `main` except through a merged
   pull request.
2. Make one logical change per commit, with a `type(scope): description`
   message (for example `docs: …` or `fix(audit): …`).
3. Add an entry under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md) in the
   same pull request.
4. Update [README.md](README.md) when user-facing behavior changes: commands,
   flags, defaults, or configuration.
5. Open a pull request. Review follows
   [standards/pr-review.md](standards/pr-review.md).
