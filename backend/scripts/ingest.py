"""
MLB Data Ingestion Script
Pulls teams, rosters, and season stats from Sportradar and seeds the database.

Usage (from backend/ directory with venv active):
    python -m scripts.ingest                    # current season, all teams
    python -m scripts.ingest --season 2024      # specific season
    python -m scripts.ingest --team NYY         # one team only
    python -m scripts.ingest --season 2023 2024 # multiple seasons
    python -m scripts.ingest --dry-run          # print what would be ingested
"""

import asyncio
import argparse
import sys
import time
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Load .env before importing app modules
from dotenv import load_dotenv
load_dotenv()

from app.core.config import get_settings
from app.core.database import Base
from app.models.team import Team
from app.models.player import Player
from app.models.stats import BattingStats, PitchingStats
from app.services.analytics import (
    calculate_woba, calculate_fip, calculate_iso,
    calculate_babip_batting, calculate_babip_pitching, calculate_wrc_plus,
)

settings = get_settings()

# Sportradar rate limit: 1 req/sec on trial, 5/sec on production
REQUEST_DELAY = 1.1


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def log(msg: str, indent: int = 0) -> None:
    prefix = "  " * indent
    print(f"{prefix}{msg}", flush=True)


def ok(msg: str, indent: int = 1) -> None:
    log(f"✓  {msg}", indent)


def warn(msg: str, indent: int = 1) -> None:
    log(f"⚠  {msg}", indent)


def section(msg: str) -> None:
    print(f"\n{'─' * 55}", flush=True)
    print(f"  {msg}", flush=True)
    print(f"{'─' * 55}", flush=True)


# ---------------------------------------------------------------------------
# Sportradar HTTP client (raw, no Redis dependency during ingestion)
# ---------------------------------------------------------------------------

class IngestClient:
    BASE = "https://api.sportradar.us/mlb/trial/v7/en"

    def __init__(self, api_key: str, dry_run: bool = False):
        self.api_key = api_key
        self.dry_run = dry_run
        self._http = httpx.AsyncClient(timeout=30.0)
        self._call_count = 0

    async def get(self, path: str) -> dict[str, Any]:
        url = f"{self.BASE}/{path}.json"
        if self.dry_run:
            log(f"[dry-run] GET {path}", indent=2)
            return {}
        await asyncio.sleep(REQUEST_DELAY)
        self._call_count += 1
        resp = await self._http.get(url, params={"api_key": self.api_key})
        if resp.status_code == 429:
            warn(f"Rate-limited on {path}, waiting 10s…")
            await asyncio.sleep(10)
            return await self.get(path)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Field mapping helpers
# ---------------------------------------------------------------------------

def _str(v: Any) -> str | None:
    return str(v) if v is not None else None


def _int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _date(v: str | None) -> date | None:
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Parse Sportradar responses
# ---------------------------------------------------------------------------

def parse_teams(data: dict) -> list[dict]:
    """Extract all teams from /league/hierarchy — handles multiple Sportradar response shapes."""
    teams = []
    league = data.get("league", {})

    # Shape 1: league -> conferences -> divisions -> teams  (v7 standard)
    for conf in league.get("conferences", []):
        league_name = "AL" if "American" in conf.get("name", "") else "NL"
        for div in conf.get("divisions", []):
            div_name = f"{league_name} {div.get('name', '').replace('Division', '').strip()}"
            for t in div.get("teams", []):
                teams.append({
                    "sportradar_id": t.get("id"),
                    "name": t.get("name"),
                    "abbreviation": t.get("abbr") or t.get("alias"),
                    "city": t.get("market"),
                    "division": div_name,
                    "league": league_name,
                    "level": "MLB",
                })

    # Shape 2: league -> divisions -> teams  (flat, no conferences)
    if not teams:
        for div in league.get("divisions", []):
            for t in div.get("teams", []):
                teams.append({
                    "sportradar_id": t.get("id"),
                    "name": t.get("name"),
                    "abbreviation": t.get("abbr") or t.get("alias"),
                    "city": t.get("market"),
                    "division": div.get("name"),
                    "league": div.get("alias", ""),
                    "level": "MLB",
                })

    # Shape 3: top-level "teams" list
    if not teams:
        for t in data.get("teams", []):
            teams.append({
                "sportradar_id": t.get("id"),
                "name": t.get("name"),
                "abbreviation": t.get("abbr") or t.get("alias"),
                "city": t.get("market"),
                "division": None,
                "league": None,
                "level": "MLB",
            })

    # Debug: if still empty, print the raw keys so we can see the actual shape
    if not teams:
        log(f"  [debug] hierarchy top-level keys: {list(data.keys())}")
        log(f"  [debug] league keys: {list(league.keys())}")
        if league:
            for k, v in league.items():
                if isinstance(v, list) and v:
                    log(f"  [debug] league['{k}'][0] keys: {list(v[0].keys()) if isinstance(v[0], dict) else v[0]}")
    return teams


def parse_players_from_roster(team_data: dict, team_db_id: str) -> list[dict]:
    """Extract players from /teams/{id}/profile."""
    team = team_data.get("team", {})
    players = []
    for p in team.get("players", []):
        bats = p.get("bat_hand", {}).get("abbr") or p.get("bat_hand", {}).get("code")
        throws = p.get("throw_hand", {}).get("abbr") or p.get("throw_hand", {}).get("code")
        pos = p.get("primary_position") or p.get("position")

        players.append({
            "sportradar_id": p.get("id"),
            "full_name": p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            "first_name": p.get("first_name"),
            "last_name": p.get("last_name"),
            "birth_date": _date(p.get("birth_date")),
            "position": _normalize_position(pos),
            "bats": bats,
            "throws": throws,
            "jersey_number": _int(p.get("jersey_number")),
            "status": "active",
            "team_sportradar_id": team.get("id"),
        })
    return players


def _normalize_position(pos: str | None) -> str | None:
    if not pos:
        return None
    mapping = {
        "P": "SP", "SP": "SP", "RP": "RP", "CP": "RP",
        "C": "C", "1B": "1B", "2B": "2B", "3B": "3B",
        "SS": "SS", "LF": "LF", "CF": "CF", "RF": "RF",
        "DH": "DH", "OF": "LF",
    }
    return mapping.get(pos.upper(), pos)


def parse_batting_stats(player_stats: dict, season: int) -> dict | None:
    """Extract batting stats from Sportradar player season stats block."""
    hitting = player_stats.get("statistics", {}).get("hitting", {})
    if not hitting:
        return None

    overall = hitting.get("overall", hitting)
    ab = _int(overall.get("ab")) or 0
    h = _int(overall.get("onbase", {}).get("h")) or _int(overall.get("hits")) or 0
    bb = _int(overall.get("onbase", {}).get("bb")) or _int(overall.get("walks")) or 0
    hbp = _int(overall.get("onbase", {}).get("hbp")) or 0
    doubles = _int(overall.get("onbase", {}).get("d")) or _int(overall.get("doubles")) or 0
    triples = _int(overall.get("onbase", {}).get("t")) or _int(overall.get("triples")) or 0
    hr = _int(overall.get("onbase", {}).get("hr")) or _int(overall.get("home_runs")) or 0
    sf = _int(overall.get("outs", {}).get("sf")) or 0
    k = _int(overall.get("outs", {}).get("klook")) or _int(overall.get("outs", {}).get("ktotal")) or _int(overall.get("strikeouts")) or 0
    sb = _int(overall.get("steal", {}).get("stolen")) or _int(overall.get("stolen_bases")) or 0
    cs = _int(overall.get("steal", {}).get("caught")) or 0
    rbi = _int(overall.get("rbi")) or 0
    runs = _int(overall.get("runs", {}).get("total")) or _int(overall.get("runs")) or 0
    games = _int(overall.get("games", {}).get("play")) or _int(overall.get("games")) or 0
    pa = _int(overall.get("ap")) or (ab + bb + hbp + sf)

    avg = _float(overall.get("avg"))
    obp = _float(overall.get("obp"))
    slg = _float(overall.get("slg"))

    row = {
        "hits": h, "doubles": doubles, "triples": triples,
        "home_runs": hr, "walks": bb, "hit_by_pitch": hbp,
        "sacrifice_flies": sf, "at_bats": ab, "strikeouts": k,
    }
    woba = calculate_woba(row) if ab > 0 else None
    iso_val = calculate_iso(avg or 0, slg or 0) if avg and slg else None
    babip = calculate_babip_batting(row) if ab > 0 else None
    wrc = calculate_wrc_plus(woba) if woba else None

    return {
        "season": season,
        "split": "overall",
        "games": games,
        "plate_appearances": pa,
        "at_bats": ab,
        "hits": h,
        "doubles": doubles,
        "triples": triples,
        "home_runs": hr,
        "rbi": rbi,
        "runs": runs,
        "walks": bb,
        "strikeouts": k,
        "stolen_bases": sb,
        "caught_stealing": cs,
        "hit_by_pitch": hbp,
        "sacrifice_flies": sf,
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": round(obp + slg, 3) if obp and slg else None,
        "woba": woba,
        "wrc_plus": wrc,
        "babip": babip,
        "iso": iso_val,
    }


def parse_pitching_stats(player_stats: dict, season: int) -> dict | None:
    """Extract pitching stats from Sportradar player season stats block."""
    pitching = player_stats.get("statistics", {}).get("pitching", {})
    if not pitching:
        return None

    overall = pitching.get("overall", pitching)
    games = _int(overall.get("games", {}).get("play")) or _int(overall.get("games")) or 0
    gs = _int(overall.get("games", {}).get("start")) or 0
    wins = _int(overall.get("games", {}).get("win")) or 0
    losses = _int(overall.get("games", {}).get("loss")) or 0
    saves = _int(overall.get("games", {}).get("save")) or 0
    ip = _float(overall.get("ip_2")) or _float(overall.get("innings_pitched")) or 0
    hits = _int(overall.get("onbase", {}).get("h")) or 0
    runs = _int(overall.get("runs", {}).get("total")) or 0
    er = _int(overall.get("runs", {}).get("earned")) or 0
    bb = _int(overall.get("onbase", {}).get("bb")) or 0
    k = _int(overall.get("outs", {}).get("ktotal")) or _int(overall.get("strikeouts")) or 0
    hr_a = _int(overall.get("onbase", {}).get("hr")) or 0
    era = _float(overall.get("era"))
    whip = _float(overall.get("whip"))

    row = {
        "innings_pitched": ip, "home_runs_allowed": hr_a,
        "walks": bb, "strikeouts": k, "hits_allowed": hits,
    }
    fip = calculate_fip(row) if ip > 0 else None

    k9 = round(k * 9 / ip, 2) if ip > 0 else None
    bb9 = round(bb * 9 / ip, 2) if ip > 0 else None
    hr9 = round(hr_a * 9 / ip, 2) if ip > 0 else None
    k_pct = round(k / (ip * 3 + hits + bb) , 3) if ip > 0 else None
    bb_pct = round(bb / (ip * 3 + hits + bb), 3) if ip > 0 else None

    return {
        "season": season,
        "split": "overall",
        "games": games,
        "games_started": gs,
        "wins": wins,
        "losses": losses,
        "saves": saves,
        "innings_pitched": ip,
        "hits_allowed": hits,
        "runs_allowed": runs,
        "earned_runs": er,
        "walks": bb,
        "strikeouts": k,
        "home_runs_allowed": hr_a,
        "era": era,
        "whip": whip,
        "fip": fip,
        "k_per_9": k9,
        "bb_per_9": bb9,
        "hr_per_9": hr9,
        "k_pct": k_pct,
        "bb_pct": bb_pct,
    }


# ---------------------------------------------------------------------------
# Database upsert helpers
# ---------------------------------------------------------------------------

async def upsert_team(session: AsyncSession, team_data: dict) -> str:
    """Insert or update a team, return its internal UUID as string."""
    stmt = pg_insert(Team).values(**{
        k: v for k, v in team_data.items()
        if k != "sportradar_id" or True  # include all
    }).on_conflict_do_update(
        index_elements=["sportradar_id"],
        set_={k: v for k, v in team_data.items() if k != "sportradar_id"},
    ).returning(Team.id)
    result = await session.execute(stmt)
    row = result.fetchone()
    await session.flush()
    return str(row[0])


async def upsert_player(session: AsyncSession, player_data: dict, team_id: str) -> str:
    """Insert or update a player, return internal UUID as string."""
    data = {k: v for k, v in player_data.items() if k != "team_sportradar_id"}
    data["team_id"] = team_id

    stmt = pg_insert(Player).values(**data).on_conflict_do_update(
        index_elements=["sportradar_id"],
        set_={k: v for k, v in data.items() if k not in ("sportradar_id",)},
    ).returning(Player.id)
    result = await session.execute(stmt)
    row = result.fetchone()
    await session.flush()
    return str(row[0])


async def upsert_batting_stats(session: AsyncSession, player_id: str, stats: dict) -> None:
    data = {"player_id": player_id, **stats}
    stmt = pg_insert(BattingStats).values(**data).on_conflict_do_update(
        index_elements=["player_id", "season", "split"],
        set_={k: v for k, v in data.items() if k not in ("player_id", "season", "split")},
    )
    await session.execute(stmt)


async def upsert_pitching_stats(session: AsyncSession, player_id: str, stats: dict) -> None:
    data = {"player_id": player_id, **stats}
    stmt = pg_insert(PitchingStats).values(**data).on_conflict_do_update(
        index_elements=["player_id", "season", "split"],
        set_={k: v for k, v in data.items() if k not in ("player_id", "season", "split")},
    )
    await session.execute(stmt)


# ---------------------------------------------------------------------------
# Main ingestion flow
# ---------------------------------------------------------------------------

async def ingest_all(seasons: list[int], team_filter: str | None, dry_run: bool) -> None:
    if not settings.sportradar_api_key:
        print("ERROR: SPORTRADAR_API_KEY is not set in your .env file.")
        sys.exit(1)

    client = IngestClient(settings.sportradar_api_key, dry_run=dry_run)

    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        # Step 1: Teams
        section("Step 1 / 3 — Teams")
        hierarchy = await client.get("league/hierarchy")
        all_teams = parse_teams(hierarchy)
        log(f"Found {len(all_teams)} teams in league hierarchy")

        if team_filter:
            all_teams = [t for t in all_teams if t["abbreviation"] == team_filter.upper()]
            if not all_teams:
                print(f"No team found with abbreviation '{team_filter}'. Check --team flag.")
                sys.exit(1)
            log(f"Filtered to: {all_teams[0]['name']}")

        team_id_map: dict[str, str] = {}  # sportradar_id -> db UUID

        if not dry_run:
            async with SessionLocal() as session:
                for t in all_teams:
                    db_id = await upsert_team(session, t)
                    team_id_map[t["sportradar_id"]] = db_id
                    ok(f"{t['abbreviation']} — {t['name']}")
                await session.commit()
        else:
            for t in all_teams:
                ok(f"[dry] {t['abbreviation']} — {t['name']}")
                team_id_map[t["sportradar_id"]] = "dry-run-id"

        # Step 2: Rosters
        section("Step 2 / 3 — Rosters")
        all_players: list[tuple[dict, str]] = []  # (player_dict, team_db_id)

        for t in all_teams:
            log(f"Fetching roster: {t['abbreviation']}…")
            roster_data = await client.get(f"teams/{t['sportradar_id']}/profile")
            players = parse_players_from_roster(roster_data, team_id_map.get(t["sportradar_id"], ""))

            if not dry_run:
                async with SessionLocal() as session:
                    db_team_id = team_id_map[t["sportradar_id"]]
                    for p in players:
                        db_player_id = await upsert_player(session, p, db_team_id)
                        all_players.append(({"sportradar_id": p["sportradar_id"], "position": p["position"]}, db_player_id))
                    await session.commit()
                ok(f"{t['abbreviation']}: {len(players)} players stored")
            else:
                ok(f"[dry] {t['abbreviation']}: {len(players)} players found")
                all_players.extend([(p, "dry-id") for p in players])

        # Step 3: Stats
        for season in seasons:
            section(f"Step 3 / 3 — Season Stats ({season})")
            log(f"Fetching stats for {len(all_teams)} teams, season {season}…")

            for t in all_teams:
                log(f"Stats: {t['abbreviation']} {season}…")
                try:
                    stats_data = await client.get(
                        f"seasons/{season}/REG/teams/{t['sportradar_id']}/statistics"
                    )
                except httpx.HTTPStatusError as e:
                    warn(f"  Could not fetch stats for {t['abbreviation']} {season}: {e.response.status_code}")
                    continue

                players_stats = stats_data.get("players", [])
                batters_saved = pitchers_saved = 0

                for p_stat in players_stats:
                    sr_id = p_stat.get("id")
                    if not sr_id:
                        continue

                    if dry_run:
                        continue

                    # Look up db player id
                    async with SessionLocal() as session:
                        result = await session.execute(
                            select(Player).where(Player.sportradar_id == sr_id)
                        )
                        player = result.scalar_one_or_none()
                        if not player:
                            continue
                        player_id = str(player.id)
                        is_pitcher = player.position in ("SP", "RP")

                    async with SessionLocal() as session:
                        if is_pitcher:
                            pstats = parse_pitching_stats(p_stat, season)
                            if pstats:
                                await upsert_pitching_stats(session, player_id, pstats)
                                pitchers_saved += 1
                        else:
                            bstats = parse_batting_stats(p_stat, season)
                            if bstats:
                                await upsert_batting_stats(session, player_id, bstats)
                                batters_saved += 1
                        await session.commit()

                ok(f"{t['abbreviation']} {season}: {batters_saved} batters, {pitchers_saved} pitchers")

        # Summary
        section("Done")
        log(f"Total API calls made: {client._call_count}")
        log(f"Teams: {len(all_teams)}")
        log(f"Seasons: {seasons}")
        if dry_run:
            log("Dry run — nothing was written to the database.")

    finally:
        await client.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest MLB data from Sportradar into the database")
    parser.add_argument(
        "--season", type=int, nargs="+", default=[2024],
        help="Season year(s) to ingest (default: 2024)"
    )
    parser.add_argument(
        "--team", type=str, default=None,
        help="Only ingest one team by abbreviation (e.g. NYY, LAD, BOS)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be ingested without writing to the database"
    )
    args = parser.parse_args()

    print(f"\n MLB Data Ingestion")
    print(f"  Seasons : {args.season}")
    print(f"  Team    : {args.team or 'all 30'}")
    print(f"  Dry run : {args.dry_run}")
    print(f"  DB      : {settings.database_url}\n")

    asyncio.run(ingest_all(
        seasons=args.season,
        team_filter=args.team,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
