#!/usr/bin/env bash
#
# RAG 2.0 — one-shot local setup for solution/ (macOS / Linux)
#
# Works on a fresh machine with nothing but a shell: it installs `uv` if missing,
# and uv fetches the right Python for you — no system Python required.
#
# Does everything:
#   1. detects the environment + installs uv        (https://astral.sh/uv)
#   2. creates a venv with the correct Python        (uv downloads Python 3.11 if needed)
#   3. installs requirements                         (uv pip — fast, reproducible)
#   4. creates .env from .env.example                (prompts for GROQ_API_KEY if missing)
#   5. builds data/transcripts.json                  (ingests a YouTube playlist)
#   6. starts the server                             (uvicorn, serves the frontend at /)
#
# Usage:
#   ./setup.sh                          # prompts for playlist URL + Groq key as needed
#   ./setup.sh "<youtube playlist URL>"
#   PLAYLIST_URL="<url>" ./setup.sh
#
# Flags:
#   --no-serve        set up everything but don't start the server
#   --force-ingest    re-ingest even if data/transcripts.json already exists
#
# Windows: use setup.ps1 instead (PowerShell).
#
set -euo pipefail

# --- locate paths (works regardless of where the script is called from) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/solution/backend"
DATA_DIR="$SCRIPT_DIR/solution/data"
VENV_DIR="$BACKEND_DIR/.venv"
TRANSCRIPTS="$DATA_DIR/transcripts.json"
PYTHON_VERSION="3.11"

# --- parse args ---
SERVE=1
FORCE_INGEST=0
PLAYLIST_URL="${PLAYLIST_URL:-}"
for arg in "$@"; do
  case "$arg" in
    --no-serve)     SERVE=0 ;;
    --force-ingest) FORCE_INGEST=1 ;;
    --*)            echo "Unknown flag: $arg" >&2; exit 1 ;;
    *)              PLAYLIST_URL="$arg" ;;
  esac
done

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$1" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }

# --- 0. environment detection ---
OS="$(uname -s 2>/dev/null || echo unknown)"
ARCH="$(uname -m 2>/dev/null || echo unknown)"
log "Environment: $OS/$ARCH"
[ -d "$BACKEND_DIR" ] || die "solution/backend not found next to setup.sh."

# --- 1. ensure uv ---
# pull every place uv might have landed into this session's PATH
_uv_onpath() {
  [ -f "$HOME/.local/bin/env" ] && . "$HOME/.local/bin/env" 2>/dev/null || true
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"
}
ensure_uv() {
  _uv_onpath
  if command -v uv >/dev/null 2>&1; then
    log "uv found: $(uv --version)"
    return
  fi
  log "uv not installed — installing (https://astral.sh/uv)"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    die "Need curl or wget to install uv. Install one, or install uv manually: https://astral.sh/uv"
  fi
  _uv_onpath
  # last resort: the installer chose a non-standard dir — locate the binary under HOME
  if ! command -v uv >/dev/null 2>&1; then
    UV_BIN="$(find "$HOME" -maxdepth 4 -type f -name uv 2>/dev/null | head -1)"
    [ -n "$UV_BIN" ] && export PATH="$(dirname "$UV_BIN"):$PATH"
  fi
  command -v uv >/dev/null 2>&1 || die "uv installed but not found on PATH. Open a new terminal and re-run, or add ~/.local/bin to PATH."
  log "uv installed: $(uv --version)"
}
ensure_uv

cd "$BACKEND_DIR"

# --- 2. venv (uv downloads Python $PYTHON_VERSION if the machine lacks it) ---
log "Creating venv with Python $PYTHON_VERSION"
uv venv --python "$PYTHON_VERSION" "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# --- 3. dependencies ---
log "Installing dependencies (first run downloads torch etc — a few minutes)"
uv pip install -r requirements.txt

# --- 4. .env / GROQ_API_KEY ---
if [ ! -f .env ]; then
  log "Creating .env from .env.example"
  cp .env.example .env
fi
# consider the key unset if it's missing or still the placeholder
if ! grep -qE '^GROQ_API_KEY=.+' .env || grep -q '^GROQ_API_KEY=your_groq_api_key_here' .env; then
  if [ -t 0 ]; then
    log "Groq API key needed (free at https://console.groq.com/keys)"
    printf 'Paste your GROQ_API_KEY: '
    read -r KEY
    if [ -n "$KEY" ]; then
      grep -v '^GROQ_API_KEY=' .env > .env.tmp || true
      printf 'GROQ_API_KEY=%s\n' "$KEY" >> .env.tmp
      mv .env.tmp .env
    else
      warn "No key entered — edit solution/backend/.env before asking questions."
    fi
  else
    warn "GROQ_API_KEY not set in .env — edit solution/backend/.env before asking questions."
  fi
fi

# --- 5. transcripts.json (the data the app is missing) ---
if [ "$FORCE_INGEST" -eq 0 ] && [ -s "$TRANSCRIPTS" ]; then
  log "Found existing $TRANSCRIPTS — skipping ingest (use --force-ingest to rebuild)"
else
  if [ -z "$PLAYLIST_URL" ] && [ -t 0 ]; then
    log "No transcripts yet — need a YouTube playlist to ingest"
    printf 'Paste a YouTube playlist URL: '
    read -r PLAYLIST_URL
  fi
  [ -n "$PLAYLIST_URL" ] || die "No playlist URL. Re-run: ./setup.sh \"<youtube playlist URL>\""
  log "Ingesting playlist into $TRANSCRIPTS"
  python -m app.ingest --playlist "$PLAYLIST_URL"
  [ -s "$TRANSCRIPTS" ] || die "Ingest produced no data (videos may lack captions). Check the playlist and retry."
fi

# --- 6. run ---
if [ "$SERVE" -eq 1 ]; then
  log "Starting server at http://127.0.0.1:8000  (Ctrl-C to stop)"
  exec uvicorn app.main:app --reload
else
  log "Setup complete. Start the server with:"
  printf '    cd solution/backend && source .venv/bin/activate && uvicorn app.main:app --reload\n'
fi
