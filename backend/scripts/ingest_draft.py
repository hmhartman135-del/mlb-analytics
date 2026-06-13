"""
ingest_draft.py
───────────────
1. Ingest all 2025 MLB Draft picks with MLB Pipeline ranks, blurbs, signing bonuses.
2. Fetch all 251 college team rosters for comprehensive college coverage.
3. Update existing players with rank/pick/blurb where mlb_id matches.

Run from backend/ directory:
    .venv/bin/python3 -m scripts.ingest_draft
"""

import asyncio
import httpx
import os
from datetime import date

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics")

from app.core.database import Base  # noqa
from app.models.team import Team    # noqa
from app.models.stats import BattingStats, PitchingStats  # noqa
from app.models.player import Player  # noqa

DRAFT_YEAR = 2025

POS_MAP = {
    "TWP": "SP", "P": "SP", "SP": "SP", "RP": "RP",
    "C": "C", "1B": "1B", "2B": "2B", "3B": "3B",
    "SS": "SS", "LF": "LF", "CF": "CF", "RF": "RF",
    "OF": "CF", "DH": "DH", "IF": "3B", "UTIL": "DH",
}


def _parse_pos(abbr: str | None) -> str | None:
    if not abbr:
        return None
    return POS_MAP.get(abbr.upper(), abbr[:8])


def _parse_bd(s: str | None):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# ── Phase 1: Fetch 2025 draft picks ──────────────────────────────────────────

async def fetch_draft_picks(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get(
        "https://statsapi.mlb.com/api/v1/draft/2025",
        params={"limit": 2000},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    picks = [p for rnd in data["drafts"]["rounds"] for p in rnd["picks"]]
    print(f"  → {len(picks)} total draft picks fetched")
    return picks


# ── Phase 2: Fetch all college team rosters ───────────────────────────────────

async def fetch_college_teams(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get(
        "https://statsapi.mlb.com/api/v1/teams",
        params={"sportId": 22, "limit": 400},
        timeout=30,
    )
    r.raise_for_status()
    teams = r.json().get("teams", [])
    # Filter out non-college entries (minor league teams mixed in)
    college_teams = [
        t for t in teams
        if any(word in t.get("name", "").lower()
               for word in ["university", "college", "state", "tech", "florida", "georgia",
                            "louisiana", "virginia", "carolina", "michigan", "oregon",
                            "alabama", "arkansas", "texas", "tennessee", "kentucky",
                            "vanderbilt", "rice", "tulane", "wake", "duke", "notre dame",
                            "stanford", "cal poly", "usc", "ucla", "arizona", "oklahoma",
                            "kansas", "nebraska", "iowa", "illinois", "indiana", "ohio",
                            "northwestern", "minnesota", "purdue", "penn", "princeton",
                            "yale", "harvard", "dartmouth", "columbia", "cornell"])
        or t.get("abbreviation", "") in [
            "CCC", "MSU", "ODU", "UW", "OSU", "GTG", "VAN", "LSU", "UNC", "UVA",
            "USC", "TCU", "UT", "UK", "UA", "ARK", "OU", "KSU", "NU", "UI", "IU"
        ]
    ]
    # If filter is too strict, just use all 251
    if len(college_teams) < 50:
        college_teams = teams
    print(f"  → {len(college_teams)} college teams identified")
    return college_teams


async def fetch_team_roster(client: httpx.AsyncClient, team_id: int, season: int) -> list[dict]:
    try:
        r = await client.get(
            f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster",
            params={
                "season": season,
                "rosterType": "fullSeason",
                "hydrate": "person(currentAge,birthDate,birthCity,birthCountry,height,weight,primaryPosition,batSide,pitchHand)",
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("roster", [])
    except Exception:
        return []


# ── DB helpers ────────────────────────────────────────────────────────────────

async def upsert_draft_pick(session: AsyncSession, pick: dict) -> str:
    """Insert or update a player from a draft pick. Returns 'inserted'/'updated'/'skipped'."""
    person = pick.get("person", {})
    mlb_id = person.get("id")
    if not mlb_id:
        return "skipped"

    existing = (await session.execute(
        select(Player).where(Player.mlb_id == mlb_id)
    )).scalar_one_or_none()

    rank = pick.get("rank")
    pick_num = pick.get("displayPickNumber")
    school_info = pick.get("school", {})
    school_name = school_info.get("name")
    school_class = school_info.get("schoolClass")
    blurb = pick.get("blurb", "")[:2048] if pick.get("blurb") else None
    bonus_str = pick.get("signingBonus")
    signing_bonus = float(bonus_str) if bonus_str else None
    pick_round = pick.get("pickRound")

    if existing:
        if rank:
            existing.draft_rank = rank
        if pick_num:
            existing.draft_pick = pick_num
        if school_name and not existing.school:
            existing.school = school_name
        if school_class:
            existing.school_class = school_class
        if blurb and not existing.scout_notes:
            existing.scout_notes = blurb
        if signing_bonus:
            existing.signing_bonus = signing_bonus
        existing.draft_year = DRAFT_YEAR
        return "updated"

    # Insert new
    pos_abbr = person.get("primaryPosition", {}).get("abbreviation") or pick.get("position", {}).get("abbreviation")
    new_player = Player(
        mlb_id=mlb_id,
        full_name=person.get("fullName", "Unknown"),
        first_name=person.get("firstName", ""),
        last_name=person.get("lastName", ""),
        birth_date=_parse_bd(person.get("birthDate")),
        age=person.get("currentAge"),
        position=_parse_pos(pos_abbr),
        bats=person.get("batSide", {}).get("code"),
        throws=person.get("pitchHand", {}).get("code"),
        status="draft_prospect",
        height=person.get("height"),
        weight=person.get("weight"),
        birth_city=pick.get("home", {}).get("city"),
        birth_country=pick.get("home", {}).get("country", "USA"),
        school=school_name,
        school_class=school_class,
        draft_year=DRAFT_YEAR,
        draft_pick=pick_num,
        draft_rank=rank,
        signing_bonus=signing_bonus,
        scout_notes=blurb,
    )
    session.add(new_player)
    return "inserted"


async def upsert_college_player(session: AsyncSession, member: dict, team_name: str) -> str:
    person = member.get("person", {})
    mlb_id = person.get("id")
    if not mlb_id:
        return "skipped"

    existing = (await session.execute(
        select(Player).where(Player.mlb_id == mlb_id)
    )).scalar_one_or_none()
    if existing:
        # Update bio fields if missing
        dirty = False
        for attr, val in [
            ("height", person.get("height")),
            ("weight", person.get("weight")),
            ("birth_city", person.get("birthCity")),
            ("birth_country", person.get("birthCountry")),
            ("school", team_name if not existing.school else None),
        ]:
            if val and getattr(existing, attr) is None:
                setattr(existing, attr, val)
                dirty = True
        return "updated" if dirty else "skipped"

    pos_abbr = member.get("position", {}).get("abbreviation") or person.get("primaryPosition", {}).get("abbreviation")
    new_player = Player(
        mlb_id=mlb_id,
        full_name=person.get("fullName", "Unknown"),
        first_name=person.get("firstName", ""),
        last_name=person.get("lastName", ""),
        birth_date=_parse_bd(person.get("birthDate")),
        age=person.get("currentAge"),
        position=_parse_pos(pos_abbr),
        bats=person.get("batSide", {}).get("code"),
        throws=person.get("pitchHand", {}).get("code"),
        status="draft_prospect",
        height=person.get("height"),
        weight=person.get("weight"),
        birth_city=person.get("birthCity"),
        birth_country=person.get("birthCountry", "USA"),
        school=team_name,
        draft_year=DRAFT_YEAR,
    )
    session.add(new_player)
    return "inserted"


# ── main ──────────────────────────────────────────────────────────────────────

async def run():
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:

        # ── Phase 1: 2025 Draft picks ─────────────────────────────────────────
        print("=" * 60)
        print("Phase 1: 2025 MLB Draft picks (picks + rankings + blurbs)")
        print("=" * 60)

        async with httpx.AsyncClient() as client:
            picks = await fetch_draft_picks(client)

        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        for pick in picks:
            result = await upsert_draft_pick(session, pick)
            counts[result] += 1
            if (counts["inserted"] + counts["updated"]) % 100 == 0 and counts["inserted"] + counts["updated"] > 0:
                await session.commit()

        await session.commit()
        print(f"  ✓  Inserted: {counts['inserted']} | Updated: {counts['updated']} | Skipped: {counts['skipped']}")

        # Verify ranked players
        ranked_result = await session.execute(
            select(Player).where(Player.draft_rank.isnot(None)).order_by(Player.draft_rank)
        )
        ranked = ranked_result.scalars().all()
        print(f"\n  Top 10 by MLB Pipeline rank:")
        for p in ranked[:10]:
            print(f"    #{p.draft_rank:3d}  {p.full_name:25s}  Pick #{p.draft_pick or '—':>4}  {p.school or '':30s}")

        # ── Phase 2: All college team rosters ────────────────────────────────
        print("\n" + "=" * 60)
        print("Phase 2: All college team rosters")
        print("=" * 60)

        async with httpx.AsyncClient() as client:
            college_teams = await fetch_college_teams(client)

            total_ins = 0
            total_upd = 0
            teams_done = 0

            # Fetch all rosters concurrently in batches
            BATCH = 20
            for i in range(0, len(college_teams), BATCH):
                batch = college_teams[i:i + BATCH]
                rosters = await asyncio.gather(*[
                    fetch_team_roster(client, t["id"], DRAFT_YEAR)
                    for t in batch
                ])

                for team, roster in zip(batch, rosters):
                    team_name = team.get("name", "")
                    for member in roster:
                        result = await upsert_college_player(session, member, team_name)
                        if result == "inserted":
                            total_ins += 1
                        elif result == "updated":
                            total_upd += 1
                    teams_done += 1

                await session.commit()
                print(f"  … {teams_done}/{len(college_teams)} teams — inserted {total_ins:,} | updated {total_upd:,}")

        await session.commit()
        print(f"\n  ✓  College phase complete: {total_ins:,} new | {total_upd:,} enriched")

        # ── Summary ───────────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("Final Summary")
        print("=" * 60)

        for status in ["active", "minors", "draft_prospect"]:
            r = await session.execute(select(Player).where(Player.status == status))
            print(f"  {status:20s}: {len(r.scalars().all()):,}")

        r = await session.execute(
            select(Player).where(Player.draft_rank.isnot(None))
        )
        print(f"  {'With MLB rank':20s}: {len(r.scalars().all()):,}")

        r = await session.execute(
            select(Player).where(Player.scout_notes.isnot(None), Player.status == "draft_prospect")
        )
        print(f"  {'With blurb':20s}: {len(r.scalars().all()):,}")

    await engine.dispose()
    print("\nDone ✓")


if __name__ == "__main__":
    asyncio.run(run())
