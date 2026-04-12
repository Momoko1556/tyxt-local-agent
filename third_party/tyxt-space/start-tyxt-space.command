#!/bin/bash
# TYXT Space — launcher
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TYXT_ROOT_CA="$PROJECT_ROOT/certs/lan/rootCA.pem"
if [ -z "${NODE_EXTRA_CA_CERTS:-}" ] && [ -f "$TYXT_ROOT_CA" ]; then
  export NODE_EXTRA_CA_CERTS="$TYXT_ROOT_CA"
  echo "[TYXT Space] Using local TYXT root CA for backend HTTPS checks."
fi

# ── Load OPENAI_API_KEY from openclaw.json ──────────────────────────────────
OPENAI_API_KEY=$(node -e "
try {
  const fs = require('fs');
  const p = process.env.OPENCLAW_CONFIG || (process.env.HOME ? (process.env.HOME + '/.openclaw/openclaw.json') : '');
  const c = JSON.parse(fs.readFileSync(p, 'utf8'));
  process.stdout.write((c.env && c.env.vars && c.env.vars.OPENAI_API_KEY) || '');
} catch(e) { process.stdout.write(''); }
" 2>/dev/null)

# ── Kill any stale auto-focus.mjs processes ─────────────────────────────────
pkill -f "node scripts/auto-focus.mjs" 2>/dev/null || true
pkill -f "node.*auto-focus.mjs" 2>/dev/null || true
sleep 1

# ── Start auto-focus sidecar ────────────────────────────────────────────────
LOG_FILE="/tmp/auto-focus-$(date +%Y%m%d).log"
OPENAI_API_KEY="$OPENAI_API_KEY" node scripts/auto-focus.mjs >> "$LOG_FILE" 2>&1 &
AUTO_FOCUS_PID=$!
echo "[TYXT Space] auto-focus.mjs started (PID: $AUTO_FOCUS_PID, log: $LOG_FILE)"

# ── Cleanup on exit ─────────────────────────────────────────────────────────
cleanup() {
  echo "[TYXT Space] Shutting down auto-focus.mjs (PID: $AUTO_FOCUS_PID)..."
  kill "$AUTO_FOCUS_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── Start TYXT Space (blocking) ──────────────────────────────────────
npm run dev

