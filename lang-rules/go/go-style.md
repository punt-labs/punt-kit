---
paths:
  - "**/*.go"
---

# Go Style Rules

Per-file rules distilled from the Punt Labs Go standard
(punt-kit `standards/go.md`).

## Package Comments

Every package has a doc comment, in `doc.go` or at the top of the
primary `.go` file.

```go
// Package identity provides CRUD operations for identities.
// Identities are YAML files stored in a known filesystem layout.
package identity
```

## Naming

- Short names for locals: `s` for store, `id` for identity, `m` for
  map, `f` for file.
- Descriptive names for exports: `NewStore`, `LoadOption`,
  `ValidationError`.
- No stuttering: `identity.Store`, not `identity.IdentityStore`
  (exception: interface names that would collide).
- Acronyms are all-caps: `ID`, `HTTP`, `URL`, `MCP`. Not `Id`, `Http`,
  `Url`.

## Imports

Three groups, separated by blank lines: stdlib, third-party, local.

```go
import (
    "fmt"
    "path/filepath"

    "gopkg.in/yaml.v3"

    "github.com/punt-labs/<project>/internal/<domain>"
)
```

## Struct Tags

`yaml` and `json` tags with `omitempty` for optional fields. Tag
order: `yaml`, then `json`.

```go
type Identity struct {
    Name   string `yaml:"name" json:"name"`
    Handle string `yaml:"handle" json:"handle"`
    Email  string `yaml:"email,omitempty" json:"email,omitempty"`
}
```

## Constants and Validation

Group related constants in a `const` block. Compile regex patterns at
package scope with `var`.

```go
const (
    MaxKeyLen   = 64
    MaxValueLen = 4096
)

var validNamespace = regexp.MustCompile(`^[a-z][a-z0-9-]*$`)
```

## File Permissions

- Directories: `0o700`.
- Files with sensitive content: `0o600`.
- `os.O_WRONLY|os.O_CREATE|os.O_EXCL` for atomic create (fail if
  exists).

## Prohibited Patterns

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
