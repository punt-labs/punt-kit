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
  inside the gate, against `standards/makefile.md:191` ("`lint` never
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

`render_section` is called with an empty context today (`seed.py:398`). It
is called with one context for every language:

```python
context = {"binaries": list(info.cli_commands)}
```

`python.mk.j2` does not reference `binaries`, and Jinja's `StrictUndefined`
(`seed.py:190`) only raises for a name a template reads, so the Python
rendering is byte-identical to today's. `go.mk.j2` reads `binaries` for the
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
