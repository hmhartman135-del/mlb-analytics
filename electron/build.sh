#!/bin/bash
# build.sh — Build the distributable desktop app.
# Run from the repo root:  ./electron/build.sh
#
# Output:
#   electron/dist/MLB Analytics.dmg        (Mac)
#   electron/dist/MLB Analytics Setup.exe  (Windows)
#   electron/dist/MLB Analytics.AppImage   (Linux)

set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
ELECTRON_DIR="$ROOT/electron"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MLB Analytics — Desktop App Builder"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Build Next.js ──────────────────────────────────────────────────────────
echo ""
echo "▸ Building Next.js frontend…"
cd "$ROOT/frontend"
NEXT_PUBLIC_API_URL="http://127.0.0.1:8000" npm run build

# ── 2. Install Electron deps ──────────────────────────────────────────────────
echo ""
echo "▸ Installing Electron dependencies…"
cd "$ELECTRON_DIR"
npm install

# ── 3. Package with electron-builder ─────────────────────────────────────────
echo ""
echo "▸ Packaging with electron-builder…"
npm run build

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Done!  Output → electron/dist/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
