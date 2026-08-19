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

# Paths below are git pathspecs, so they must stay repo-relative. The
# shippable surface lives under plugin/ (DES-025); this script is copied
# verbatim into every plugin repo and the fleet migrates one repo at a time,
# so resolve the prefix rather than hardcode it. An unresolvable prefix is a
# hard error — restoring nothing would leave main advertising the prod plugin
# name, which is exactly what this script exists to prevent.
PLUGIN_PREFIX=""
PREFIX_FOUND=0
for candidate in "plugin/" ""; do
  if [ -f "${REPO_ROOT}/${candidate}.claude-plugin/plugin.json" ]; then
    PLUGIN_PREFIX="$candidate"
    PREFIX_FOUND=1
    break
  fi
done

if [ "$PREFIX_FOUND" -eq 0 ]; then
  echo "ERROR: no .claude-plugin/plugin.json under ${REPO_ROOT}/plugin or ${REPO_ROOT}" >&2
  exit 1
fi

PLUGIN_JSON="${PLUGIN_PREFIX}.claude-plugin/plugin.json"
COMMANDS_DIR="${PLUGIN_PREFIX}commands/"

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
git -C "$REPO_ROOT" checkout "$DEV_COMMIT" -- "$PLUGIN_JSON" "$COMMANDS_DIR"
git -C "$REPO_ROOT" add "$PLUGIN_JSON" "$COMMANDS_DIR"
# Deliberately no commit — see CONTRACT above. The caller re-stamps the
# version in plugin.json and commits both the restore and the re-stamp
# together, so the commit passes the pre-commit hook and the message
# still carries the CI-skip marker, which spares a push-CI run on main
# after the post-release PR merges. That marker does not affect
# release.yml — that workflow fires on tag push, and the tag is placed in
# phase 5, before this commit exists.
