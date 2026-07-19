---
paths:
  - "**/*.swift"
  - "**/.swiftformat"
  - "**/.swiftlint.yml"
---

# Formatter and Linter Standards

The formatter and the linter are two different tools with two different jobs,
and every Swift repo uses both. These rules follow
[standards/swift.md](../../standards/swift.md); the canonical settings below
are the consistent configuration across Punt Labs Swift repos.

## SW-TL-1: SwiftFormat Owns Layout

**Statement**: SwiftFormat, configured in `.swiftformat`, owns canonical
formatting, and `make format` rewrites the source to match. The canonical
configuration:

- four-space indent, 120-column max width, no Allman braces, no semicolons
- alphabetized import grouping (`--importgrouping alpha`, `sortedImports`)
- arguments, parameters, and collections wrapped `before-first`
- attributes on the line before the declaration (`--funcattributes`,
  `--typeattributes`, `--varattributes` = `prev-line`)
- redundant `self` removed (`--self remove`)
- declaration organization on: `markTypes` and `organizeDeclarations` file a
  type's members under `MARK` sections, so member order is generated, not
  argued about
- generated and vendored trees excluded (`DerivedData`, `.build`, `build`,
  `**/*.generated.swift`)

Layout is never enforced by the linter and never produced by hand — a layout
opinion belongs in `.swiftformat`.

**Criterion**:

- Pass: `.swiftformat` carries the canonical settings; `make format` is a
  no-op on committed code
- Fail: hand-maintained layout diverging from the formatter; layout rules
  smuggled into `.swiftlint.yml`

**Tooling**:

- `make format` applies; `make build` depends on it (SW-PJ-3), so unformatted
  code cannot compile into a change

## SW-TL-2: SwiftLint Owns Correctness and Smell

**Statement**: SwiftLint, configured in `.swiftlint.yml`, owns the rules about
correctness and smell rather than layout. `trailing_whitespace` and
`line_length` are disabled — SwiftFormat owns layout (SW-TL-1). Alongside the
default rules, the configuration opts in to at minimum:

`closure_spacing`, `contains_over_filter_is_empty`,
`discouraged_object_literal`, `empty_collection_literal`, `empty_count`,
`empty_string`, `fatal_error_message`, `first_where`, `force_unwrapping`,
`implicitly_unwrapped_optional`, `last_where`, `modifier_order`,
`overridden_super_call`, `redundant_nil_coalescing`,
`redundant_type_annotation`, `unneeded_parentheses_in_closure_argument`

with the canonical size and complexity thresholds:

| Metric | Warning | Error |
|--------|---------|-------|
| `function_body_length` | 60 | 100 |
| `type_body_length` | 400 | 500 |
| `file_length` | 750 | 1000 |
| `cyclomatic_complexity` | 15 | 25 |
| `nesting` | type 2, function 3 | — |

Test targets are covered: only generated and vendored trees are excluded, so
`force_unwrapping` and the rest apply to tests exactly as to production code.

**Criterion**:

- Pass: `.swiftlint.yml` opts in to the list above and carries the canonical
  thresholds; `make lint` reports zero findings
- Fail: a required opt-in rule missing; test directories added to `excluded`;
  a threshold raised to accommodate a growing type

**Tooling**:

- `make lint` runs SwiftLint with no mutations; a violation fails the target
  and therefore the build (SW-PJ-3)

## SW-TL-3: Zero Findings, No Suppressions

**Statement**: A lint finding is fixed in the code, not silenced. No
`// swiftlint:disable` comments, no removing a rule or raising a threshold to
make a finding go away, no lowering the compiler's concurrency checking to
quiet a diagnostic (SW-CC-4). When the formatter and a lint rule genuinely
conflict, reconcile the configurations — adjust `.swiftformat` so the
formatted output satisfies the linter — rather than disabling the lint rule.
If a suppression is ever genuinely necessary, it requires operator approval
before it lands, with the reason written next to it.

**Criterion**:

- Pass: zero `swiftlint:disable` comments in the tree; configuration changes
  loosen nothing without approval
- Fail: an inline disable to ship a finding; a rule deleted in the same PR
  that violates it

**Tooling**:

- Grep: `grep -rn "swiftlint:disable" --include="*.swift" .` — zero hits
- Review: any `.swiftlint.yml` or `.swiftformat` diff that loosens a rule is
  a finding unless the operator approved it
