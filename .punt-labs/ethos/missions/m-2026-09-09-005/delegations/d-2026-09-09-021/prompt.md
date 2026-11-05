You have an ethos mission to execute: m-2026-09-09-005 (bead pkit-i48o).

First run `ethos mission show m-2026-09-09-005` and `ethos mission claim m-2026-09-09-005` to load the contract. Then implement it to the letter.

This is a docs-only change to `standards/go.md`, section 7 (Static Analysis, around lines 270–294). The egregiously false golangci-lint claim is already gone; your job is to ADD the missing positive guidance, scoped additively to section 7.

The principle to add: pinning the golangci-lint VERSION NUMBER alone does not guarantee identical formatting verdicts, because golangci-lint's gofmt/gofumpt formatters embed the gofmt implementation of whatever Go toolchain BUILT the binary. Two installs of the same pinned version can therefore disagree on formatting if one side `go install`s a locally-compiled build and the other uses the official prebuilt release. The correct rule: local and CI must run the same prebuilt release artifact — pin the artifact, not just the version. Motivate it with the observed failure mode (file passes local `make check`, CI fails it with "File is not properly formatted (gofmt)").

HARD CONSTRAINT: do NOT prescribe, name, or copy any specific install command or install-mode. A security review of the curl|sh installer mechanism is pending and may change the recommended form. Keep the guidance at the principle level and explicitly note the concrete install form is deferred pending that review.

MANDATORY fleet reality check (per punt-kit CLAUDE.md): before writing, survey the sibling Go repos — `../ethos`, `../cryptd`, `../beadle-email` — for how they currently install golangci-lint in their Makefile `tools` target and CI workflows (grep for golangci-lint install lines; check `git log` recency). Report in your result whether deployed practice already pins the artifact (ethos commit 7da32c6 reportedly switched `make tools` to fetch the official prebuilt release). The standard must generalize the most advanced deployed reality or explicitly supersede it with stated rationale.

markdownlint must pass on go.md. Do NOT touch CHANGELOG.md (leader owns it). You are in an isolated git worktree — do NOT push, do NOT open a PR. Work on branch `fix/pkit-i48o-go-formatter-pin` off main. When done, report: the branch name, commit SHAs, what the fleet reality check found, and the exact prose you added.