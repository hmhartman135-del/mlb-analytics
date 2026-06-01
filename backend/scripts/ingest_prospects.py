"""
ingest_prospects.py
───────────────────
1. Update existing MiLB players with height / weight / birth_country from MLB Stats API.
2. Insert college (sportId=22) and HS (sportId=586) draft prospects that don't already exist.

Run from the backend/ directory:
    .venv/bin/python3 -m scripts.ingest_prospects
"""

import asyncio
import httpx
import sys
import os

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update
from dotenv import load_dotenv

load_dotenv()  # picks up backend/.env when run from backend/ dir

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics")

from app.core.database import Base  # noqa: E402
from app.models.team import Team  # noqa: E402
from app.models.stats import BattingStats, PitchingStats  # noqa: E402
from app.models.player import Player  # noqa: E402

# MiLB sport IDs → our level labels
SPORT_LEVELS = {
    11: "AAA",
    12: "AA",
    13: "A+",
    14: "A",
    16: "Rookie",
}

DRAFT_SPORT_IDS = {
    22: "college",
    586: "high_school",
}

CURRENT_SEASON = 2025


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_height(h: str | None) -> str | None:
    """'6\' 2"' → return as-is; None → None."""
    return h if h else None


async def _fetch_sport_players(client: httpx.AsyncClient, sport_id: int, season: int) -> list[dict]:
    url = "https://statsapi.mlb.com/api/v1/sports/{}/players".format(sport_id)
    params = {
        "season": season,
        "hydrate": "currentTeam,team",
        "fields": (
            "people,id,fullName,firstName,lastName,birthDate,birthCity,birthCountry,"
            "height,weight,primaryPosition,batSide,pitchHand,currentAge"
        ),
    }
    try:
        r = await client.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("people", [])
    except Exception as e:
        print(f"  ⚠  Failed to fetch sport {sport_id}: {e}")
        return []


async def _fetch_draft_players(client: httpx.AsyncClient, sport_id: int, season: int) -> list[dict]:
    """Fetch draft-eligible players (college/HS) from MLB Stats API."""
    url = "https://statsapi.mlb.com/api/v1/sports/{}/players".format(sport_id)
    params = {
        "season": season,
        "fields": (
            "people,id,fullName,firstName,lastName,birthDate,birthCity,birthCountry,"
            "height,weight,primaryPosition,batSide,pitchHand,currentAge,school"
        ),
    }
    try:
        r = await client.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("people", [])
    except Exception as e:
        print(f"  ⚠  Failed to fetch draft sport {sport_id}: {e}")
        return []


# ── main ──────────────────────────────────────────────────────────────────────

async def run():
    engine = create_async_engine(DATABASE_URL, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        # ── Phase 1: Update existing MiLB players with bio data ──────────────
        print("=" * 60)
        print("Phase 1: Enriching existing MiLB players with height/weight/country")
        print("=" * 60)

        async with httpx.AsyncClient() as client:
            for sport_id, level_label in SPORT_LEVELS.items():
                print(f"\n  Fetching {level_label} (sportId={sport_id}) …")
                people = await _fetch_sport_players(client, sport_id, CURRENT_SEASON)
                print(f"  → {len(people)} players from API")

                updated = 0
                for p in people:
                    mlb_id = p.get("id")
                    if not mlb_id:
                        continue

                    result = await session.execute(
                        select(Player).where(Player.mlb_id == mlb_id)
                    )
                    player = result.scalar_one_or_none()
                    if not player:
                        continue

                    dirty = False
                    for attr, val in [
                        ("height",        _parse_height(p.get("height"))),
                        ("weight",        p.get("weight")),
                        ("birth_city",    p.get("birthCity")),
                        ("birth_country", p.get("birthCountry")),
                    ]:
                        if val and getattr(player, attr) is None:
                            setattr(player, attr, val)
                            dirty = True

                    if dirty:
                        updated += 1

                await session.commit()
                print(f"  ✓  Updated {updated} players at {level_label}")

        # ── Phase 2: Insert draft prospects (college + HS) ────────────────────
        print("\n" + "=" * 60)
        print("Phase 2: Ingesting draft prospects (college + HS)")
        print("=" * 60)

        # We use the current draft year (latest MLB Draft)
        # Try both 2025 and 2024 — many APIs have the most recent draft
        for draft_season in [2025, 2024]:
            async with httpx.AsyncClient() as client:
                for sport_id, sport_label in DRAFT_SPORT_IDS.items():
                    print(f"\n  Fetching {sport_label} (sportId={sport_id}, season={draft_season}) …")
                    people = await _fetch_draft_players(client, sport_id, draft_season)
                    print(f"  → {len(people)} players from API")

                    if not people:
                        continue

                    inserted = 0
                    skipped = 0

                    for p in people:
                        mlb_id = p.get("id")
                        if not mlb_id:
                            continue

                        # Skip if already in DB
                        existing = await session.execute(
                            select(Player).where(Player.mlb_id == mlb_id)
                        )
                        if existing.scalar_one_or_none():
                            skipped += 1
                            continue

                        pos_info = p.get("primaryPosition", {})
                        pos_abbr = pos_info.get("abbreviation", "OF")
                        # Normalize to our position format
                        pos_map = {
                            "TWP": "SP", "P": "SP", "SP": "SP", "RP": "RP",
                            "C": "C", "1B": "1B", "2B": "2B", "3B": "3B",
                            "SS": "SS", "LF": "LF", "CF": "CF", "RF": "RF",
                            "OF": "RF", "DH": "DH", "IF": "3B", "UTIL": "DH",
                        }
                        position = pos_map.get(pos_abbr, pos_abbr[:8])

                        school_info = p.get("school", {})
                        school_name = school_info.get("name") if isinstance(school_info, dict) else None

                        from datetime import date
                        birth_date = None
                        bd_str = p.get("birthDate")
                        if bd_str:
                            try:
                                birth_date = date.fromisoformat(bd_str)
                            except ValueError:
                                pass

                        new_player = Player(
                            mlb_id=mlb_id,
                            full_name=p.get("fullName", "Unknown"),
                            first_name=p.get("firstName", ""),
                            last_name=p.get("lastName", ""),
                            birth_date=birth_date,
                            age=p.get("currentAge"),
                            position=position,
                            bats=p.get("batSide", {}).get("code"),
                            throws=p.get("pitchHand", {}).get("code"),
                            status="draft_prospect",
                            height=_parse_height(p.get("height")),
                            weight=p.get("weight"),
                            birth_city=p.get("birthCity"),
                            birth_country=p.get("birthCountry"),
                            school=school_name,
                            draft_year=draft_season,
                        )
                        session.add(new_player)
                        inserted += 1

                        if inserted % 100 == 0:
                            await session.commit()
                            print(f"    … committed {inserted} so far")

                    await session.commit()
                    print(f"  ✓  Inserted {inserted} | Skipped (already in DB) {skipped}")

            break  # Only use first season that returns data

        # ── Summary ───────────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)

        counts = {}
        for status in ["active", "minors", "draft_prospect"]:
            r = await session.execute(
                select(Player).where(Player.status == status)
            )
            counts[status] = len(r.scalars().all())

        for status, count in counts.items():
            print(f"  {status:20s}: {count:,}")

        # Height/weight fill rate
        r = await session.execute(select(Player))
        all_players = r.scalars().all()
        with_height = sum(1 for p in all_players if p.height)
        with_weight = sum(1 for p in all_players if p.weight)
        print(f"\n  Height populated: {with_height:,} / {len(all_players):,}")
        print(f"  Weight populated: {with_weight:,} / {len(all_players):,}")

    await engine.dispose()
    print("\nDone ✓")


if __name__ == "__main__":
    asyncio.run(run())
