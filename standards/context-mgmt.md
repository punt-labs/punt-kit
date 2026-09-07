# Context Management Standard

**Introduced:** 2026-09-07

How Punt Labs writes agent-facing configuration — `CLAUDE.md`, `AGENTS.md`,
vendored tool guides, and the docs they point to — so it stays lean, portable
across coding agents, and free of drift. The governing idea: **an agent's
always-loaded context is scarce and shared; put in it only what must be there
every session, and point to everything else so the agent reads it on demand.**

This standard is the *policy* — what belongs in a config file and what does not.
The *mechanism* that produces per-tool files from one source is
[§ 8](#8-one-source-generate-per-tool-files-punt-labs-dev-repos) below and, for
tool users, [tool-enable-disable.md](tool-enable-disable.md). This document does
not restate those; it governs the content they carry.

---

## 1. Don't duplicate what a hook injects

If a SessionStart or PreCompact hook already injects a fact into context, do not
also write it in markdown. Ethos injects identity, persona, team roster, and
collaborations every session — so a `CLAUDE.md` that also lists the roster and
delegation pairings is pure duplication that can only drift out of sync with the
live ethos data. Delete it; the hook is the source.

## 2. Don't duplicate what a tool discovers at runtime

A fact a CLI can answer does not belong hand-copied into markdown. The team
roster is `ethos team show`; the ready work is `bd ready`; the tool verbs are
`punt --help`. Point to the command and state that it must be run to discover the
current answer. A pasted copy is stale the moment the tool's output changes.

## 3. Cite the source for facts that live in code

When a fact is derivable from the codebase — a dependency edge, a config value, a
file path — cite where it lives (`vox/pyproject.toml:48`) rather than asserting
it in prose. A cited fact is self-verifying: the reader confirms it in one
command, and when the source moves, the citation is visibly wrong instead of
silently stale. Prefer a generated list over a hand-maintained one for anything
drift-prone (see § 8).

## 4. One home per fact

Every fact has exactly one authoritative location; every other place links to it.
Three files each carrying "the project map" is three copies that drift apart. When
you find the same fact in two files, keep one authoritative copy and replace the
other with a link to it — or extract it to a third home and link from both.

**DRY is deduplication, never deletion.** "One home" means the fact lives in
exactly one place and is *reachable by reference* from everywhere it is relevant —
it does NOT mean a second copy is removed with no pointer. Before removing any
content, confirm its single home exists and that a reference to it remains from
where a reader would look. Content unreachable from any index or link is lost, not
deduplicated; if a fact has no home yet, give it one before removing it.

**Repos work standalone.** Each repo must function checked out on its own. A
reference must therefore resolve without assuming a sibling repo is present — do
not point at a fact by a relative path into another repo that a solo clone would
not have.

## 5. Index and disclose — do not inline

Agent config is a lean **index**, not a container. The always-loaded file holds
orientation, exact commands, and a *descriptive* index of what deeper docs exist
and when each is relevant — not the docs themselves. The agent opens a referenced
doc only when the task matches. This is **progressive disclosure**, the dominant
pattern in modern agent tooling: content is pulled on demand, not pushed up front.

Concretely: a repo's standards, workflow, testing, and architecture docs stay as
their own files and are *referenced* by a path that resolves in a standalone
checkout ("formal-spec workflow: `docs/WORKFLOW.md`; testing: `TESTING.md`"),
never inlined into the
always-loaded file. Nothing is lost — it is reachable, just not preloaded. A
descriptive index ("what it covers and when") outperforms a bare filename list.

## 6. `@`-imports organize; they do not save context, and they are Claude-only

Claude Code's `@`-import loads the imported file **eagerly at launch** — it
organizes content across files but does not reduce what enters context. And no
other agent follows it: codex, opencode, and pi read a flat file and ignore
`@`-imports entirely. So:

- Use `@`-import only for Claude-only content that genuinely must load every
  session.
- For context economy and for cross-tool portability, use a *reference* (prose
  pointer or link) that the agent follows on demand — not an import.
- Content behind an `@`-import is invisible to codex/opencode/pi. Never rely on it
  to carry anything those tools need.

## 7. Global config holds only what is true everywhere

A user-level `~/.claude/CLAUDE.md` (or equivalent) loads in every repo on the
machine, including unrelated ones. It holds only what is true across all of them —
communication preferences, cross-domain working principles, a machine note. One
project's operating manual does not belong there; it belongs in that project.

## 8. One source, generate per-tool files (Punt Labs dev repos)

**This section governs #1 — how we configure our own repos. It does not apply to
users of our tools (see § 10).**

Because each agent reads a different native file (Claude → `CLAUDE.md`; codex,
opencode, pi → `AGENTS.md`), a repo maintains one source and *generates* each
tool's file from it, rather than hand-maintaining parallel copies. The generator
adopted for this is **rulesync** (`.rulesync/` source → `generate` → per-tool
files); a repo that adopts it wires `rulesync generate --check` into CI so a
hand-edited generated file fails the build. A generated agent file is a **build
artifact**: never hand-edit it; edit the `.rulesync/` source and regenerate.
Adoption is per-repo and rolling — z-spec is the reference implementation.

The generated files obey this whole standard — the root `AGENTS.md` is the lean
index of § 5, the big standards are referenced not inlined, and Claude-only tool
guides are scoped to the Claude target so they never leak into the portable
`AGENTS.md`.

## 9. Respect the reader's budget — measure it

codex silently truncates its concatenated `AGENTS.md` past a byte cap
(`project_doc_max_bytes`, 32 KiB default) — the file closest to the working
directory is cut first, with no error. Leanness is therefore not a preference but
a correctness requirement: config that overflows is config the agent never sees.
Keep the always-loaded root small (single-digit KiB), push detail to referenced
docs (§ 5), and where a repo generates its files, gate the combined always-loaded
size in CI so an overflow fails the build rather than silently dropping guidance.

## 10. Portable content is flat; tool-only config stays tool-native

The portable root (`AGENTS.md`) is plain markdown that every agent reads — no
imports, no tool-specific syntax. Anything with no cross-tool equivalent — MCP
server config, hooks, skills, slash commands, ethos identity wiring — stays in
each tool's own native config, never in the portable file.

**Tool users are a separate population.** When a Punt Labs tool is installed in a
*user's* repo, we do not control that repo or its CI, so no build step, no
rulesync, and no regenerate can be required of them. Enablement there adds a
single short **prose pointer line** to the user's `AGENTS.md`/`CLAUDE.md` pointing
at the tool's own guide (`.punt-labs/<tool>/AGENTS.md`), which the agent opens on
demand — one line, tool-owned target, never a managed block written into the
user's prose. The mechanics are [tool-enable-disable.md](tool-enable-disable.md);
this standard fixes only that the line is a lean pointer, not an inlined guide.
