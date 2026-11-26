#!/usr/bin/env bash
set -euo pipefail

# Run punt repo audit across all sibling projects that look like real repos.
# Usage: bash scripts/audit-all.sh [--fix]
# Exits non-zero if any project fails.

failures=0

for dir in ../*/; do
    if [ -f "$dir/pyproject.toml" ] || [ -f "$dir/package.json" ] || [ -f "$dir/project.yml" ]; then
        echo "=== $(basename "$dir") ==="
        if ! punt repo audit "$dir" "$@"; then
            failures=$((failures + 1))
        fi
        echo
    fi
done

if [ "$failures" -gt 0 ]; then
    echo "=== $failures project(s) failed ==="
    exit 1
fi
