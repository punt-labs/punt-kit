---
paths:
  - "**/*.go"
---

# Go Code Rules

Per-file rules distilled from the Punt Labs Go standard
(punt-kit `standards/go.md`). Go is idiomatic in its own paradigm:
composition, small interfaces satisfied structurally, explicit error
handling. Do not import OO-discipline rules from other languages.

## Interfaces

- Small interfaces: 1–5 methods. More than 5 usually combines two
  concerns — split it.
- Define interfaces where consumed, not where implemented. The consumer
  package declares the interface it needs; the implementing package
  does not import the consumer.
- Compile-time interface checks are mandatory for every concrete type
  that implements an interface:

```go
// Compile-time check: *Store satisfies IdentityStore.
var _ IdentityStore = (*Store)(nil)
```

- Accept interfaces, return structs. Take interface parameters when
  polymorphism is needed; return concrete types so callers get the
  full API.

## Error Handling

- Errors are values. Wrap with `fmt.Errorf` and `%w` at every call
  site, adding the operation as context:

```go
if err := os.MkdirAll(dir, 0o700); err != nil {
    return fmt.Errorf("creating identity directory: %w", err)
}
```

- The context describes the operation that failed, not the error
  itself. `"creating identity directory: %w"` adds information;
  `"error creating identity directory: %w"` adds the word "error" to
  an error — do not do this.
- Every error is handled at the call site. No ignored return values,
  no `_ = doThing()`.
- No panics in library code. Panics are for programmer bugs in `main`
  or test helpers only.
- Use typed errors (`*ValidationError`, `*NotFoundError`) when callers
  need to distinguish failure modes; inspect with `errors.Is` and
  `errors.As`. A validation error carries the field that failed, so
  callers never parse strings:

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

## Constructor Options

Use functional options for configurable constructors and methods. The
config struct is unexported; the option functions are exported.

```go
// LoadOption configures Load behavior.
type LoadOption func(*loadConfig)

type loadConfig struct {
    reference bool
}

func (s *Store) Load(handle string, opts ...LoadOption) (*Identity, error) {
    var cfg loadConfig
    for _, o := range opts {
        o(&cfg)
    }
    // ...
}
```

## Composition Over Scope Flags

When data exists at multiple scopes (repo-local, global), compose
single-scope stores into a layered store. The layered store holds the
single-scope stores as fields and delegates; the single-scope store
has no knowledge of layers. Do not add scope flags to the base store.

```go
type LayeredStore struct {
    repo   *Store // repo-local scope
    global *Store // global scope
}
```

## Path Safety

Any function that builds filesystem paths from external input calls
`filepath.Base` to prevent path traversal. Not optional.

```go
func (s *Store) Path(handle string) string {
    return filepath.Join(s.identitiesDir(), filepath.Base(handle)+".yaml")
}
```

## Concurrency

- `context.Context` is the first argument of any function that does
  I/O, blocks, or spans goroutines. Thread it from the entry point
  down. Never store a context in a struct field; never substitute
  `context.Background()` deep in the call tree.
- Always call the `cancel` returned by `context.WithTimeout` or
  `context.WithCancel`, on every path — deferred or inline, never
  leaked.
- Filesystem concurrency: advisory file locking (`flock`) plus
  write-to-temp-then-`os.Rename` for atomic replacement when multiple
  processes may touch the same file.
- `sync.Once` for lazy initialization, not `init()`.
- No goroutines in CLI commands unless required. When goroutines are
  needed, use `errgroup` for lifecycle management.
- Channels for communication, mutexes for state. Do not use channels
  as mutexes or mutexes as signals.
