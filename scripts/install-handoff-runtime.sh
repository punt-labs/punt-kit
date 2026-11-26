#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 1 || $(uname -s)/$(uname -m) != Linux/x86_64 ]]; then
    printf 'usage (Linux x86_64): %s [LOCAL_ARCHIVE]\n' "$0" >&2
    exit 2
fi

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
sidecar=$repo/.punt-labs/ethos/checks/snapshots/punt-kit.yaml
pin=$(python3 -I - "$sidecar" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as sidecar:
        entry = json.load(sidecar)["checks"]["full-gate"]["runtime"]["platforms"]["linux-amd64"]
    url, sha = entry["url"], entry["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", sha) or not re.fullmatch(
        r"https://github\.com/punt-labs/punt-kit/releases/download/"
        r"handoff-runtime-v[1-9][0-9]*/punt-kit-linux-amd64-v[1-9][0-9]*\.tar\.gz", url
    ):
        raise ValueError
except (OSError, KeyError, TypeError, ValueError):
    sys.exit("Invalid punt-kit snapshot runtime pin for linux-amd64.")
print(url, sha)
PY
)
read -r url sha <<< "$pin"

store=$HOME/.punt-labs/ethos/runtimes
archive=$store/$sha.tar.gz
umask 077
mkdir -p -- "$store"
if [[ ! -O $store || -L $store ]]; then
    echo 'Runtime store must be a directory you own, not a symlink.' >&2
    exit 1
fi
chmod 700 -- "$store"

matches_pin() {
    local actual
    actual=$(sha256sum -- "$1") && [[ ${actual%% *} == "$sha" ]]
}
if [[ ! -L $archive && -f $archive ]] && matches_pin "$archive"; then
    printf '%s\n' "$archive"
    exit 0
fi

download=$(mktemp "$store/.punt-kit-runtime.XXXXXX")
trap 'rm -f -- "$download"' EXIT
if [[ $# == 1 ]]; then
    cp -- "$1" "$download"
else
    curl --proto '=https' --proto-redir '=https' --fail --silent --show-error \
        --connect-timeout 15 --retry 2 --retry-max-time 120 --max-time 300 \
        --max-filesize 1073741824 --location --output "$download" "$url"
fi
if ! matches_pin "$download"; then
    printf 'punt-kit snapshot runtime checksum mismatch; expected %s.\n' "$sha" >&2
    exit 1
fi
mv -T -- "$download" "$archive"
printf '%s\n' "$archive"
