#!/bin/sh
# Install all Punt Labs tools and Claude Code plugins.
# Usage: curl -fsSL https://raw.githubusercontent.com/punt-labs/punt-kit/<SHA>/install-all.sh | sh
#
# This is a thin orchestrator. Each CLI tool has its own installer that handles
# pre-flight checks, uv setup, and plugin registration independently. This
# script curls them in sequence and adds the pure-plugin installs that have no
# standalone installer. Child installer URLs are pinned to auditable SHAs.
set -eu

# --- Colors (disabled when not a terminal) ---
if [ -t 1 ]; then
  BOLD='\033[1m' GREEN='\033[32m' YELLOW='\033[33m' NC='\033[0m'
else
  BOLD='' GREEN='' YELLOW='' NC=''
fi

info()   { printf '%b▶%b %s\n' "$BOLD" "$NC" "$1"; }
ok()     { printf '  %b✓%b %s\n' "$GREEN" "$NC" "$1"; }
warn()   { printf '  %b!%b %s\n' "$YELLOW" "$NC" "$1"; }
fail()   { printf '  %b✗%b %s\n' "$YELLOW" "$NC" "$1"; exit 1; }
banner() { printf '\n%b── %s ──%b\n\n' "$BOLD" "$1" "$NC"; }

GH="https://raw.githubusercontent.com/punt-labs"

# --- Pre-flight: Claude Code CLI ---

info "Checking Claude Code..."

if command -v claude >/dev/null 2>&1; then
  ok "claude CLI found"
else
  fail "'claude' CLI not found. Install Claude Code first: https://docs.anthropic.com/en/docs/claude-code"
fi

# --- Step 1: Marketplace ---

banner "Marketplace"
curl -fsSL "$GH/claude-plugins/8ba82a3/install.sh" | sh

# --- Step 2: CLI tools ---
# Each installer handles its own pre-flight (Python, uv, SSH fallback).

banner "punt-kit"
curl -fsSL "$GH/punt-kit/7bf2735/install.sh" | sh

banner "biff"
curl -fsSL "$GH/biff/419ac99/install.sh" | sh

banner "quarry"
curl -fsSL "$GH/quarry/0e4e6d1/install.sh" | sh

banner "tts"
curl -fsSL "$GH/tts/2d8922f/install.sh" | sh

# --- Step 3: Pure plugins (no CLI, marketplace-only) ---

banner "Plugins"

NEED_HTTPS_REWRITE=0
cleanup_https_rewrite() {
  if [ "$NEED_HTTPS_REWRITE" = "1" ]; then
    git config --global --unset url."https://github.com/".insteadOf 2>/dev/null || true
    NEED_HTTPS_REWRITE=0
  fi
}
trap cleanup_https_rewrite EXIT INT TERM

if ! ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=5 -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
  if ! git config --global --get url."https://github.com/".insteadOf >/dev/null 2>&1; then
    warn "SSH auth to GitHub unavailable, using HTTPS fallback"
    git config --global url."https://github.com/".insteadOf "git@github.com:"
    NEED_HTTPS_REWRITE=1
  fi
fi

for plugin in prfaq dungeon z-spec; do
  info "Installing $plugin plugin..."
  if claude plugin install "$plugin@punt-labs" --scope user 2>/dev/null; then
    ok "$plugin"
  else
    warn "Failed to install $plugin (install manually: claude plugin install $plugin@punt-labs)"
  fi
done

cleanup_https_rewrite

# --- Done ---

printf '\n%b%bAll Punt Labs tools are installed!%b\n\n' "$GREEN" "$BOLD" "$NC"
printf 'CLIs:    punt, biff, quarry, tts\n'
printf 'Plugins: biff, dungeon, prfaq, punt, quarry, tts, z-spec\n\n'
printf 'Restart Claude Code twice to activate all plugins.\n\n'
