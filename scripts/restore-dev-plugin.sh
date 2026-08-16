#!/usr/bin/env bash
set -euo pipefail

# Restore dev plugin state on main after a release tag.
#
# Instead of assuming HEAD~1 has the dev state (which breaks when multiple
# PRs merge between the release swap and Phase 9), walk plugin.json history
# to find the most recent commit where the name ended with -dev.
#
# CONTRACT: This script restores dev-state files and stages them. It does
# NOT commit. The caller (Phase 9 in punt_kit.release) re-stamps the
# version in plugin.json (which the historical dev commit reverted along
# with the name) and then creates a single commit with hooks running. If
# this script committed on its own, the re-stamp would land in a separate
# commit that had to be squashed with --amend, and the org bans the
# --no-verify escape hatch that the amend previously used.

REPO_ROOT="$(cd "$(dirname "$0")/.." || exit 1; pwd)"
PLUGIN_JSON=".claude-plugin/plugin.json"

# Find the most recent commit where plugin.json contained the dev name.
# Dev plugin names always end with -dev. Walk plugin.json history and
# check each commit's content until we find one with the dev name.
LOG_OUTPUT="$(git -C "$REPO_ROOT" log --format='%H' -- "$PLUGIN_JSON")"
if [ -z "$LOG_OUTPUT" ]; then
  echo "ERROR: No commit history found for ${PLUGIN_JSON} — is the path correct?" >&2
  exit 1
fi

STDERR_FILE="$REPO_ROOT/.tmp/git-show-stderr"
mkdir -p "$(dirname "$STDERR_FILE")"

DEV_COMMIT=""
while IFS= read -r sha; do
  show_output=""
  show_output="$(git -C "$REPO_ROOT" show "${sha}:${PLUGIN_JSON}" 2>"$STDERR_FILE")" && rc=0 || rc=$?
  if [ "$rc" -ne 0 ]; then
    show_stderr="$(cat "$STDERR_FILE")"
    if echo "$show_stderr" | grep -qE "does not exist|not a valid object"; then
      continue
    fi
    echo "ERROR: git show failed: ${show_stderr}" >&2
    exit 1
  fi
  if echo "$show_output" | grep -q '"name".*-dev"'; then
    DEV_COMMIT="$sha"
    break
  fi
done <<< "$LOG_OUTPUT"

if [ -z "$DEV_COMMIT" ]; then
  echo "ERROR: No commit found with dev plugin name in ${PLUGIN_JSON}" >&2
  exit 1
fi

echo "Restoring dev state from commit ${DEV_COMMIT:0:12}..."
git -C "$REPO_ROOT" checkout "$DEV_COMMIT" -- "$PLUGIN_JSON" commands/
git -C "$REPO_ROOT" add "$PLUGIN_JSON" commands/
# Deliberately no commit — see CONTRACT above. The caller re-stamps the
# version in plugin.json and commits both the restore and the re-stamp
# together, so the commit passes the pre-commit hook and the message
# still carries [skip ci] to keep the tag-triggered release.yml
# workflow from firing on this chore commit.
