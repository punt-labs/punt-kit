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

### Path-scoped rule syntax

Claude Code matches path-scoped rules under exactly two tool names:

| Form | Covers |
|------|--------|
| `Read(path)` | Read, Glob |
| `Edit(path)` | Write, Edit, MultiEdit, NotebookEdit |

**`Write(path)`, `MultiEdit(path)`, `NotebookEdit(path)`, and `Glob(path)` are
not valid rule forms.** Each matches nothing and prints a warning at every
session start, in every project that carries it:

> Permission allow rule (...): `Write(.env)` is not matched by file permission
> checks — only `Edit(path)` rules are. Use `Edit(.env)` instead (Edit rules
> cover all file-editing tools).

This applies to all three tiers. A dead `deny` rule is not an unenforced guard
— it grants nothing and blocks nothing — but it is warning noise in every
session, so it must still be removed.

The bare tool name (`Write` with no parentheses) is a different thing and is
valid: it gates the tool itself rather than a path. See section 3.

This applies to `settings.local.json` exactly as it does to `settings.json` —
the warning names whichever file the rule came from.

`punt audit` reports unmatched rules in both files. `punt init` removes them.

**Cleanup drops dead rules; it never rewrites them.** Every rule it removes
was already inert, so effective permissions are identical before and after.
Rewriting would not be — in either tier:

| Tier | Rewriting an orphan would... |
|------|------------------------------|
| `allow` | switch on a grant that has never been in effect |
| `deny`, `ask` | switch on a block that has never been in effect |

Neither is a cleanup; both are policy changes wearing a cleanup's clothes. The
deny case is the more damaging of the two, because a deny cannot be overridden
by approval — activating one can hard-break a workflow that has been writing
that path for months, with no escape but editing the file.

#### Why the wrong intuition is attractive

The rule above was originally written the other way round, on the reasoning
that repairing a broken *guard* only tightens things, and tightening is the
safe direction. That reasoning is wrong, and it is worth naming the error
because it is easy to re-derive.

**"Safe direction for security" and "safe to do silently" are different
properties.** They come apart precisely when the operation is billed as a
cleanup, because a cleanup carries an implicit promise: nothing about the
system's behavior changes, only dead weight goes away. A silent tightening
breaks that promise. That is what makes it a defect rather than an
improvement — not the direction it moves in, but the fact that it moves at
all while claiming not to.

The test to apply is not *"is this change more restrictive?"* but *"could a
user observe a behavior difference after this command that they did not ask
for?"* If yes, it belongs behind an explicit action, not inside a cleanup.

A tool may always report what it found. Deciding what a rule was *supposed*
to do requires knowing the author's intent, and the tool does not have it.

So the tool reports and lets the operator decide. Each removal says which case
it was:

```text
dead rule removed: Write(.env) — Edit(.env) already covers it
dead rule removed: Write(build/**) — never took effect; add Edit(build/**) to deny if you meant it
```

The first is purely redundant. The second is a rule that never did anything,
and only a human can say whether it was supposed to.

---

## 2. File Split

Permissions are split across two files based on portability:

### `settings.json` (checked in)

Portable permissions that apply to all collaborators on the project.

Contains:

- MCP plugin tool wildcards
- Build tool Bash commands
- Skills catalog (informational, not enforced)
- WebFetch domain allowlist
- Deny rules
- Project-specific entries (hooks, env, additionalDirectories)

### `settings.local.json` (gitignored)

Machine-specific permissions tied to local paths or OS-specific tools.

Contains:

- `Read(path)`/`Edit(path)` with absolute or `~` paths
- OS-specific commands (e.g., `Bash(say:*)` on macOS)

**Every project must gitignore `settings.local.json`.** Add to `.gitignore`:

```gitignore
.claude/settings.local.json
```

---

## 3. Required Allow Rules

### MCP wildcards

**All Punt Labs plugin MCP servers, or none.** A subset is not a policy — it
is whoever edited the list last. Every plugin that ships an MCP server is
allowed; plugins without one contribute nothing:

```json
"mcp__github__*",
"mcp__plugin_beadle_email__*",
"mcp__plugin_biff_tty__*",
"mcp__plugin_dungeon_grimoire__*",
"mcp__plugin_ethos_self__*",
"mcp__plugin_lux_lux__*",
"mcp__plugin_quarry_quarry__*",
"mcp__plugin_vox_mic__*",
"mcp__plugin_z-spec_zspec__*"
```

`github` is not a Punt Labs plugin — it ships with Claude Code. It is included
because these settings scaffold a development environment.

Each entry is the tool prefix Claude Code derives from the plugin manifest:
`mcp__plugin_<plugin>_<server>__*`, where `<server>` is a key under
`mcpServers` in the plugin's `plugin/.claude-plugin/plugin.json`. Derive the prefix
from the manifest rather than guessing it — `prfaq` and `punt` ship no MCP
server, and a wildcard naming a plugin that has none matches nothing while
looking like a working grant.

A server configured directly rather than through its plugin has a different
prefix (`mcp__quarry__*` instead of `mcp__plugin_quarry_quarry__*`). Which one
a machine uses is a local choice, so it belongs in `settings.local.json`, not
in the checked-in file.

### Build tools

Every project must allow these generic Bash commands:

```json
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
"Bash(make:*)",
"Bash(pip index:*)",
"Bash(punt:*)",
"Bash(shellcheck:*)",
"Bash(tail:*)",
"Bash(test:*)"
```

**`Bash(bash:*)` and `Bash(sed:*)` must not be allowed.**

`Bash(bash:*)` permits any command at all, because `bash -c "<anything>"`
matches it. That makes every other entry in this list decorative and reaches
straight through the deny rules in section 4 — `bash -c "curl ..."` satisfies
the allow list while `Bash(curl:*)` is denied. Allowing it grants an
unrestricted shell in a file that is committed and rarely re-read.

`Bash(sed:*)` edits any file in place, bypassing the `Edit(path)` rules that
gate file modification.

`git` and `gh` stay. They are development tools, and these settings scaffold a
development environment.

Projects add their own build tools as needed:

| Project type | Additional allows |
|-------------|-------------------|
| Python | `Bash(uv:*)`, `Bash(uvx:*)`, `Bash(python3:*)` |
| Node.js | `Bash(npx:*)`, `Bash(npm:*)` |
| Swift | `Bash(xcodebuild:*)`, `Bash(xcodegen:*)`, `Bash(swiftformat:*)`, `Bash(swiftlint:*)` |
| CLI project | `Bash(<cli-name>:*)`, `Bash(<cli-name>-server:*)` |

### Skills

`Skill()` rules **are** enforced. `SkillTool` has its own permission layer,
documented in Claude Code's skills architecture:

> - explicit deny rules win first;
> - explicit allow rules are honored next;
> - prompt commands whose populated properties are all in a safe-property
>   allowlist are auto-allowed;
> - otherwise, the runtime asks the user and offers exact-skill and
>   `skill:*` local-settings rule suggestions.

So a seeded `Skill()` allow entry is load-bearing: without it, a skill whose
prompt-command properties fall outside the safe-property allowlist prompts the user on
every invocation. The design is deliberately future-conservative — new
properties default to requiring permission until reviewed — which means a
skill that is auto-allowed today can start prompting after an upstream change.

This section previously stated the opposite. It was wrong, and the error was
load-bearing in both directions: it invited deleting 76 working entries as
dead weight, and it told `punt audit` to flag them as a defect.

- **biff**: `biff`, `biff:finger`, `biff:last`, `biff:mesg`, `biff:plan`,
  `biff:read`, `biff:talk`, `biff:tty`, `biff:wall`, `biff:who`, `biff:write`
  (plus short names: `biff`, `finger`, `last`, `mesg`, `plan`, `read`, `talk`,
  `tty`, `wall`, `who`, `write`)
- **dungeon**: `d`
- **prfaq**: `prfaq:prfaq`, `prfaq:vote`, `prfaq:meeting`,
  `prfaq:meeting-hive`, `prfaq:streamline`, `prfaq:research`, `prfaq:review`,
  `prfaq:feedback`, `prfaq:feedback-to-us`, `prfaq:externalize`, `prfaq:import`
- **punt-kit**: `punt:audit`, `punt:auto`, `punt:init`, `punt:pii`,
  `punt:reconcile`
- **quarry**: `quarry`, `quarry:find`, `quarry:explain`, `quarry:ingest`,
  `quarry:quarry`, `quarry:source` (plus short names: `find`, `explain`,
  `ingest`, `source`)
- **tts**: `tts:notify`, `tts:recap`, `tts:say`, `tts:speak`, `tts:vibe`,
  `tts:voice` (plus short names: `notify`, `recap`, `say`, `speak`, `vibe`,
  `voice`)
- **local commands**: `auto`
- **z-spec**: `z-spec:audit`, `z-spec:check`, `z-spec:cleanup`,
  `z-spec:code2model`, `z-spec:elaborate`, `z-spec:help`, `z-spec:model2code`,
  `z-spec:partition`, `z-spec:setup`, `z-spec:test`

### Cross-project file access

Every project must allow file operations across the monorepo workspace.
Sub-agents do not honor path-scoped `Read(path)`/`Edit(path)` rules from
`settings.json` or `settings.local.json` — only the bare tool-name form
unblocks sub-agent file operations. The team hit this three times
(2026-04-05, 2026-04-06, 2026-04-08) and routed around it each time before
root-causing: sub-agents silently failed every file operation, including
reads inside the current repo, because the allow list only contained
path-scoped entries like `Read(../**)`.

```json
"Read",
"Edit",
"Write"
```

The bare form grants Read/Edit/Write across the entire filesystem scope the
user runs Claude Code in; the path-scoped alternative was false protection
because sub-agents bypassed it, and the main session already has that scope
anyway. Deny rules (section 4) still enforce `.env`, `.envrc`, and
dangerous-bash guards.

#### Why

Claude Code sub-agents inherit the permissions allow list from
`settings.json`. When `Read`/`Write`/`Edit` are not present as bare entries,
the default tier is `prompt`, which auto-denies in non-interactive background
sub-agent execution. Path-scoped forms (`Read(../**)`) are not honored by
sub-agents in testing. The bare form is the only reliable unblock.

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
| `Edit(.env)` | Prevent creating or modifying environment secrets |
| `Edit(.envrc)` | Prevent creating or modifying direnv configuration |
| `Bash(direnv allow:*)` | Prevent trusting untrusted `.envrc` files |

`Edit(.env)` covers the Write tool as well as Edit — there is no separate
`Write(.env)` rule to add, and adding one produces a startup warning without
adding any protection (section 1).

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
not checked in because they contain local paths or OS-specific commands.

### Temporary file access

```json
"Read(/tmp/**)",
"Edit(/tmp/**)"
```

### OS-specific commands

| OS | Rule |
|----|------|
| macOS | `Bash(say:*)` |

---

## 6. Plugin-Distributed Permissions

Plugins installed via the marketplace operate in arbitrary projects — not just
the plugin's own repo. They still need permissions so commands, skills, and
hooks run without constant approval prompts. Where those rules land is the
whole of this section.

### Principles

1. **Project scope, never global.** Non-MCP rules go in the project's
   `.claude/settings.json`. A plugin has no business granting itself standing
   permission in projects the user never pointed it at.

2. **MCP tool wildcards are the sole global exception.** An MCP server is
   process-global and its tool names are namespaced to the plugin
   (`mcp__plugin_<name>_<server>__*`), so a global allow entry grants nothing
   outside the plugin's own tools. The SessionStart hook handles these — see
   [plugins.md](plugins.md).

3. **The user asks for it.** The installer installs; it does not grant. Rules
   land when the user runs the plugin's own permissions command inside a
   project. Installing a plugin is not consent to edit files in every repo on
   the machine.

4. **Least privilege.** Only allow operations the plugin performs
   autonomously. Risky, rare, or destructive operations stay at the prompt
   tier.

5. **Pattern specificity.** Patterns must be narrow enough not to reach
   unrelated files — use the plugin name or a domain term (`*prfaq*.tex`, not
   `*.tex`).

6. **`Edit(path)` for every path rule.** `Write(path)` matches nothing and
   warns at every session start (section 1).

7. **Idempotent.** Running the command twice must not duplicate rules,
   reorder existing user permissions, or rewrite the file when there is
   nothing to add. A no-op that dirties the user's git status is not a no-op.

8. **Order preservation.** New rules append; existing order is preserved.

9. **Reversible.** Every rule the plugin adds must be removable by the plugin,
   and the file must be backed up before it changes — including rules earlier
   versions added to places the plugin no longer writes.

Precedent: prfaq shipped installer-injected global rules in v1.5.0 and carried
them to v1.6.1. The result was a plugin holding standing permission to edit
`README.md` and `.gitignore` and to reach the web in every project the user
ever opened. A user hit it in an unrelated repo — eight warnings per session,
from a plugin that repo does not use. Removed in v1.7.0.

### What to auto-allow

| Category | Auto-allow when... | Example |
|----------|-------------------|---------|
| Bash (build tools) | Deterministic, non-destructive | `Bash(bash */compile_prfaq.sh *)` |
| Bash (scaffolding) | Creates empty directories only | `Bash(mkdir -p meetings)` |
| Bash (utilities) | No side effects, no network | `Bash(uuidgen)` |
| Edit (plugin output) | Pattern contains plugin name or is plugin-owned | `Edit(*prfaq*.tex)` |
| Edit (plugin config) | Plugin's own config files | `Edit(.claude/prfaq.local.md)` |
| WebSearch | Plugin performs research as core functionality | `WebSearch` |
| WebFetch | Plugin fetches from arbitrary domains as core functionality | `WebFetch` |
| MCP tools | Plugin's own MCP server tools | `mcp__plugin_<name>_<server>__*` |

There is no separate Write row. `Edit(pattern)` is the only path-scoped
edit form and it already covers the Write tool.

### What to never auto-allow

| Category | Rationale |
|----------|-----------|
| `Bash(curl *)`, `Bash(wget *)` | Network requests to external endpoints |
| `Bash(rm *)` | File deletion — users approve every delete |
| Broad `Edit(*)` | Patterns that match files outside the plugin's domain |
| `Write(anything)` | Not a working form — use `Edit(...)` |
| Anything in `~/.claude/settings.json` except MCP wildcards | Applies in every project the user opens |
| Bash with side effects | Package installs, process management, system config |

### Pattern specificity

```text
# Good — scoped to plugin output
"Edit(*prfaq*.tex)"
"Edit(.punt-labs/vox/**)"
"Edit(*prfaq*.bib)"

# Bad — matches any .tex file
"Edit(*.tex)"

# Bad — matches nothing, warns every session
"Write(*prfaq*.tex)"
```

### Implementation pattern

The plugin ships one script, invoked by one command
(`/<plugin>:permissions`), operating on one file:
`<project>/.claude/settings.json`. It supports `--add`, `--check`, and
`--remove`, refuses to write when the target resolves to `$HOME`, backs up
before changing anything, and exits without touching the file when there is
nothing to do.

**Note on Bash rule syntax.** Project-level settings (section 3) use
per-command patterns like `Bash(make:*)` — broad within one tool, but naming
the tool. Plugin-distributed rules are narrower still, like
`Bash(bash */compile_prfaq.sh *)`, because the user is granting them to a
plugin rather than to themselves. Neither tier may use `Bash(bash:*)`: it
names no tool at all and permits everything (section 3).

```sh
PLUGIN_RULES='[
  "Bash(bash */compile_prfaq.sh *)",
  "Edit(*prfaq*.tex)"
]'

# Resolve both sides before comparing: an unset, relative, trailing-slash, or
# symlinked path would slip past a bare string comparison and let the command
# write the user's global settings file.
PROJECT_DIR=$(cd "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null && pwd -P) || {
  echo "Cannot resolve the project directory." >&2
  exit 1
}

if [ "$PROJECT_DIR" = "$(cd "$HOME" && pwd -P)" ]; then
  echo "Refusing to write the global settings file." >&2
  exit 1
fi

SETTINGS_FILE="$PROJECT_DIR/.claude/settings.json"

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

### Legacy global cleanup

An installer that previously injected non-MCP rules into
`~/.claude/settings.json` is responsible for removing them on upgrade. The
list of rules to remove is frozen historical data — every rule the plugin ever
wrote globally — and is never added to.

```sh
LEGACY_GLOBAL_RULES='[ ... ]'

FOUND=$(jq -r --argjson legacy "$LEGACY_GLOBAL_RULES" '
  [(.permissions.allow // [])[] | select(. as $r | $legacy | index($r))] | length
' "$SETTINGS_FILE")

if [ "$FOUND" -gt 0 ]; then
  cp "$SETTINGS_FILE" "${SETTINGS_FILE}.backup.$(date +%Y%m%d%H%M%S)"
  jq --argjson legacy "$LEGACY_GLOBAL_RULES" '
    .permissions.allow = [(.permissions.allow // [])[] | select(. as $r | $legacy | index($r) | not)]
  ' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
fi
```

Print every rule removed. Cleanup cannot distinguish a rule the plugin
injected from an identical rule the user wrote by hand, so the backup and the
printed list are what make the operation safe.

### Uninstall cleanup

The uninstaller removes only the rules the plugin added, from the project file
it added them to:

```sh
jq --argjson remove "$PLUGIN_RULES" '
  .permissions.allow = [(.permissions.allow // [])[] | select(. as $r | $remove | index($r) | not)]
' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
```

### Repo-scoped `enable` / `disable`

The same mechanics serve `<tool> enable` / `disable` for repo-scoped hook,
config, and permission entries — written to `<repo>/.claude/settings.json`,
not `~/.claude/settings.json`. The tool computes a deterministic entry set;
`enable` adds the missing members with the order-preserving merge above;
`disable` recomputes the identical set and removes those exact values with the
removal pattern above. **Exact value-match is the contract — no tag schema.**
Because the file is shared across tools and invocations, the read-modify-write
takes an exclusive lock. See
[tool-enable-disable.md § 2.8](tool-enable-disable.md#28-hooks-and-config).

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
- No unmatched path rules (`Write(path)`, `MultiEdit(path)`,
  `NotebookEdit(path)`, `Glob(path)`) in any tier of either settings file
- `settings.local.json` is gitignored
- No local paths appear in `settings.json`

`punt init` removes unmatched path rules from both `settings.json` and
`settings.local.json`, per the table in section 1.

### Adding new deny rules

When adding a new deny rule, apply it to all projects simultaneously. Use a
script to merge the rule into every project's `settings.json` to maintain
consistency.

---

## 8. Engine-Level Scoping — the No-Superuser Rule

The Claude Code permission tiers above gate Claude's *tool
invocations*. They do not gate what one engine operation, running on
behalf of one client, is allowed to see or change on behalf of
another. That scoping is the engine's responsibility, not the
permission file's.

**Every write is caller-scoped.** An engine operation invoked over
any client surface (CLI, MCP, REST, library) composes its store keys,
its ownership fields, and its authorization checks on the caller's
identity — the `ConnectionId` in the lux reference (DES-086),
whatever the equivalent shape is in a given project. No operation on
any client surface accepts an `owner=` override letting the caller
act on someone else's state. The engine has no admin path exposed on
a client surface.

**Every content read is caller-scoped.** Operations that return
content another client owns (`scene inspect`, `event ls`, `error ls`,
`screenshot` — the lux vocabulary; the equivalent in any other
project) compose on the caller's identity and return only what the
caller owns. Metadata that is not confidential (peer-discovery lists,
identity strings, connect times) can stay visible to all callers;
content cannot.

**The CLI's per-invocation identity flags are not privilege
elevation.** A CLI that accepts `--as/--kind/--name/--repo/--agent`
(lux) or an equivalent identity-composition flag lets one invocation
*be* a different client for that call. It does not grant the caller
any operation the declared identity would not have; it declares a
fresh identity for the invocation. This is how tests exercise
multi-client scenarios without a superuser path.

**Admin verbs stay on the CLI.** Process supervision, install,
uninstall, enable, disable, and doctor never appear on MCP, REST, or
the library surface (see [tool-enable-disable.md § 2.3](tool-enable-disable.md#23-the-enable--disable-convention)
and [cli.md § Layer 2](cli.md#layer-2-admin-commands)). Exposing them
on any client surface an agent-turn can reach recreates the
superuser surface this rule forbids.
