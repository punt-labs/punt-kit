#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 1 || ! -d $1 || $(uname -s)/$(uname -m) != Linux/x86_64 ]]; then
    printf 'usage (Linux x86_64): %s OUTPUT_DIRECTORY\n' "$0" >&2
    exit 2
fi

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
output=$(cd -- "$1" && pwd -P)
uv_tool=$(command -v uv)
node_tool=$(node -p 'process.execPath')
node_home=$(dirname -- "$(dirname -- "$node_tool")")
if [[ $(uv --version) != 'uv 0.13.9 '* || $(node --version) != v24.22.3 ||
      ! -f $node_home/lib/node_modules/npm/bin/npx-cli.js ]]; then
    echo 'Use uv 0.13.9 and the upstream Node v24.22.3 distribution with npm.' >&2
    exit 1
fi

work=$(mktemp -d "$output/.punt-kit-runtime.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
runtime=$work/runtime
mkdir -p "$runtime/bin" "$runtime/node/bin" "$runtime/node/lib/node_modules" \
    "$runtime/cache/uv" "$runtime/cache/npm" "$runtime/licenses" "$work/home" "$work/tmp"
install -m 0755 "$uv_tool" "$runtime/bin/uv"
install -m 0755 "$node_tool" "$runtime/node/bin/node"
cp -RP "$node_home/lib/node_modules/npm" "$runtime/node/lib/node_modules/npm"
ln -s ../lib/node_modules/npm/bin/npm-cli.js "$runtime/node/bin/npm"
ln -s ../lib/node_modules/npm/bin/npx-cli.js "$runtime/node/bin/npx"
install -m 0644 "$node_home/LICENSE" "$runtime/licenses/node-LICENSE"
for notice in LICENSE-APACHE LICENSE-MIT; do
    curl --proto '=https' --proto-redir '=https' --fail --silent --show-error \
        --location --connect-timeout 15 --max-time 180 --output "$runtime/licenses/uv-$notice" \
        "https://raw.githubusercontent.com/astral-sh/uv/0.13.9/$notice"
    test -s "$runtime/licenses/uv-$notice"
done
(
    cd "$runtime/licenses"
    sha256sum --check --status <<'SUMS'
c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4  uv-LICENSE-APACHE
860e3d7a86b84e6a7012c7a635fc64df475cebc6cce34dfeb73a5982ec58176c  uv-LICENSE-MIT
SUMS
) || { echo 'uv license checksum mismatch.' >&2; exit 1; }

isolated=(env -i "HOME=$work/home" "TMPDIR=$work/tmp"
    "PATH=$runtime/bin:$runtime/node/bin:/usr/bin:/bin" LC_ALL=C TZ=UTC PYTHONDONTWRITEBYTECODE=1)
python_env=("${isolated[@]}" "UV_PYTHON_INSTALL_DIR=$work/python" "UV_CACHE_DIR=$work/python-cache")
"${python_env[@]}" uv --no-config python install 3.13.18 --no-bin >&2
python_tool=$("${python_env[@]}" uv --no-config python find --managed-python --no-project 3.13.18)
python_home=$("${isolated[@]}" "$python_tool" -I -c 'import sys; print(sys.base_prefix)')
mv -- "$python_home" "$runtime/python"
python_tool=$runtime/python/bin/python3.13

uv_env=("${isolated[@]}" "UV_PYTHON=$python_tool" UV_PYTHON_DOWNLOADS=never
    "UV_CACHE_DIR=$runtime/cache/uv" "UV_PROJECT_ENVIRONMENT=$work/venv" UV_LINK_MODE=copy)
"${uv_env[@]}" uv --no-config --directory "$repo" sync --locked --no-install-project >&2
# Resolve the build backend using the same constraints as a fresh editable build.
"${isolated[@]}" "$python_tool" -I -c '
import sys, tomllib
with open(sys.argv[1], "rb") as config:
    print(*tomllib.load(config)["build-system"]["requires"], sep="\n")
' "$repo/pyproject.toml" > "$work/build-requirements.txt"
"${uv_env[@]}" uv --no-config pip install --python "$work/venv/bin/python" \
    --requirements "$work/build-requirements.txt" >&2
# The release-smoke tests resolve packaging outside the locked project.
"${uv_env[@]}" uv --no-config pip install --python "$work/venv/bin/python" \
    --reinstall-package packaging packaging >&2

npm_env=("${isolated[@]}" "npm_config_cache=$runtime/cache/npm" npm_config_ignore_scripts=true
    npm_config_audit=false npm_config_fund=false npm_config_update_notifier=false)
(
    cd "$work"
    "${npm_env[@]}" npx --yes --package=markdownlint-cli2@0.24.2 -- node --version >&2
    npm_version=$("${npm_env[@]}" npm_config_offline=true npx --yes markdownlint-cli2 --version)
    [[ $npm_version == 'markdownlint-cli2 v0.24.2 '* ]]
)
rm -rf -- "$runtime/cache/npm/_logs"
rm -f -- "$runtime/cache/npm/_update-notifier-last-checked"
{
    "${isolated[@]}" uv --version
    "${isolated[@]}" "$python_tool" --version
    "${isolated[@]}" node --version
    "${isolated[@]}" npm --version
} > "$runtime/versions.txt"

"${isolated[@]}" "$python_tool" -I -c '
import os, pathlib, sys
root = pathlib.Path(sys.argv[1])
for directory, dirs, files in os.walk(root):
    for name in dirs + files:
        path = pathlib.Path(directory, name)
        if path.is_symlink() and (
            path.readlink().is_absolute() or not path.resolve().is_relative_to(root)
        ):
            sys.exit(f"Unsafe runtime symlink: {path.relative_to(root)}")
' "$runtime"

LC_ALL=C tar --sort=name --format=gnu --mtime=@0 --numeric-owner \
    --owner=0 --group=0 --hard-dereference -C "$runtime" -cf - bin cache licenses node python versions.txt \
    | gzip -n > "$work/runtime.tar.gz"
sha=$(sha256sum "$work/runtime.tar.gz")
archive=$output/${sha%% *}.tar.gz
mv -- "$work/runtime.tar.gz" "$archive"
printf '%s\n' "$archive"
