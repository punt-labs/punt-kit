# Language Coding Rules (canonical)

This directory is the **canonical home** for Punt Labs per-language coding
rules — the `.claude/rules` content an agent loads when it touches a file in
that language. It is organized one directory per language:

| Language | Directory | Contents |
|----------|-----------|----------|
| Python | `python/` | present — the Python coding rules from `punt-labs/.claude/rules/`, reconciled to the four-surface architecture |
| C | `c/` | present — `c-code.md`, `tests.md` from `xboing-c/.claude/rules/` |
| Go | not yet present | to be authored from `go.md`, cryptd, and ethos |
| Swift | not yet present | to be authored from `swift.md` and koch-trainer-swift |

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

The Python and C rule sets are present, seeded from their reference repos. The
Python rules have been reconciled to the four-surface architecture; some seeded
rules may still carry repo-specific assumptions to generalize during a later
tuning pass. The Go and Swift rule sets are not yet authored — they are tracked
as a follow-on.
