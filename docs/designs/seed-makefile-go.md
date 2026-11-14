# Design: `punt seed makefile` Renders the Go Standard-Targets Block

**Introduced:** 2026-11-14
**Worker:** adb · **Evaluator:** mdm
**Tracker:** Linear PL-1043

This document settles how `punt seed makefile` renders the `standard-targets`
and `help` managed sections for a Go repository, so the Go repos get the same
marker-managed blocks the Python repos get. It follows the shape of
[lang-rules-deploy.md](lang-rules-deploy.md): problem, fleet reality check,
mechanism, the rendered block, rollout, failure contract, tests, operator
decisions, a `DESIGN.md` ADR draft, and the implementation write-set.

Every `file:line` citation below was read on `origin/main` of punt-kit on
2026-11-14 with `git show origin/main:<path>`; sibling Makefiles were read
from the sibling checkouts under the workspace root, and their dates are the
`git log -1 -- Makefile` author dates.

---

## 1. Problem

`punt seed makefile` renders nothing for any repository whose detected
language is not Python. The guard is `src/punt_kit/seed.py:384-388`:

```python
    if target == "makefile" and info.language != "python":
        # Only python makefile templates for now
        console.print(
            "  [yellow]⚠[/yellow] Makefile templates only support Python — skipping"
        )
        return []
```

The return is empty, the exit status is 0, and `run_seed` then prints
`No changes needed.` (`seed.py:362`). A Go repo therefore gets a warning
glyph and a success exit from a command that did nothing. The one test that
covers the path, `tests/test_seed.py:360-366`
(`test_seed_makefile_skips_non_python`), pins that silence as the contract.

The section registry is a single flat list, `MAKEFILE_SECTIONS` at
`seed.py:231-234`, which names `makefile/python.mk.j2` for
`standard-targets` and `makefile/help.mk.j2` for `help`; `TARGETS` at
`seed.py:236-238` binds the `makefile` target to that one list. There is no
place to register a second language's template, which is why the guard
exists.

What each Go repo lacks as a result:

- **No `# punt:begin standard-targets` block.** The `check`, `lint`, `test`,
  `format`, `build`, and `clean` targets in every Go Makefile are hand-rolled,
  and a change to the standard (a golangci-lint version bump, the move from
  `go install` to the prebuilt binary) is six separate hand edits with no
  tool to apply or verify them.
- **No `# punt:begin help` block.** Five of the six Go repos carry their own
  `help` recipe in three different formats (§ 2).
- **Nothing for `punt audit` to check.** The marker is what makes a managed
  section auditable: a block that `punt seed --dry-run` would change is a
  drifted block. Without markers, `punt audit` can only observe that a
  Makefile exists, never that its standard targets match the standard.

The scope here is the two managed sections and the Go block. Operator
direction of 2026-11-14 is that this gap outranks how any single section is
handled, and that a `prfaq` section is not part of this design (the recipe is
the prfaq tool's; PL-506 is canceled).

---

## 2. Fleet reality check

Surveyed on 2026-11-14 across the six repos the mission names, read-only
from the sibling checkouts. No Makefile in the set carries a `# punt:begin`
marker. `detect` classes a repo as Go when `go.mod` exists at the root and no
`pyproject.toml` `[project]` table or `package.json` preceded it
(`src/punt_kit/detect.py:132-135`).

### 2.1 Classification

| Repo | Root markers | `detect` language | In scope |
|------|--------------|-------------------|----------|
| beadle | `go.mod`, `.golangci.yml` | `go` | yes |
| cryptd | `go.mod` (no `.golangci.yml`) | `go` | yes |
| circuit | `go.mod`, `.golangci.yml` | `go` | yes |
| points | `go.mod`, `.golangci.yml` | `go` | yes |
| mcp-proxy | `go.mod`, `.golangci.yml` | `go` | yes |
| biff | `pyproject.toml` with `[project]`; no `go.mod` anywhere in the tree (`find` on 2026-11-14 returned none outside `node_modules`/`.venv`, and none there either) | `python` | no |

**biff is out of scope.** `detect.py:115-120` reads `pyproject.toml` first
and sets `language = "python"` when it has a `[project]` table; the Go branch
at `detect.py:132-135` runs only when `language is None`. biff's 108-line
Makefile (2026-10-24) is a Python Makefile (`uv run pytest`, `ruff`, `mypy`,
`pyright`) with `fuzz`, `prob`, `depot`, and `prfaq` extras. It already gets
`python.mk.j2` from `punt seed makefile` and its only difference from the
Python block is `check: lint type mdlint test` (one extra prerequisite,
`mdlint`), which the § 5.2 extension mechanism covers. It is listed in § 8 as
a decision only so the ruling is recorded.

### 2.2 The five Go Makefiles

| | beadle | cryptd | circuit | points | mcp-proxy |
|---|---|---|---|---|---|
| Lines / last commit | 357 / 2026-11-07 | 253 / 2026-11-09 | 169 / 2026-10-15 | 128 / 2026-10-11 | 54 / 2026-08-29 |
| `check:` prerequisites | `lint lint-strict vulncheck docs test` (l. 304) | `vet test lint markdownlint` (l. 21) | `format check-engine check-rpc check-pi-extension check-docs check-agent-skills` (l. 25) | `lint test markdownlint workflows evaluator-models` (l. 26) | `lint lint-strict vulncheck docs test` (l. 29) |
| `lint` chain | `gofmt -s -l` + `go vet` + `go run staticcheck@v0.8.1` + shellcheck (l. 63-70); `lint-strict` = `go run golangci-lint@v2.12.2` (l. 72-73) | `staticcheck ./...` unpinned, from `PATH` (l. 45-46); `vet` separate (l. 25-26) | `$(GOLANGCI_LINT) run ./...`, refuses when the binary is absent and names `make tools` (l. 68-70); no `fmt --diff` | binary present + version equals pin, then `run` and `fmt --diff` (l. 42-48) | `go vet` + `go run staticcheck@v0.7.0` (l. 10-12); `lint-strict` = `go run golangci-lint@v2.12.1` (l. 14-15) |
| golangci-lint pin / install | v2.12.2 via `go run` | none; CI `go install staticcheck@v0.8.1` (`lint.yml:23`) | v2.12.2 via `go install` (`tools`, l. 152-153) | v2.13.1 via `go install` (`tools`, l. 98-102); CI uses `golangci-lint-action` binary mode at v2.13.1 (`ci.yml:27-29`) | v2.12.1 via `go run` |
| govulncheck | in `check`, `go run @v1.7.0` (l. 75-76) | none | none | CI-only `security.yml` job, `go install @v1.1.4` | in `check`, `go run @v1.7.0` (l. 17-18) |
| markdownlint | `docs` (l. 93-94) | `markdownlint` (l. 48-49) | `check-docs` (l. 110-111) | `markdownlint` (l. 50-56) | `docs` (l. 20-21) |
| shellcheck | `lint-shell`, shebang discovery (l. 50-56, 78-81) | none | none | none | none |
| `test` flags | `-race -count=1`, with a `PATH` that carries provisioned ethos, biff, and a self-built beadle-email (l. 287-299) | `-race -count=1` (l. 28-29) | `-race -count=1 -coverprofile` per tier (l. 74-78) + `npm` tests | `-race -count=1` (l. 32-34) | `-race -count=1` (l. 23-24) |
| `format` | `go run golangci-lint fmt` (l. 306-307) | none | `$(GOLANGCI_LINT) fmt` + prettier (l. 88-90) | `$(GOLANGCI_LINT) fmt` (l. 67-70) | `gofmt -w .` (l. 31-32), while `.golangci.yml` enables gofumpt and goimports |
| `build` | `CGO_ENABLED=0`, `LDFLAGS`, one binary; `build-daemon` second (l. 309-313) | three `go build` lines, no `CGO_ENABLED`, no ldflags (l. 52-61) | `CGO_ENABLED=0`, `LDFLAGS` (l. 83-86) | `CGO_ENABLED=0`, `LDFLAGS`, `$(BINARY)` `$(CMD)` variables (l. 72-74) | `CGO_ENABLED=0`, `LDFLAGS` (l. 34-35) |
| `dist` / `install` | `dist` 8 artifacts + checksums (l. 334-344); `install` to `~/.local/bin` (l. 315-317) | no `dist`; `install` to `PREFIX=/usr/local` with man pages (l. 67-75) | no `dist`; `install` to `~/.local/bin` (l. 92-95) | `dist` 4 artifacts (l. 76-82); `install` to `PREFIX=$(HOME)/.local` (l. 84-87) | `dist` 4 artifacts (l. 45-50); `install` to `~/.local/bin` (l. 37-39) |
| `help` | standard grep/awk, `%-12s` (l. 60-61) | awk with `##@` section headers, `%-22s` (l. 249-253) | standard grep/awk, `%-24s` (l. 22-23) | standard grep/awk piped through `sort`, `%-16s` (l. 125-128) | standard grep/awk, `%-12s` (l. 7-8) |
| Default goal | first target `help` | first target `all: build check` (l. 18) | first target `help` | `.DEFAULT_GOAL := all` (l. 20) | first target `help` |
| `cmd/<name>/main.go` | beadle-daemon, beadle-email | crypt, crypt-admin, cryptd, eval-balance, eval-slm | circuit, circuit-rpc-spike | points | mcp-proxy |
| Targets with no standard counterpart | `lint-shell`, `lint-strict`, `test-shell-discovery`, `vet`, `staticcheck`, `vulncheck`, `docs`, `prfaq`, `clean-tex`, `tools-ethos`, `tools-biff`, `tools-beadle-email`, `test-integration`, `build-daemon`, `install`, `deploy-commands`, `dist`, `docker`, `docker-push`, `cover`, `doctor` | `all`, `check-full`, `vet`, `test-integration`, `test-e2e`, `test-acceptance`, `coverage`, `markdownlint`, `build-server`, `build-client`, `build-admin`, `install`, `uninstall`, `man`, `play`, `play-unix`, `play-mega`, `demo*` (6), `ollama-*` (4), `eval-slm`, `generate-dungeon`, `validate-dungeon`, `eval-balance*` (4), `prfaq`, `clean-tex` | `check-engine`, `check-go-quality`, `check-go-all`, `check-rpc`, `check-specs`, `check-runtime-spec`, `model-check-runtime-spec`, `check-machines`, `lint-engine`, `test-engine`, `test-rpc`, `test-pi-extension`, `build-engine`, `install`, `check-pi-extension`, `typecheck-pi-extension`, `lint-pi-extension`, `format-check-pi-extension`, `docs`, `check-docs`, `check-agent-skills`, `docs-pdf`, `clean-latex`, `smoke-pi`, `smoke-drive`, `coverage` | `all`, `check-dev`, `coverage`, `markdownlint`, `workflows`, `evaluator-models`, `dist`, `install`, `uninstall`, `doctor`, `spec` | `lint-strict`, `vulncheck`, `docs`, `test-e2e`, `install`, `dist`, `cover` |
| Dirty on this host (2026-11-14) | clean | one untracked dir (`playbooks/`) | clean | `Makefile` modified (a `doctor` jq filter, uncommitted) plus four other tracked files | `.envrc` modified, one untracked file |

Two Go siblings outside the six are the reference implementations the
standard already names and are read here for the block, not for rollout:

- **ethos** (489 lines, 2026-11-10): `tools` downloads the official
  golangci-lint release tarball for `$(GOLANGCI_LINT_VERSION)` (v2.13.1),
  verifies it against the release's `checksums.txt` with `sha256sum` or
  `shasum`, and installs to `$(GOBIN)` (`Makefile:426-485`); `lint` refuses
  when the binary is absent and names `make tools` (l. 62-64). Its CI runs
  `golangci-lint-action` in binary mode (`test.yml:37-38`) and a separate
  matrix job runs `make tools` for real (`test.yml:149-163`).
- **agent-image** (2026-11-07): the same prebuilt fetch, pinned by SHA-256 in
  a pins file, installed into a per-checkout `.tools/bin`; `lint-go` refuses
  any binary whose `version` output is not the pin (`Makefile:241-273`).

### 2.3 The most advanced deployed practice, and what this design does with it

**Generalized into the block:**

- `go test -race -count=1 ./...` is universal across the five and is
  `standards/go.md:219` ("`-race -count=1` mandatory").
- The pinned golangci-lint binary at `$(GOBIN)/golangci-lint`, resolved the
  way `go install` resolves `GOBIN` then the first `GOPATH` entry, is in
  circuit, points, ethos, and the standard's own template
  (`standards/makefile.md:88-93`).
- `lint` refusing when the binary is absent and naming `make tools` (circuit
  l. 69, points l. 43, ethos l. 63), and refusing when the installed version
  is not the pin (points l. 44-46, agent-image l. 241-249), is the most
  advanced lint gate deployed; the block takes both checks.
- `lint` = `run ./...` + `fmt --diff` (points l. 47-48, agent-image) is what
  `standards/makefile.md:101-103` prescribes.
- `tools` fetching the prebuilt release binary and verifying the checksum
  (ethos, agent-image) is what `standards/go.md:329-383` prescribes and what
  Linear PL-964 asks for; the block takes ethos's recipe without the GitHub
  API fallback route and without the system-directory refusal (§ 4.3).
- `vulncheck` in `check` via `go run golang.org/x/vuln/cmd/govulncheck@<pin>`
  (beadle l. 75-76 and l. 304, mcp-proxy l. 17-18 and l. 29) is the most
  recent practice on the two repos that run it at all, and points runs it in
  CI. The block takes it (§ 8, decision 3).
- `CGO_ENABLED=0 go build -ldflags="$(LDFLAGS)" -o <name> ./cmd/<name>/` with
  `VERSION` from `git describe` and `LDFLAGS := -X main.version=$(VERSION)`
  is in four of five and is `standards/go.md:524-528`.
- v2.13.1 is the newest golangci-lint pin deployed (points, ethos); the
  block pins it.

**Superseded, with the rationale:**

- Separate `vet` and `staticcheck` targets, and `go run honnef.co/go/tools/cmd/staticcheck@<tag>`
  (beadle, cryptd, mcp-proxy). golangci-lint bundles `govet` and
  `staticcheck` (`standards/go.md:266-272`), every repo that has a
  `.golangci.yml` enables both, and the standalone `go run` compiles the
  analyzer from source against the host toolchain, which is the failure
  beadle had to pin `GOTOOLCHAIN` around (beadle `Makefile:14-22`). One
  binary, one pin.
- `go install github.com/golangci/golangci-lint/...@<tag>` and
  `go run ...@<tag>` (beadle, circuit, points, mcp-proxy, and the standard's
  own template at `standards/makefile.md:110-111`). `standards/go.md:337-339`
  already forbids it; the standard's Makefile template contradicts the
  standard's Go document. § 4.3 and § 8 decision 1 resolve that in favor of
  the prebuilt binary and amend the template.
- `gofmt -s -l` and `gofmt -w .` as the format gate (beadle l. 64, mcp-proxy
  l. 32). `golangci-lint fmt` applies whatever formatters `.golangci.yml`
  enables (gofumpt and goimports in beadle and mcp-proxy), so `gofmt` alone
  is a weaker check than the lint gate itself runs.
- An unpinned `staticcheck` from `PATH` (cryptd l. 46) and `go build` without
  `CGO_ENABLED=0` or ldflags (cryptd l. 52-61). cryptd is the one repo with
  no `.golangci.yml`; its rollout PR adds the `standards/go.md:306-326`
  baseline config (§ 5.3).
- `format` as a prerequisite of `check` (circuit l. 25) mutates the tree
  inside the gate, against `standards/makefile.md:192` ("`lint` never
  mutates"); the block's `check` is `lint test vulncheck`.

**Kept outside the block, by design of the merge** (§ 4.4): everything in the
"no standard counterpart" row, `install` and `dist` included, plus beadle's
`GOTOOLCHAIN` export, points's and cryptd's `all`, and every repo's
markdownlint target under whichever name it carries.

---

## 3. Mechanism

### 3.1 Command line

```text
punt seed makefile [PATH] [--dry-run|-n]
```

The command, its arguments, and its flag are unchanged
(`src/punt_kit/__main__.py:131-141`). What changes is what the command does
for a Go repo and what it says for every other non-Python repo.

### 3.2 The `detect` mapping

`detect` sets `info.language = "go"` at `detect.py:132-135` when `go.mod`
exists at the root and no earlier branch set a language:

```python
    # Check Go
    go_mod = root / "go.mod"
    if go_mod.exists() and language is None:
        language = "go"
        project_type = "package"
        standards_refs.append("go")
```

It also fills `info.cli_commands` for Go from every `cmd/<name>/main.go`
(`detect.py:191-198`), sorted by directory name. The Go block renders its
`build` and `clean` targets from that list (§ 4.2). The `ProjectInfo.language`
docstring at `detect.py:47` lists `"python", "node", "swift"` and omits `go`;
the implementation adds `go` to that comment. The existing tests
`test_detect_go` (`tests/test_detect.py:48-55`), `test_detect_go_hybrid`
(l. 189-204), and `test_detect_go_no_cmd_dir` (l. 207-215) already pin the
mapping and the command list.

### 3.3 The per-language registry

`MAKEFILE_SECTIONS` (`seed.py:231-234`) becomes a mapping from language to
the ordered section list. Order is the append order `merge_file` uses
(`seed.py:118-170`: new sections are appended in dict insertion order), so
`standard-targets` precedes `help` in every rendered file.

```python
# Each language maps to its ordered (section_id, template_name) list.
# Templates are relative to templates/seed/. help.mk.j2 is shared.
MAKEFILE_SECTIONS: dict[str, list[tuple[str, str]]] = {
    "python": [
        ("standard-targets", "makefile/python.mk.j2"),
        ("help", "makefile/help.mk.j2"),
    ],
    "go": [
        ("standard-targets", "makefile/go.mk.j2"),
        ("help", "makefile/help.mk.j2"),
    ],
}

TARGETS: dict[str, tuple[str, dict[str, list[tuple[str, str]]]]] = {
    "makefile": ("makefile", MAKEFILE_SECTIONS),
}
```

`_seed_file` (`seed.py:367-416`) looks the language up in that mapping
instead of testing `info.language != "python"`. Adding a third language is
one template file and one registry entry; nothing else in `seed.py` changes.

### 3.4 The render context

`render_section` is called with an empty context on `origin/main` (`seed.py:398`). It
is called with one context for every language:

```python
context = {"binaries": list(info.cli_commands)}
```

`python.mk.j2` does not reference `binaries`, and Jinja's `StrictUndefined`
(`seed.py:190`) only raises for a name a template reads, so the Python
rendering is byte-identical to the `origin/main` rendering. `go.mk.j2` reads `binaries` for the
`build` and `clean` targets.

### 3.5 The guard becomes two explicit errors

The silent skip at `seed.py:384-388` is replaced by two checks that print
one `Error:` line on stderr and exit 1, the same shape as every other refusal
in `seed.py` (`seed.py:107-111`, `212-215`, `345-348`):

```python
    if info.language is None:
        console.print(
            f"[red]Error:[/red] no language detected in {info.root}"
            " (no pyproject.toml [project] table, package.json, go.mod,"
            " project.yml, or *.swift) — nothing to render"
        )
        raise SystemExit(1)
    if info.language not in sections_by_language:
        known = ", ".join(sorted(sections_by_language))
        console.print(
            f"[red]Error:[/red] no Makefile template for language"
            f" '{info.language}' — templates exist for: {known}"
        )
        raise SystemExit(1)
```

A `node` or `swift` repo therefore gets a one-line refusal naming the
language and the known set, and an exit status a script can branch on. The
docs-only case (`project_type == "docs"`, `detect.py:174-178`) is the first
error: it has no language.

### 3.6 Managed-target collisions

A hand-rolled target that shares a name with a block target and has its own
recipe would, after the block is appended, make `make` print
`warning: overriding recipe for target 'lint'` on every invocation and run
the block's recipe (last definition wins). Every Go repo in § 2.2 is in that
state on first adoption. `_seed_file` detects it before writing:

- A **collision** is a rule line `^<name>:` in a local (unmanaged) segment
  whose `<name>` is a target the rendered `standard-targets` or `help` block
  defines, and which is followed by at least one tab-indented recipe line
  before the next blank or non-recipe line.
- A rule line with prerequisites and **no recipe** (`check: docs`) is not a
  collision; it is the extension mechanism of § 5.2.
- `.PHONY:` lines are never collisions.

With one or more collisions, seed prints one line per collision
(`Error: Makefile:45 defines 'lint' with a recipe; the managed block owns it — move the repo's own steps to another target or delete the rule`),
writes nothing, and exits 1. `--dry-run` prints the same lines after the
diff summary and also exits 1, because the write it describes would be
refused. The rollout procedure in § 5.1 is built on this: dry-run, read the
collision list, trim, seed.

### 3.7 What `--dry-run` prints

`_print_diff_summary` (`seed.py:457-476`) is unchanged. For a Go repo the
possible outputs are:

| State | Line |
|-------|------|
| no `Makefile` | `+ Would create Makefile` |
| `Makefile` present, blocks absent | `~ Makefile (+N lines)` with N the rendered block size (§ 5.1 gives per-repo N) |
| blocks present and current | nothing, then `Dry run — no files modified.` |
| blocks present and stale | `~ Makefile (+N lines)`, `~ Makefile (-N lines)`, or `~ Makefile (content changed)` |
| any of the above, with collisions | the summary line, then one `Error:` line per collision, exit 1 |

After the summary, `run_seed` prints `Dry run — no files modified.`
(`seed.py:355-356`) and exits 0 unless a collision was reported.

---

## 4. The Go `standard-targets` block

### 4.1 As rendered for mcp-proxy

`binaries = ["mcp-proxy"]` from `cmd/mcp-proxy/main.go`. Marker lines
included, this is 65 lines; `help` adds 7 (`help.mk.j2` is 5 lines plus two
markers), so a one-binary Go repo gains 72 lines on first seed.

```makefile
# punt:begin standard-targets
.PHONY: check lint test vulncheck format build clean tools

# One pin per tool, read by every target below and by CI. Keep the
# golangci-lint-action `version:` in .github/workflows equal to this value.
GOLANGCI_LINT_VERSION := v2.13.1
GOVULNCHECK_VERSION := v1.7.0

# Resolve the install dir the way `go install` does: GOBIN if set, else the
# first GOPATH entry + /bin, so `tools` and `lint` agree on one path.
GOBIN := $(shell go env GOBIN)
ifeq ($(GOBIN),)
GOBIN := $(shell go env GOPATH | cut -d: -f1)/bin
endif
GOLANGCI_LINT := $(GOBIN)/golangci-lint

VERSION := $(or $(shell git describe --tags --always 2>/dev/null | sed 's/^v//'),dev)
LDFLAGS := -X main.version=$(VERSION) $(LDFLAGS_EXTRA)

check: lint test vulncheck  ## Run all quality gates

lint:  ## Lint and format check (golangci-lint bundles go vet, staticcheck, gofmt)
	@test -x "$(GOLANGCI_LINT)" || { echo "golangci-lint not found at $(GOLANGCI_LINT) — run 'make tools' to install $(GOLANGCI_LINT_VERSION)" >&2; exit 1; }
	@actual=$$("$(GOLANGCI_LINT)" version --short); \
	  test "$$actual" = "$(patsubst v%,%,$(GOLANGCI_LINT_VERSION))" || { echo "golangci-lint at $(GOLANGCI_LINT) is $$actual, not $(GOLANGCI_LINT_VERSION) — run 'make tools'" >&2; exit 1; }
	"$(GOLANGCI_LINT)" run ./...
	"$(GOLANGCI_LINT)" fmt --diff

test:  ## Run tests with the race detector, uncached
	go test -race -count=1 ./...

vulncheck:  ## Scan imports and call graph for known Go vulnerabilities
	go run golang.org/x/vuln/cmd/govulncheck@$(GOVULNCHECK_VERSION) ./...

format:  ## Apply the formatters .golangci.yml enables
	@test -x "$(GOLANGCI_LINT)" || { echo "golangci-lint not found at $(GOLANGCI_LINT) — run 'make tools' to install $(GOLANGCI_LINT_VERSION)" >&2; exit 1; }
	"$(GOLANGCI_LINT)" fmt

build:  ## Build a static binary per cmd/<name>/main.go into the repo root
	CGO_ENABLED=0 go build -ldflags="$(LDFLAGS)" -o mcp-proxy ./cmd/mcp-proxy/

clean:  ## Remove build artifacts
	rm -f mcp-proxy coverage.out
	rm -rf dist/

tools:  ## Install the pinned golangci-lint release binary into $(GOBIN), checksum-verified
	@test -n "$(GOBIN)" || { echo "tools: GOBIN is empty — is Go on PATH? ('go env GOBIN' and 'go env GOPATH' both returned nothing)" >&2; exit 1; }
	@set -e; \
	ver=$(GOLANGCI_LINT_VERSION); num=$${ver#v}; \
	os=$$(uname -s | tr '[:upper:]' '[:lower:]'); arch=$$(uname -m); \
	case "$$arch" in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; esac; \
	name=golangci-lint-$$num-$$os-$$arch; tarball=$$name.tar.gz; sums=golangci-lint-$$num-checksums.txt; \
	base=https://github.com/golangci/golangci-lint/releases/download/$$ver; \
	tmp=$$(mktemp -d "$${TMPDIR:-/tmp}/punt-tools.XXXXXXXX"); trap 'rm -rf "$$tmp"' EXIT; \
	curl -sSfL --retry 5 --retry-delay 5 -o "$$tmp/$$tarball" "$$base/$$tarball"; \
	curl -sSfL --retry 5 --retry-delay 5 -o "$$tmp/$$sums" "$$base/$$sums"; \
	line=$$(awk -v n="$$tarball" '$$2 == n' "$$tmp/$$sums"); \
	test "$$(printf '%s\n' "$$line" | grep -c .)" -eq 1 || { echo "tools: expected one checksum line for $$tarball in $$sums" >&2; exit 1; }; \
	if command -v sha256sum >/dev/null 2>&1; then (cd "$$tmp" && echo "$$line" | sha256sum -c -); \
	elif command -v shasum >/dev/null 2>&1; then (cd "$$tmp" && echo "$$line" | shasum -a 256 -c -); \
	else echo "tools: neither sha256sum nor shasum found; cannot verify $$tarball" >&2; exit 1; fi; \
	tar -xzf "$$tmp/$$tarball" -C "$$tmp" "$$name/golangci-lint"; \
	mkdir -p "$(GOBIN)"; install -m 0755 "$$tmp/$$name/golangci-lint" "$(GOBIN)/golangci-lint"; \
	echo "tools: installed $(GOBIN)/golangci-lint $$ver"
# punt:end standard-targets
```

The `version --short` form prints the bare number (`2.13.1` on this host on
2026-11-14), so the pin is compared with its `v` stripped. The binary on this
host reports `built with go1.27.3 from (unknown, modified: ?)`, which is the
`go install` artifact § 4.3 replaces; CI's `golangci-lint-action` binary
reports the release's own build.

### 4.2 The template, `src/punt_kit/templates/seed/makefile/go.mk.j2`

Identical to § 4.1 except for the two targets that read the context:

```jinja
build:  ## Build a static binary per cmd/<name>/main.go into the repo root
{%- if binaries %}
{%- for b in binaries %}
	CGO_ENABLED=0 go build -ldflags="$(LDFLAGS)" -o {{ b }} ./cmd/{{ b }}/
{%- endfor %}
{%- else %}
	go build ./...
{%- endif %}

clean:  ## Remove build artifacts
	rm -f {{ binaries | join(' ') }} coverage.out
	rm -rf dist/
```

A module with no `cmd/<name>/main.go` (a library, `detect.py:191-198`
returns an empty list) gets a `build` that compiles every package and a
`clean` that removes only `coverage.out` and `dist/`. The markers are added
by `render_section` (`seed.py:195-224`), not by the template.

### 4.3 golangci-lint: the prebuilt release binary, and the standard amendment

Two documents on `origin/main` disagree. `standards/go.md:329-339` says:
"Pin to a release tag in the Makefile and run the same prebuilt release
binary for that tag locally and in CI. [...] Never
`go install github.com/golangci/golangci-lint/...@<tag>`: that compiles a
copy from source." `standards/makefile.md:110-111`, the Go template's `tools`
target, says:

```makefile
tools: ## Install development tools
	go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@$(GOLANGCI_LINT_VERSION)
```

Linear PL-964 ("Go repos: run golangci-lint as the prebuilt release binary,
not go install/go run") asks for the `go.md` rule to be applied to the
fleet. `go.md:340-383` records the observed failure the rule exists for: two
builds of one tag that disagree on `gofmt` because the formatter is the
builder's `go/printer`, so a file passes locally and fails CI under one
version label. ethos hit it (`ethos/Makefile:15-30`); the block takes the
`go.md` side.

**The block's `tools` is ethos's recipe (`ethos/Makefile:426-485`) with
three things removed**, each a decision the leader can reverse (§ 8,
decision 8):

1. The GitHub API asset-route fallback (`ethos/Makefile:452-468`), which
   needs `jq` and an optional `GITHUB_TOKEN`. The block retries the release
   CDN five times and fails loudly; a repo that needs the second route keeps
   it in a local `tools` override (§ 4.4) and takes the collision rule with
   it.
2. The refusal to install into `/bin`, `/usr/bin`, and the like
   (`ethos/Makefile:431-435`). `GOBIN` is read from `go env`, which never
   returns a system directory unless the developer set it to one.
3. The long explanatory comment. The block carries the two-line reason; the
   rest is `standards/go.md` § 7.

**The standard amendment, in the same PR as the template** (write-set in
§ 10): `standards/makefile.md:73-119` ("Template: Go projects") is replaced
by the § 4.1 block verbatim, with the `binaries` lines shown for one binary
named `<name>` and the markers kept, and one sentence above it saying the
block is what `punt seed makefile` renders and that a Go repo's standard
targets are that block. The "Go example" column of the required-targets
table (`standards/makefile.md:19-26`) is unchanged: it already names
`golangci-lint run ./... && golangci-lint fmt --diff` and `golangci-lint fmt`.
`makefile.md` is on the markdownlint ignore list
(`.markdownlint-cli2.jsonc`) because its Makefile code blocks carry hard
tabs; that stays. § 8 decision 6 asks whether the verbatim replacement is
the ruling.

### 4.4 What the block does not absorb, and how a repo keeps it

`merge_file` replaces the text between a section's markers and leaves every
other byte of the file in place (`seed.py:118-170`,
`test_seed_makefile_updates_managed_preserves_local` at
`tests/test_seed.py:334-351`). Everything in the "no standard counterpart"
row of § 2.2 stays outside the markers, untouched by every future
`punt seed makefile` run. By name, from the mission's list and the survey:

| Target or variable | Where it lives | Why the block does not own it |
|---|---|---|
| `prfaq`, `clean-tex`, `clean-latex`, `docs-pdf` | outside | the prfaq tool's recipe; PL-506 canceled; operator direction 2026-11-14 |
| `play`, `play-unix`, `play-mega`, `demo*`, `eval-*`, `ollama-*`, `generate-dungeon`, `validate-dungeon` | outside (cryptd) | product-specific |
| `man`, `install`, `uninstall` | outside | `install` has three different `PREFIX` conventions in the fleet (§ 2.2) and `standards/go.md:556-564` names it as a convention, not a target the Makefile standard requires |
| `dist` | outside | three of five define it and two do not; `go.md:533-538` gives the recipe; not in `makefile.md`'s required table |
| `tools-ethos`, `tools-biff`, `tools-beadle-email`, `TEST_PREREQS`, `TEST_RUN` | outside (beadle) | beadle's test provisioning; `test` in beadle keeps its `PATH` prefix by the § 5.2 collision procedure (beadle is the one repo whose `test` recipe differs from the block's, see § 5.3) |
| `spec`, `check-specs`, `check-machines`, `fuzz`, `prob` | outside | z-spec gates |
| `doctor` | outside | per-product |
| `docs`, `markdownlint`, `check-docs`, `lint-shell`, `workflows`, `evaluator-models`, `check-agent-skills` | outside; wired in by `check: <extras>` (§ 5.2) | not Go gates; `makefile.md` has no markdownlint or shellcheck target in its required table |
| `lint-strict`, `vet`, `staticcheck` | deleted in the rollout PR | superseded (§ 2.3): the block's `lint` runs the same analyzers from one binary |
| `vulncheck` | absorbed | beadle's and mcp-proxy's recipes are the block's recipe; the collision rule removes the duplicate |
| `export GOTOOLCHAIN := go1.26.10` (beadle l. 22) | outside | a repo-level toolchain pin; `go test` and `go build` in the block honor it |
| `.DEFAULT_GOAL := all` (points l. 20), `all:` first (cryptd l. 18) | outside, overridden | `help.mk.j2` ends with `.DEFAULT_GOAL := help`; the appended block's assignment is the last one `make` reads, so a bare `make` prints help in every seeded repo (§ 8, decision 10) |
| `LDFLAGS_EXTRA` | outside, optional | the one hook the block offers for a repo that injects more `-X` values |

Make reads variable assignments in file order and the last `:=` wins, so a
repo that sets `GOLANGCI_LINT_VERSION` above the block is overridden by the
block's pin; that is the point of the block. A repo that needs a different
value for a block variable places the assignment after the `# punt:end help`
marker; `merge_file` preserves segments after the last managed section in
place. No repo in § 2.2 needs that.

---

## 5. Rollout

### 5.1 Per-repo dry-run expectation

The first `punt seed makefile --dry-run` in each repo prints `~ Makefile
(+N lines)` with N = 65 + 7 = 72 for one binary, plus one `build` line per
binary beyond the first, followed by one `Error:` line per collision (§ 3.6)
and exit 1. A collision is a block-owned target (`check`, `lint`, `test`,
`vulncheck`, `format`, `build`, `clean`, `tools`, `help`) with a local
recipe; the superseded targets of § 2.3 (`vet`, `staticcheck`,
`lint-strict`) are not collisions and are deleted in the same PR because
the block's `lint` runs their analyzers. The rollout PR for each repo is
then: delete or rename each colliding recipe, delete the superseded
targets, add the `check:` extension line, run `punt seed makefile` for
real, run `make tools`, `make check`, and `make help`, commit.

| Repo | Binaries | First dry-run | Colliding recipes to remove (block-owned) | Superseded targets deleted | Extension line | Net after rollout (approx.) |
|---|---|---|---|---|---|---|
| mcp-proxy | 1 | `+72 lines`, 8 collisions | `help`, `lint`, `vulncheck`, `test`, `check`, `format`, `build`, `clean` (l. 7-8, 10-12, 17-18, 23-24, 29-35, 41-43) | `lint-strict` (l. 14-15) | `check: docs` | 54 → about 95 |
| points | 1 | `+72 lines`, 8 collisions | `check`, `test`, `lint`, `format`, `build`, `clean`, `tools`, `help` (l. 25-26, 32-34, 41-48, 67-70, 72-74, 93-96, 98-102, 125-128); the `actionlint` and `gopls` lines of `tools` move to a local `tools-extra` target | none | `check: markdownlint workflows evaluator-models` | 128 → about 150 |
| circuit | 2 | `+73 lines`, 8 collisions | `help`, `check`, `lint`, `test`, `build`, `format`, `clean`, `tools` (l. 22-23, 25, 66, 72, 83, 88-90, 152-153, 167-169); `format`'s prettier line moves to `format-pi-extension`; `check-engine` becomes `check-engine: test-engine` since `lint` is the block's | none | `check: check-rpc check-pi-extension check-docs check-agent-skills` | 169 → about 200 |
| cryptd | 5 | `+76 lines`, 6 collisions | `check`, `test`, `lint`, `build`, `clean`, `help` (l. 21, 28-29, 45-46, 52-53, 63-64, 249-253); `build-server`, `build-client`, `build-admin` stay as aliases of the three binaries `play` and `install` name; `check-full` keeps its own prerequisite list; the `##@` section headers stop rendering in `help` (the block's recipe is the plain grep/awk) | `vet` (l. 25-26) | `check: markdownlint` | 253 → about 300, plus a new `.golangci.yml` (§ 5.3) |
| beadle | 2 | `+73 lines`, 8 collisions | `help`, `lint`, `vulncheck`, `test`, `check`, `format`, `build`, `clean` (l. 60-64, 75-76, 298-299, 304-307, 309-310, 330-332); `build-daemon` stays as an alias | `vet`, `staticcheck`, `lint-strict` (l. 66-73) and `STATICCHECK_VERSION`, `GOLANGCI_LINT_VERSION` (l. 8-9) | `check: lint-shell docs` | 357 → about 390 |

Line numbers are the sibling Makefiles' on 2026-11-14 (§ 2.2 dates). The
"net" column is the block plus the file minus the removed recipes, rounded;
the PR's own diff is the number that matters and the rollout worker records
it in the PR description.

### 5.2 How a repo extends `check`

**Recommendation: a prerequisite-only rule outside the block.** Make merges
the prerequisite lists of every rule for one target when at most one of them
has a recipe, so a local line

```makefile
check: docs lint-shell
```

above the block adds `docs` and `lint-shell` to the block's
`check: lint test vulncheck` without a warning, and `make check` runs the
local extras first (prerequisites run in file order across rule lines) and
the block's three after. The line reads as what it is, it needs no new
target name and no variable, and `make -n check` shows the merged list.

Rejected:

- **`check: check-standard <extras>`**, with the block owning
  `check-standard`. It renames the one target every CI workflow and every
  `CLAUDE.md` in the fleet calls, and a repo that forgets the local line has
  no `check` at all.
- **A documented variable** (`CHECK_EXTRA := docs`, with the block's
  `check: lint test vulncheck $(CHECK_EXTRA)`). It hides the prerequisite
  list behind an indirection and must be set above the block to take
  effect, which the variable-order rule in § 4.4 makes fragile.

The same rule extends `lint`, `test`, and `format` (circuit's
`test: test-pi-extension`, `format: format-pi-extension`) without touching
the block.

### 5.3 Per-repo notes

- **cryptd** has no `.golangci.yml`. The rollout PR adds the
  `standards/go.md:306-326` baseline (govet, staticcheck, unused, the ST
  exclusions, gofmt) and fixes whatever `golangci-lint run` reports on the
  tree before `make check` is green. Its CI `lint.yml:21-24` installs
  staticcheck with `go install`; the PR replaces that step with
  `golangci-lint-action` at the block's pin (`go.md:343-349`).
- **beadle** is the one repo whose `test` recipe is not the block's: it
  wraps `go test` in `TEST_RUN` to carry three provisioned tools on `PATH`
  (`Makefile:287-299`). The collision rule refuses the file until that
  recipe moves; the rollout PR renames it `test-provisioned`, keeps
  `TEST_PREREQS` and `TEST_RUN` as they are, and adds
  `check: lint-shell docs test-provisioned`. The block's plain `test` then
  runs the packages that need no provisioned binary and `test-provisioned`
  runs them all; CI's `make test` (`test.yml`, `release.yml:27`) becomes
  `make test-provisioned`. The `GOTOOLCHAIN` export (l. 14-22) stays.
- **circuit** CI runs `nix develop --command make check` (`check.yml:31`);
  the nix shell must provide `curl`, `tar`, and `shasum` or `sha256sum` for
  `make tools`, or the rollout PR adds golangci-lint at the pin to the
  flake and the block's `lint` finds it at `$(GOBIN)` only if the flake
  installs it there. The rollout worker reads `flake.nix` and picks; the
  block does not change for it.
- **points** CI already runs `golangci-lint-action` at v2.13.1 and
  `golangci-lint fmt --diff` (`ci.yml:26-32`); the PR is the Makefile and
  the `tools` split only. Its `security.yml` govulncheck job at v1.1.4
  moves to the block's pin or is deleted in favor of `make vulncheck`.
- **mcp-proxy** CI `lint.yml:21-23` runs all three tools with `go run`; the
  PR replaces the three steps with `golangci-lint-action` plus
  `make vulncheck`.

### 5.4 Dirty repos on this host, 2026-11-14

Every rollout PR is a worktree PR (`docs/WORKFLOW.md`, one worktree per
unit). The repos where the main checkout cannot be used as the base without
first moving work aside:

- **points**: `Makefile` itself is modified and uncommitted (a `doctor`
  jq-filter change at l. 115-116), with `.bin/check-dev-config.sh`,
  `.gitignore`, `.punt-labs/ethos/CLAUDE.md`, and `CLAUDE.md` also
  modified. The leader rules on that diff before the rollout branch is cut.
- **mcp-proxy**: `.envrc` modified, `resume.md` untracked.
- **cryptd**: `playbooks/` untracked only; the tracked tree is clean.
- **beadle**, **circuit**: clean.

---

## 6. Failure contract

Every row prints exactly one line per failure on stderr, prefixed `Error:`,
and exits 1, matching `seed.py`'s existing refusals (`seed.py:107-111`,
`212-215`, `345-348`). Nothing is written on any failing row.

| Condition | How it is detected | Line | Exit | `--dry-run` |
|---|---|---|---|---|
| Path is not a directory | `seed.py:328-330` | `Error: <path> is not a directory` | 1 | same |
| Language undetected (`info.language is None`) | § 3.5, first check | `Error: no language detected in <root> (no pyproject.toml [project] table, package.json, go.mod, project.yml, or *.swift) — nothing to render` | 1 | same |
| Language detected, no template (`node`, `swift`) | § 3.5, second check | `Error: no Makefile template for language 'swift' — templates exist for: go, python` | 1 | same |
| Template file missing from the install | `seed.py:211-215` | `Error: Template 'makefile/go.mk.j2' not found — punt-kit may need reinstalling` | 1 | same |
| Template raises (undefined name, syntax) | `seed.py:216-219` | `Error: Template 'makefile/go.mk.j2' failed: <jinja message>` | 1 | same |
| `Makefile` absent | `seed.py:392-394`, `original = ""` | no error; both blocks are written as the whole file | 0 | `+ Would create Makefile`, nothing written |
| `Makefile` present, no markers, no collisions | `parse_segments` returns one local segment | no error; blocks appended after the last line | 0 | `~ Makefile (+N lines)` |
| `Makefile` present, no markers, collisions | § 3.6 | one `Error: Makefile:<line> defines '<target>' with a recipe; the managed block owns it — move the repo's own steps to another target or delete the rule` per collision | 1 | summary line, then the same lines, exit 1 |
| Markers present, current | `merged == original` (`seed.py:407`) | none | 0 | `Dry run — no files modified.` |
| Markers present, stale | `merged != original` | none; the section text is replaced | 0 | `~ Makefile (…)` |
| Begin marker with no end marker | `seed.py:103-111` | `Error: Unclosed marker 'standard-targets' — fix the end marker before running punt seed` | 1 | same |
| End marker with no begin marker | `parse_segments` treats it as local text | none; the stray line is kept as local content and the blocks are appended | 0 | `~ Makefile (+N lines)` |
| Begin and end ids differ (`begin standard-targets` … `end help`) | the end marker never matches `current_id` (`seed.py:97-99`), so the block is unclosed | the unclosed-marker error | 1 | same |
| `Makefile` unreadable (not UTF-8, permission) | `TextFile.read` raises `ReleaseError`, caught at `seed.py:350-353` | `Error: <TextFile's message naming the file>` | 1 | same |
| Write fails (read-only tree) | `TextFile.write` raises `ReleaseError`, same handler | `Error: <message>` | 1 | not reached |

Two rows are new behavior the implementation must add: the two language
errors and the collision rows. The others are the existing contract, listed
so the table is complete.

---

## 7. Tests

All in `tests/test_seed.py` unless named otherwise; each is a plain pytest
function or method on the existing classes, `tmp_path`-based, no mocking of
the filesystem. A Go fixture is `go.mod` with `module example.com/x` and
`go 1.26` plus `cmd/<name>/main.go` files as the case needs.

**Rendering, one snapshot per language.**

- `test_render_go_standard_targets_snapshot`: `render_section("standard-targets", "makefile/go.mk.j2", {"binaries": ["mcp-proxy"]}, "makefile")` equals the § 4.1 text byte for byte, read from `tests/fixtures/seed/go-standard-targets.mk`. The fixture is the § 4.1 block and the standard's template at once; a change to one is a change to both.
- `test_render_python_standard_targets_unchanged`: rendering `python.mk.j2` with the new context `{"binaries": []}` equals rendering it with `{}`; the Python block is byte-identical before and after the context change.
- `test_render_go_build_one_line_per_binary`: `binaries=["a", "b"]` renders two `go build` lines in that order and `rm -f a b coverage.out`.
- `test_render_go_library_module`: `binaries=[]` renders `go build ./...` and `rm -f coverage.out`.
- `test_standard_targets_template` (existing, l. 220-229) is kept as the Python counterpart.

**The explicit-error path** (replaces `test_seed_makefile_skips_non_python`, l. 360-366).

- `test_seed_makefile_refuses_undetected_language`: a `README.md`-only directory; `run_seed` raises `SystemExit(1)`, no `Makefile` is created, and the captured output contains `no language detected`.
- `test_seed_makefile_refuses_language_without_template`: a `package.json` directory; `SystemExit(1)`, output contains `no Makefile template for language 'node'` and `templates exist for: go, python`.
- `test_seed_makefile_dry_run_refuses_the_same_way`: both of the above with `dry_run=True` exit 1 and write nothing.

**The detect mapping** (`tests/test_detect.py`).

- `test_detect_go` (existing, l. 48-55), `test_detect_go_hybrid` (l. 189-204), and `test_detect_go_no_cmd_dir` (l. 207-215) already pin `language == "go"` and `cli_commands`. One addition: `test_detect_go_cli_commands_sorted_and_main_go_only`: `cmd/b/main.go`, `cmd/a/main.go`, and `cmd/c/helper.go` give `["a", "b"]`.

**Seeding a Go repo end to end.**

- `test_seed_makefile_go_creates_both_sections`: a Go fixture with one binary; after `run_seed`, the `Makefile` contains both marker pairs, `go test -race -count=1 ./...`, and `-o x ./cmd/x/`; the returned list is `["Makefile"]`.
- `test_seed_makefile_go_idempotent`: a second run returns `[]` and the file is byte-identical.
- `test_seed_makefile_go_dry_run_writes_nothing`: `dry_run=True` on the fixture; no `Makefile`.

**The marker-merge round trip on mcp-proxy's real Makefile.**

- `tests/fixtures/seed/mcp-proxy.Makefile` is a copy of `mcp-proxy/Makefile` at its 2026-08-29 commit (54 lines), checked in with its hard tabs.
- `test_seed_go_collisions_on_a_real_makefile`: copy the fixture into a Go fixture directory as `Makefile`; `run_seed` exits 1 and the output names each of `help`, `lint`, `vulncheck`, `test`, `check`, `format`, `build`, and `clean` with its line number (`Makefile:7`, `Makefile:10`, …), does not name `lint-strict` (not a block target), and the file is unchanged.
- `test_seed_go_round_trip_on_a_real_makefile`: the same copy with those recipes removed and `check: docs` added (the § 5.1 rollout shape, checked in as `tests/fixtures/seed/mcp-proxy.trimmed.Makefile`); `run_seed` writes the file; assert the local lines `docs:`, `test-e2e:`, `install:`, `dist:`, `cover:`, `VERSION ?= dev`, and `LDFLAGS_DIST` are all still present verbatim, in their original order, that both blocks follow them, and that a second `run_seed` is a no-op. Then edit the managed block's `GOVULNCHECK_VERSION` line in the file, run again, and assert the block is restored and the local lines are still untouched.
- `test_merged_check_prerequisites`: run `make -n check` (`subprocess`, skipped when `make` is not on `PATH`) on the round-trip output and assert the dry-run command list contains the `docs` recipe's `markdownlint-cli2` line before the block's `golangci-lint` lines.

**Collision detection, unit level.**

- `test_collision_rule_with_recipe`: `lint:\n\tgo vet ./...\n` is a collision.
- `test_collision_prerequisite_only_is_not`: `check: docs\n` is not.
- `test_collision_phony_is_not`: `.PHONY: lint test\n` is not.
- `test_collision_inside_managed_block_is_not`: a stale managed block that defines `lint` is replaced, not reported.

**Failure table rows not covered above.**

- `test_seed_makefile_end_marker_without_begin_is_local`, `test_seed_makefile_mismatched_marker_ids_is_unclosed`, and the existing `test_unclosed_marker_raises` (l. 83-86) and `test_seed_makefile_updates_managed_preserves_local` (l. 334-351).

The assertion count goes up by the number of tests above; `make check`
runs them all.

---

## 8. Operator decisions

Each is numbered, carries a recommendation, and is ratified by "proceed as
designed" or amended before the implementation contract is written.

1. **Prebuilt golangci-lint release binary, not `go install`, and amend
   `standards/makefile.md:73-119` in the same PR.** Recommend: yes. The
   `go.md` rule (`standards/go.md:329-383`) is already the standard and
   records the observed gofmt split; the Makefile template is the one place
   on `origin/main` that still says `go install`, and a standard must not
   describe a rejected practice. PL-964 closes when the six rollout PRs
   merge.
2. **`vet` and `staticcheck` fold into golangci-lint; no separate
   targets.** Recommend: fold. Every `.golangci.yml` in the fleet enables
   `govet` and `staticcheck`; a standalone `go run staticcheck@<tag>`
   compiles against the host toolchain and is the export-data crash beadle
   pinned `GOTOOLCHAIN` for. One binary, one pin, one gate.
3. **`vulncheck` is in `check`.** Recommend: yes, as `go run
   golang.org/x/vuln/cmd/govulncheck@$(GOVULNCHECK_VERSION) ./...`. It is
   in `check` on the two most recently edited Go Makefiles (beadle,
   mcp-proxy) and in points's CI; the standard's security ordering puts a
   known-vulnerable dependency above every other finding. The cost is one
   module download per run and a network dependency inside `make check`; a
   repo that must run `check` offline (agent-image's `check-offline`
   pattern) sets `GOFLAGS=-mod=mod` aside and that is its own override. The
   alternative, a separate `security` target outside `check`, leaves the
   scan to CI only, which for cryptd and circuit means no scan at all.
4. **biff is out of scope.** Recommend: yes. `detect` classes it `python`
   (`detect.py:115-120` runs before `132-135`); it has no `go.mod`; it
   already receives `python.mk.j2`. Its one `check` extra (`mdlint`) is the
   § 5.2 pattern and is a separate T4 in biff's own funnel if the leader
   wants it.
5. **A repo extends `check` with a prerequisite-only `check: <extras>`
   rule outside the block.** Recommend: yes, over `check-standard` and over
   a `CHECK_EXTRA` variable (§ 5.2 gives both rejections). It is
   plain Make, needs no new name, and `make -n check` shows the merged list.
6. **The standard's "Template: Go projects" section is replaced by the
   rendered block verbatim.** Recommend: yes. One source: the Jinja
   template renders the block, a snapshot test pins the rendering to the
   fixture, and the standard shows the fixture. A standard that paraphrases
   the template drifts from it the next time either changes.
7. **Ship order: the Python-only guard change ships with the Go template,
   in one PR.** Recommend: one PR. The guard's replacement (§ 3.5) and the
   per-language registry (§ 3.3) are the same edit to `_seed_file`; a Go
   template without the registry has nowhere to register, and a registry
   without a second language is an untested refactor. The PR is the
   template, the registry, the two error paths, the collision rule, and the
   tests; the standard amendment is the second PR (§ 10); the six rollouts
   are the third wave.
8. **The block's `tools` drops ethos's GitHub-API fallback route and
   system-directory refusal.** Recommend: drop both. The fallback needs
   `jq` and doubles the recipe; the release CDN with five retries is what
   `golangci-lint-action` itself uses. A repo that has hit the CDN outage
   keeps the longer recipe as a local `tools` and takes the collision rule
   (ethos is not in the rollout set). The system-directory case cannot
   arise from `go env`.
9. **Collisions refuse the write (exit 1) rather than warn and append.**
   Recommend: refuse. Appending produces a Makefile that prints
   `warning: overriding recipe` on every `make` and silently runs the
   block's recipe instead of the repo's; a refusal that names each line is
   the rollout checklist. The cost is that first adoption is never a single
   `punt seed makefile` run on any of the five repos; § 5.1 is that
   procedure.
10. **`help.mk.j2`'s `.DEFAULT_GOAL := help` overrides points's and
    cryptd's `all` default.** Recommend: accept the override. A bare `make`
    printing the target list is the `makefile.md` discoverability
    rationale (`standards/makefile.md:9-12`); `make all` still runs
    `build check` in both repos. If the leader wants `all` kept as the
    default in those two, the repo places `.DEFAULT_GOAL := all` after the
    `# punt:end help` marker and the last assignment wins (§ 4.4).
11. **golangci-lint pin v2.13.1, govulncheck pin v1.7.0, in the template.**
    Recommend: those values. v2.13.1 is the newest deployed (points, ethos);
    v1.7.0 is the newest deployed (beadle, mcp-proxy). A bump is one edit to
    `go.mk.j2` and one `punt seed makefile` per repo, which is the point of
    a managed block.

---

## 9. `DESIGN.md` ADR draft

To be appended to `DESIGN.md` by the leader when the implementation PR
opens; numbered after DES-040, which
[audit-findings-and-examiner.md](audit-findings-and-examiner.md) claims.

## DES-041: `punt seed makefile` Renders a Per-Language Block, and Go Is the Second Language

**Context.** `punt seed makefile` managed two sections, `standard-targets`
and `help`, for Python repos only. The section registry was one flat list
bound to `python.mk.j2`, and `_seed_file` returned silently with exit 0 for
every other language. The six Go repos in the fleet had hand-rolled standard
targets with four golangci-lint install methods, three lint tool chains, and
no marker a tool could audit. `standards/makefile.md`'s Go template
prescribed `go install` for golangci-lint while `standards/go.md` forbade it.

**Decision.** `MAKEFILE_SECTIONS` is a mapping from `info.language` to an
ordered section list; `go` maps to `makefile/go.mk.j2` plus the shared
`help.mk.j2`. A language with no entry, or no detected language, is a
one-line `Error:` and exit 1, never a skip. The Go block owns `check`,
`lint`, `test`, `vulncheck`, `format`, `build`, `clean`, and `tools`;
`lint` runs the pinned golangci-lint from `$(GOBIN)` and refuses an absent
or wrong-version binary; `tools` installs the official release artifact
after verifying it against the release checksums; `build` renders one line
per `cmd/<name>/main.go` from `info.cli_commands`. A local recipe for a
block-owned target is a collision that refuses the write and names the
line. A repo extends `check` with a prerequisite-only rule outside the
block. `standards/makefile.md`'s Go template is the rendered block verbatim.

**Rejected.**

- *Keep the silent skip and add Go as a special case.* Leaves `node` and
  `swift` silent and the registry flat; the next language repeats the bug.
- *`go install` for golangci-lint, as the old template had it.* The
  compile-from-source artifact disagrees with CI's release binary on gofmt
  under one version label; `standards/go.md` § 7 records the observed
  failure.
- *Separate `vet` and `staticcheck` targets.* The same analyzers run inside
  golangci-lint from one pinned binary; the standalone `go run` form is the
  export-data crash beadle pinned `GOTOOLCHAIN` around.
- *`check-standard` or a `CHECK_EXTRA` variable for extension.* Renames the
  target every CI calls, or hides the prerequisite list behind an
  order-sensitive variable; a second `check:` rule line is plain Make.
- *Append on collision and let `make` warn.* The warning fires on every
  invocation and the block's recipe silently replaces the repo's.
- *A `prfaq` section in the same design.* The recipe is the prfaq tool's;
  PL-506 canceled; operator direction 2026-11-14.

**Consequences.** Every Go repo gets the same eight standard targets from
one template, auditable by marker; a golangci-lint bump is one template
edit and one seed per repo. First adoption on an existing Makefile is a
procedure, not one command, because the collision rule refuses until the
hand-rolled recipes move. `make check` in a Go repo needs the network once
for `make tools` and once per run for govulncheck's module download. The
`help` recipe is the shared one; cryptd's `##@` section headers stop
rendering.

---

## 10. Implementation write-set and wave plan

Three waves. The first gates the other two and is one PR in punt-kit; the
second and third run in parallel once it merges, in their own worktrees.

### Wave 1: the template, the registry, the guard, the collision rule, the tests (punt-kit, one PR)

Worker `rmh`, evaluator `adb` (Python in punt-kit, per the
`punt-kit/CLAUDE.md` table). T2, `budget.minutes` 180, first commit within
30 minutes. The first commit is the smallest user-visible change with its
test: `go.mk.j2`, the registry entry, and
`test_seed_makefile_go_creates_both_sections`.

| Path | Change |
|---|---|
| `src/punt_kit/templates/seed/makefile/go.mk.j2` | new; § 4.2 |
| `src/punt_kit/seed.py` | `MAKEFILE_SECTIONS` per language (§ 3.3); `_seed_file` reads the language entry, passes `{"binaries": info.cli_commands}` (§ 3.4), the two errors (§ 3.5), the collision scan (§ 3.6); the `TARGETS` type |
| `src/punt_kit/detect.py` | the `language` comment at l. 47 names `go` |
| `tests/test_seed.py` | § 7: the snapshot, error-path, end-to-end, round-trip, and collision tests; `test_seed_makefile_skips_non_python` replaced |
| `tests/test_detect.py` | `test_detect_go_cli_commands_sorted_and_main_go_only` |
| `tests/fixtures/seed/go-standard-targets.mk` | the § 4.1 block, the snapshot |
| `tests/fixtures/seed/mcp-proxy.Makefile`, `tests/fixtures/seed/mcp-proxy.trimmed.Makefile` | the round-trip inputs |
| `CHANGELOG.md` | leader-authored: Added, `punt seed makefile` renders Go; Changed, a non-Python repo without a template is an error |
| `README.md` | leader-authored, if the seed section lists supported languages |
| `DESIGN.md` | leader-authored: DES-041 from § 9 |

Demo: `punt seed makefile --dry-run` from the installed wheel against
`../mcp-proxy` prints the `+72 lines` summary and eight collision lines and
exits 1; against a `tmp` Go module with one binary it writes the file and
`make -n check` lists the three gates; against `../koch-trainer-swift` it
prints the swift error and exits 1.

### Wave 2: the standard amendment (punt-kit, one PR, after wave 1 merges)

Worker `mdm`, evaluator `rop` (standards doc authoring). T3,
`budget.minutes` 60.

| Path | Change |
|---|---|
| `standards/makefile.md` | lines 73-119 replaced by the wave-1 fixture verbatim with `<name>` for the binary, markers kept, one sentence that the block is what `punt seed makefile` renders; the "Go example" column at l. 19-26 unchanged |
| `standards/go.md` | § 7 "Installing golangci-lint" (l. 329-383) gains one sentence pointing at the Makefile standard's block as the rendered form; nothing removed |
| `CHANGELOG.md` | leader-authored |

Docs-only; `qodo review` and markdownlint on `go.md` (`makefile.md` is on
the ignore list); the fleet-reality step is § 2 of this document and the
evaluator checks it ran.

### Wave 3: the five rollout PRs (parallel, after wave 1 merges; wave 2 need not have merged)

Worker `adb`, evaluator `djb` for each (Makefile and CI workflow changes).
T3 each, `budget.minutes` 60, one worktree and branch per repo, filed in
each repo's own funnel with the repo label. Each PR: remove the colliding
recipes and the superseded targets per § 5.1, add the `check:` extension
line, `punt seed makefile`, `make tools`, `make check` green, `make help`
read, CI workflow steps replaced per § 5.3, PR description carries the
actual `--dry-run` output before and the `No changes needed.` after.

| Repo | Extra scope | Blocked on |
|---|---|---|
| mcp-proxy | `lint.yml` three `go run` steps replaced | wave 1; `.envrc` diff moved aside |
| points | `tools-extra` for actionlint and gopls; `security.yml` govulncheck pin or deletion | wave 1; the leader's ruling on the uncommitted `Makefile` and four other files |
| circuit | `format-pi-extension`; `check-engine: test-engine`; `flake.nix` provides curl/tar/sha for `make tools` or installs golangci-lint at the pin | wave 1 |
| cryptd | new `.golangci.yml` from `go.md:306-326`; tree made clean under it; `lint.yml` staticcheck step replaced | wave 1 |
| beadle | `test` renamed `test-provisioned`; `test.yml` and `release.yml:27` call it; `vet`, `staticcheck`, `lint-strict` and their pins deleted | wave 1 |

PL-964 closes when all five merge. ethos and agent-image already run the
prebuilt binary and are not in the set; the leader files a follow-up for
each to adopt the block when its own next Makefile change comes due, since
both have `tools` recipes that collide and both carry local reasons (the
API fallback, the per-checkout `GOBIN`) the block does not.

### Follow-ups for the leader to file in Linear

- biff: `check: mdlint` as the § 5.2 extension line once `python.mk.j2` is
  re-seeded there (T4, repo:biff).
- ethos and agent-image: adopt the Go block on their next Makefile change
  (T3 each, repo:ethos and repo:agent-image).
- `punt audit`: a check that `punt seed makefile --dry-run` reports no
  change, so a drifted managed block is a finding (repo:pkit; depends on
  wave 1 and on the audit-findings design, DES-040).
- koch-trainer-swift and quarry-menubar: a `swift.mk.j2`, or a ruling that
  Swift repos stay unmanaged and the § 3.5 error is their contract
  (repo:pkit).
