# Go Standards

Standards for all Punt Labs Go projects. This document is the canonical
reference --- individual project CLAUDE.md files should reference it, not
duplicate it.

Current Go projects: cryptd, ethos, beadle-email.

Go is idiomatic in its own paradigm. It is a language of composition, of small
interfaces satisfied structurally, and of explicit error handling, and we write
it that way. It is not object-oriented, so it does not answer to [oo.md](oo.md);
nothing in this document asks Go to imitate objects. Where a Go type carries
behavior, it does so through methods on a concrete struct that satisfies an
interface the consumer defines, not by inheriting from a base class --- Go has no
base classes to inherit from, and embedding is composition, not a subclass
relation.

---

## Where Go Fits the Architecture

The [Projection Model](architecture.md#the-projection-model-canonical) describes
a Punt Labs product as one engine fronted by thin library, CLI, MCP, and REST
clients. Go usually enters that picture as the engine itself. Where a C program
is often a whole self-contained binary, and a Python package realizes the four
surfaces in one process, a Go product is typically the engine that grows those
client surfaces over time, or the daemon that engine becomes once its clients
contend for shared state.

cryptd is that engine as a daemon. Its game logic lives in `internal/engine` as
pure Go with no knowledge of a socket, and `internal/daemon` is the front door:
`cryptd serve` listens on a Unix socket or TCP, speaks JSON-RPC, and holds
session and game state authoritatively behind a mutex. The `crypt` binary is the
thin client --- a terminal UI under `cmd/crypt/tui` and an MCP surface in
`cmd/crypt/mcp.go` --- and it reaches the engine only through the daemon, never
by importing the engine directly. One engine, decomposed into a daemon that owns
state and clients that render it, is exactly the decomposition architecture.md
allows: two processes, one engine, complementary jobs.

ethos is the same model with the daemon deferred. It is a Go tool whose engine
lives under `internal/` --- `internal/identity`, `internal/attribute`,
`internal/mission` --- and whose surfaces are the `ethos` CLI in `cmd/ethos` and
an MCP server that `ethos serve` starts over stdio. ethos keeps its state as YAML
on disk with no concurrent writers, so it has no daemon today; architecture.md
names it as the example of a tool that defers its daemon until scale demands one.
Because its CLI and its MCP surface already sit as thin clients over a clean
`internal/` engine boundary, adding that daemon later is a deployment change, not
a rewrite.

Read the invariants in architecture.md before deciding how they apply. The one
that always governs a Go project is the first: one engine, implemented once,
never duplicated per surface. A capability runs the same `internal/` code
whether it arrived from the CLI, from the MCP server, or --- in cryptd --- from a
networked client across the socket.

---

## 1. Version Policy

- **Go 1.24+**. Track the latest stable release. Update `go.mod` when a new minor version ships.
- Module path: `github.com/punt-labs/<project>`.
- `go.sum` is committed. `go.mod` and `go.sum` stay in sync --- run `go mod tidy` before every commit that touches dependencies.
- Pin tool versions as prescribed in the [Makefile standards](makefile.md).

## 2. Module Layout

```text
<project>/
  cmd/<binary>/
    main.go               # Entry point: flag parsing, version injection, os.Exit
  internal/<domain>/
    <domain>.go            # Types, constructors, core logic
    <domain>_test.go       # Tests mirror source 1:1
    store.go               # Filesystem or DB persistence (if applicable)
    ...
  Makefile                 # Build, lint, test (see makefile.md)
  go.mod
  go.sum
  CLAUDE.md                # Project-specific instructions (references this doc)
  CHANGELOG.md
  README.md
  DESIGN.md                # ADRs
  .beads/                  # Issue tracking
```

### Rules

1. **`internal/` for everything.** Nothing is exported outside the module. No `pkg/` directory.
2. **One binary per `cmd/` subdirectory.** `cmd/<binary>/main.go` contains only wiring --- flag parsing, dependency construction, `os.Exit`. No business logic.
3. **One package per domain concept.** `internal/identity/`, `internal/session/`, `internal/attribute/`. Do not dump unrelated types into a `util` or `common` package.
4. **CLI framework lives in `cmd/`.** Cobra command trees, flag definitions, and output formatting belong in `cmd/`. See [CLI standards](cli.md) for Cobra patterns.

## 3. Package Design

### Functional options

Use functional options for configurable constructors and methods. The option type is an unexported struct; the option functions are exported.

```go
// LoadOption configures Load behavior.
type LoadOption func(*loadConfig)

type loadConfig struct {
    reference bool
}

// Reference returns a LoadOption that skips attribute content resolution.
func Reference(v bool) LoadOption {
    return func(c *loadConfig) { c.reference = v }
}

func (s *Store) Load(handle string, opts ...LoadOption) (*Identity, error) {
    var cfg loadConfig
    for _, o := range opts {
        o(&cfg)
    }
    // ...
}
```

### ValidationError

Domain validation errors carry structured field information. Callers can inspect which field failed without parsing strings.

```go
// ValidationError reports a field-level validation failure.
type ValidationError struct {
    Field   string
    Message string
}

func (e *ValidationError) Error() string {
    return fmt.Sprintf("%s: %s", e.Field, e.Message)
}
```

Return `*ValidationError` from validation functions. Callers use `errors.As` to extract field details.

### Layered stores

When data exists at multiple scopes (repo-local, global), compose single-scope stores into a layered store rather than adding scope logic to the base store. This is composition, not inheritance: the layered store holds the single-scope stores as fields and delegates to them; it does not extend a base store. ethos does exactly this in `internal/attribute/layered.go`, where a layered attribute store fronts a repo-local store and a global store.

```go
type LayeredStore struct {
    repo   *Store  // repo-local scope (read-only for some ops)
    global *Store  // global scope (writable)
}
```

The layered store delegates to the appropriate single-scope store. The single-scope store has no knowledge of layers.

### Path safety

Any function that builds filesystem paths from user input must call `filepath.Base` to prevent path traversal.

```go
func (s *Store) Path(handle string) string {
    return filepath.Join(s.identitiesDir(), filepath.Base(handle)+".yaml")
}
```

This is not optional. Every path-building function that accepts external input uses `filepath.Base`.

## 4. Interfaces

### Rules

1. **Small interfaces.** 1--5 methods is normal. If an interface has more than 5 methods, it probably combines two concerns.
2. **Define where consumed, not where implemented.** The consumer package declares the interface it needs. The implementing package does not import the consumer.
3. **Compile-time interface checks are mandatory.** Every concrete type that implements an interface must have a `var _` assertion at package scope.

```go
// IdentityStore defines the contract for identity storage operations.
type IdentityStore interface {
    Load(handle string, opts ...LoadOption) (*Identity, error)
    Save(id *Identity) error
    List() (*ListResult, error)
    Exists(handle string) bool
}

// Compile-time check: *Store satisfies IdentityStore.
var _ IdentityStore = (*Store)(nil)
```

1. **Accept interfaces, return structs.** Functions take interface parameters when they need polymorphism. They return concrete types so callers get the full API.

## 5. Error Handling

### Rules

1. **Errors are values, not strings.** Use `fmt.Errorf` with `%w` to wrap errors with context at every call site.

```go
data, err := os.ReadFile(path)
if err != nil {
    return nil, fmt.Errorf("identity %q not found: %w", handle, err)
}
```

1. **Every error is handled at the call site.** No ignored return values. No `_ = doThing()`.
1. **No panics in library code.** Panics are for programmer bugs (violated invariants) in `main` or test helpers only.
1. **Structured errors for domain failures.** Use typed errors (`*ValidationError`, `*NotFoundError`) when callers need to distinguish failure modes. Use `errors.As` and `errors.Is` for inspection.
1. **Wrap with context, not repetition.** `"creating identity directory: %w"` adds information. `"error creating identity directory: %w"` adds the word "error" to an error --- do not do this.

### Error wrapping pattern

```go
if err := os.MkdirAll(dir, 0o700); err != nil {
    return fmt.Errorf("creating identity directory: %w", err)
}
```

The context describes the operation that failed, not the error itself. The wrapped error carries the details.

## 6. Testing

Tests run through the Go toolchain and are wired into `make check` as the gate. cryptd's `make test` is `go test -race -count=1 ./...` and its `make check` chains `vet test lint markdownlint`; ethos's `make test` adds a coverage profile and its `make check` chains `lint docs test validate-content`. Both run the race detector on every invocation, and both treat a change to a module and the change to its tests as one change, not two.

### Rules

1. **`-race -count=1` mandatory.** Every `go test` invocation uses both flags. The Makefile enforces this.
2. **testify/assert and testify/require.** `require` for preconditions that must hold (test aborts on failure). `assert` for the actual assertions (test continues to report all failures).
3. **Table-driven tests.** Use a slice of test cases with descriptive names. Run each case in a subtest with `t.Run`.
4. **`t.TempDir()` for filesystem tests.** Never write to `/tmp` or the working directory. `t.TempDir()` is automatically cleaned up.
5. **`t.Helper()` in test helpers.** Every helper function that calls `t.Fatal`, `t.Error`, or testify assertions must call `t.Helper()` so failure messages report the caller's line.
6. **Tests mirror source 1:1.** `store.go` has `store_test.go`. `ext.go` has `ext_test.go`.

### Table-driven test pattern

```go
func TestExtValidation(t *testing.T) {
    s := NewStore(t.TempDir())
    require.NoError(t, s.Save(&Identity{Name: "Test", Handle: "test", Kind: "human"}))

    tests := []struct {
        name      string
        namespace string
        key       string
        value     string
        wantErr   string
    }{
        {"invalid namespace uppercase", "INVALID", "key", "val", "must match"},
        {"invalid namespace leading dash", "-bad", "key", "val", "must match"},
        {"invalid key uppercase", "beadle", "INVALID", "val", "must match"},
        {"value too long", "beadle", "key", string(make([]byte, MaxValueLen+1)), "maximum length"},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            err := s.ExtSet("test", tt.namespace, tt.key, tt.value)
            require.Error(t, err)
            assert.Contains(t, err.Error(), tt.wantErr)
        })
    }
}
```

### Test helper pattern

```go
func setupExtTest(t *testing.T) *Store {
    t.Helper()
    s := NewStore(t.TempDir())
    require.NoError(t, s.Save(&Identity{Name: "Test", Handle: "test", Kind: "human"}))
    return s
}
```

## 7. Static Analysis

| Tool | Purpose | Required? |
|------|---------|-----------|
| `go vet` | Built-in correctness checks | Yes |
| `staticcheck` | Extended static analysis | Yes |
| `gofmt` / `gofumpt` | Canonical formatting (`make format`) | Yes (non-negotiable; projects may use `gofumpt` as a stricter drop-in) |
| `shellcheck` | Shell script linting | Yes (if project has `.sh` files) |

`go vet` and `staticcheck` both run under `make check` with zero warnings. The two projects wire them slightly differently --- cryptd runs `go vet ./...` as its own `vet` target and `staticcheck ./...` as `lint`, while ethos bundles `go vet`, `staticcheck`, and `shellcheck` into a single `lint` target --- but in both, `make check` will not pass while either tool reports anything. Do not suppress warnings with `//nolint` unless the suppression includes a comment explaining why.

The Makefile is the source of truth for which tools run. See [Makefile standards](makefile.md) for the Go template.

### Installing staticcheck

Pin to a release tag and force the Go toolchain at install time:

```bash
GOTOOLCHAIN=go1.26.1 go install honnef.co/go/tools/cmd/staticcheck@2025.1.1
```

`GOTOOLCHAIN` matters at install time only. Without it, Go's toolchain directive in the consumer module can trigger an auto-switch that tries to compile the pinned staticcheck release under a toolchain it was not cut against — the symptom is a `go install` failure or an internal compiler error when running `staticcheck ./...` afterward, and the failure is quiet enough to be mistaken for a project bug. Once installed to `$GOBIN/staticcheck` (or `$(go env GOPATH)/bin/staticcheck` when `GOBIN` is unset), the binary runs clean against projects on any toolchain.

Reference: bead `punt-t0j`.

## 8. Concurrency

### Rules

1. **flock for filesystem concurrency.** When multiple processes may read/write the same file, use advisory file locking (`syscall.Flock`). Write to a temp file, then `os.Rename` for atomic replacement.

```go
func (s *Store) Update(handle string, mutate func(*Identity) error) error {
    path := s.Path(handle)
    lockPath := path + ".lock"

    lockFile, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, 0o600)
    if err != nil {
        return fmt.Errorf("creating lock file: %w", err)
    }
    defer lockFile.Close()
    if err := flock(lockFile); err != nil {
        return fmt.Errorf("acquiring lock: %w", err)
    }
    defer funlock(lockFile)

    // Read, mutate, validate, write-to-tmp, rename.
    // ...
}
```

1. **`sync.Once` for lazy initialization.** When a value is computed once and read many times, use `sync.Once`. Do not use `init()` for this.
1. **No goroutines in CLI commands unless required.** CLI tools are sequential by nature. Do not add concurrency for the sake of it. When goroutines are needed (e.g., watching multiple files), use `errgroup` for lifecycle management.
1. **Channels for communication, mutexes for state.** Do not use channels as mutexes or mutexes as signals.

### Context propagation

A `context.Context` is the first argument of any function that does I/O, blocks, or spans goroutines, and it is threaded from the entry point down --- never stored in a struct field, never replaced by a package-level `context.Background()` deep in the call tree. The context carries cancellation and deadlines, so a caller that gives up can stop the work it started.

cryptd shows both halves of the discipline. Its daemon holds a server-scoped `context.Context` and matching `cancel` that bound the lifetime of every game goroutine it spawns, so shutting the server down cancels the work in flight. At the leaf, a call that must not block forever wraps the parent context with a deadline and cancels it as soon as the call returns:

```go
probeCtx, probeCancel := context.WithTimeout(context.Background(), 5*time.Second)
_, probeErr := client.ChatCompletion(probeCtx, msgs, opts)
probeCancel()
```

The `cancel` function is always called, on every path, to release the timer the context allocates --- deferring it or calling it inline both satisfy the rule; leaking it does not.

## 9. Style

### Package comments

Every package has a doc comment in a `doc.go` file or at the top of the primary `.go` file.

```go
// Package identity provides CRUD operations for ethos identities.
// Identities are YAML files stored in a known filesystem layout.
package identity
```

### Struct tags

Use `yaml` and `json` tags with `omitempty` for optional fields. Tag order: `yaml`, then `json`.

```go
type Identity struct {
    Name         string   `yaml:"name" json:"name"`
    Handle       string   `yaml:"handle" json:"handle"`
    Kind         string   `yaml:"kind" json:"kind"`
    Email        string   `yaml:"email,omitempty" json:"email,omitempty"`
    GitHub       string   `yaml:"github,omitempty" json:"github,omitempty"`
    Talents      []string `yaml:"talents,omitempty" json:"talents,omitempty"`
}
```

### Import grouping

Three groups, separated by blank lines: stdlib, third-party, local.

```go
import (
    "fmt"
    "os"
    "path/filepath"

    "gopkg.in/yaml.v3"

    "github.com/punt-labs/ethos/internal/attribute"
)
```

### Naming

- **Short names for locals**: `s` for store, `id` for identity, `m` for map, `f` for file.
- **Descriptive names for exports**: `NewStore`, `LoadOption`, `ValidationError`.
- **No stuttering**: `identity.Store`, not `identity.IdentityStore` (exception: interface names that would collide).
- **Acronyms are all-caps**: `ID`, `HTTP`, `URL`, `MCP`. Not `Id`, `Http`, `Url`.

### Constants and validation

Group related constants with a `const` block. Compile regex patterns at package scope with `var`.

```go
const (
    MaxNamespaceLen    = 32
    MaxKeyLen          = 64
    MaxValueLen        = 4096
)

var validNamespace = regexp.MustCompile(`^[a-z][a-z0-9-]*$`)
```

### File permissions

- Directories: `0o700`
- Files with sensitive content: `0o600`
- Use `os.O_WRONLY|os.O_CREATE|os.O_EXCL` for atomic create (fail if exists).

## 10. Prohibited Patterns

| Pattern | Why | Use instead |
|---------|-----|-------------|
| `any` or `interface{}` | Defeats static typing | Concrete types, generics, or small interfaces |
| `panic()` in library code | Crashes the program | Return an error |
| `init()` outside `cmd/` | Hidden side effects, untestable | Explicit initialization in `main` or constructors |
| `log.Fatal` outside `main` | Calls `os.Exit`, skips defers | Return an error to the caller |
| `os.Exit` outside `main` | Same as above | Return an error to the caller |
| Suppressed errors (`_ = f()`) | Hides failures | Handle or wrap the error |
| `//nolint` without explanation | Hides the reasoning | Add a comment explaining why |
| Global mutable state | Races, test pollution | Pass dependencies explicitly |
| `pkg/` directory | Punt Labs convention is `internal/` only | `internal/<domain>/` |

## 11. Cross-Compilation

All Go projects produce static binaries. The standard build matrix:

| OS | Arch | Binary suffix |
|----|------|---------------|
| darwin | arm64 | `<name>-darwin-arm64` |
| darwin | amd64 | `<name>-darwin-amd64` |
| linux | arm64 | `<name>-linux-arm64` |
| linux | amd64 | `<name>-linux-amd64` |

### Build flags

```makefile
VERSION := $(or $(shell git describe --tags --always 2>/dev/null | sed 's/^v//'),dev)
LDFLAGS := -X main.version=$(VERSION)

build: ## Build binary
    CGO_ENABLED=0 go build -ldflags="$(LDFLAGS)" -o <name> ./cmd/<name>/

dist: clean ## Cross-compile for all platforms
    mkdir -p dist
    CGO_ENABLED=0 GOOS=darwin  GOARCH=arm64 go build -ldflags="-s -w $(LDFLAGS)" -o dist/<name>-darwin-arm64 ./cmd/<name>/
    CGO_ENABLED=0 GOOS=darwin  GOARCH=amd64 go build -ldflags="-s -w $(LDFLAGS)" -o dist/<name>-darwin-amd64 ./cmd/<name>/
    CGO_ENABLED=0 GOOS=linux   GOARCH=arm64 go build -ldflags="-s -w $(LDFLAGS)" -o dist/<name>-linux-arm64  ./cmd/<name>/
    CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -ldflags="-s -w $(LDFLAGS)" -o dist/<name>-linux-amd64  ./cmd/<name>/
```

### Rules

1. **`CGO_ENABLED=0` always.** Static binaries with no system library dependencies.
2. **`-ldflags "-X main.version=$(VERSION)"`** for version injection. The `main` package declares `var version = "dev"` and the build overrides it.
3. **`-s -w` for release builds only.** Strips debug info and symbol tables. Development builds keep them for debugging.
4. **Version variable in `main.go`:**

```go
var version = "dev"

func main() {
    // Pass version to Cobra root command or print it directly.
}
```

## Distribution

Go binaries install to `~/.local/bin`. No package manager needed for consumers.

- **Development**: `make install` copies the binary to `~/.local/bin/<name>`.
- **Release**: `make dist` cross-compiles. Binaries are attached to GitHub releases.
- **Install script**: `install.sh` downloads the correct binary for the platform and places it in `~/.local/bin`.

See [CLI standards](cli.md) for naming conventions and [Makefile standards](makefile.md) for build targets.

## Secrets

- API keys and credentials from environment variables only.
- No `.env` files committed, no hardcoded keys.
- `doctor` verifies required secrets are available without printing them.

## Enforcement

Go carries its coding rules as `.claude/rules/go-*.md` files, the same mechanism the other languages use, loaded by an ancestor walk when an agent touches a matching file. These rules are the Go analog of the Python rules under `.claude/rules/python-*.md` and the C rules xboing-c holds under its own `.claude/rules/`. They are the intended home for the naming, layout, interface-placement, error-wrapping, concurrency, and prohibited-pattern conventions this document describes, and a change to Go must satisfy them the way a change to Python must satisfy its own.

Go has no OO ratchet. The ratchet that scores object-oriented quality against a committed baseline is a Python mechanism, described in [python.md](python.md), and it exists because LLM-generated Python drifts toward procedural code that only looks object-oriented. Go is not object-oriented, so there is nothing for such a ratchet to measure --- it has no class hierarchy to score, no baseline of encapsulation to hold. What holds Go to its standard is the combination the sections above describe: `go vet` and `staticcheck` reporting zero warnings, the race detector on every `go test` run, the table-driven test suite, and the `.claude/rules/go-*.md` files --- all run together by `make check`, in cryptd and ethos alike, before a change ships.
