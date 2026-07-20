# Language Coding Rules (canonical)

This directory is the **canonical home** for Punt Labs per-language coding
rules — the `.claude/rules` content an agent loads when it touches a file in
that language. It is organized one directory per language:

| Language | Directory | Contents |
|----------|-----------|----------|
| Python | `python/` | present — 22 files; seeded from `punt-labs/.claude/rules/`, reconciled to the four-surface architecture and generalized (repo-specific assumptions removed) |
| C | `c/` | present — `c-code.md`, `tests.md`; seeded from `xboing-c/.claude/rules/` and generalized. `tests.md` deliberately keeps the xboing-c fixtures as the reference set per [`../standards/c.md`](../standards/c.md); a repo deploying it needs a per-project counterpart |
| Go | `go/` | present — `go-project.md`, `go-code.md`, `go-style.md`, `go-tests.md`; authored from [`../standards/go.md`](../standards/go.md) and verified against cryptd and ethos |
| Swift | `swift/` | present — 7 files, 38 rules; authored from [`../standards/swift.md`](../standards/swift.md) and [`../standards/oo.md`](../standards/oo.md), verified against koch-trainer-swift and quarry-menubar |

Pharo has no directory here **by design**: Pharo's quality is enforced by the
linting engine inside the Pharo image (Code Critics / Renraku / SmallLint), not
by an external rules file. See [`../standards/pharo.md`](../standards/pharo.md).

## Canonical here, deployed elsewhere

These files are the single source of truth. They are meant to be **deployed**
from here into any repo where the language is active — copied to that repo's
`.claude/rules/` (or the workspace `.claude/rules/`) so the ancestor-walk
mechanism loads them. The deployment tooling is a follow-on; for now this
directory holds the canonical copies so there is one place to review and tune
them.

## Relationship to the standards

Each language's standard in [`../standards/`](../standards/) describes the
conventions in prose and points at its rules here; the rules are the
per-file-enforced form of that standard. The Python rules additionally back the
OO ratchet (see [`../standards/python.md`](../standards/python.md)).

## Status

All four rule sets are present and lint-clean under the repo markdownlint
config. Python and C were seeded from their reference repos and have had a
full generalization pass; Go and Swift were authored fresh from their merged
standards and reference repos, with evaluator sign-off. Remaining follow-on:
the deployment tooling that copies these sets into consuming repos'
`.claude/rules/`.
