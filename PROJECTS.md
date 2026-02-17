# Punt Labs Project Guide

A reference for how each project works, how users install and use it, and how it integrates with the Claude ecosystem.

---

## PR/FAQ

PR/FAQ brings Amazon's Working Backwards product discovery process into the terminal. You describe a product idea through a structured conversation, and the plugin generates a complete PR/FAQ document — a mock press release followed by external and internal FAQs, a four-risks assessment, and a feature appendix — compiled to a PDF via LaTeX. From there, you can peer-review it, stress-test it in a simulated review meeting with four agentic personas, apply feedback surgically, streamline the prose, and render a go/no-go decision. The entire lifecycle happens without leaving Claude Code.

Users install via `curl | bash`, which clones the repo into `~/.claude/plugins/local-plugins/plugins/prfaq` and registers it as a Claude Code plugin. The installer optionally sets up a LaTeX distribution (~4 GB) for PDF compilation and claude-flow for autonomous consensus meetings. Once installed, `/prfaq` starts the workflow. Ten additional slash commands cover the full lifecycle: `/prfaq:review`, `/prfaq:meeting`, `/prfaq:meeting-hive`, `/prfaq:feedback`, `/prfaq:research`, `/prfaq:streamline`, `/prfaq:vote`, `/prfaq:import`, `/prfaq:externalize`, and `/prfaq:feedback-to-us`.

PR/FAQ is a Claude Code plugin — the richest one in the portfolio. It uses a **skill** (the main generation workflow), **eight agents** (peer-reviewer, researcher, feedback engine, streamliner, and four meeting personas), and **ten commands** (one per slash command). Agents are defined as markdown files with model preferences and tool restrictions. The skill orchestrates a six-phase pipeline. No MCP server — all logic lives in prompts and reference guides that agents load as context. PR/FAQ works better when [Quarry](https://github.com/jmf-pobox/quarry-mcp) is installed — the researcher agent uses Quarry's semantic search to find evidence across your full indexed knowledge base during `/prfaq:research` and Phase 0 discovery, not just files in the `research/` directory. Research findings are saved back to `research/`, growing the indexed corpus over time.

---

## Z Spec

Z Spec brings formal specification to AI-assisted development. It lets you create, validate, and test Z specifications for stateful systems — the mathematical notation used to describe what software should do before (or after) you write it. The plugin works bidirectionally: `code2model` extracts a formal spec from existing code, and `model2code` generates code from a spec. Specifications are type-checked with fuzz and animated/model-checked with ProB.

Users install by cloning the repo into `~/.claude/plugins/local-plugins/plugins/z-spec` and registering it in their local marketplace. `/z setup` guides installation of fuzz (compiled from source) and probcli (ProB CLI). From there, `/z create` generates a spec, `/z check` type-checks it, `/z test` animates it, `/z elaborate` enriches it with narrative, and `/z audit` checks test coverage. Koch Trainer was built using this workflow.

Z Spec is a Claude Code plugin using **nine commands** — one per slash command. Each command declares restricted tool allowlists (e.g., only allowing Bash calls to `fuzz` or `probcli`), which limits what Claude can execute during each operation. No skills, no agents, no MCP server. The plugin is the most command-focused in the portfolio, with each command being a self-contained operation.

---

## Biff

Biff is team communication for engineers who work in the terminal. It resurrects the BSD Unix communication vocabulary — `who`, `finger`, `write`, `plan`, `mesg` — as both CLI commands and Claude Code slash commands. Messages travel over a NATS relay, so teams communicate across machines without leaving their coding environment. Humans and AI agents show up side by side in `/who`; there is no distinction between them at the protocol level.

Users install via `pip install biff-mcp` followed by `biff install` and `biff doctor`. The pip package is `biff-mcp` on PyPI. Once installed, the `biff` CLI works standalone from any terminal, and the slash commands (`/who`, `/finger`, `/write`, `/read`, `/plan`, `/mesg`, `/tty`) work inside Claude Code. A `.biff` file in the repo root configures the team roster and relay connection.

Biff uses three Claude ecosystem extension points. It is an **MCP server** (Python, FastMCP) that provides communication tools over stdio transport. It is also a Claude Code **plugin** that wraps those MCP tools as **seven commands** (slash commands). And it has a **PostToolUse hook** that suppresses raw MCP tool output so the conversation stays clean. The plugin layer is what gives users `/who` instead of Claude silently calling an MCP tool.

---

## Quarry

Quarry is local semantic search for your documents. It indexes PDFs, scanned images, spreadsheets, presentations, source code, HTML, and 30+ other formats, then lets you search by meaning rather than keywords. Everything runs offline — the embedding model downloads once (~500 MB) and all indexing and search happens locally. Named databases keep work and personal content separated, and directory sync watches folders for changes.

Quarry is distributed three ways. On **PyPI** as `quarry-mcp` (`pip install quarry-mcp` or `quarry install` for guided setup). As an **`.mcpb` bundle** for Claude Desktop — download `quarry-mcp.mcpb`, double-click, and Claude Desktop configures itself. And as a standalone **CLI** (`quarry search`, `quarry ingest-file`, `quarry sync`). A companion **macOS menu bar app** ([Quarry Menu Bar](https://github.com/jmf-pobox/quarry-menubar)) provides a native search interface that spawns `quarry serve` as a subprocess. The one-liner `curl | bash` installer handles the CLI path.

Quarry is a pure **MCP server** — no Claude Code plugin manifest, no skills, no commands, no hooks. It exposes 15+ tools via FastMCP (Python) over stdio transport: `search_documents`, `ingest_file`, `ingest_url`, `ingest_content`, `get_documents`, `delete_document`, `register_directory`, `sync_all_registrations`, `use_database`, and more. The `.mcpb` bundle packages the MCP server for one-click installation in Claude Desktop, making it the most broadly accessible project — it works in Claude Code, Claude Desktop, and any other MCP client. The menu bar app communicates with Quarry's HTTP API (`quarry serve`), not MCP. 
---

## LangLearn TTS

LangLearn TTS gives Claude the ability to speak. It synthesizes speech in 70+ languages through ElevenLabs, OpenAI TTS, or AWS Polly. Users can ask Claude to pronounce words, generate audio flashcards (English then target language with a pause), batch-synthesize vocabulary lists, or run full language lessons. The project ships with 28 AI tutor personas — one for each combination of seven languages and four proficiency levels, calibrated to Mollick & Mollick's "Assigning AI" framework.

LangLearn TTS is distributed three ways, like Quarry. On **PyPI** as `langlearn-tts` (`uv tool install langlearn-tts`). As an **`.mcpb` bundle** for Claude Desktop — download `langlearn-tts.mcpb`, double-click, and Claude Desktop prompts for an API key and output directory. And as a standalone **CLI** (`langlearn-tts synthesize`, `langlearn-tts synthesize-pair`, `langlearn-tts synthesize-batch`). The CLI works independently of Claude for scripted audio generation.

LangLearn TTS is a pure **MCP server** (Python, FastMCP, stdio transport) with four tools: `synthesize`, `synthesize_batch`, `synthesize_pair`, and `synthesize_pair_batch`. Each tool accepts an `auto_play` flag to play audio immediately. Like Quarry, it has no plugin manifest, no skills, no commands, and no hooks. The `.mcpb` bundle is the primary distribution path, targeting Claude Desktop users who want language learning without terminal setup. The tutor personas are prompt files in the package, not Claude Code skills — they're pasted into Claude Desktop project instructions.

---

## Dungeon

Dungeon is a clickable prototype for a text adventure engine where Claude is the game master. The entire game engine is a markdown file containing instructions that Claude follows — no code parses player input, no runtime evaluates game logic. Players type natural language commands and Claude interprets them, manages state, and narrates the outcome. Three bundled adventures ship with the plugin: a classic fantasy dungeon crawl, a UNIX system internals meta-adventure, and a gothic horror stealth game. As a prototype, it demonstrates the concept — skills for behavior, MCP for persistence, hooks for presentation — but a real game would need deeper mechanics, better content, and likely a proper game engine backing it.

Users install via `curl | bash`, which clones the repo into `~/.claude/plugins/local-plugins/plugins/dungeon`, installs Node.js MCP dependencies, registers the plugin, and creates a `/d` shorthand command. Once installed, `/dungeon` or `/d` starts or continues a game. The game state persists as YAML frontmatter in `.claude/dungeon.local.md`, so games survive across sessions.

Dungeon is the only project that combines three extension points. A **skill** (`SKILL.md`) contains the game master instructions — how to render scenes, match actions, manage inventory and health, and narrate outcomes. An **MCP server** (Node.js, `@modelcontextprotocol/sdk`) handles game I/O with six tools: `load`, `save`, `delete_save`, `read_script`, `list_scripts`, and `read_assets`. A **PostToolUse hook** suppresses raw MCP tool output so players see narration, not JSON. The skill tells Claude *what* to do; the MCP server handles *persistence*; the hook keeps the experience *clean*.

---

## Quarry Menu Bar

Quarry Menu Bar is a native macOS companion for Quarry. It sits in the menu bar and provides instant semantic search across all indexed documents without switching apps. Click the icon or press a hotkey, type a query, and get syntax-highlighted results for code, Markdown, and prose. A detail view shows full page context for each result. The app can switch between named databases.

The app is built with Swift/SwiftUI (macOS 14+, `@Observable`) and generated via XcodeGen from `project.yml`. Developers build with `make generate && make run`. It requires `quarry-mcp` installed separately as a peer dependency. There is no App Store distribution or pre-built binary — it is currently source-only.

Quarry Menu Bar does not use any Claude ecosystem extension points. It is a standalone native app that communicates with Quarry's HTTP API (`quarry serve`) over localhost. The app spawns and manages the `quarry serve` process itself, discovering the port via `~/.quarry/data/<db>/serve.port`. No MCP, no plugin, no skills — it's the one project in the portfolio that sits entirely outside the Claude ecosystem, connecting to the same search engine through a different interface.

---

## Koch Trainer

Koch Trainer is an iOS app for learning Morse code using the Koch method — a progressive technique where you start with two characters and add one each time you reach 90% accuracy. The app supports receive training (listening), send training (keying), QSO simulation with virtual amateur radio stations, spaced repetition scheduling, and vocabulary practice.

Koch Trainer is distributed through the App Store (or TestFlight). It is a native iOS app written in Swift.

Koch Trainer does not use any Claude ecosystem extension points. It is included in the Punt Labs portfolio as an example of the design-to-code workflow that the development tools support — its state machine and domain logic were formally specified using Z Spec before implementation.

---

## Languages

| Project | Language | Source files | Notes |
|---------|----------|-------------|-------|
| Biff | Python | ~27 | MCP server + CLI (`biff-mcp` on PyPI) |
| Quarry | Python | ~29 | MCP server + CLI (`quarry-mcp` on PyPI) |
| LangLearn TTS | Python | ~11 | MCP server + CLI (`langlearn-tts` on PyPI) |
| Quarry Menu Bar | Swift | ~47 | SwiftUI, macOS 14+, XcodeGen |
| Koch Trainer | Swift | — | iOS, not hosted locally |
| Dungeon | JavaScript | 1 | Single `server.mjs` for MCP game state |
| PR/FAQ | Markdown + Shell | — | Pure prompts, reference guides, install script |
| Z Spec | Markdown | — | Pure prompts, reference guides |

Three projects have real application code in Python. Two are native Swift apps. Dungeon has a single JavaScript file for its MCP server. PR/FAQ and Z Spec are entirely prompt-driven — no application code, just markdown skills, agents, commands, and reference guides that Claude loads as context.

---

## Extension Points Summary

| Project | Plugin | Skills | Agents | Commands | Hooks | MCP Server | .mcpb | PyPI |
|---------|--------|--------|--------|----------|-------|------------|-------|------|
| PR/FAQ | Yes | 1 | 8 | 10 | — | — | — | — |
| Z Spec | Yes | — | — | 9 | — | — | — | — |
| Biff | Yes | — | — | 7 | 1 | Yes (Python) | — | `biff-mcp` |
| Quarry | — | — | — | — | — | Yes (Python) | Yes | `quarry-mcp` |
| LangLearn TTS | — | — | — | — | — | Yes (Python) | Yes | `langlearn-tts` |
| Dungeon | Yes | 1 | — | — | 1 | Yes (Node.js) | — | — |
| Quarry Menu Bar | — | — | — | — | — | — | — | — |
| Koch Trainer | — | — | — | — | — | — | — | — |

**Four integration patterns:**

1. **Plugin + commands** (PR/FAQ, Z Spec) — Claude Code plugins where slash commands are the primary interface. PR/FAQ adds skills and agents for complex orchestration.
2. **Plugin + MCP + commands** (Biff) — An MCP server wrapped by a plugin layer that exposes tools as slash commands.
3. **Pure MCP** (Quarry, LangLearn TTS) — Standalone MCP servers distributed via PyPI and `.mcpb`. No plugin wrapper. Work in Claude Code, Claude Desktop, and any MCP client.
4. **Plugin + MCP + skill** (Dungeon) — A skill defines behavior, an MCP server handles state, and a hook cleans up output. The most tightly integrated pattern.
