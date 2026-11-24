#!/usr/bin/env bash
set -euo pipefail

# Install one exact punt-kit artifact in a clean venv and run real punt
# operations against a throwaway Python project.
#
# Usage:
#   scripts/smoke-release.sh candidate <wheel>
#   scripts/smoke-release.sh published <version> [<candidate-wheel>]
#
# candidate: installs the given wheel file, offline from any index for
#   punt-kit itself, and expects the version in its filename.
# published: installs punt-kit==<version> from production PyPI. With a
#   candidate wheel, the wheel PyPI serves must be byte-identical to it.

usage() {
    echo "usage: $0 candidate <wheel> | published <version> [<candidate-wheel>]" >&2
    exit 2
}

fail() {
    echo "::error::$*" >&2
    exit 1
}

[ "$#" -ge 2 ] || usage
mode=$1
case "$mode" in
    candidate)
        [ "$#" -eq 2 ] || usage
        wheel=$(realpath -- "$2")
        [ -f "$wheel" ] || fail "candidate wheel not found: $2"
        name=$(basename -- "$wheel")
        [[ "$name" == punt_kit-*-py3-none-any.whl ]] || fail "not a punt-kit wheel: $name"
        version=${name#punt_kit-}
        version=${version%%-*}
        ;;
    published)
        [ "$#" -le 3 ] || usage
        version=$2
        candidate_wheel=${3:-}
        if [ -n "$candidate_wheel" ]; then
            candidate_wheel=$(realpath -- "$candidate_wheel")
            [ -f "$candidate_wheel" ] || fail "candidate wheel not found: $3"
        fi
        ;;
    *) usage ;;
esac

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
unset UV_INDEX UV_INDEX_URL UV_EXTRA_INDEX_URL UV_FIND_LINKS UV_NO_INDEX
export UV_NO_CONFIG=1 PUNT_TELEMETRY=off
export HOME="$work/home" XDG_CONFIG_HOME="$work/home/.config"
export GIT_CONFIG_GLOBAL="$work/gitconfig" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME"
: >"$GIT_CONFIG_GLOBAL"

uv venv --quiet --python 3.13 "$work/venv"
py="$work/venv/bin/python"
punt="$work/venv/bin/punt"

if [ "$mode" = candidate ]; then
    echo "Smoke testing candidate $(basename -- "$wheel")"
    uv pip install --quiet --python "$py" --default-index https://pypi.org/simple/ "$wheel"
else
    echo "Smoke testing punt-kit==$version from PyPI"
    for attempt in 1 2 3 4 5 6; do
        if uv pip install --quiet --python "$py" \
            --default-index https://pypi.org/simple/ --refresh-package punt-kit \
            "punt-kit==$version"; then
            break
        fi
        [ "$attempt" -lt 6 ] || fail "could not install punt-kit==$version from PyPI"
        sleep 12
    done
    if [ -n "$candidate_wheel" ]; then
        mkdir "$work/pypi"
        "$py" -I - "$version" "$work/pypi" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

version, dest = sys.argv[1:]
with urllib.request.urlopen(f"https://pypi.org/pypi/punt-kit/{version}/json", timeout=30) as r:
    files = json.load(r)["urls"]
wheels = [f for f in files if f["packagetype"] == "bdist_wheel"]
if len(wheels) != 1:
    sys.exit(f"::error::expected one wheel for punt-kit {version}, PyPI lists {len(wheels)}")
with urllib.request.urlopen(wheels[0]["url"], timeout=60) as r:
    (Path(dest) / wheels[0]["filename"]).write_bytes(r.read())
PY
        published_wheel=$(find "$work/pypi" -name '*.whl' -print -quit)
        [ "$(basename -- "$published_wheel")" = "$(basename -- "$candidate_wheel")" ] \
            || fail "PyPI wheel $(basename -- "$published_wheel") is not $(basename -- "$candidate_wheel")"
        cmp -s "$published_wheel" "$candidate_wheel" \
            || fail "PyPI wheel differs from the candidate wheel built for this release"
        echo "PyPI wheel is byte-identical to the candidate"
    fi
fi

# Identity: distribution metadata, CLI version, and the module actually imported.
"$py" -I - "$version" "$("$punt" --json version)" "$work/venv" <<'PY'
import json
import sys
from importlib.metadata import version
from pathlib import Path

import punt_kit
from packaging.version import Version

expected, cli_json, venv = sys.argv[1:]
installed = version("punt-kit")
cli = json.loads(cli_json)["version"]
if Version(installed) != Version(expected) or Version(cli) != Version(expected):
    sys.exit(f"::error::expected punt-kit {expected}, metadata {installed}, CLI {cli}")
module = Path(punt_kit.__file__).resolve()
if not module.is_relative_to(Path(venv).resolve()):
    sys.exit(f"::error::punt_kit imported from {module}, outside the clean venv")
PY

# Real operation: scaffold a Python CLI project, then audit and inspect it.
proj="$work/smoke-demo"
mkdir -p "$proj/.beads"
cd "$proj"
git init --quiet
printf '%s\n' '[project]' 'name = "smoke-demo"' 'version = "0.1.0"' \
    '[project.scripts]' 'smoke-demo = "smoke_demo.cli:app"' >pyproject.toml
"$punt" init . >"$work/init.txt" 2>&1 || { cat "$work/init.txt"; fail "punt init failed"; }
for f in .github/workflows/lint.yml .github/workflows/test.yml .github/workflows/docs.yml \
    .github/workflows/release.yml .claude/settings.json CLAUDE.md; do
    [ -s "$f" ] || fail "punt init did not create $f"
done
grep -q '^  published-smoke:$' .github/workflows/release.yml \
    || fail "scaffolded release.yml has no published-smoke job"
# shellcheck disable=SC2016 # the literal workflow text, not an expansion
grep -qF '"smoke-demo==$version"' .github/workflows/release.yml \
    || fail "scaffolded release.yml does not smoke-install smoke-demo from PyPI"

# The audit fails on files init leaves to the author; every check init owns must pass.
set +e
"$punt" audit . >"$work/audit.txt" 2>&1
audit_rc=$?
set -e
[ "$audit_rc" -le 1 ] || { cat "$work/audit.txt"; fail "punt audit crashed (exit $audit_rc)"; }
for check in "CI lint workflow exists" "CI test workflow exists" "CI docs workflow exists" \
    "Beads initialized" "CLAUDE.md exists" ".claude/settings.json exists" \
    "Standard allow rules present" "Standard deny rules present"; do
    grep -qF "✓ $check" "$work/audit.txt" || { cat "$work/audit.txt"; fail "audit check did not pass: $check"; }
done

"$punt" --json status >"$work/status.json"
"$py" -I - "$version" "$work/status.json" <<'PY'
import json
import sys
from pathlib import Path

expected, path = sys.argv[1:]
status = json.loads(Path(path).read_text())
want = {"punt_kit_version": expected, "language": "python", "has_beads": True}
got = {key: status.get(key) for key in want}
if got != want:
    sys.exit(f"::error::punt status: expected {want}, got {got}")
PY

echo "Release smoke passed ($mode): punt-kit $version scaffolded, audited and inspected a Python project"
