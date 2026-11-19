# Standards and Rules

**Introduced:** 2026-11-19

How Punt Labs writes standards and the language rules that implement them:
what each layer holds, how a rule traces to the policy it enforces, and what
never goes in either. Punt Labs writes Python, Go and Smalltalk (Pharo), so
one policy has to hold in several languages without being restated in each.

---

## The Two Layers

| Layer | Location | Holds | Never holds |
|-------|----------|-------|-------------|
| Policy | `standards/*.md` | What must be true and why, stated once for every language | Language syntax, tool configuration, code |
| Rule | `lang-rules/<lang>/*.md` | How one language makes a policy true, and the gate that checks it | New policy, or a policy that differs from the standard |

A standard is the authority. A rule is an implementation of it: it may be
stricter in how it gets there, but it never decides something the standard
did not. Status belongs to neither layer.

## Go / No-Go

| Go | No-go |
|----|-------|
| State a policy once, in `standards/`, in language-neutral terms | Restate a policy in a second standard or a rule |
| Give each policy clause a stable ID | Renumber, reuse or delete a clause ID |
| Put each language's implementation in `lang-rules/<lang>/` | Put language syntax or tool settings in a policy clause |
| Make each rule cite the clause IDs it implements and name its gate | Write a rule with no clause behind it, or a clause with no rule |
| Track adoption, audits and deviations in the project and Linear | Put project status, adoption tables or open deviations in a standard or rule |
| Change a clause and its rules in the same PR | Let a rule drift from its clause |

---

## Clauses

### STD-1: Standards state language-neutral policy

**Applies to:** markdown

A standard in `standards/` says what must be true and why. Its normative
clauses hold for every language a project is written in, so they name
behavior, not syntax: "every log file has exactly one writer or rotates
under a cross-process lock", not "use `RotatingFileHandler`". A standard
may name a reference implementation as an example. A requirement that only
makes sense in one language is a rule, not a clause.

### STD-2: Each language implements policy in its own rules directory

**Applies to:** markdown

The rules for one language live in `lang-rules/<lang>/`, named for the
language (`python`, `go`, `pharo`) or, for a non-program artifact, its
format (`markdown`). When languages differ, the rules differ and the policy
does not. A language's overview (its toolchain and how it realizes the
policies) is `lang-rules/<lang>/README.md`; it links to rules and does not
restate them. A clause that holds only for some languages lists them on an
`**Applies to:**` line, and each listed language implements it. The names
are those of the files the clause governs: this standard's clauses govern
standards and rules documents, so they apply to `markdown`.

### STD-3: Standards and rules carry no status

**Applies to:** markdown

A standard or rule describes the required end state. It never records where
a project or the org is relative to it. The following are status and do not
belong: per-repo adoption or compliance tables, audit findings, deviations
to resolve, lists of projects currently using or migrating to something,
follow-on work, "not yet implemented" notes, and issue IDs. Status
lives in the project (its own docs and code) and in Linear. A standard may
link to a Linear project for its rollout; it does not summarize it.

### STD-4: Every policy clause has a stable ID

**Applies to:** markdown

A clause is a heading of the form `### <PREFIX>-<n>: <title>`. The prefix
is 2 to 8 uppercase letters or digits, starting with a letter, unique to
one standard, and shared by every clause in it (this standard uses `STD`).
`<n>` counts up from 1 in the order clauses are added. An ID is permanent:
it is never renumbered, reused, or moved to another standard. To withdraw
a clause, keep its heading, change its title to start with `Retired`, and
say what replaced it. A clause carries one obligation that a gate can check
or a reviewer can judge.

### STD-5: Every rule cites the clauses it implements and names its gate

**Applies to:** markdown

A rule is a heading of the form `## <LANG>-<AREA>-<n>: <title>`, unique
across `lang-rules/`. Directly under it is one line:

```markdown
**Implements:** LOG-2, LOG-5 · **Gate:** `make lint` (Ruff `LOG`, `G`)
```

`Implements` lists the clause IDs the rule makes true. `Gate` names what
fails when the rule is broken: a make target, a linter rule, a CI job, an
in-image check or test, or `review` with the evaluator role when no
mechanical check is practical. A rule file that carries one `Implements`
line carries one on every rule.

### STD-6: The traceability check fails on broken links

**Applies to:** markdown

`make check` runs `make check-standards`, which fails when:

- two clauses share an ID, or two rules share an ID;
- two standards share a clause prefix, or one standard uses more than one;
- a rule cites a clause that is not defined, or is retired;
- a rule cites a clause whose `Applies to` line omits the rule's language;
- a clause is cited by no rule, or by no rule in a language it applies to;
- a rule in a file that carries `Implements` lines has none.

### STD-7: A clause and its rules change together

**Applies to:** markdown

A PR that changes what a clause requires updates every rule that cites it in
the same PR. When a rule and its clause disagree, the clause wins and the
rule is fixed. Rules are canonical in punt-kit; a copy deployed to another
repo's `.claude/rules/` is replaced from here, never edited in place.

### STD-8: Conformance is forward-only

**Applies to:** markdown

These clauses bind a standard or rule file when it is created or normatively
amended. Amending a document brings it into conformance in the same PR:
give its clauses IDs, cite them from rules, remove status, and move
language-specific requirements into `lang-rules/<lang>/`. A document that
has not been amended is not rewritten for conformance alone, and which
documents conform is itself status (STD-3). Dates follow the
[Introduced dates](../AGENTS.md#introduced-dates) convention.
