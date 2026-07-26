# Makefile Standards

Every Punt Labs project with quality gates must include a `Makefile` at the project root. The Makefile provides discoverable, memorable entry points for development tasks — no tool-specific knowledge required.

---

## Why

- **Universal**: `make test` works for every developer, every CI system, every agent. No need to know whether the project uses uv, hatch, npm, or xcodegen.
- **Discoverable**: `make help` lists available targets. New contributors and agents don't need to read CLAUDE.md to find the right incantation.
- **Stable interface**: The underlying commands change (uv replaces hatch, ruff replaces flake8), but `make check` stays the same.
- **Composable**: `check` composes `lint`, `type`, and `test`. CI runs `make check`. Humans run the piece they need.

## Required targets

Every project must define these targets. The underlying commands vary by ecosystem.

| Target | Purpose | Python example | Go example |
|--------|---------|----------------|------------|
| `help` | List available targets with descriptions | `@grep -E ...` | `@grep -E ...` |
| `test` | Run the default test suite | `uv run pytest` | `go test -race -count=1 ./...` |
| `lint` | Lint and format check (no mutations) | `uv run ruff check . && uv run ruff format --check .` | `golangci-lint run ./... && golangci-lint fmt --diff` |
| `check` | Run all quality gates | `$(MAKE) lint type test` | `$(MAKE) lint test` |
| `format` | Auto-fix formatting and lint issues | `uv run ruff format . && uv run ruff check --fix .` | `golangci-lint fmt` |
| `build` | Build distributable artifacts | `uv build` | `CGO_ENABLED=0 go build -o <binary> .` |
| `clean` | Remove build artifacts and temp files | `rm -rf dist/ .tmp/` | `rm -f <binary> && rm -rf dist/` |

## Optional targets

Add these when the project needs them.

| Target | Purpose | When to add |
|--------|---------|-------------|
| `type` | Static type checking | Python projects (mypy, pyright) |
| `coverage` | Test with coverage report | When tracking coverage |
| `depot` | Build wheel and copy to local depot | Projects that are cross-project dependencies (see [distribution](distribution.md#local-development-depot)) |
| `prfaq` | Compile `.tex` → `.pdf` and clean artifacts | Projects with LaTeX documents (prfaq, press releases) |

## Template: Python projects

```makefile
.PHONY: help test lint type check format build clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Run tests (excludes slow integration tests)
	uv run pytest

lint: ## Lint and format check
	uv run ruff check .
	uv run ruff format --check .

type: ## Type check with mypy and pyright
	uv run mypy src/ tests/
	uv run pyright src/ tests/

check: lint type test ## Run all quality gates

format: ## Auto-format code
	uv run ruff format .
	uv run ruff check --fix .

build: ## Build wheel and sdist
	rm -rf dist/
	uv build
	uvx twine check dist/*

clean: ## Remove build artifacts
	rm -rf dist/ .tmp/
```

## Template: Go projects

```makefile
.PHONY: help test lint check format build clean tools

BINARY  := <binary-name>
VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
LDFLAGS := -s -w -X main.version=$(VERSION)

# golangci-lint is the Go lint gate (Go Report Card successor). Pin the
# version so local and CI run the same analyzer bundle; keep it in sync with
# the golangci-lint-action version in .github/workflows. Config: .golangci.yml.
# Resolve the install dir the way `go install` does: GOBIN if set, else the
# first GOPATH entry + /bin — so the `tools` target and this path agree. GOPATH
# can be colon-separated, so take the first entry before appending /bin.
GOLANGCI_LINT_VERSION := v2.12.2
GOBIN := $(shell go env GOBIN)
ifeq ($(GOBIN),)
GOBIN := $(shell go env GOPATH | cut -d: -f1)/bin
endif
GOLANGCI_LINT := $(GOBIN)/golangci-lint

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Run tests
	go test -race -count=1 ./...

lint: ## Lint and format check (golangci-lint bundles go vet, staticcheck)
	$(GOLANGCI_LINT) run ./...
	$(GOLANGCI_LINT) fmt --diff

check: lint test ## Run all quality gates

format: ## Auto-format code
	$(GOLANGCI_LINT) fmt

tools: ## Install development tools
	go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@$(GOLANGCI_LINT_VERSION)

build: ## Build binary
	CGO_ENABLED=0 go build -ldflags="$(LDFLAGS)" -o $(BINARY) .

clean: ## Remove build artifacts
	rm -f $(BINARY) coverage.out
	rm -rf dist/
```

## Template: `depot` target

The depot target builds a wheel and copies it to the shared local depot
directory for cross-project testing. See
[distribution standards](distribution.md#local-development-depot) for the full
protocol.

```makefile
DEPOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../.depot

depot: build ## Build and copy wheel to local depot
	@mkdir -p $(DEPOT)
	@cp dist/*.whl $(DEPOT)/
	@echo "depot: $$(ls dist/*.whl | xargs -n1 basename) -> $(DEPOT)/"
```

Add `depot` to `.PHONY`. The `DEPOT` variable resolves to `../.depot` relative
to the Makefile location, which is the workspace root when projects are checked
out as siblings.

## Template: `prfaq` target

Most projects have LaTeX documents via the prfaq plugin. Add `make prfaq` to
compile `.tex` files and sweep up intermediate artifacts, leaving only the PDF.

```makefile
# LaTeX intermediate files to remove after compilation
LATEX_ARTIFACTS = *.aux *.log *.out *.bbl *.bcf *.blg *.run.xml *.fls \
                  *.fdb_latexmk *.synctex.gz *.toc

TEX_FILES = prfaq.tex

prfaq: ## Compile .tex to .pdf and clean artifacts
	@for f in $(TEX_FILES); do \
	  echo "Compiling $$f ..."; \
	  dir=$$(dirname "$$f"); base=$$(basename "$$f" .tex); \
	  pdflatex -interaction=nonstopmode -output-directory="$$dir" "$$f" > /dev/null 2>&1; \
	  if [ -f "$$dir/$$base.bib" ] && command -v biber > /dev/null 2>&1; then \
	    (cd "$$dir" && biber "$$base") > /dev/null 2>&1 || true; \
	    pdflatex -interaction=nonstopmode -output-directory="$$dir" "$$f" > /dev/null 2>&1; \
	  fi; \
	  pdflatex -interaction=nonstopmode -output-directory="$$dir" "$$f" > /dev/null 2>&1; \
	  if [ -f "$$dir/$$base.pdf" ]; then \
	    echo "  $$dir/$$base.pdf"; \
	  else \
	    echo "Error: $$f failed to compile" >&2; exit 1; \
	  fi; \
	done
	@rm -f $(LATEX_ARTIFACTS)

clean-tex: ## Remove LaTeX intermediate files
	@rm -f $(LATEX_ARTIFACTS)
```

Customize `TEX_FILES` per project. For projects with multiple documents
(e.g., prfaq repo with both `prfaq.tex` and `assets/prfaq-template.tex`),
list all files. The artifact cleanup runs once after all files compile.

In the prfaq repo itself, `test` and `check` compose around the `prfaq`
target since compilation IS the quality gate:

```makefile
test: prfaq ## Verify all documents compile
check: test ## Run all quality gates
```

## Rules

1. **All targets in `.PHONY`.** Make targets are commands, not files.
2. **Every target has a `## ` comment** for `make help` extraction.
3. **`check` composes, never duplicates.** It lists other targets as prerequisites (e.g., `check: lint type test`), never repeats their commands.
4. **`lint` never mutates.** It checks and fails — `format` is the one that writes.
5. **`test` runs the default suite.** Slow or integration tests are opt-in (`make test-slow` or `uv run pytest -m slow`).
6. **No secrets in Makefiles.** Credentials come from environment variables.

## CLAUDE.md integration

Project CLAUDE.md files should reference `make check` as the quality gate command instead of listing raw `uv run` commands:

```markdown
## Quality Gates

Run before every commit:

    make check
```

The Makefile is the source of truth for what `check` means. CLAUDE.md just says to run it.
