"""
ingest_free_agents.py
──────────────────────
Phase 1 — Current Free Agents (Sportradar)
  Pulls the league/free_agents.json endpoint, filters to players updated
  since Oct 2025 (this offseason), matches by mlbam_id → sets status='free_agent'.
  Unmatched players are fetched from the MLB Stats API and inserted.

Phase 2 — Upcoming Free Agents (MLB Stats API)
  Fetches service-time for all active MLB players.  Players with
  service_time >= 5.000 are flagged as upcoming free agents via
  the 'contract_years' column set to 1 (walk-year approximation).

Run from backend/:
    .venv/bin/python3 -m scripts.ingest_free_agents
"""

import asyncio
import os
from datetime import date

import httpx
from dotenv import load_dotenv
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics")
SPORTRADAR_KEY = os.getenv("SPORTRADAR_API_KEY", "")
STATS_BASE = "https://statsapi.mlb.com/api/v1"

from app.models.player import Player  # noqa
from app.models.stats import BattingStats, PitchingStats  # noqa
from app.models.team import Team  # noqa

# Only consider FAs updated since this threshold = current offseason
FA_CUTOFF = "2025-10-01"
BATCH = 100


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


POS_MAP = {
    "OF": "CF", "IF": "3B", "P": "SP", "SP": "SP", "RP": "RP",
    "C": "C", "1B": "1B", "2B": "2B", "3B": "3B", "SS": "SS",
    "LF": "LF", "CF": "CF", "RF": "RF", "DH": "DH",
}

def _pos(raw):
    return POS_MAP.get((raw or "").upper(), raw[:8] if raw else None)


# ── Phase 1: Current FAs from Sportradar ──────────────────────────────────────

async def fetch_sportradar_fas(client: httpx.AsyncClient) -> list[dict]:
    url = f"https://api.sportradar.com/mlb/trial/v8/en/league/free_agents.json?api_key={SPORTRADAR_KEY}"
    r = await client.get(url, timeout=30)
    r.raise_for_status()
    all_fas = r.json()["league"]["free_agents"]
    # Filter to this offseason only
    recent = [p for p in all_fas if p.get("updated", "") >= FA_CUTOFF]
    print(f"  Sportradar FAs: {len(all_fas):,} total, {len(recent):,} updated since {FA_CUTOFF}")
    return recent


async def hydrate_mlb_player(client: httpx.AsyncClient, mlb_id: int) -> dict | None:
    try:
        r = await client.get(f"{STATS_BASE}/people/{mlb_id}", timeout=10)
        r.raise_for_status()
        people = r.json().get("people", [])
        return people[0] if people else None
    except Exception:
        return None


async def phase1_current_fas(S: async_sessionmaker, client: httpx.AsyncClient):
    print("\n=== Phase 1: Current Free Agents (Sportradar) ===")
    fas = await fetch_sportradar_fas(client)

    # Reset all existing free_agents to see what's still unsigned
    async with S() as session:
        await session.execute(
            update(Player)
            .where(Player.status == "free_agent")
            .values(status="free_agent")   # keep them, just log existing count
        )
        r = await session.execute(select(Player).where(Player.status == "free_agent"))
        existing_fas = len(r.scalars().all())
        print(f"  Existing FA records in DB: {existing_fas}")

    matched = inserted = 0
    not_found = []

    async with S() as session:
        for fa in fas:
            mlbam_id = fa.get("mlbam_id")
            if not mlbam_id:
                continue
            mlb_id = int(mlbam_id)

            r = await session.execute(select(Player).where(Player.mlb_id == mlb_id))
            player = r.scalar_one_or_none()

            if player:
                player.status = "free_agent"
                # Update bio if missing
                if not player.bats and fa.get("bat_hand"):
                    player.bats = fa["bat_hand"]
                if not player.throws and fa.get("throw_hand"):
                    player.throws = fa["throw_hand"]
                matched += 1
            else:
                not_found.append(fa)

            if (matched + inserted) % 100 == 0 and (matched + inserted) > 0:
                await session.commit()

        await session.commit()

    print(f"  Matched existing players: {matched}")
    print(f"  New players to fetch from MLB API: {len(not_found)}")

    # Fetch and insert unmatched players from MLB Stats API
    sem = asyncio.Semaphore(10)
    new_players = []

    async def fetch_one(fa_record):
        async with sem:
            mlb_id = int(fa_record.get("mlbam_id", 0))
            if not mlb_id:
                return
            p = await hydrate_mlb_player(client, mlb_id)
            if not p:
                return
            new_players.append((fa_record, p))

    await asyncio.gather(*[fetch_one(fa) for fa in not_found])
    print(f"  Fetched {len(new_players)} new player profiles from MLB API")

    async with S() as session:
        for fa_record, p in new_players:
            mlb_id = int(fa_record.get("mlbam_id", 0))
            # Double-check not already in DB
            r = await session.execute(select(Player).where(Player.mlb_id == mlb_id))
            if r.scalar_one_or_none():
                continue

            pos = (p.get("primaryPosition") or {}).get("abbreviation")
            new = Player(
                mlb_id=mlb_id,
                full_name=p.get("fullName", fa_record["full_name"]),
                first_name=p.get("firstName", fa_record.get("first_name", "")),
                last_name=p.get("lastName", fa_record.get("last_name", "")),
                birth_date=_parse_date(p.get("birthDate")),
                age=p.get("currentAge"),
                position=_pos(pos or fa_record.get("position")),
                bats=(p.get("batSide") or {}).get("code") or fa_record.get("bat_hand"),
                throws=(p.get("pitchHand") or {}).get("code") or fa_record.get("throw_hand"),
                height=p.get("height"),
                weight=p.get("weight"),
                birth_country=p.get("birthCountry"),
                status="free_agent",
            )
            session.add(new)
            inserted += 1

        await session.commit()

    print(f"  Inserted new FA records: {inserted}")
    print(f"  Total current FAs in DB: {matched + inserted}")


# ── Phase 2: Upcoming FAs from Sportradar team profiles ───────────────────────
#
# Sportradar's team profile endpoint returns every rostered player with:
#   reference  → mlbam_id (matches Player.mlb_id)
#   pro_debut  → MLB debut date (YYYY-MM-DD)  ← key field
#   salary     → current-season salary
#
# From pro_debut we approximate service time and identify walk-year players
# (5.0 ≤ service_time < 6.5).  This avoids the over-broad "any player with
# service_time ≥ 5.0" problem — a 14-year veteran on an extension has
# service_time >> 6.5 and is correctly excluded.

SR_BASE = "https://api.sportradar.com/mlb/trial/v8/en"


def _approx_service_time(debut_date_str: str | None) -> float | None:
    """
    Approximate MLB service time from debut date.
    172 service days ≈ 1 service year.  Clamped to 0–15.
    """
    if not debut_date_str:
        return None
    try:
        debut = date.fromisoformat(debut_date_str[:10])
        service_days = max((date.today() - debut).days, 0)
        return round(min(service_days / 172, 15.0), 2)
    except ValueError:
        return None


async def _sr_team_ids(client: httpx.AsyncClient) -> list[str]:
    """Return all 30 MLB team IDs from Sportradar's league hierarchy."""
    r = await client.get(
        f"{SR_BASE}/league/hierarchy.json",
        params={"api_key": SPORTRADAR_KEY},
        timeout=30,
    )
    r.raise_for_status()
    team_ids: list[str] = []
    for league in r.json().get("leagues", []):
        for division in league.get("divisions", []):
            for team in division.get("teams", []):
                team_ids.append(team["id"])
    return team_ids


async def _sr_team_players(
    client: httpx.AsyncClient, team_id: str
) -> list[dict]:
    """Fetch one team profile and return its player list.
    Retries up to 3 times on 429 with exponential back-off.
    """
    url = f"{SR_BASE}/teams/{team_id}/profile.json"
    for attempt in range(3):
        await asyncio.sleep(1.1 * (2 ** attempt))   # 1.1 s → 2.2 s → 4.4 s
        try:
            r = await client.get(url, params={"api_key": SPORTRADAR_KEY}, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5)) + 1
                print(f"    429 on {team_id[:8]}… waiting {wait}s")
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            return r.json().get("players", [])
        except Exception as e:
            print(f"  Profile fetch error {team_id[:8]}… ({type(e).__name__}): {e}")
    return []


async def phase2_upcoming_fas(S: async_sessionmaker, client: httpx.AsyncClient):
    print("\n=== Phase 2: Upcoming Free Agents (Sportradar roster profiles) ===")

    # ── 1. Collect all 30 team IDs ─────────────────────────────────────────────
    team_ids = await _sr_team_ids(client)
    print(f"  Teams found: {len(team_ids)}")

    # ── 2. Fetch rosters sequentially (trial API = 1 req/sec) ──────────────────
    all_players: list[dict] = []
    for i, tid in enumerate(team_ids, 1):
        players = await _sr_team_players(client, tid)
        all_players.extend(players)
        print(f"  [{i:02d}/{len(team_ids)}] fetched {len(players)} players", end="\r")
    print()
    print(f"  Rostered players from Sportradar: {len(all_players):,}")

    # ── 3. Build mlbam_id → player dict map ───────────────────────────────────
    #  Sportradar uses "reference" for the mlbam_id (stored as a string).
    sr_map: dict[int, dict] = {}
    for p in all_players:
        ref = p.get("reference")
        if ref:
            try:
                sr_map[int(ref)] = p
            except (ValueError, TypeError):
                pass
    print(f"  Players with mlbam_id reference: {len(sr_map):,}")

    # ── 4. Update DB ───────────────────────────────────────────────────────────
    # First: clear walk-year flags on all active/injured players so stale data
    # doesn't persist across ingestion runs.
    async with S() as session:
        await session.execute(
            update(Player)
            .where(Player.status.in_(["active", "injured"]))
            .values(contract_years=None)
        )
        await session.commit()

    updated = walk_year = 0
    async with S() as session:
        for mlb_id, sr_p in sr_map.items():
            debut = sr_p.get("pro_debut")
            st = _approx_service_time(debut)
            if st is None:
                continue

            r = await session.execute(select(Player).where(Player.mlb_id == mlb_id))
            player = r.scalar_one_or_none()
            if not player:
                continue

            player.service_time = st
            # Only update salary from Sportradar when the DB has no value yet.
            # ingest_salaries.py (Spotrac) is the authoritative salary source;
            # Sportradar returns salary in dollars so we convert to millions.
            if sr_p.get("salary") and not player.salary:
                player.salary = round(sr_p["salary"] / 1_000_000, 4)
            updated += 1

            # Walk-year window: first FA-eligible season only.
            # service_time < 6.5 ensures we exclude veterans on extensions who
            # already passed their first FA eligibility date.
            if 5.0 <= st < 6.5:
                player.contract_years = 1
                walk_year += 1

        await session.commit()

    print(f"  Updated service time for {updated:,} players")
    print(f"  Flagged as walk-year (5.0 ≤ svc < 6.5): {walk_year:,}")


# ── Summary ───────────────────────────────────────────────────────────────────

async def print_summary(S: async_sessionmaker):
    from sqlalchemy import text
    async with S() as session:
        r = await session.execute(text("SELECT COUNT(*) FROM players WHERE status='free_agent'"))
        fa_count = r.scalar()
        r = await session.execute(text("SELECT COUNT(*) FROM players WHERE contract_years=1 AND status IN ('active','injured')"))
        upcoming_count = r.scalar()
        r = await session.execute(text("SELECT COUNT(*) FROM players WHERE service_time IS NOT NULL"))
        svc_count = r.scalar()

    print(f"\n{'=' * 50}")
    print(f"  Current free agents     : {fa_count:,}")
    print(f"  Upcoming (walk-year)    : {upcoming_count:,}")
    print(f"  Players with svc time   : {svc_count:,}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def run():
    engine = create_async_engine(DATABASE_URL, echo=False)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with httpx.AsyncClient() as client:
        await phase1_current_fas(S, client)
        await phase2_upcoming_fas(S, client)

    await print_summary(S)
    await engine.dispose()
    print("\nDone ✓")


if __name__ == "__main__":
    asyncio.run(run())
