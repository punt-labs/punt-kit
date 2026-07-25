# CLI-Only Install Standard

**Introduced:** 2026-07-24

How a tool's `install.sh` installs the CLI while skipping the Claude Code
plugin. Every punt tool whose installer does two jobs in one run — installs a
**harness-neutral CLI** (binary, PATH, tool directories, seed content, per-repo
`enable`, health check) and registers a **Claude-Code-only plugin**
(marketplace add, `claude plugin install`) — MUST offer a way to do the first
job and skip the second. It is implemented identically across tools so an
operator learns it once.

For where each surface is shipped, see
[distribution.md](distribution.md); for the plugin channel itself, see
[plugins.md](plugins.md).

**Reference implementation:** ethos `install.sh` (`--no-plugin`, forthcoming
v-next). The design and its rejected alternatives are recorded in the ethos
design doc `docs/install-cli-only.md` and ratified as ethos ADR DES-063.

---

## Who this is for

Two audiences want the CLI without the plugin:

- **Non-Claude harnesses** — Codex, Cursor, a plain terminal. There is no
  plugin surface to install; the tool is used via the CLI, MCP (`<tool>
  serve`), and the filesystem.
- **Enterprise-policy Claude users** — `claude` is present and working, but org
  policy blocks plugin/marketplace installation. The CLI works fine.

The capability-absent case (no `claude`, no `git`) is already an auto-skip
signal (below). The gap this standard closes is the **operator-driven** skip:
the enterprise user has `claude` present, so the auto-skip never fires, and a
piped `curl … | sh` has nowhere to put a flag.

---

## The standard

### Flag

The flag is `--no-plugin`. It skips **only** the Claude Code
marketplace-register and plugin-install steps. Every other step — binary
download/build, PATH setup, tool directories, seed content, per-repo `enable`,
and the final health check — runs unchanged. Unknown flags are a usage error
(exit 2) with a one-line usage string: a piped installer must not silently
ignore a misspelled `--no-plguin` and install the plugin the user asked to
skip.

`--no-plugin` is preferred over `--cli-only` and `--skip-plugin`.
`--cli-only` overclaims — hooks, the identity dir, PATH edits, seed, and
`enable` all still run, so "CLI only" is inaccurate; it names the audience, not
the action. `--skip-plugin` names the internal implementation verb, not the
user intent. `--no-plugin` is the GNU/POSIX `--no-<feature>` idiom for turning
off a default-on feature (`--no-color`, `--no-verify`, `--no-cache`): plugin
installation *is* a default-on feature of the installer, and `--no-plugin`
turns it off. It states exactly what is disabled and nothing more.

### Environment variable

The env var is `<TOOL>_NO_PLUGIN` (uppercased tool name, e.g. `ETHOS_NO_PLUGIN`,
`VOX_NO_PLUGIN`). It skips the plugin when set to exactly `1`. Any other value —
including empty, `0`, `true`, `yes` — is ignored. One accepted value matches the
installer's existing internal `0/1` convention; document `=1` as the only
accepted form. Do not implement a truthy-string parser (`true`/`yes`/`on`/
non-empty): it is locale- and convention-dependent and inconsistent with the
internal flag.

The env var exists because some contexts are argument-hostile: CI that templates
a bare `curl … | sh`, corporate proxies that mangle the pipeline, config systems
that set env but cannot append operands.

### Piped invocation

Because the tool is installed via `curl … | sh`, the installer MUST parse
arguments so both forms work over a pipe:

```sh
curl -fsSL …/install.sh | sh -s -- --no-plugin      # flag form
curl -fsSL …/install.sh | <TOOL>_NO_PLUGIN=1 sh     # env form
```

`sh` reads a script from stdin when given `-s`; `--` ends `sh`'s own option
parsing; everything after `--` becomes the script's positional parameters
(`$1`, `$2`, …). This is POSIX and works identically in `dash`, `bash --posix`,
and BusyBox `sh`. The installer parses `"$@"` with a POSIX `case` loop before
doing any work:

```sh
for arg in "$@"; do
  case "$arg" in
    --no-plugin) SKIP_PLUGIN_REQUESTED=1 ;;
    -h|--help)   usage; exit 0 ;;
    *)           printf '%s: unknown option: %s\n' "install.sh" "$arg" >&2; usage >&2; exit 2 ;;
  esac
done
```

The default one-liner is unchanged:

```sh
curl -fsSL …/install.sh | sh
```

### Skip resolution

A single internal boolean gates the plugin steps. It is set to "skip" when the
flag is present, OR the env var equals `1`, OR a required capability (`claude`,
`git`) is absent:

```text
SKIP_PLUGIN = 1  if  --no-plugin present
                 or  <TOOL>_NO_PLUGIN = 1
                 or  claude absent            (capability auto-skip)
                 or  git absent               (capability auto-skip)
             = 0  otherwise
```

The flag and the env var express the same intent (skip), so resolution is a
simple OR. There is deliberately **no** counter-flag to force the plugin on:
explicit request and capability-absence cannot conflict — both drive the
variable to 1 — and you cannot install a plugin without `claude`, so a
force-on flag would have no correct behavior.

### Skip semantics

Skipping is scoped to the marketplace-register and plugin-install steps. It MUST
NOT skip the binary, PATH edits, tool directories, seed content, per-repo
enablement, or the health check. A tool's per-repo `enable`/`setup` verbs are
unaffected and gain no parallel flag — those verbs never install the plugin, so
the flag has no home on them. It lives solely on `install.sh`.

The per-repo `enable` verb's git hooks (audit seal, commit trailer) are
harness-neutral and are the audit backbone the tool exists to provide; they MUST
run in CLI-only mode. Skipping them would strip the audit trail.

### Success messaging

On skip, the final message MUST state that the CLI is installed and works, and
MUST NOT print plugin-specific instructions (e.g. "Restart Claude Code to
activate the plugin"). The message names the next CLI steps (`<tool> setup`,
session start) and how to add the plugin later.

The message is gated on the skip boolean, not on the reason for skipping, so the
capability-absent auto-skip and the explicit skip print the same accurate block.
A common bug this rule prevents: the capability-absent path emitting a
"restart to activate the plugin" line when no plugin was ever installed.

The default (plugin-installed) success block is unchanged.

### No policy auto-detection

The installer MUST NOT probe the plugin command to guess an enterprise policy
block and skip on failure. A plugin-command error (`claude plugin marketplace
add` returning non-zero) is indistinguishable from a transient network failure,
a marketplace-repo outage, an auth hiccup, or a genuine bug. Auto-skipping on
any such failure masks real install failures as "probably policy."

Capability-absence (`command -v claude`, `command -v git`) is the only auto-skip
signal — it is a clean binary present/absent test with unambiguous meaning. A
policy block requires the explicit flag or env var: the operator who works under
a plugin-blocking policy knows it and says so with one reviewable word, which is
strictly better than the installer guessing from an error code.

---

## Conformance checklist

- [ ] `--no-plugin` flag parsed from `"$@"`; unknown flags exit 2 with usage.
- [ ] `<TOOL>_NO_PLUGIN=1` env var honored identically to the flag.
- [ ] `sh -s -- --no-plugin` and `<TOOL>_NO_PLUGIN=1 sh` both work over `curl … | sh`.
- [ ] Skip is scoped to marketplace + plugin steps only; binary, PATH, dirs, seed, enable, doctor all still run.
- [ ] Single boolean OR-combines flag, env, and capability-absence auto-skip.
- [ ] No counter-flag to force the plugin on.
- [ ] On skip, success message is CLI-only accurate; no "restart to activate plugin" line.
- [ ] Auto-skip (missing `claude`/`git`) prints the same CLI-only message as the explicit skip.
- [ ] No auto-detection of policy block via probing the plugin command.
- [ ] README/website document both the default and the `--no-plugin` one-liner.

---

## Rejected alternatives

- **A separate `install-cli.sh` script.** Two scripts sharing ~90% of their
  logic drift. One script with a boolean flag has one code path to test and
  maintain.
- **Post-install `<tool> plugin remove`.** Installs the plugin, then uninstalls
  it — wasteful, racy, leaves the marketplace registered, and requires `claude
  plugin install` to *succeed first*, which is exactly what fails for the
  enterprise-blocked audience.
- **Making CLI-only the default.** Breaks the happy path for the majority
  (Claude Code users who want the plugin) and would force them to pass a flag
  for the common case. Opting out is the minority action, so it takes the flag.
- **Auto-detecting the policy block** by probing `claude plugin` and skipping on
  error. Fragile, and masks real failures. Capability-absence is the only signal
  clean enough to auto-skip on.
- **A truthy env-var parser** (`true`/`yes`/`on`/non-empty). Locale- and
  convention-dependent, and inconsistent with the installer's `0/1` internal
  flag. One accepted value (`1`) is unambiguous.
