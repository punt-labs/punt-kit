#!/usr/bin/env bash
set -euo pipefail

# Restore -dev commands on main after a release tag.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

git -C "$REPO_ROOT" checkout HEAD~1 -- commands/
git -C "$REPO_ROOT" add commands/
git -C "$REPO_ROOT" commit --no-verify -m "chore: restore dev commands"
