#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'usage (Linux x86_64): %s [--apply | LOCAL_ARCHIVE]\n' "$0"
    printf 'Without arguments, preview installation; use --apply to download the pinned runtime.\n'
}

if [[ $# -gt 1 ]]; then
    usage >&2
    exit 2
fi
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    --apply) ;;
    -*) usage >&2; exit 2 ;;
esac

if [[ $(uname -s)/$(uname -m) != Linux/x86_64 ]]; then
    usage >&2
    exit 2
fi

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
sidecar=$repo/.punt-labs/ethos/checks/snapshots/punt-kit.yaml
pin=$(python3 -IB - "$sidecar" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as sidecar:
        entry = json.load(sidecar)["checks"]["full-gate"]["runtime"]["platforms"]["linux-amd64"]
    url, sha = entry["url"], entry["sha256"]
    release = re.fullmatch(
        r"https://github\.com/punt-labs/punt-kit/releases/download/"
        r"handoff-runtime-v(?P<version>[1-9][0-9]*)/punt-kit-linux-amd64-v(?P=version)\.tar\.gz", url
    )
    if (
        not re.fullmatch(r"[0-9a-f]{64}", sha)
        or release is None
        or entry["bundle"] != f"punt-kit-linux-amd64-v{release['version']}"
    ):
        raise ValueError
except (OSError, KeyError, TypeError, ValueError):
    sys.exit("Invalid punt-kit snapshot runtime pin for linux-amd64.")
print(url, sha, entry["bundle"])
PY
)
read -r url sha bundle <<< "$pin"

store=$HOME/.punt-labs/ethos/runtimes
archive=$store/$sha.tar.gz
if [[ -z ${1:-} ]]; then
    printf 'Bundle: %s\nURL: %s\nSHA-256: %s\nDestination: %s\n' "$bundle" "$url" "$sha" "$archive"
    printf 'Use --apply to install this runtime.\n'
    exit 0
fi
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
if [[ $1 == --apply ]]; then
    curl --proto '=https' --proto-redir '=https' --fail --silent --show-error \
        --connect-timeout 15 --retry 2 --retry-max-time 120 --max-time 300 \
        --max-filesize 1073741824 --location --output "$download" "$url"
else
    cp -- "$1" "$download"
fi
if ! matches_pin "$download"; then
    printf 'punt-kit snapshot runtime checksum mismatch; expected %s.\n' "$sha" >&2
    exit 1
fi
mv -T -- "$download" "$archive"
printf '%s\n' "$archive"
