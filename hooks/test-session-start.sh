#!/usr/bin/env bash
# Temporary test: verify SessionStart hooks work from plugin cache.
# This file will be removed after verification.
echo "PUNT PLUGIN SessionStart hook fired. CLAUDE_PLUGIN_ROOT resolved to: $(cd "$(dirname "$0")/.." && pwd)"
