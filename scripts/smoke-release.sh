#!/usr/bin/env bash
set -euo pipefail

# Install one exact punt-kit artifact in a clean venv and run real punt
# operations against a throwaway Python project.
#
# Usage:
#   scripts/smoke-release.sh candidate <wheel> [<expected-version>]
#   scripts/smoke-release.sh published <version> [<candidate-wheel>]
#
# candidate: installs the given wheel file and expects the version in its
#   filename, which must equal <expected-version> (e.g. the tag) when given.
# published: installs punt-kit==<version> from production PyPI. With a
#   candidate wheel, the one wheel PyPI serves must be byte-identical to it;
#   the install itself may only use that wheel, never build the sdist.

usage() {
    echo "usage: $0 candidate <wheel> [<expected-version>] | published <version> [<candidate-wheel>]" >&2
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
        [ "$#" -le 3 ] || usage
        [ -f "$2" ] || fail "candidate wheel not found: $2"
        wheel=$(realpath -- "$2")
        name=$(basename -- "$wheel")
        [[ "$name" == punt_kit-*-py3-none-any.whl ]] || fail "not a punt-kit wheel: $name"
        version=${name#punt_kit-}
        version=${version%%-*}
        if [ "$#" -eq 3 ]; then
            uv run --quiet --no-project --with packaging python -I -c \
                'import sys; from packaging.version import Version as V; sys.exit(V(sys.argv[1]) != V(sys.argv[2]))' \
                "$version" "$3" || fail "wheel version $version is not the expected $3"
        fi
        ;;
    published)
        [ "$#" -le 3 ] || usage
        version=$2
        candidate_wheel=${3:-}
        if [ -n "$candidate_wheel" ]; then
            [ -f "$candidate_wheel" ] || fail "candidate wheel not found: $3"
            candidate_wheel=$(realpath -- "$candidate_wheel")
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
            --only-binary punt-kit \
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
"$punt" repo init . >"$work/init.txt" 2>&1 || { cat "$work/init.txt"; fail "punt repo init failed"; }
for f in .github/workflows/lint.yml .github/workflows/test.yml .github/workflows/docs.yml \
    .github/workflows/release.yml .claude/settings.json CLAUDE.md; do
    [ -s "$f" ] || fail "punt repo init did not create $f"
done
grep -q '^  published-smoke:$' .github/workflows/release.yml \
    || fail "scaffolded release.yml has no published-smoke job"
# shellcheck disable=SC2016 # the literal workflow text, not an expansion
grep -qF '"smoke-demo==$version"' .github/workflows/release.yml \
    || fail "scaffolded release.yml does not smoke-install smoke-demo from PyPI"

# The audit fails on files init leaves to the author; every check init owns must pass.
set +e
"$punt" repo audit . >"$work/audit.txt" 2>&1
audit_rc=$?
set -e
[ "$audit_rc" -le 1 ] || { cat "$work/audit.txt"; fail "punt repo audit crashed (exit $audit_rc)"; }
for check in "CI lint workflow exists" "CI test workflow exists" "CI docs workflow exists" \
    "Linting configured ([tool.ruff])" "Type checking configured ([tool.mypy])" \
    "Type checking configured ([tool.pyright])" "Test config exists ([tool.pytest.ini_options])" \
    "Beads initialized" "CLAUDE.md exists" ".claude/settings.json exists" \
    "Standard allow rules present" "Standard deny rules present"; do
    grep -qF "✓ $check" "$work/audit.txt" || { cat "$work/audit.txt"; fail "audit check did not pass: $check"; }
done

"$punt" --json status >"$work/status.json"
"$py" -I - "$version" "$work/status.json" <<'PY'
import json
import sys
from pathlib import Path

from packaging.version import Version

expected, path = sys.argv[1:]
status = json.loads(Path(path).read_text())
want = {"punt_kit_version": Version(expected), "language": "python", "has_beads": True}
got = {key: status.get(key) for key in want}
got["punt_kit_version"] = Version(str(got["punt_kit_version"]))
if got != want:
    sys.exit(f"::error::punt status: expected {want}, got {got}")
PY

"$py" -I - "$punt" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

punt = sys.argv[1]
leaves = (
    ("repo", "init"),
    ("repo", "audit"),
    ("repo", "scan-pii"),
    ("repo", "seed"),
    ("release", "run"),
    ("enable",),
    ("disable",),
    ("status",),
    ("doctor",),
    ("version",),
    ("install",),
)

def run(*args, env=None):
    return subprocess.run(
        [punt, *args], capture_output=True, text=True, timeout=60, env=env
    )

for path in ((), ("repo",), ("release",), *leaves):
    short, long = run(*path, "-h"), run(*path, "--help")
    assert short.returncode == long.returncode == 0, (path, short.stderr)
    assert short.stdout == long.stdout and "Usage:" in short.stdout, path
assert run().stdout == run("-h").stdout
print("Installed CLI: bare help and both help flags at every command path")

def result(args, code, *, env=None):
    invocation = run(*args, env=env)
    assert invocation.returncode == code, (args, invocation)
    value = json.loads(invocation.stdout)
    if code:
        assert isinstance(value["error"], str), (args, value)
    return value

assert "changes" in result(("repo", "init", "--json"), 0)
assert result(("repo", "--json", "audit"), 1)["failed"] > 0
assert result(("repo", "scan-pii", "--staged", "--json"), 0)["findings"] == []
seed = result(("repo", "seed", "makefile", "-n", "--json"), 0)
assert seed["would_change"] == ["Makefile"] and not Path("Makefile").exists()
assert "error" in result(("release", "run", "--path", "missing", "--json"), 1)
assert "requires an argument" in result(("release", "run", "--path", "--json"), 2)["error"]
assert result(("enable", "--json"), 0)["changes"]
assert result(("disable", "--json"), 0)["changes"]
assert result(("status", "--json"), 0)["language"] == "python"
doctor = run("doctor", "--json")
health = json.loads(doctor.stdout)
assert doctor.returncode in (0, 1)
assert health if doctor.returncode == 0 else health["error"] and health["checks"]
assert "version" in result(("-q", "version", "--json"), 0)
assert "Claude Code" in result(("install", "--json"), 1, env={**os.environ, "PATH": ""})["error"]
for old in ("init", "audit", "pii", "seed", "--version", "-V"):
    result((old, "--json"), 2)
result(("release", "--dry-run", "--json"), 2)
print("Installed CLI: JSON for every verb, including operation and parser failures")
PY

echo "Release smoke passed ($mode): punt-kit $version"
