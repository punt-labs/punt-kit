---
paths:
  - "**/*.go"
  - "**/go.mod"
---

# Go Project Layout and Modules

Per-file rules distilled from the Punt Labs Go standard
(punt-kit `standards/go.md`).

## Module

- Module path: `github.com/punt-labs/<project>`.
- Track the latest stable Go release in `go.mod`.
- `go.sum` is committed and stays in sync with `go.mod` — run
  `go mod tidy` before every commit that touches dependencies.

## Layout

- `internal/` for everything. Nothing is exported outside the module.
  No `pkg/` directory.
- One binary per `cmd/` subdirectory. `cmd/<binary>/main.go` contains
  only wiring — flag parsing, dependency construction, `os.Exit`.
  No business logic.
- One package per domain concept: `internal/<domain>/`. No `util` or
  `common` dump packages.
- CLI framework code — command trees, flag definitions, output
  formatting — lives in `cmd/`, never in `internal/`.
- Tests mirror source 1:1: `store.go` has `store_test.go`.

## Engine and Clients

One engine, implemented once, never duplicated per surface. The engine
lives under `internal/` with no knowledge of its transport; the CLI,
MCP server, or daemon front door in `cmd/` is a thin client over it.
A capability runs the same `internal/` code no matter which surface
invoked it.

## Version Injection

`main.go` declares the version variable; the build overrides it with
`-ldflags "-X main.version=$(VERSION)"`.

```go
var version = "dev"
```

## Static Analysis

- `go vet` and `staticcheck` run under `make check` with zero warnings.
- `gofmt` (or `gofumpt` as a stricter drop-in) formatting is
  non-negotiable.
- No `//nolint` without a comment explaining why.
- The Makefile is the source of truth for which tools run.

## Secrets

- API keys and credentials come from environment variables only.
- No `.env` files committed, no hardcoded keys.
