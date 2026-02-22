#!/usr/bin/env bash
set -euo pipefail

# Restore the -dev plugin manifest on main after a release tag.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEV_MANIFEST="${REPO_ROOT}/.claude-plugin/plugin.json"
DIST_MANIFEST="${REPO_ROOT}/.claude-plugin/plugin-dist.json"

dist_name="$(jq -r .name "$DIST_MANIFEST")"

jq --arg name "${dist_name}-dev" \
   --arg desc "$(jq -r .description "$DIST_MANIFEST") — DEV (working tree)" \
   '.name = $name | .description = $desc' \
   "$DIST_MANIFEST" > "$DEV_MANIFEST"

git -C "$REPO_ROOT" add .claude-plugin/plugin.json
git -C "$REPO_ROOT" commit --no-verify -m "chore: restore dev plugin name"
