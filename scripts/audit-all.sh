#!/usr/bin/env bash
set -euo pipefail

# Run punt audit across all sibling projects that look like real repos.
# Usage: bash scripts/audit-all.sh [--fix]

for dir in ../*/; do
    if [ -f "$dir/pyproject.toml" ] || [ -f "$dir/package.json" ] || [ -f "$dir/project.yml" ]; then
        echo "=== $(basename "$dir") ==="
        punt audit "$dir" "$@" || true
        echo
    fi
done
