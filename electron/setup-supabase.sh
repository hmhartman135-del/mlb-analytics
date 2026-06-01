#!/bin/bash
# =============================================================================
# setup-supabase.sh — Migrate your local PostgreSQL to Supabase.
#
# Run this ONCE before building the shareable app.
# It creates all your tables and loads your existing data into Supabase.
#
# Usage:
#   ./electron/setup-supabase.sh <SUPABASE_DB_URL>
#
# Where SUPABASE_DB_URL looks like:
#   postgresql://postgres.XXXX:PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres
#
# Get it from: supabase.com → your project → Settings → Database → Connection string
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}▸${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
error() { echo -e "${RED}✗${NC} $*"; exit 1; }

if [ -z "${1:-}" ]; then
  echo "Usage: ./electron/setup-supabase.sh <SUPABASE_POSTGRES_URL>"
  echo ""
  echo "Get your URL from:"
  echo "  supabase.com → your project → Settings → Database → Connection string → URI"
  echo "  (Use the 'Transaction mode' URL on port 6543 for asyncpg)"
  exit 1
fi

SUPABASE_URL="$1"
# asyncpg needs postgresql+asyncpg:// prefix for SQLAlchemy
ASYNCPG_URL="${SUPABASE_URL/postgresql:\/\//postgresql+asyncpg://}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Supabase Migration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Step 1: Create tables in Supabase ─────────────────────────────────────────
info "Creating tables in Supabase…"
cd "$BACKEND"
DATABASE_URL="$ASYNCPG_URL" .venv/bin/python3 -c "
import asyncio, os
os.environ['DATABASE_URL'] = '$ASYNCPG_URL'
from dotenv import load_dotenv
load_dotenv()
import os; os.environ['DATABASE_URL'] = '$ASYNCPG_URL'

from app.core.database import engine, Base
from app.models import team, player, stats, spotrac_fa  # noqa

async def create():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from sqlalchemy import text
        await conn.execute(text(
            'ALTER TABLE players ADD COLUMN IF NOT EXISTS roster_status VARCHAR(16)'
        ))
    await engine.dispose()
    print('Tables created.')

asyncio.run(create())
"
ok "Tables created in Supabase"

# ── Step 2: Dump local data ───────────────────────────────────────────────────
info "Dumping local database…"
LOCAL_DB="${DATABASE_URL:-postgresql://postgres:password@localhost:5432/mlb_analytics}"
# Strip asyncpg prefix if present
LOCAL_PG="${LOCAL_DB/postgresql+asyncpg:\/\//postgresql://}"

DUMP_FILE="/tmp/mlb_analytics_dump.sql"
pg_dump --data-only --no-owner --no-privileges "$LOCAL_PG" \
  --table=teams \
  --table=players \
  --table=batting_stats \
  --table=pitching_stats \
  --table=spotrac_free_agents \
  > "$DUMP_FILE" 2>/dev/null || {
    warn "pg_dump not found or local DB unavailable."
    warn "Skipping data migration — the app will load fresh data from the MLB Stats API on first launch."
    info "Writing app-config.json with Supabase URL…"
    python3 - <<PYEOF
import json, pathlib
cfg_path = pathlib.Path("$ROOT/electron/app-config.json")
cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
cfg["database_url"] = "$ASYNCPG_URL"
cfg_path.write_text(json.dumps(cfg, indent=2))
print(f"  Written to {cfg_path}")
PYEOF
    ok "app-config.json updated with Supabase URL"
    exit 0
  }
ok "Local data dumped to $DUMP_FILE ($(du -sh "$DUMP_FILE" | cut -f1))"

# ── Step 3: Load data into Supabase ──────────────────────────────────────────
info "Loading data into Supabase…"
SUPABASE_PG="${SUPABASE_URL}"
psql "$SUPABASE_PG" < "$DUMP_FILE" && ok "Data loaded into Supabase" || \
  warn "psql load had warnings — check output above"

rm -f "$DUMP_FILE"

# ── Step 4: Update app-config.json ───────────────────────────────────────────
info "Updating app-config.json…"
python3 - <<PYEOF
import json, pathlib
cfg_path = pathlib.Path("$ROOT/electron/app-config.json")
cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
cfg["database_url"] = "$ASYNCPG_URL"
cfg_path.write_text(json.dumps(cfg, indent=2))
print(f"  Written to {cfg_path}")
PYEOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ok "Supabase setup complete!"
echo ""
echo "  Next step: run  ./electron/build-app.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
