.PHONY: help test lint type check check-oo report update-oo check-coupling update-coupling check-suppressions update-suppressions check-comments check-docstrings check-policy-traceability build-api-docs format build clean depot prfaq clean-tex

SRC := src/punt_kit/
OO_BASE ?=
COUPLING_BASE ?=
SUPPRESSION_BASE ?=

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Run tests (excludes slow integration tests)
	uv run pytest

lint: check-comments check-docstrings check-policy-traceability ## Lint and format check
	uv run ruff check .
	uv run ruff format --check .
	shellcheck install.sh scripts/*.sh

check-comments: ## Reject commented-out code and tracker references in Python prose
	uv run ruff check --select ERA001 .
	uv run python tools/check_python_docs.py comments src tests tools

check-policy-traceability: ## Check policy IDs against Python language-rule citations
	uv run python tools/check_policy_traceability.py

check-docstrings: ## Check public Python docstrings and documented argument names
	uv run ruff check --select D,D401 --ignore D105,D107,D417 src/
	uv run python tools/check_python_docs.py docstrings src/

build-api-docs: ## Build and verify the generated Python API reference
	uv run --group docs mkdocs build --strict
	uv run python tools/check_python_docs.py api .tmp/api-site/objects.inv

type: ## Type check with mypy and pyright
	uv run mypy src/ tests/ tools/
	uv run pyright src/ tests/ tools/

check: lint type test check-oo check-coupling check-suppressions ## Run all quality gates

check-oo: ## OO must-improve ratchet
	uv run oo-ratchet oo $(SRC) --check $(OO_BASE)

update-oo: ## Update touched OO baseline entries
	uv run oo-ratchet oo $(SRC) --update $(OO_BASE)

report: ## Report per-file OO metrics and thresholds
	uv run oo-ratchet oo $(SRC) --threshold

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
