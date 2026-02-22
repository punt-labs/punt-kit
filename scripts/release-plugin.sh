#!/usr/bin/env bash
set -euo pipefail

# Swap dev plugin manifest for prod before tagging a release.
# The tagged commit gets the prod name; the marketplace cache clones from it.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEV_MANIFEST="${REPO_ROOT}/.claude-plugin/plugin.json"
DIST_MANIFEST="${REPO_ROOT}/.claude-plugin/plugin-dist.json"

if [[ ! -f "$DIST_MANIFEST" ]]; then
  echo "ERROR: ${DIST_MANIFEST} not found" >&2
  exit 1
fi

dev_ver="$(jq -r .version "$DEV_MANIFEST")"
dist_ver="$(jq -r .version "$DIST_MANIFEST")"
if [[ "$dev_ver" != "$dist_ver" ]]; then
  echo "ERROR: version mismatch — plugin.json=${dev_ver}, plugin-dist.json=${dist_ver}" >&2
  exit 1
fi

cp "$DIST_MANIFEST" "$DEV_MANIFEST"
git -C "$REPO_ROOT" add .claude-plugin/plugin.json
git -C "$REPO_ROOT" commit --no-verify -m "chore: set plugin name for release [skip ci]"
