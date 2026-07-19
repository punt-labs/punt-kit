# Language Coding Rules (canonical)

This directory is the **canonical home** for Punt Labs per-language coding
rules — the `.claude/rules` content an agent loads when it touches a file in
that language. It is organized one directory per language:

| Language | Directory | Source of the seed |
|----------|-----------|--------------------|
| Python | `python/` | the Python coding rules from `punt-labs/.claude/rules/python-*.md` |
| C | `c/` | `c-code.md`, `tests.md` from `xboing-c/.claude/rules/` |
| Go | `go/` | new — derived from `go.md`, cryptd, and ethos |
| Swift | `swift/` | new — derived from `swift.md` and koch-trainer-swift |

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

The Python and C rule sets are seeded from their reference repos and still carry
repo-specific assumptions (paths, project names) that must be generalized during
review. Go and Swift rules are authored fresh from their standards and reference
repos.
