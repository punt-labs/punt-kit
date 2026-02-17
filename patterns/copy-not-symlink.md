# Copy, Not Symlink

## Problem

A PyPI package bundles plugin files (command prompts, hooks, manifests) that must be deployed to `~/.claude/plugins/<name>/`. The files need to survive package upgrades, virtualenv moves, and `pip uninstall` without breaking the plugin.

## Forces

- Symlinks point to a specific filesystem location. If the virtualenv moves, the package upgrades to a new version, or `pip uninstall` runs, the symlinks break and the plugin silently stops working.
- `importlib.resources` provides a stable, version-correct path to package data regardless of installation method (editable install, wheel, sdist).
- Claude Code loads plugin files from `~/.claude/plugins/<name>/` at startup. Broken files mean broken commands with no clear error message.
- Upgrades should update plugin files to match the new package version.

## Solution

Use `importlib.resources.files("<package>.plugins")` to locate the bundled plugin source, then `shutil.copytree()` to copy the entire directory to `~/.claude/plugins/<name>/`. On upgrade, remove the target directory first and re-copy.

```python
import importlib.resources
import shutil

source = importlib.resources.files("mypackage.plugins.mypackage")
target = Path.home() / ".claude" / "plugins" / "mypackage"

if target.exists():
    shutil.rmtree(target)
shutil.copytree(str(source), str(target))
```

The same approach works for user commands — copy individual `.md` files to `~/.claude/commands/`.

## Consequences

- Plugin files are self-contained and survive package lifecycle changes.
- Upgrades get new plugin files by re-running the install command.
- No symlink management, no marketplace manifest, no filesystem coupling.
- Hand-edits to deployed plugin files are overwritten on next install. This is intentional — the package is the source of truth.
- The install command must be rerun after package upgrades to pick up new plugin files.

## Rejected Alternative: Local Marketplace Symlinks

Claude Code has a "local marketplace" pattern using symlinks and `marketplace.json`. This was rejected because it requires maintaining a separate manifest, ties the plugin to a specific filesystem path, and adds indirection without benefit. The copy approach is simpler: one step, no manifest, no symlink management.

## Known Uses

- **Biff** — `biff install` copies from `importlib.resources.files("biff.plugins.biff")` to `~/.claude/plugins/biff/`. The `biff@local` registry key mimics the local plugin convention without the marketplace indirection.
