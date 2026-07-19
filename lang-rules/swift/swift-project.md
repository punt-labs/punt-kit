---
paths:
  - "**/*.swift"
  - "**/project.yml"
  - "**/Package.swift"
---

# Project Structure Standards

An Apple-platform app is built from a generated Xcode project; a library
package is built with SwiftPM. Either way the checked-in source of truth is a
small declarative file, and a `make` wrapper is the interface to the build.
These rules follow [standards/swift.md](../../standards/swift.md).

## SW-PJ-1: XcodeGen Owns the Project File

**Statement**: For an app target, the project structure is declared in
`project.yml` and the `.xcodeproj` is generated from it by XcodeGen. The
project is regenerated, never hand-edited: targets, schemes, build settings,
Info.plist properties, and version numbers all live in the YAML. Editing the
generated project loses the change on the next `make generate` and reopens
the merge conflicts the generator exists to remove.

**Criterion**:

- Pass: every project-level change is a `project.yml` diff; `make generate`
  reproduces the `.xcodeproj` exactly
- Fail: a hand-edit inside the `.xcodeproj`; settings that exist only in the
  generated project

**Tooling**:

- Makefile: `make generate` runs `xcodegen generate`; build targets depend on
  it so a stale project is never compiled
- Review: a `.xcodeproj` diff without a corresponding `project.yml` diff is a
  finding

## SW-PJ-2: Apps Build With `xcodebuild`, Packages With SwiftPM

**Statement**: An app targets a simulator or device through `xcodebuild`
against the generated project. A Swift package that exports a library builds
with SwiftPM — `Package.swift` is its manifest, and `swift build` and
`swift test` are its gate. Do not wrap a library in an app project to build
it, and do not try to ship an app from a bare package when it needs an app
target's resources and signing.

**Criterion**:

- Pass: the build tool matches the artifact — `xcodebuild` for app bundles,
  SwiftPM for libraries
- Fail: a library buildable only through an `.xcodeproj`; app resources
  bolted onto a package manifest

**Tooling**:

- Makefile: the wrapper hides the `xcodebuild` flags (scheme, destination,
  derived-data path) so they need not be memorized

## SW-PJ-3: Makefile Targets Are the Lifecycle

**Statement**: The Makefile is the interface to the build, and its targets
are the lifecycle every Swift repo shares:

| Target | What it does |
|--------|--------------|
| `make generate` | Regenerate the `.xcodeproj` from `project.yml` via XcodeGen |
| `make format` | Apply SwiftFormat across the tree |
| `make lint` | Run SwiftLint with no mutations; a violation fails the target |
| `make build` | Generate, format, lint, then compile |
| `make test` | Run the unit-test suite |
| `make ui-test` | Run the UI-test suite (slower; nightly in CI) |
| `make coverage` | Run the unit tests with coverage and report the line percentage |
| `make check` | Build and test — the full quality gate for a change |

`make build` depends on `generate`, `format`, and `lint`, so a change cannot
reach the compiler without first passing the formatter and the linter, and
`make check` must pass before every commit.

**Criterion**:

- Pass: the targets exist with these meanings; `build` runs the format and
  lint gates first; `check` is the pre-commit gate
- Fail: raw `xcodebuild` invocations documented instead of targets; a build
  path that skips the linter

**Tooling**:

- `make help` lists the targets; CI runs the same targets developers run

## SW-PJ-4: Source Layout Separates the Core From the Edges

**Statement**: The app's source tree keeps the domain core apart from the
rendering edge, one directory per role:

| Directory | Role |
|-----------|------|
| `App/` | Entry point and root view — the app declaration |
| `Models/` | Value-typed domain logic with no dependency on SwiftUI |
| `Services/` | Side-effectful collaborators (audio, persistence, network, notifications) behind protocol seams |
| `ViewModels/` | `@MainActor` observable classes adapting the core to the screen |
| `Views/` | SwiftUI views — the thin rendering edge, grouped by feature |
| `Resources/` | Asset catalogs, localizations, plists |

Domain logic lives in `Models/` and `Services/` as pure Swift the unit suite
can drive; a view model is the humble object between them and the screen; a
view renders and forwards intent. Nothing in `Models/` or `Services/` imports
SwiftUI. Additional role directories (a design system, shared utilities) are
fine when they name a real role; what is not fine is logic filed by
convenience instead of role.

**Criterion**:

- Pass: each source file sits in the directory matching its role; `Models/`
  and `Services/` compile without SwiftUI
- Fail: business logic inside a `View` body; a model importing SwiftUI for
  convenience; a flat source directory once the target has more than a
  handful of files

**Tooling**:

- Grep: `grep -rln "import SwiftUI" Models/ Services/` relative to the source
  root — zero hits
- Review: new files land in the directory their role names

## SW-PJ-5: Versions Live in `project.yml`

**Statement**: The user-visible version (`MARKETING_VERSION`) and the build
number (`CURRENT_PROJECT_VERSION`) are settings in `project.yml`, bumped by
Makefile targets (`bump-patch`, `bump-minor`, `bump-major`, `bump-build`) —
not edited inside the generated project or Xcode UI. The changelog follows
Keep a Changelog, and a release stamps it.

**Criterion**:

- Pass: version bumps are `project.yml` diffs made by the bump targets;
  CHANGELOG uses the bracketed Keep a Changelog format
- Fail: a version set in the Xcode UI that `make generate` erases; releases
  without changelog entries

**Tooling**:

- Makefile: `make version` reads the current pair from `project.yml`
