# Go Standards

Standards for all Punt Labs Go projects. This document is the canonical reference --- individual project CLAUDE.md files should reference it, not duplicate it.

Current Go projects: ethos, beadle-email.

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

When data exists at multiple scopes (repo-local, global), compose single-scope stores into a layered store rather than adding scope logic to the base store.

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

`go vet` and `staticcheck` run as part of `make lint`. Zero warnings. Do not suppress warnings with `//nolint` unless the suppression includes a comment explaining why.

The Makefile `lint` target is the source of truth. See [Makefile standards](makefile.md) for the Go template.

### Installing staticcheck

Pin to a release tag and force the Go toolchain at install time:

```bash
GOTOOLCHAIN=go1.26.1 go install honnef.co/go/tools/cmd/staticcheck@2025.1.1
```

`GOTOOLCHAIN` matters at install time only. Without it, Go's toolchain directive in the consumer module can trigger an auto-switch that tries to compile the pinned staticcheck release under a toolchain it was not cut against — the symptom is a `go install` failure or an internal compiler error when running `staticcheck ./...` afterward, and the failure is quiet enough to be mistaken for a project bug. Once installed to `~/go/bin/staticcheck`, the binary runs clean against projects on any toolchain.

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
