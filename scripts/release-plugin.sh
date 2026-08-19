#!/usr/bin/env bash
set -euo pipefail

# Prepare plugin for release: swap name to prod, remove -dev commands.
# The tagged commit has only prod artifacts; the marketplace cache clones from it.

REPO_ROOT="$(cd "$(dirname "$0")/.." || exit 1; pwd)"

# The shippable surface lives under plugin/ (DES-025), but this script is
# copied verbatim into every plugin repo and the fleet migrates one repo at a
# time, so resolve the plugin root instead of hardcoding it. Silence here
# would tag a release whose plugin.json was never swapped, so an unresolvable
# root is a hard error, not a fallback to the repo root.
PLUGIN_ROOT=""
for candidate in "${REPO_ROOT}/plugin" "${REPO_ROOT}"; do
  if [[ -f "${candidate}/.claude-plugin/plugin.json" ]]; then
    PLUGIN_ROOT="$candidate"
    break
  fi
done

if [[ -z "$PLUGIN_ROOT" ]]; then
  echo "ERROR: no .claude-plugin/plugin.json under ${REPO_ROOT}/plugin or ${REPO_ROOT}" >&2
  exit 1
fi

PLUGIN_JSON="${PLUGIN_ROOT}/.claude-plugin/plugin.json"
COMMANDS_DIR="${PLUGIN_ROOT}/commands"

# Swap plugin name from *-dev to prod
current_name="$(python3 -c "import json; print(json.load(open('${PLUGIN_JSON}'))['name'])")"
prod_name="${current_name%-dev}"

if [[ "$current_name" == "$prod_name" ]]; then
  echo "Plugin name is already '${prod_name}' (no -dev suffix)" >&2
  exit 1
fi

echo "Swapping plugin name: ${current_name} → ${prod_name}"
python3 -c "
import json, pathlib
p = pathlib.Path('${PLUGIN_JSON}')
d = json.loads(p.read_text())
d['name'] = '${prod_name}'
p.write_text(json.dumps(d, indent=2) + '\n')
"

# Remove -dev commands. Three outcomes, and telling them apart is the point:
#
#   1. commands/ is tracked at HEAD but missing from the working tree.
#      Something deleted it out from under the release. Abort — continuing
#      would tag a "prod" commit still carrying every *-dev command.
#   2. commands/ is absent at HEAD too. A plugin that ships only skills,
#      agents, or hooks is valid, and for it the name swap IS the whole
#      preparation. Skip the removal and say so.
#   3. commands/ is present with no *-dev.md. Either the variants were never
#      written or a prior run already swapped. Both need a human. Abort.
#
# A bare `[[ -d ]]` cannot separate 1 from 2, and `find` below cannot either:
# inside a process substitution its exit status is discarded, so a directory
# that vanished yields an empty dev_files and reads exactly like case 2. Hence
# the HEAD check — git knows what this plugin is supposed to have.
commands_rel="${COMMANDS_DIR#"${REPO_ROOT}/"}"
if git -C "$REPO_ROOT" ls-tree HEAD -- "$commands_rel" | grep -q . \
   && [[ ! -d "$COMMANDS_DIR" ]]; then
  echo "ERROR: ${commands_rel} is tracked at HEAD but missing from the working tree" >&2
  echo "       Refusing to prepare a release that would keep every -dev command." >&2
  exit 1
fi

dev_files=()
if [[ -d "$COMMANDS_DIR" ]]; then
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
else
  echo "No ${COMMANDS_DIR} — swapping the name only"
fi

git -C "$REPO_ROOT" add "$PLUGIN_JSON"
if [[ ${#dev_files[@]} -gt 0 ]]; then
  git -C "$REPO_ROOT" rm "${dev_files[@]}"
fi
# Phase 4 does not follow the swap with any additional edit that needs
# to land in this commit, so this script commits on its own (unlike
# restore-dev-plugin.sh, which stages and lets the caller commit). The
# hooks fire — the org bans --no-verify — and this remains one commit
# per logical step.
git -C "$REPO_ROOT" commit -m "chore: prepare plugin for release"
