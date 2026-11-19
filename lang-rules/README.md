# Language Coding Rules (canonical)

This directory is the **canonical home** for Punt Labs per-language coding
rules — the `.claude/rules` content an agent loads when it touches a file in
that language. Each rule implements a policy clause in
[`../standards/`](../standards/); the relationship, the ID scheme and the
traceability check are defined in
[Standards and Rules](../standards/standards.md).

## Layout

One directory per language, named for the language (`python/`, `go/`,
`swift/`, `c/`) or, for a non-program artifact, its format (`markdown/`).
A language's directory exists once a clause applies to it. For Pharo, whose
quality is enforced by the linting engine inside the image (Code Critics /
Renraku / SmallLint, see [`../standards/pharo.md`](../standards/pharo.md)),
a rule names the in-image check or SUnit test as its gate.

## Canonical here, deployed elsewhere

These files are the single source of truth. They are **deployed** from here
into any repo where the language is active — copied to that repo's
`.claude/rules/` (or the workspace `.claude/rules/`) so the ancestor-walk
mechanism loads them. A deployed copy is replaced from here, never edited in
place.

## Relationship to the standards

A standard states the policy once, for every language. A rule says how one
language makes that policy true and names the gate that fails when it does
not. A rule never adds policy: when a rule and its clause disagree, the
clause wins. The Python rules additionally back the OO ratchet (see
[`../standards/python.md`](../standards/python.md)).
