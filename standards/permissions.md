# Permissions Standards

Rules for Claude Code permission configuration across all Punt Labs projects.
Defines what agents can do automatically, what requires approval, and what is
blocked entirely.

---

## 1. Permission Tiers

Claude Code uses a three-tier permission model:

| Tier | Behavior | Where defined |
|------|----------|---------------|
| **Allow** | Auto-approved, no prompt | `settings.json` (checked in) or `settings.local.json` (gitignored) |
| **Prompt** | User approves or rejects each time | Default for anything not in allow or deny |
| **Deny** | Blocked entirely, cannot be approved | `settings.json` (checked in) |

The prompt tier is the safety net. Most tools fall here by default. Only
promote to allow when the tool is safe for autonomous use; only promote to
deny when the tool should never run, even with explicit approval.

---

## 2. File Split

Permissions are split across two files based on portability:

### `settings.json` (checked in)

Portable permissions that apply to all collaborators on the project.

Contains:

- MCP plugin tool wildcards
- Build tool Bash commands
- Skill permissions
- WebFetch domain allowlist
- Deny rules
- Project-specific entries (hooks, env, additionalDirectories)

### `settings.local.json` (gitignored)

Machine-specific permissions tied to local paths or OS-specific tools.

Contains:

- `Read`/`Edit`/`Write` with absolute or `~` paths
- OS-specific commands (e.g., `Bash(say:*)` on macOS)

**Every project must gitignore `settings.local.json`.** Add to `.gitignore`:

```gitignore
.claude/settings.local.json
```

---

## 3. Required Allow Rules

### MCP plugin wildcards

Every project must allow all Punt Labs plugin MCP tools:

```json
"mcp__plugin_biff_tty__*",
"mcp__plugin_github_github__*",
"mcp__plugin_quarry_quarry__*",
"mcp__github__*",
"mcp__quarry__*"
```

Projects with their own MCP servers add project-specific wildcards (e.g.,
`"mcp__plugin_tts_vox__*"`).

### Build tools

Every project must allow these generic Bash commands:

```json
"Bash(bash:*)",
"Bash(bd:*)",
"Bash(cat:*)",
"Bash(chmod +x:*)",
"Bash(claude mcp:*)",
"Bash(claude plugin:*)",
"Bash(export:*)",
"Bash(find:*)",
"Bash(gh:*)",
"Bash(git:*)",
"Bash(ls:*)",
"Bash(pip index:*)",
"Bash(punt:*)",
"Bash(sed:*)",
"Bash(shellcheck:*)",
"Bash(tail:*)",
"Bash(test:*)"
```

Projects add their own build tools as needed:

| Project type | Additional allows |
|-------------|-------------------|
| Python | `Bash(uv:*)`, `Bash(uvx:*)`, `Bash(python3:*)` |
| Node.js | `Bash(npx:*)`, `Bash(npm:*)` |
| Swift | `Bash(make:*)`, `Bash(xcodebuild:*)` |
| CLI project | `Bash(<cli-name>:*)`, `Bash(<cli-name>-server:*)` |

### Skills

Every project must allow all Punt Labs plugin skills. This includes both
short names and fully qualified names for each plugin:

- **biff**: `biff`, `biff:finger`, `biff:last`, `biff:mesg`, `biff:plan`,
  `biff:read`, `biff:talk`, `biff:tty`, `biff:wall`, `biff:who`, `biff:write`
  (plus short names: `biff`, `finger`, `last`, `mesg`, `plan`, `read`, `talk`,
  `tty`, `wall`, `who`, `write`)
- **dungeon**: `d`
- **prfaq**: `prfaq:prfaq`, `prfaq:vote`, `prfaq:meeting`,
  `prfaq:meeting-hive`, `prfaq:streamline`, `prfaq:research`, `prfaq:review`,
  `prfaq:feedback`, `prfaq:feedback-to-us`, `prfaq:externalize`, `prfaq:import`
- **punt-kit**: `punt:audit`, `punt:init`, `punt:pii`, `punt:reconcile`,
  `punt:release`
- **quarry**: `quarry`, `quarry:find`, `quarry:explain`, `quarry:ingest`,
  `quarry:quarry`, `quarry:source` (plus short names: `find`, `explain`,
  `ingest`, `source`)
- **tts**: `tts:notify`, `tts:recap`, `tts:say`, `tts:speak`, `tts:vibe`,
  `tts:voice` (plus short names: `notify`, `recap`, `say`, `speak`, `vibe`,
  `voice`)
- **local commands**: `autopilot`
- **z-spec**: `z-spec:audit`, `z-spec:check`, `z-spec:cleanup`,
  `z-spec:code2model`, `z-spec:elaborate`, `z-spec:help`, `z-spec:model2code`,
  `z-spec:partition`, `z-spec:setup`, `z-spec:test`

### WebFetch domains

Allow research domains relevant to org work:

```json
"WebFetch(domain:claude.com)",
"WebFetch(domain:docs.anthropic.com)",
"WebFetch(domain:elevenlabs.io)",
"WebFetch(domain:ics.uci.edu)",
"WebFetch(domain:survey.stackoverflow.co)",
"WebFetch(domain:venturebeat.com)",
"WebFetch(domain:www.anthropic.com)",
"WebFetch(domain:www.cartesia.ai)"
```

---

## 4. Required Deny Rules

Every project must deny these operations. Deny rules block the operation
entirely — the user cannot approve them even if prompted.

### Destructive operations

| Rule | Rationale |
|------|-----------|
| `Bash(rm -rf /:*)` | System destruction |
| `Bash(rm -rf ~:*)` | Home directory destruction |
| `Bash(dd:*)` | Raw disk writes, can overwrite devices |

### Privilege escalation

| Rule | Rationale |
|------|-----------|
| `Bash(sudo:*)` | No agent should have root access |
| `Bash(su:*)` | No agent should switch users |

### Network access

| Rule | Rationale |
|------|-----------|
| `Bash(curl:*)` | Arbitrary HTTP requests |
| `Bash(wget:*)` | Arbitrary HTTP downloads |
| `Bash(ssh:*)` | Remote shell access |
| `Bash(scp:*)` | Remote file transfer |
| `Bash(ftp:*)` | Remote file transfer |
| `Bash(tftp:*)` | Remote file transfer |
| `Bash(nc:*)` | Raw network connections, reverse shells |
| `Bash(netcat:*)` | Raw network connections |
| `Bash(ncat:*)` | Raw network connections |
| `Bash(telnet:*)` | Plain text remote access |
| `Bash(socat:*)` | Advanced network proxy |

### Secrets and environment

| Rule | Rationale |
|------|-----------|
| `Edit(.env)` | Prevent modifying environment secrets |
| `Write(.env)` | Prevent creating/overwriting environment secrets |
| `Edit(.envrc)` | Prevent modifying direnv configuration |
| `Write(.envrc)` | Prevent creating/overwriting direnv configuration |
| `Bash(direnv allow:*)` | Prevent trusting untrusted `.envrc` files |

### Known limitations

Deny rules match on command prefixes. Flags placed after arguments (e.g.,
`git push origin main --force`) may not match a deny rule for
`Bash(git push --force:*)`. These rules are guardrails against common
mistakes, not a sandbox.

Allowed interpreters (`python3`, `uv run`) can bypass network deny rules
programmatically. The deny list prevents direct invocation of network tools,
not all possible network access.

---

## 5. Local-Only Permissions

The `settings.local.json` file contains machine-specific entries. These are
not checked in because they contain local paths.

### Cross-project file access

Allow read/edit/write across the punt-labs workspace using both path forms:

```json
"Read(~/Coding/punt-labs/**)",
"Read(/Users/<username>/Coding/punt-labs/**)",
"Edit(~/Coding/punt-labs/**)",
"Edit(/Users/<username>/Coding/punt-labs/**)",
"Write(~/Coding/punt-labs/**)",
"Write(/Users/<username>/Coding/punt-labs/**)"
```

### Temporary file access

```json
"Read(/tmp/**)",
"Write(/tmp/**)"
```

### OS-specific commands

| OS | Rule |
|----|------|
| macOS | `Bash(say:*)` |

---

## 6. Plugin-Distributed Permissions

Plugins installed via the marketplace operate in arbitrary projects — not just
the plugin's own repo. They need permissions in the **user's**
`~/.claude/settings.json` so commands, skills, and hooks can run without
constant approval prompts.

The SessionStart hook (see [plugins.md](plugins.md)) handles MCP tool
wildcards. This section covers everything else: Bash commands, file
write/edit patterns, and web access.

### What to auto-allow

| Category | Auto-allow when... | Example |
|----------|-------------------|---------|
| Bash (build tools) | Deterministic, non-destructive | `Bash(bash */compile_prfaq.sh *)` |
| Bash (scaffolding) | Creates empty directories only | `Bash(mkdir -p meetings)` |
| Bash (utilities) | No side effects, no network | `Bash(uuidgen)` |
| Write (plugin output) | Pattern contains plugin name or is plugin-owned | `Write(*prfaq*.tex)` |
| Write (plugin config) | Plugin's own config directory | `Write(.tts/**)` |
| Edit (plugin output) | Same constraint as Write | `Edit(*prfaq*.tex)` |
| WebSearch | Plugin performs research as core functionality | `WebSearch` |
| WebFetch | Plugin fetches from arbitrary domains as core functionality | `WebFetch` |

### What to never auto-allow

| Category | Rationale |
|----------|-----------|
| `Bash(curl *)`, `Bash(wget *)` | Network requests to external endpoints |
| `Bash(rm *)` | File deletion — users approve every delete |
| Broad `Write(*)` / `Edit(*)` | Patterns that match files outside the plugin's domain |
| Bash with side effects | Package installs, process management, system config |

### Pattern specificity

Permission patterns must be narrow enough that they don't grant access to
unrelated files. Include the plugin name or a domain-specific identifier:

```text
# Good — scoped to plugin output
"Write(*prfaq*.tex)"
"Write(.tts/**)"
"Edit(*prfaq*.bib)"

# Bad — matches any .tex file
"Write(*.tex)"
"Edit(*.tex)"
```

### Implementation pattern

Define rules as a JSON array. Use `jq` for atomic, order-preserving merge.
Fall back to manual instructions when `jq` is unavailable.

**Note on Bash rule syntax.** Project-level settings (section 3) use broad
patterns like `Bash(bash:*)` because the developer trusts their own project.
Plugin-distributed permissions use narrow patterns like
`Bash(bash */compile_prfaq.sh *)` because they are injected into the user's
global settings and should match only the specific commands the plugin needs.

```sh
PLUGIN_RULES='[
  "Bash(bash */compile_prfaq.sh *)",
  "Write(*prfaq*.tex)",
  "Edit(*prfaq*.tex)"
]'

SETTINGS_FILE="$HOME/.claude/settings.json"

if command -v jq >/dev/null 2>&1; then
  # Ensure valid JSON exists
  if [ ! -f "$SETTINGS_FILE" ]; then
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    printf '{}' > "$SETTINGS_FILE"
  elif ! jq -e . "$SETTINGS_FILE" >/dev/null 2>&1; then
    cp "$SETTINGS_FILE" "${SETTINGS_FILE}.bak" 2>/dev/null || true
    printf '{}' > "$SETTINGS_FILE"
  fi

  # Count new rules, then merge (order-preserving, idempotent)
  ADDED=$(jq -r --argjson new "$PLUGIN_RULES" '
    (.permissions.allow // []) as $orig
    | [$new[] | select(. as $r | $orig | index($r) | not)] | length
  ' "$SETTINGS_FILE")

  jq --argjson new "$PLUGIN_RULES" '
    (.permissions.allow // []) as $orig
    | .permissions.allow = $orig + [$new[] | select(. as $r | $orig | index($r) | not)]
  ' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"

  if [ "$ADDED" -gt 0 ]; then
    echo "$ADDED permission rule(s) added to $SETTINGS_FILE"
  else
    echo "permissions already configured"
  fi
else
  echo "jq not found — add these rules manually to $SETTINGS_FILE under permissions.allow:"
  printf '%s\n' "$PLUGIN_RULES"
fi
```

### Uninstall cleanup

The uninstaller must remove only the rules the plugin added:

```sh
jq --argjson remove "$PLUGIN_RULES" '
  .permissions.allow = [(.permissions.allow // [])[] | select(. as $r | $remove | index($r) | not)]
' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
```

---

## 7. Applying These Standards

### New repositories

1. Create `settings.json` with shared allow rules (sections 3) and deny rules
   (section 4), plus any project-specific build tool allows.
2. Create `settings.local.json` with local path permissions (section 5).
3. Add `.claude/settings.local.json` to `.gitignore`.
4. Verify with `punt audit`.

### Existing repositories

Run `punt audit` to check compliance. The audit checks:

- All required deny rules are present
- All required MCP wildcards are present
- All required skill permissions are present
- `settings.local.json` is gitignored
- No local paths appear in `settings.json`

### Adding new deny rules

When adding a new deny rule, apply it to all projects simultaneously. Use a
script to merge the rule into every project's `settings.json` to maintain
consistency.
