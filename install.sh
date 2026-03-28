#!/bin/sh
# Install punt — standards tooling for Punt Labs projects.
# Usage: curl -fsSL https://raw.githubusercontent.com/punt-labs/punt-kit/<SHA>/install.sh | sh
set -eu

# --- Colors (disabled when not a terminal) ---
if [ -t 1 ]; then
  BOLD='\033[1m' GREEN='\033[32m' YELLOW='\033[33m' NC='\033[0m'
else
  BOLD='' GREEN='' YELLOW='' NC=''
fi

info() { printf '%b▶%b %s\n' "$BOLD" "$NC" "$1"; }
ok()   { printf '  %b✓%b %s\n' "$GREEN" "$NC" "$1"; }
warn() { printf '  %b!%b %s\n' "$YELLOW" "$NC" "$1"; }
fail() { printf '  %b✗%b %s\n' "$YELLOW" "$NC" "$1"; exit 1; }

PACKAGE="punt-kit"
VERSION="0.11.0"
BINARY="punt"

# --- Step 1: uv ---

info "Checking uv..."

if command -v uv >/dev/null 2>&1; then
  ok "uv already installed"
else
  info "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  if [ -f "$HOME/.local/bin/env" ]; then
    # shellcheck source=/dev/null
    . "$HOME/.local/bin/env"
  elif [ -f "$HOME/.cargo/env" ]; then
    # shellcheck source=/dev/null
    . "$HOME/.cargo/env"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    fail "uv install succeeded but 'uv' not found on PATH. Restart your shell and re-run."
  fi
  ok "uv installed"
fi

# --- Step 2: Python 3.13+ ---

info "Checking Python..."

PYTHON_FLAG=""
HAVE_PYTHON=0
if command -v python3 >/dev/null 2>&1; then
  PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
  PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
  if [ "$PY_MAJOR" -gt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 13 ]; }; then
    ok "Python ${PY_MAJOR}.${PY_MINOR}"
    HAVE_PYTHON=1
  fi
fi

if [ "$HAVE_PYTHON" = "0" ]; then
  info "Installing Python 3.13 via uv..."
  uv python install 3.13 || fail "Failed to install Python 3.13"
  ok "Python 3.13 (uv-managed)"
  PYTHON_FLAG="--python 3.13"
fi

# --- Step 3: punt-kit ---

info "Installing $PACKAGE..."

# shellcheck disable=SC2086
uv tool install --force $PYTHON_FLAG "$PACKAGE==$VERSION" || fail "Failed to install $PACKAGE==$VERSION"
ok "$PACKAGE==$VERSION installed"

if ! command -v "$BINARY" >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v "$BINARY" >/dev/null 2>&1; then
    fail "$PACKAGE installed but '$BINARY' not found on PATH"
  fi
fi

ok "$BINARY $(command -v "$BINARY")"

# --- Step 4: Claude Code plugin (optional) ---

if command -v claude >/dev/null 2>&1; then
  info "Setting up Claude Code plugin..."

  if ! command -v git >/dev/null 2>&1; then
    warn "'git' not found — skipping plugin install"
    printf '  Install git (https://git-scm.com/downloads), then run: claude plugin install punt@punt-labs\n'
  else

  NEED_HTTPS_REWRITE=0
  cleanup_https_rewrite() {
    if [ "$NEED_HTTPS_REWRITE" = "1" ]; then
      git config --global --unset url."https://github.com/".insteadOf 2>/dev/null || true
      NEED_HTTPS_REWRITE=0
    fi
  }
  trap cleanup_https_rewrite EXIT INT TERM

  if ! ssh -n -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=5 -T git@github.com 2>&1 | grep -q "successfully authenticated"; then
    if ! git config --global --get url."https://github.com/".insteadOf >/dev/null 2>&1; then
      warn "SSH auth to GitHub unavailable, using HTTPS fallback"
      git config --global url."https://github.com/".insteadOf "git@github.com:"
      NEED_HTTPS_REWRITE=1
    fi
  fi

  if claude plugin marketplace list < /dev/null 2>/dev/null | grep -q "punt-labs"; then
    ok "marketplace already registered"
    claude plugin marketplace update "punt-labs" < /dev/null 2>/dev/null || true
  else
    claude plugin marketplace add "punt-labs/claude-plugins" < /dev/null || warn "Failed to register marketplace"
    ok "marketplace registered"
  fi

  claude plugin uninstall punt@punt-labs < /dev/null 2>/dev/null || true
  if claude plugin install punt@punt-labs --scope user < /dev/null 2>/dev/null; then
    if claude plugin list < /dev/null 2>/dev/null | grep -q "punt@punt-labs"; then
      ok "Claude Code plugin installed"
    else
      warn "Plugin install reported success but plugin not found (install manually: claude plugin install punt@punt-labs)"
    fi
  else
    warn "Failed to install plugin (install manually: claude plugin install punt@punt-labs)"
  fi

  cleanup_https_rewrite

  fi
else
  warn "Claude Code not found — skipping plugin install"
  printf '  Install Claude Code, then run: claude plugin install punt@punt-labs\n'
fi

# --- Done ---

printf '\n%b%b%s is ready!%b\n\n' "$GREEN" "$BOLD" "$PACKAGE" "$NC"
