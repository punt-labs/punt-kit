# Design Decision Log

## Problem

Design decisions accumulate during development but are not recorded systematically. When a new contributor (human or AI) encounters existing code, they may propose changes that revisit already-settled decisions. Without a record, the team wastes time re-debating resolved issues or inadvertently reverting hard-won solutions.

## Forces

- AI assistants have no memory across sessions. Without a decision log, they will propose approaches that were already tried and rejected.
- Design decisions often involve tradeoffs that are not obvious from the code alone.
- Some decisions required multiple iterations to reach — the final solution only makes sense in the context of what failed before.
- Decisions span multiple concerns: architecture, UX, installation, protocol, naming.

## Solution

Maintain a design decision log as a markdown file in the repository. Each decision follows a consistent format:

```markdown
## DES-NNN: Short Title

**Date:** YYYY-MM-DD
**Status:** SETTLED | OPEN | SUPERSEDED
**Topic:** One-sentence scope

### Design

What was decided and how it works.

### Why

The reasoning behind the decision.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| Option A | Reason |
| Option B | Reason |
```

### Rules

1. Before proposing any design change, consult the log for prior decisions on the same topic.
2. Do not revisit a settled decision without new evidence.
3. Log the decision, alternatives considered, and outcome.
4. Include failed approaches — they are as valuable as the solution.

### Organization

For projects with distinct concern areas, split into multiple files:

- `DESIGN.md` — Runtime architecture, protocol, UX decisions
- `DESIGN-INSTALLER.md` — Installation, distribution, setup decisions

Each file owns a numbered sequence (DES-001..., INS-001...) within its domain.

### Status values

- **SETTLED** — Decision is final. Do not revisit without new evidence.
- **OPEN** — Decision is under discussion. May change.
- **SUPERSEDED** — Replaced by a later decision. Reference the replacement.

## Consequences

- New contributors (human or AI) can understand why the code is the way it is before proposing changes.
- Failed approaches are documented, preventing repeat experiments.
- The log grows with the project. For mature projects, a table of contents at the top helps navigation.
- The "do not revisit without new evidence" rule prevents decision churn while allowing genuine improvements.
- AI assistants that read the log before making changes produce more informed proposals.

## Known Uses

- **Biff** — `DESIGN.md` (13 decisions, DES-001 through DES-013) covers runtime architecture, protocol, and UX. `DESIGN-INSTALLER.md` (9 decisions, INS-001 through INS-009) covers installation and distribution. Both files are referenced in CLAUDE.md as required reading before changes.
