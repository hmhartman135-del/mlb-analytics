"""
fix_prospect_positions.py
──────────────────────────
Fixes incorrect positions for draft prospects using the already-scraped
Pipeline data (no network calls needed).

What went wrong:
  - `upsert_pipeline_prospect` updates draft_rank for existing players
    but never updates their position.
  - Many prospects were first inserted via the MLB Stats API with generic
    positions like "RF" (for all outfielders).
  - When the Pipeline upsert found them, it kept the wrong position.

This script:
  1. Reads pipeline_data/draft_prospects_scraped.json  (150 top prospects)
  2. For each, finds the matching player in the DB
  3. Applies the correct position from the Pipeline data
  4. Also fixes multi-position entries (e.g. "OF/1B" → "CF")

Run from backend/:
    .venv/bin/python3 -m scripts.fix_prospect_positions
"""

import asyncio
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics"
)

from app.models.player import Player  # noqa
from app.models.team import Team  # noqa
from app.models.stats import BattingStats, PitchingStats  # noqa  — must be imported to satisfy ORM relationships

DATA_DIR = Path(__file__).parent / "pipeline_data"

# ── Position normalisation ─────────────────────────────────────────────────────
# For slash-separated multi-position entries, take the primary (first) position.
POS_MAP = {
    "RHP": "SP", "LHP": "SP", "TWP": "SP", "P": "SP", "SP": "SP",
    "RP": "RP",
    "C": "C",
    "1B": "1B", "2B": "2B", "3B": "3B", "SS": "SS",
    "LF": "LF", "CF": "CF", "RF": "RF",
    "OF": "CF",   # generic OF → CF
    "DH": "DH", "IF": "3B", "UTIL": "DH",
}


def _normalise_pos(raw: str | None) -> str | None:
    if not raw:
        return None
    # Handle slash-separated (take first)
    primary = raw.split("/")[0].strip().upper()
    return POS_MAP.get(primary, primary[:4])


# ── DB helpers ─────────────────────────────────────────────────────────────────

async def find_player(session: AsyncSession, mlb_id: int | None, name: str) -> Player | None:
    if mlb_id:
        r = await session.execute(select(Player).where(Player.mlb_id == mlb_id))
        p = r.scalar_one_or_none()
        if p:
            return p
    # Name fallback — exact ilike
    r = await session.execute(
        select(Player).where(Player.full_name.ilike(name))
    )
    p = r.scalars().first()
    if p:
        return p
    # Looser: first + last name
    parts = name.split()
    if len(parts) >= 2:
        r = await session.execute(
            select(Player).where(
                Player.full_name.ilike(f"%{parts[0]}%{parts[-1]}%")
            )
        )
        return r.scalars().first()
    return None


async def run():
    scraped_file = DATA_DIR / "draft_prospects_scraped.json"
    if not scraped_file.exists():
        print(f"ERROR: {scraped_file} not found — run ingest_all_draft_prospects.py first.")
        return

    prospects = json.loads(scraped_file.read_text())
    print(f"Loaded {len(prospects)} scraped prospects from Pipeline")

    engine = create_async_engine(DATABASE_URL, echo=False)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    updated = 0
    skipped = 0
    not_found = 0

    async with S() as session:
        for entry in prospects:
            name     = (entry.get("name") or "").strip()
            raw_pos  = entry.get("position") or ""
            mlb_id   = entry.get("mlb_id")
            new_pos  = _normalise_pos(raw_pos)
            rank     = entry.get("rank")

            if not name:
                skipped += 1
                continue

            player = await find_player(session, mlb_id, name)
            if not player:
                not_found += 1
                print(f"  NOT FOUND: {name} (rank={rank}, pos={raw_pos})")
                continue

            changed = []
            if new_pos and player.position != new_pos:
                changed.append(f"pos {player.position!r} → {new_pos!r}")
                player.position = new_pos
            if rank and player.draft_rank != rank:
                changed.append(f"rank {player.draft_rank} → {rank}")
                player.draft_rank = rank
            if player.status != "draft_prospect":
                player.status = "draft_prospect"
                changed.append("status → draft_prospect")

            if changed:
                updated += 1
                print(f"  UPDATED: {player.full_name:28s} [{', '.join(changed)}]")
            else:
                skipped += 1

        await session.commit()

    await engine.dispose()

    print(f"\n{'─'*50}")
    print(f"Updated  : {updated}")
    print(f"Skipped  : {skipped} (no change needed)")
    print(f"Not found: {not_found}")
    print("Done ✓")


if __name__ == "__main__":
    asyncio.run(run())
