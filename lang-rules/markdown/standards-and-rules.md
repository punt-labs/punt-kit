---
paths:
  - "standards/**/*.md"
  - "lang-rules/**/*.md"
---

# Standards and Rules Documents

**Introduced:** 2026-11-19

These rules implement [standards/standards.md](../../standards/standards.md)
for the Markdown files under `standards/` and `lang-rules/`.

## MD-STD-1: Keep language syntax out of policy clauses

**Implements:** STD-1 · **Gate:** `review` (standards evaluator)

A clause in `standards/` names behavior. Language code, configuration keys
and tool settings go in a rule under `lang-rules/<lang>/`; the clause may
link to that rule or name a reference implementation as an example.

## MD-STD-2: Put each language's rules in its own directory

**Implements:** STD-2 · **Gate:** `make check-standards` (missing language coverage)

A rule lives under `lang-rules/<lang>/`. When a clause lists languages on
its `**Applies to:**` line, each listed language has a directory with a rule
that cites the clause.

## MD-STD-3: Remove status from standards and rules

**Implements:** STD-3 · **Gate:** `review` (standards evaluator)

Delete adoption tables, per-repo state, audit results, deviations, project
lists, follow-on notes and tracker IDs when you see them, and move the facts
to the project or Linear.

## MD-STD-4: Write clause headings with a stable ID

**Implements:** STD-4 · **Gate:** `make check-standards` (duplicate or mixed prefixes)

Use `### <PREFIX>-<n>: <title>` with the standard's one prefix and the next
unused number. Retire a clause by renaming its title to start with
`Retired`; never delete or renumber it.

## MD-STD-5: Put an Implements and Gate line under every rule heading

**Implements:** STD-5 · **Gate:** `make check-standards` (missing citations)

Write `**Implements:** <IDs> · **Gate:** <gate>` as the first line under a
`## <LANG>-<AREA>-<n>: <title>` heading. When the gate needs a paragraph,
write `**Implements:** <IDs>` alone and start a later paragraph of the rule
with `**Gate:**`. Name `review` as the gate only when no mechanical check is
practical.

## MD-STD-6: Run the traceability check in make check

**Implements:** STD-6 · **Gate:** `make lint` (runs `check-standards`)

`make check-standards` runs `tools/check_standards.py` from `make lint`, so
`make check` and CI fail on any broken link between clauses and rules.

## MD-STD-7: Update a clause and its rules in one PR

**Implements:** STD-7 · **Gate:** `review` (standards evaluator)

Before changing a clause, find every rule that cites its ID and update them
in the same PR. Do not edit deployed `.claude/rules/` copies directly.

## MD-STD-8: Bring an amended document into conformance

**Implements:** STD-8 · **Gate:** `review` (standards evaluator)

When a PR normatively amends a standard or rule file, apply STD-1 through
STD-7 to that whole file in the same PR.
