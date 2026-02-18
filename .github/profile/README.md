# Punt Labs

Tools for engineers who work with AI. Open source. Quality-focused.

## About

Punt Labs builds software that keeps engineers in flow. Most of our tools work two ways: as standalone CLIs and as plugins or MCP servers inside Claude Code and Claude Desktop. Use them from the terminal or let your AI assistant use them for you. Our name comes from punting in Oxford: a casual way to give something a go.

Our design standards and project guide live in [punt-kit](https://github.com/punt-labs/punt-kit).

## Projects

### Product Planning

- [**PR/FAQ**](https://github.com/punt-labs/prfaq) `Claude Code` — Amazon's Working Backwards process in the terminal. Generate, review, stress-test, and iterate on product discovery documents with eight specialized agents, simulated review meetings, and compiled PDF output.

### Development

- [**Biff**](https://github.com/punt-labs/biff) `CLI` `Claude Code` — Team communication for engineers who never leave the terminal. Resurrects the BSD Unix communication vocabulary (`who`, `finger`, `write`, `plan`) as both CLI commands and MCP-native slash commands over a NATS relay. Humans and agents show up side by side.
- [**Quarry**](https://github.com/punt-labs/quarry) `CLI` `Claude Code` `Claude Desktop` `macOS` — Local semantic search across your documents. Index PDFs, images, spreadsheets, source code, and 30+ formats. Search by meaning, not keywords. Works as a standalone CLI, an MCP server, or through the [menu bar app](https://github.com/punt-labs/quarry-menubar). Runs entirely offline.
- [**Z Spec**](https://github.com/punt-labs/z-spec) `Claude Code` — Formal Z specifications for stateful systems. Extract specs from existing code (`code2model`) or generate code from specs (`model2code`). Type-check with fuzz, animate and model-check with ProB.

### Applications

- [**Dungeon**](https://github.com/punt-labs/dungeon) `Claude Code` — Text adventure prototype where Claude is the game master. No code runs, only prompts. Demonstrates what's possible with skills, MCP state management, and natural language as the parser.
- [**LangLearn TTS**](https://github.com/punt-labs/langlearn-tts) `CLI` `Claude Desktop` — Gives Claude the ability to speak. Pronounce words, generate audio flashcards, or run full language lessons with audio in 70+ languages. Works as a standalone CLI or an MCP server. Ships with 28 AI tutor personas across seven languages and four levels.
- [**Koch Trainer**](https://github.com/punt-labs/koch-trainer-swift) `iOS` — Morse code trainer using the Koch method. Receive/send training, QSO simulation, spaced repetition, and vocabulary practice for amateur radio operators. Built from a formal [Z Spec](https://github.com/punt-labs/z-spec) specification — an example of the design-to-code workflow our tools support.
