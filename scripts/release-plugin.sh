#!/usr/bin/env bash
set -euo pipefail

# Remove -dev commands before tagging a release.
# The tagged commit has only prod commands; the marketplace cache clones from it.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMANDS_DIR="${REPO_ROOT}/commands"

dev_files=()
while IFS= read -r -d '' f; do
  dev_files+=("$f")
done < <(find "$COMMANDS_DIR" -name '*-dev.md' -print0)

if [[ ${#dev_files[@]} -eq 0 ]]; then
  echo "No -dev commands found in ${COMMANDS_DIR}" >&2
  exit 1
fi

for f in "${dev_files[@]}"; do
  echo "Removing: $(basename "$f")"
done

git -C "$REPO_ROOT" rm "${dev_files[@]}"
git -C "$REPO_ROOT" commit --no-verify -m "chore: remove dev commands for release [skip ci]"
