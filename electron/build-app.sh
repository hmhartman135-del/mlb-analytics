#!/bin/bash
# =============================================================================
# build-app.sh — Build MLB Analytics as a shareable desktop installer.
#
# Usage (from the repo root):
#   ./electron/build-app.sh
#
# Prerequisites:
#   1. You have set up your Supabase database (see SETUP.md)
#   2. You have filled in electron/app-config.json
#   3. macOS: Xcode CLI tools installed  (xcode-select --install)
#   4: Python venv with all deps installed (cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)
#
# Output:
#   electron/dist/MLB Analytics-1.0.0.dmg          (Mac)
#   electron/dist/MLB Analytics Setup 1.0.0.exe    (Windows)
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ELECTRON="$ROOT/electron"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
CONFIG="$ELECTRON/app-config.json"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}▸${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✗${NC} $*"; exit 1; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MLB Analytics — Desktop App Builder"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 0: Check app-config.json ────────────────────────────────────────────
info "Checking build config…"
if [ ! -f "$CONFIG" ]; then
  error "Missing $CONFIG — copy app-config.template.json to app-config.json and fill it in."
fi

DB_URL=$(python3 -c "import json; c=json.load(open('$CONFIG')); print(c.get('database_url',''))" 2>/dev/null || echo "")
if [ -z "$DB_URL" ]; then
  error "database_url is empty in app-config.json — add your Supabase connection string."
fi
ok "Config loaded"

# ── Step 1: Write the bundled .env for PyInstaller ────────────────────────────
info "Writing bundled .env for backend binary…"
python3 - <<PYEOF
import json, pathlib

config = json.loads(pathlib.Path("$CONFIG").read_text())
env_path = pathlib.Path("$BACKEND/.env.bundled")

lines = [
    f'DATABASE_URL={config["database_url"]}',
    f'ANTHROPIC_API_KEY={config.get("anthropic_api_key", "")}',
    "DEBUG=false",
    "REDIS_URL=",
]
env_path.write_text("\n".join(lines) + "\n")
print(f"  Written to {env_path}")
PYEOF
ok "Bundled .env written"

# ── Step 2: Install Python deps + PyInstaller ─────────────────────────────────
info "Installing PyInstaller…"
cd "$BACKEND"
.venv/bin/pip install pyinstaller --quiet
ok "PyInstaller ready"

# ── Step 3: Build Python backend binary ───────────────────────────────────────
info "Building backend binary (this takes ~2 minutes)…"
.venv/bin/pyinstaller mlb_backend.spec --clean --noconfirm 2>&1 | tail -20

BINARY="$BACKEND/dist/mlb-backend"
[ -f "$BINARY" ] || error "PyInstaller failed — binary not found at $BINARY"
ok "Backend binary built: $(du -sh "$BINARY" | cut -f1)"

# Clean up the bundled .env (don't leave credentials on disk longer than needed)
rm -f "$BACKEND/.env.bundled"

# ── Step 4: Build Next.js ─────────────────────────────────────────────────────
info "Building Next.js frontend…"
cd "$FRONTEND"
NEXT_PUBLIC_API_URL="http://127.0.0.1:8000" npm run build 2>&1 | tail -10

STANDALONE="$FRONTEND/.next/standalone"
[ -d "$STANDALONE" ] || error "Next.js build failed — .next/standalone not found. Make sure next.config.js has output: 'standalone'."
ok "Next.js built"

# ── Step 5: Install Electron deps ─────────────────────────────────────────────
info "Installing Electron dependencies…"
cd "$ELECTRON"
npm install --quiet
ok "Electron deps ready"

# ── Step 6: Package with electron-builder ────────────────────────────────────
info "Packaging app with electron-builder…"
npm run "build:$(uname -s | tr '[:upper:]' '[:lower:]' | sed 's/darwin/mac/')" 2>&1 | tail -20

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ok "Done!  Your installer is in: electron/dist/"
ls -lh "$ELECTRON/dist/"*.{dmg,exe,AppImage} 2>/dev/null || true
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
