# Node.js Standards

Standards for Punt Labs Node.js projects. Currently only Dungeon uses Node.js (a single MCP server file), so these standards are lightweight and will evolve as more Node.js projects are added.

---

## Toolchain

| Tool | Purpose |
|------|---------|
| **Node.js** | Runtime (v20+) |
| **npm** | Package manager |
| **@modelcontextprotocol/sdk** | MCP server framework |
| **zod** | Schema validation for tool inputs |

## Project Layout

```
mcp/
  package.json              # Dependencies and metadata
  package-lock.json         # Locked dependencies
  server.mjs                # MCP server (ES modules)
```

Node.js MCP servers in plugin projects live in a `mcp/` subdirectory, not at the project root. The project root belongs to the plugin structure (skills, commands, hooks, scripts).

## ES Modules

- Use `"type": "module"` in `package.json`.
- Use `.mjs` extension for server files.
- Use `import`/`export`, not `require()`.

## package.json

Required fields:

```json
{
  "name": "<project>-mcp",
  "version": "X.Y.Z",
  "type": "module",
  "private": true,
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.x",
    "zod": "^3.x"
  }
}
```

Node.js MCP servers that are embedded in plugins (not standalone npm packages) should be `"private": true`. The version should match the plugin's `plugin.json` version.

## MCP Server Pattern

```javascript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const server = new McpServer(
  { name: "<project>", version: "X.Y.Z" },
  { instructions: "..." }
);

// Register tools with zod schemas for input validation
server.registerTool("tool_name", {
  description: "...",
  inputSchema: {
    param: z.string().describe("..."),
  },
}, async ({ param }) => {
  // Implementation
  return { content: [{ type: "text", text: "..." }] };
});

const transport = new StdioServerTransport();
await server.connect(transport);
```

## Input Validation

- All tool inputs validated via zod schemas in `inputSchema`.
- Sanitize user-provided strings before using in file paths (e.g., strip path traversal characters).
- Use `node:fs/promises` for async file I/O.

## Error Handling

- Let unknown errors propagate to the MCP SDK's error handling.
- Catch expected errors (e.g., `ENOENT` for missing files) and return meaningful text responses.
- Do not swallow errors silently.

## Path Resolution

- Resolve paths relative to the module using `import.meta.url`:
  ```javascript
  const __dirname = dirname(fileURLToPath(import.meta.url));
  ```
- State files that belong to the user's project go in `process.cwd()`, not the plugin directory.
- Plugin assets (scripts, art, templates) resolve relative to the plugin root.

## Style

- No TypeScript compilation step for simple MCP servers. Plain `.mjs` is preferred for single-file servers.
- For larger Node.js projects, TypeScript with `tsc` is acceptable.
- No build tooling (webpack, esbuild, etc.) unless the project genuinely requires it.

## Testing

- For single-file MCP servers embedded in plugins, manual testing via the plugin is acceptable.
- For standalone Node.js projects, use a test framework (vitest or node:test).

## Distribution

Node.js MCP servers embedded in plugins are distributed with the plugin (via the plugin's `install.sh`). The installer runs `npm install` in the `mcp/` directory.

Standalone Node.js MCP servers (if any) should be published to npm.
