.PHONY: help hooks test test-changed test-push test-quarantine test-quarantine-run coverage coverage-ci lint type check check-oo report update-oo check-coupling update-coupling check-suppressions update-suppressions check-comments check-docstrings check-standards build-api-docs format build smoke-candidate clean depot prfaq clean-tex

SRC := src/punt_kit/
.DEFAULT_GOAL := help
OO_BASE ?=
COUPLING_BASE ?=
SUPPRESSION_BASE ?=
DESIGN_BASE ?= origin/main
override export DESIGN_BASE := $(value DESIGN_BASE)

.PHONY: design-shadow

design-shadow: ## Gate design changes against DESIGN_BASE
	uv run python tools/design_gate.py "$(SRC)" "$${DESIGN_BASE}"

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Run the default suite (excludes quarantined tests)
	uv run pytest

test-changed: ## Pre-commit: run the tests affected by staged changes
	TMPDIR=/tmp uv run python tools/test_changed.py

test-push: export TMPDIR = /tmp
test-push: test ## Pre-push: run the default suite

test-quarantine: ## List quarantines; an empty selection is expected
	@uv run pytest --collect-only -q -m quarantine || [ "$$?" = 5 ]

test-quarantine-run: ## Run only quarantined tests
	uv run pytest -m quarantine

coverage: ## Run the default suite with branch coverage (terminal + HTML)
	uv run pytest --cov --cov-report=term-missing --cov-report=html

coverage-ci: ## Run the default suite with branch coverage (terminal + XML)
	uv run pytest --cov --cov-report=term --cov-report=xml

hooks: ## Install the pre-commit and pre-push hooks without overwriting other hooks
	@if path=$$(git config --get core.hooksPath); then \
		echo "core.hooksPath already set to $$path; chain .githooks manually" >&2; exit 1; \
	fi; \
	dir=$$(git rev-parse --git-path hooks) && mkdir -p "$$dir" || exit; \
	for hook in pre-commit pre-push; do \
		if { [ -e "$$dir/$$hook" ] || [ -L "$$dir/$$hook" ]; } && \
		   ! cmp -s ".githooks/$$hook" "$$dir/$$hook"; then \
			echo "$$dir/$$hook already exists; chain .githooks/$$hook manually" >&2; exit 1; \
		fi; \
	done; \
	for hook in pre-commit pre-push; do \
		[ -x "$$dir/$$hook" ] || install -m 755 ".githooks/$$hook" "$$dir/$$hook" || exit; \
	done

lint: check-comments check-docstrings check-standards ## Lint and format check
	uv run ruff check .
	uv run ruff format --check .
	shellcheck install.sh scripts/*.sh .githooks/*

check-comments: ## Reject commented-out code and tracker references in Python prose
	uv run ruff check --select ERA001 .
	uv run python tools/check_python_docs.py comments src tests tools

check-docstrings: ## Check public Python docstrings and documented argument names
	uv run ruff check --select D,D401 --ignore D105,D107,D417 src/
	uv run python tools/check_python_docs.py docstrings src/

check-standards: ## Check that policy clauses and language rules cite each other
	uv run python tools/check_standards.py

build-api-docs: ## Build and verify the generated Python API reference
	uv run --group docs mkdocs build --strict
	uv run python tools/check_python_docs.py api .tmp/api-site/objects.inv

type: ## Type check with mypy and pyright
	uv run mypy src/ tests/ tools/
	uv run pyright src/ tests/ tools/

check: design-shadow lint type test check-oo check-coupling check-suppressions ## Run all quality gates

check-oo: ## OO must-improve ratchet
	uv run oo-ratchet oo $(SRC) --check $(OO_BASE)

update-oo: ## Update touched OO baseline entries
	uv run oo-ratchet oo $(SRC) --update $(OO_BASE)

report: ## Report per-file OO metrics and thresholds
	-uv run oo-ratchet oo $(SRC) --threshold
	-uv run oo-ratchet design "$(SRC)"

check-coupling: ## Coupling/cohesion regression gate
	uv run oo-ratchet coupling $(SRC) --check $(COUPLING_BASE)

update-coupling: ## Update touched coupling baseline entries
	uv run oo-ratchet coupling $(SRC) --update $(COUPLING_BASE)

check-suppressions: ## Suppression-count regression gate
	uv run oo-ratchet suppressions $(SRC) --check $(SUPPRESSION_BASE)

update-suppressions: ## Update suppression baseline
	uv run oo-ratchet suppressions $(SRC) --update

format: ## Auto-format code
	uv run ruff format .
	uv run ruff check --fix .

build: ## Build wheel and sdist
	rm -rf dist/
	uv build
	uvx twine check dist/*

smoke-candidate: build ## Install the built wheel in a clean venv and run real punt operations
	scripts/smoke-release.sh candidate dist/punt_kit-*-py3-none-any.whl

clean: ## Remove build artifacts
	rm -rf dist/ .tmp/

DEPOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))../.depot

depot: build ## Build and copy wheel to local depot
	@mkdir -p $(DEPOT)
	@cp dist/*.whl $(DEPOT)/
	@echo "depot: $$(ls dist/*.whl | xargs -n1 basename) -> $(DEPOT)/"

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
