---
paths:
  - "**/*_test.go"
---

# Go Test Rules

Per-file rules distilled from the Punt Labs Go standard
(punt-kit `standards/go.md`).

## Rules

- `-race -count=1` on every `go test` invocation. The Makefile
  enforces this; do not run tests without the race detector.
- testify: `require` for preconditions that must hold (test aborts on
  failure), `assert` for the actual assertions (test continues to
  report all failures).
- Table-driven tests: a slice of cases with descriptive names, each
  run in a subtest with `t.Run`.
- `t.TempDir()` for filesystem tests. Never write to `/tmp` or the
  working directory.
- `t.Helper()` in every helper that calls `t.Fatal`, `t.Error`, or a
  testify assertion, so failures report the caller's line.
- Tests mirror source 1:1: `store.go` has `store_test.go`.
- A change to a module and the change to its tests are one change,
  not two.

## Table-Driven Pattern

```go
func TestValidation(t *testing.T) {
    s := NewStore(t.TempDir())

    tests := []struct {
        name    string
        key     string
        value   string
        wantErr string
    }{
        {"invalid key uppercase", "INVALID", "val", "must match"},
        {"value too long", "key", string(make([]byte, MaxValueLen+1)), "maximum length"},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            err := s.Set(tt.key, tt.value)
            require.Error(t, err)
            assert.Contains(t, err.Error(), tt.wantErr)
        })
    }
}
```

## Helper Pattern

```go
func setupStore(t *testing.T) *Store {
    t.Helper()
    s := NewStore(t.TempDir())
    require.NoError(t, s.Save(&Identity{Name: "Test", Handle: "test"}))
    return s
}
```
