# Integration Matrix

The peer integrations among Punt Labs tools, the layers each uses and how the
consumer degrades without its building block.
[INT-12](../standards/integration.md#int-12-record-every-peer-integration-before-implementing-it)
requires recording an integration before implementing it, here or in the
consumer's DESIGN.md.

All arrows are **unidirectional** — building blocks never know about their
consumers.

## Building Blocks

Pure building blocks with no upstream awareness:

| Block | Role | Consumers |
|-------|------|-----------|
| **vox** | TTS engine — audio output | biff (peer), langlearn-tts (hard), dungeon (peer) |
| **lux** | Visual output surface — tables, charts, UI | prfaq (peer), quarry (peer), langlearn (peer), dungeon (peer) |
| **langlearn-types** | Shared interfaces for langlearn family | langlearn (hard), langlearn-tts (hard), langlearn-anki (hard), langlearn-imagegen (hard) |
| **ethos** | Identity + session context delivery | quarry (peer), biff (peer), vox (peer) |

## Peer Integrations

| Integration | Layers | Degradation |
|-------------|--------|-------------|
| biff → vox | L0, L2, L3 | Without vox: messages are text-only. Hook-triggered vocalizations (L2) are the primary path; 1–2 use cases may also use MCP tools (L1). |
| prfaq → quarry | L1, L5 | Without quarry: researcher agent falls back to web search. |
| prfaq → lux | L1 | Without lux: text-only output in terminal. With lux: visual PR/FAQ dashboard, meeting displays. |
| quarry → lux | L1 | Without lux: CLI text output. With lux: interactive data explorer, search result tables. Could replace quarry-menubar. |
| quarry-menubar → quarry | L1 | Without quarry: menubar app has no backend. REST API discovery over HTTP. Lux may replace this surface. |
| langlearn → langlearn-tts | L1 | Without langlearn-tts: no audio output. Flashcards, spaced repetition, and other non-audio functions still work. Langlearn is an LLM outer loop — it discovers langlearn-tts MCP tools at runtime. |
| langlearn → lux | L1 | Without lux: no visual flashcard display. Audio and SRS still work. |
| dungeon → lux | L1 | Without lux: text adventure in terminal. With lux: visual game UI, maps, inventory. |
| dungeon → vox | L1 | Without vox: silent gameplay. With vox: narration, sound effects, ambient audio. |
| quarry → ethos | L2 | Without ethos: no agent-scoped memory, no session context injection. Quarry still works for project-scoped search. |
| biff → ethos | L2 | Without ethos: no identity-aware messaging. Biff still works with anonymous sessions. |
| vox → ethos | L2 | Without ethos: no voice personality persistence. Vox still works with default voice. |

## Candidates for bundled integrations

| Tool | What we read | What it enables |
|------|-------------|----------------|
| **git** | `.git/`, status, log, `.gitignore` | Commit-aware sync, branch detection, ignore filtering |
| **beadle** | Email via MCP | Email memory, auto-ingest correspondence |
| **gh** | GitHub API via CLI | PR context, issue linking, review integration |

Each of these follows the same pattern: the integration ships with
quarry (or whichever consumer), is structurally separated from core
logic, and degrades gracefully when the external tool is absent.
