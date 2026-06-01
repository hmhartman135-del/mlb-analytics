"""
Minor League Data Ingestion Script
Uses the free MLB Stats API (no key required) to pull players and stats
from all MiLB levels: AAA, AA, A+, A, and Rookie.

Usage (from backend/ directory with venv active):
    python -m scripts.ingest_minors                      # all levels, current season
    python -m scripts.ingest_minors --season 2024        # specific season
    python -m scripts.ingest_minors --level AAA AA       # specific levels only
    python -m scripts.ingest_minors --affiliate NYY      # one MLB org's affiliates
    python -m scripts.ingest_minors --dry-run            # preview without writing

Levels available: AAA, AA, A+, A, Rookie
"""

import asyncio
import argparse
import sys
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

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

MLB_STATS_API = "https://statsapi.mlb.com/api/v1"
REQUEST_DELAY = 0.25   # MLB Stats API is generous — 4 req/sec is safe

# MLB Stats API sport IDs for each level
LEVELS = {
    "MLB":    1,    # Major League Baseball
    "AAA":    11,
    "AA":     12,
    "A+":     13,
    "A":      14,
    "Rookie": 16,
}

# Levels that count as "minor league"
MINOR_LEVELS = {"AAA", "AA", "A+", "A", "Rookie"}

# Position code normalization (MLB Stats API uses different codes)
POSITION_MAP = {
    "P":   "SP",  # resolved to SP or RP after checking games started
    "SP":  "SP",
    "RP":  "RP",
    "C":   "C",
    "1B":  "1B",
    "2B":  "2B",
    "3B":  "3B",
    "SS":  "SS",
    "LF":  "LF",
    "CF":  "CF",
    "RF":  "RF",
    "DH":  "DH",
    "OF":  "LF",   # generic outfield → LF as default; can refine
    "IF":  "2B",   # generic infield → 2B
    "TWP": "SP",   # two-way player
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str, indent: int = 0) -> None:
    print("  " * indent + msg, flush=True)

def ok(msg: str, indent: int = 1) -> None:
    log(f"✓  {msg}", indent)

def warn(msg: str, indent: int = 1) -> None:
    log(f"⚠  {msg}", indent)

def section(msg: str) -> None:
    print(f"\n{'─' * 55}", flush=True)
    print(f"  {msg}", flush=True)
    print(f"{'─' * 55}", flush=True)


# ---------------------------------------------------------------------------
# MLB Stats API client
# ---------------------------------------------------------------------------

class MLBStatsClient:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._http = httpx.AsyncClient(
            timeout=45.0,
            headers={"User-Agent": "MLBAnalyticsPlatform/0.1"},
        )
        self._call_count = 0

    async def get(self, path: str, params: dict | None = None, retries: int = 3) -> dict[str, Any]:
        if self.dry_run:
            return {}
        url = f"{MLB_STATS_API}/{path}"
        await asyncio.sleep(REQUEST_DELAY)
        self._call_count += 1
        for attempt in range(retries):
            try:
                resp = await self._http.get(url, params=params or {})
                resp.raise_for_status()
                return resp.json()
            except (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt < retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    log(f"  Network error on {path} (attempt {attempt+1}), retrying in {wait}s…")
                    await asyncio.sleep(wait)
                    # Recreate client on connection errors
                    await self._http.aclose()
                    self._http = httpx.AsyncClient(
                        timeout=45.0,
                        headers={"User-Agent": "MLBAnalyticsPlatform/0.1"},
                    )
                else:
                    log(f"  ⚠ Skipping {path} after {retries} failed attempts: {exc}")
                    return {}
        return {}

    async def close(self) -> None:
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

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

def _norm_pos(code: str | None) -> str | None:
    if not code:
        return None
    return POSITION_MAP.get(code.upper(), code.upper())

def _parse_ip(ip_str: str | None) -> float:
    """Convert '105.2' (105 and 2/3 innings) to decimal 105.667."""
    if not ip_str:
        return 0.0
    try:
        whole, frac = str(ip_str).split(".")
        return int(whole) + int(frac) / 3
    except (ValueError, AttributeError):
        return _float(ip_str) or 0.0


def parse_mlb_team(team_data: dict, level: str, sport_id: int) -> dict:
    venue = team_data.get("venue", {})
    # "parentOrgId" is a top-level field on the team object in the MLB Stats API.
    # The "parentOrganization" hydration endpoint returns an empty dict, so we
    # read parentOrgId directly and fall back to the nested form just in case.
    parent_id = _int(team_data.get("parentOrgId")) or _int(
        (team_data.get("parentOrganization") or {}).get("id")
    )
    return {
        "mlb_id": _int(team_data.get("id")),
        "name": team_data.get("teamName") or team_data.get("name", ""),
        "abbreviation": team_data.get("abbreviation") or team_data.get("teamCode", "").upper(),
        "city": team_data.get("locationName") or team_data.get("franchiseName", ""),
        "division": team_data.get("division", {}).get("name"),
        "league": team_data.get("league", {}).get("abbreviation"),
        "ballpark": venue.get("name"),
        "level": level,
        "sport_id": sport_id,
        "affiliate_mlb_id": parent_id,
    }


_ROSTER_STATUS_TO_PLAYER_STATUS = {
    "A":   "active",    # 26-man active
    "D7":  "injured",   # 7-day IL (rarely used)
    "D10": "injured",   # 10-day IL
    "D15": "injured",   # 15-day IL
    "D25": "injured",   # 25-day IL
    "D60": "injured",   # 60-day IL
    "ILF": "injured",   # Full-season IL
    "RM":  "active",    # Reassigned to minors (still on 40-man)
}


def parse_mlb_player(person: dict, team_mlb_id: int, level: str,
                     roster_status_code: str | None = None) -> dict:
    pos = person.get("primaryPosition", {})
    pos_code = _norm_pos(pos.get("abbreviation") or pos.get("code"))
    hand_bat = person.get("batSide", {}).get("code")
    hand_throw = person.get("pitchHand", {}).get("code") or person.get("throwHand", {}).get("code")
    birth = _date(person.get("birthDate"))

    age = None
    if birth:
        today = date.today()
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))

    is_mlb = level == "MLB"
    # Derive player status from roster_status_code when available
    if roster_status_code:
        player_status = _ROSTER_STATUS_TO_PLAYER_STATUS.get(roster_status_code, "active")
    else:
        player_status = "active" if is_mlb else "minors"

    return {
        "mlb_id": _int(person.get("id")),
        "full_name": person.get("fullName", ""),
        "first_name": person.get("firstName"),
        "last_name": person.get("lastName"),
        "birth_date": birth,
        "age": age,
        "position": pos_code,
        "bats": hand_bat,
        "throws": hand_throw,
        "jersey_number": _int(person.get("primaryNumber")),
        "status": player_status,
        "roster_status": roster_status_code if is_mlb else None,
        "minor_league_level": None if is_mlb else level,
        "_team_mlb_id": team_mlb_id,
    }


def parse_batting_stats_mlb(stat_block: dict, season: int) -> dict | None:
    s = stat_block.get("stat", {})
    ab = _int(s.get("atBats")) or 0
    if ab == 0 and not s.get("gamesPlayed"):
        return None

    h   = _int(s.get("hits")) or 0
    d   = _int(s.get("doubles")) or 0
    t   = _int(s.get("triples")) or 0
    hr  = _int(s.get("homeRuns")) or 0
    bb  = _int(s.get("baseOnBalls")) or 0
    hbp = _int(s.get("hitByPitch")) or 0
    sf  = _int(s.get("sacFlies")) or 0
    k   = _int(s.get("strikeOuts")) or 0
    sb  = _int(s.get("stolenBases")) or 0
    cs  = _int(s.get("caughtStealing")) or 0
    rbi = _int(s.get("rbi")) or 0
    runs= _int(s.get("runs")) or 0
    g   = _int(s.get("gamesPlayed")) or 0
    pa  = _int(s.get("plateAppearances")) or (ab + bb + hbp + sf)

    avg  = _float(s.get("avg"))
    obp  = _float(s.get("obp"))
    slg  = _float(s.get("slg"))
    ops  = _float(s.get("ops"))

    row = {"hits": h, "doubles": d, "triples": t, "home_runs": hr,
           "walks": bb, "hit_by_pitch": hbp, "sacrifice_flies": sf,
           "at_bats": ab, "strikeouts": k}
    woba  = calculate_woba(row) if ab > 0 else None
    iso   = calculate_iso(avg or 0, slg or 0) if avg and slg else None
    babip = calculate_babip_batting(row) if ab > 0 else None
    wrc   = calculate_wrc_plus(woba) if woba else None

    return {
        "season": season, "split": "overall",
        "games": g, "plate_appearances": pa, "at_bats": ab,
        "hits": h, "doubles": d, "triples": t, "home_runs": hr,
        "rbi": rbi, "runs": runs, "walks": bb, "strikeouts": k,
        "stolen_bases": sb, "caught_stealing": cs,
        "hit_by_pitch": hbp, "sacrifice_flies": sf,
        "avg": avg, "obp": obp, "slg": slg, "ops": ops,
        "woba": woba, "wrc_plus": wrc, "babip": babip, "iso": iso,
    }


def parse_pitching_stats_mlb(stat_block: dict, season: int) -> dict | None:
    s = stat_block.get("stat", {})
    ip = _parse_ip(s.get("inningsPitched"))
    if ip == 0 and not s.get("gamesPlayed"):
        return None

    g   = _int(s.get("gamesPlayed")) or 0
    gs  = _int(s.get("gamesStarted")) or 0
    w   = _int(s.get("wins")) or 0
    l   = _int(s.get("losses")) or 0
    sv  = _int(s.get("saves")) or 0
    h   = _int(s.get("hits")) or 0
    r   = _int(s.get("runs")) or 0
    er  = _int(s.get("earnedRuns")) or 0
    bb  = _int(s.get("baseOnBalls")) or 0
    k   = _int(s.get("strikeOuts")) or 0
    hr  = _int(s.get("homeRuns")) or 0
    era = _float(s.get("era"))
    whip= _float(s.get("whip"))

    row = {"innings_pitched": ip, "home_runs_allowed": hr,
           "walks": bb, "strikeouts": k, "hits_allowed": h}
    fip  = calculate_fip(row) if ip > 0 else None
    k9   = round(k * 9 / ip, 2) if ip > 0 else None
    bb9  = round(bb * 9 / ip, 2) if ip > 0 else None
    hr9  = round(hr * 9 / ip, 2) if ip > 0 else None
    bf   = ip * 3 + h + bb
    kpct = round(k / bf, 3) if bf > 0 else None
    bbpct= round(bb / bf, 3) if bf > 0 else None

    # Refine SP vs RP based on actual games started
    position = "SP" if gs >= g * 0.5 else "RP"

    return {
        "season": season, "split": "overall",
        "games": g, "games_started": gs,
        "wins": w, "losses": l, "saves": sv,
        "innings_pitched": round(ip, 3),
        "hits_allowed": h, "runs_allowed": r, "earned_runs": er,
        "walks": bb, "strikeouts": k, "home_runs_allowed": hr,
        "era": era, "whip": whip, "fip": fip,
        "k_per_9": k9, "bb_per_9": bb9, "hr_per_9": hr9,
        "k_pct": kpct, "bb_pct": bbpct,
        "_resolved_position": position,
    }


# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------

async def upsert_team_mlb(session: AsyncSession, data: dict) -> str:
    payload = {k: v for k, v in data.items()}
    # Build the update set, but never overwrite affiliate_mlb_id with NULL —
    # once the parent-org link is established we want to keep it across re-ingests.
    update_set = {k: v for k, v in payload.items() if k != "mlb_id"}
    if update_set.get("affiliate_mlb_id") is None:
        update_set.pop("affiliate_mlb_id", None)
    stmt = pg_insert(Team).values(**payload).on_conflict_do_update(
        index_elements=["mlb_id"],
        set_=update_set,
    ).returning(Team.id)
    result = await session.execute(stmt)
    return str(result.fetchone()[0])


async def upsert_player_mlb(session: AsyncSession, data: dict, team_id: str) -> str:
    payload = {k: v for k, v in data.items() if not k.startswith("_")}
    payload["team_id"] = team_id
    stmt = pg_insert(Player).values(**payload).on_conflict_do_update(
        index_elements=["mlb_id"],
        set_={k: v for k, v in payload.items() if k != "mlb_id"},
    ).returning(Player.id)
    result = await session.execute(stmt)
    return str(result.fetchone()[0])


async def upsert_batting(session: AsyncSession, player_id: str, stats: dict) -> None:
    data = {"player_id": player_id, **stats}
    stmt = pg_insert(BattingStats).values(**data).on_conflict_do_update(
        index_elements=["player_id", "season", "split"],
        set_={k: v for k, v in data.items() if k not in ("player_id", "season", "split")},
    )
    await session.execute(stmt)


async def upsert_pitching(session: AsyncSession, player_id: str, stats: dict) -> None:
    data = {k: v for k, v in stats.items() if not k.startswith("_")}
    data["player_id"] = player_id
    stmt = pg_insert(PitchingStats).values(**data).on_conflict_do_update(
        index_elements=["player_id", "season", "split"],
        set_={k: v for k, v in data.items() if k not in ("player_id", "season", "split")},
    )
    await session.execute(stmt)


# ---------------------------------------------------------------------------
# Core ingestion logic
# ---------------------------------------------------------------------------

async def ingest_level(
    client: MLBStatsClient,
    session_factory: async_sessionmaker,
    level_name: str,
    sport_id: int,
    season: int,
    affiliate_filter: str | None,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Returns (teams_count, players_count, stats_count)."""

    log(f"\n  Level: {level_name}  (sport_id={sport_id})")

    # Fetch all teams at this level
    teams_data = await client.get("teams", {
        "sportId": sport_id,
        "season": season,
        "hydrate": "parentOrganization,venue,league,division",
    })
    all_teams = teams_data.get("teams", [])
    log(f"  Found {len(all_teams)} {level_name} teams", indent=1)

    if affiliate_filter:
        # Filter by parent MLB org abbreviation
        affiliate_upper = affiliate_filter.upper()
        all_teams = [
            t for t in all_teams
            if (t.get("parentOrganization", {}) or {}).get("abbreviation", "").upper() == affiliate_upper
        ]
        if not all_teams:
            warn(f"No {level_name} affiliate found for '{affiliate_filter}'")
            return 0, 0, 0
        log(f"  Filtered to {len(all_teams)} team(s) affiliated with {affiliate_filter}", indent=1)

    teams_saved = players_saved = stats_saved = 0

    for team_raw in all_teams:
        team_dict = parse_mlb_team(team_raw, level_name, sport_id)
        team_name = f"{team_dict['city']} {team_dict['name']}"
        log(f"  → {team_name} ({level_name})", indent=1)

        if dry_run:
            teams_saved += 1
            continue

        async with session_factory() as session:
            team_db_id = await upsert_team_mlb(session, team_dict)
            await session.commit()
        teams_saved += 1

        # Fetch full roster for this team
        roster_data = await client.get(
            f"teams/{team_raw['id']}/roster",
            {"season": season, "rosterType": "fullRoster"},
        )
        roster = roster_data.get("roster", [])

        for entry in roster:
            person_raw = entry.get("person", {})
            person_id = _int(person_raw.get("id"))
            if not person_id:
                continue

            # Fetch full player details
            person_data = await client.get(f"people/{person_id}", {"hydrate": "currentTeam"})
            person_full = (person_data.get("people") or [{}])[0]

            player_dict = parse_mlb_player(person_full, team_raw["id"], level_name)

            if dry_run:
                players_saved += 1
                continue

            async with session_factory() as session:
                player_db_id = await upsert_player_mlb(session, player_dict, team_db_id)
                await session.commit()
            players_saved += 1

            # Fetch season stats
            is_pitcher = player_dict.get("position") in ("SP", "RP", "P")
            group = "pitching" if is_pitcher else "hitting"

            try:
                stats_data = await client.get(
                    f"people/{person_id}/stats",
                    {"stats": "season", "season": season, "sportId": sport_id, "group": group},
                )
            except Exception:
                continue

            stats_list = stats_data.get("stats", [])
            if not stats_list:
                continue

            splits = stats_list[0].get("splits", [])
            if not splits:
                continue

            stat_block = splits[0]

            try:
                async with session_factory() as session:
                    if is_pitcher:
                        pstats = parse_pitching_stats_mlb(stat_block, season)
                        if pstats:
                            # Refine SP/RP on player record
                            resolved = pstats.get("_resolved_position")
                            if resolved:
                                res = await session.execute(
                                    select(Player).where(Player.id == player_db_id)
                                )
                                p = res.scalar_one_or_none()
                                if p and p.position in ("SP", "RP", "P", None):
                                    p.position = resolved
                            await upsert_pitching(session, player_db_id, pstats)
                            stats_saved += 1
                    else:
                        bstats = parse_batting_stats_mlb(stat_block, season)
                        if bstats:
                            await upsert_batting(session, player_db_id, bstats)
                            stats_saved += 1
                    await session.commit()
            except Exception:
                continue

    ok(f"{level_name}: {teams_saved} teams, {players_saved} players, {stats_saved} stat lines")
    return teams_saved, players_saved, stats_saved


# ---------------------------------------------------------------------------
# Fast MLB ingestion (2 API calls per team instead of 2 per player)
# ---------------------------------------------------------------------------

async def ingest_mlb_fast(
    client: MLBStatsClient,
    session_factory: async_sessionmaker,
    season: int,
    dry_run: bool,
) -> tuple[int, int, int]:
    """
    Load all 30 MLB teams + active rosters using just 2 API calls per team:
      1) GET /teams/{id}/roster?hydrate=person(batSide,pitchHand,birthDate,primaryPosition)
      2) GET /teams/{id}/stats?stats=season&group=hitting,pitching
    No per-player detail fetch needed — much faster than ingest_level().
    """
    log("\n  Mode: MLB fast-track  (2 calls/team ≈ 60 total API calls)")

    # 1. Get all 30 MLB teams
    teams_data = await client.get("teams", {
        "sportId": 1,
        "season": season,
        "hydrate": "venue,league,division",
    })
    all_teams = teams_data.get("teams", [])
    log(f"  Found {len(all_teams)} MLB teams", indent=1)

    teams_saved = players_saved = stats_saved = 0

    for team_raw in all_teams:
        team_dict = parse_mlb_team(team_raw, "MLB", 1)
        team_name = f"{team_dict['city']} {team_dict['name']}"
        log(f"  → {team_name}", indent=1)

        team_db_id = "dry-run"
        if not dry_run:
            async with session_factory() as session:
                team_db_id = await upsert_team_mlb(session, team_dict)
                await session.commit()
        teams_saved += 1

        # 2. 40-man roster with status codes + hydrated player details (1 call)
        #    Using 40Man (not fullRoster) so we get exactly the 40-man with
        #    correct MLB roster_status codes (A=26-man, D10/D60=IL, RM=optioned).
        try:
            roster_data = await client.get(
                f"teams/{team_raw['id']}/roster",
                {
                    "season": season,
                    "rosterType": "40Man",
                    "hydrate": "person(batSide,pitchHand,birthDate,primaryPosition,currentAge)",
                },
            )
        except Exception as exc:
            warn(f"Could not fetch roster for {team_name}: {exc}")
            continue

        # Build player_id -> player_dict map from roster
        player_db_ids: dict[int, str] = {}   # mlb_id -> db UUID

        for entry in roster_data.get("roster", []):
            person = entry.get("person", {})
            mlb_person_id = _int(person.get("id"))
            if not mlb_person_id:
                continue

            roster_status_code = entry.get("status", {}).get("code")
            player_dict = parse_mlb_player(person, team_raw["id"], "MLB",
                                           roster_status_code=roster_status_code)

            if not dry_run:
                try:
                    async with session_factory() as session:
                        player_db_id = await upsert_player_mlb(session, player_dict, team_db_id)
                        await session.commit()
                    player_db_ids[mlb_person_id] = player_db_id
                except Exception:
                    continue
            players_saved += 1

        # 3. Per-player batting stats  (GET /stats?group=hitting&teamId=…)
        try:
            bat_data = await client.get(
                "stats",
                {"stats": "season", "season": season, "group": "hitting",
                 "sportIds": 1, "teamId": team_raw["id"], "limit": 200},
            )
            for split_group in bat_data.get("stats", []):
                for split in split_group.get("splits", []):
                    player_info = split.get("player", {})
                    mlb_pid = _int(player_info.get("id"))
                    if not mlb_pid or mlb_pid not in player_db_ids:
                        continue
                    bstats = parse_batting_stats_mlb(split, season)
                    if bstats and not dry_run:
                        try:
                            async with session_factory() as session:
                                await upsert_batting(session, player_db_ids[mlb_pid], bstats)
                                await session.commit()
                            stats_saved += 1
                        except Exception:
                            pass
        except Exception:
            pass

        # 4. Per-player pitching stats  (GET /stats?group=pitching&teamId=…)
        try:
            pitch_data = await client.get(
                "stats",
                {"stats": "season", "season": season, "group": "pitching",
                 "sportIds": 1, "teamId": team_raw["id"], "limit": 200},
            )
            for split_group in pitch_data.get("stats", []):
                for split in split_group.get("splits", []):
                    player_info = split.get("player", {})
                    mlb_pid = _int(player_info.get("id"))
                    if not mlb_pid or mlb_pid not in player_db_ids:
                        continue
                    pstats = parse_pitching_stats_mlb(split, season)
                    if pstats and not dry_run:
                        try:
                            async with session_factory() as session:
                                # Refine SP vs RP from actual usage (all pitchers start as "SP"
                                # from the roster's primaryPosition "P" → SP mapping)
                                resolved = pstats.get("_resolved_position")
                                if resolved:
                                    res = await session.execute(
                                        select(Player).where(Player.id == player_db_ids[mlb_pid])
                                    )
                                    pp = res.scalar_one_or_none()
                                    if pp and pp.position in ("SP", "RP", "P", None):
                                        pp.position = resolved
                                await upsert_pitching(session, player_db_ids[mlb_pid], pstats)
                                await session.commit()
                            stats_saved += 1
                        except Exception:
                            pass
        except Exception:
            pass

    ok(f"MLB: {teams_saved} teams, {players_saved} players, {stats_saved} stat lines")
    return teams_saved, players_saved, stats_saved


# ---------------------------------------------------------------------------
# Draft picks ingestion
# ---------------------------------------------------------------------------

async def ingest_draft_picks(
    client: MLBStatsClient,
    session_factory: async_sessionmaker,
    season: int,
    dry_run: bool,
) -> int:
    """Pull draft picks from MLB Stats API and store as draft_prospect players."""
    try:
        data = await client.get(f"draft/{season}")
    except Exception as e:
        warn(f"Could not fetch draft data for {season}: {e}")
        return 0

    rounds = data.get("drafts", {}).get("rounds", [])
    saved = 0

    for rnd in rounds:
        for pick in rnd.get("picks", []):
            person = pick.get("person", {})
            mlb_id = _int(person.get("id"))
            if not mlb_id:
                continue

            name = person.get("fullName", "")
            pos_info = pick.get("pickRound", "")
            pos = _norm_pos(person.get("primaryPosition", {}).get("abbreviation"))
            school = pick.get("school", {}).get("name", "")
            pick_num = _int(pick.get("pickNumber"))
            round_num = rnd.get("round", "")

            notes = f"Round {round_num}, Pick {pick_num}"
            if school:
                notes += f" — {school}"

            player_data = {
                "mlb_id": mlb_id,
                "full_name": name,
                "first_name": person.get("firstName"),
                "last_name": person.get("lastName"),
                "position": pos,
                "bats": person.get("batSide", {}).get("code"),
                "throws": person.get("pitchHand", {}).get("code"),
                "status": "draft_prospect",
                "minor_league_level": None,
                "scout_notes": notes,
            }

            if dry_run:
                saved += 1
                continue

            async with session_factory() as session:
                stmt = pg_insert(Player).values(**player_data).on_conflict_do_update(
                    index_elements=["mlb_id"],
                    set_={k: v for k, v in player_data.items() if k != "mlb_id"},
                )
                await session.execute(stmt)
                await session.commit()
            saved += 1

    return saved


async def ingest_international(
    client: MLBStatsClient,
    session_factory: async_sessionmaker,
    dry_run: bool,
) -> int:
    """Pull international prospects (DSL/VSL/ACL) — treated as Rookie level."""
    try:
        data = await client.get("teams", {
            "sportId": 19,   # Dominican Summer League
            "hydrate": "parentOrganization",
        })
    except Exception as e:
        warn(f"Could not fetch international teams: {e}")
        return 0

    saved = 0
    for team_raw in data.get("teams", []):
        team_dict = parse_mlb_team(team_raw, "Rookie", 19)
        team_dict["level"] = "Rookie"

        if dry_run:
            saved += 1
            continue

        async with session_factory() as session:
            team_db_id = await upsert_team_mlb(session, team_dict)
            await session.commit()

        roster_data = await client.get(
            f"teams/{team_raw['id']}/roster",
            {"rosterType": "fullRoster"},
        )
        for entry in roster_data.get("roster", []):
            person_raw = entry.get("person", {})
            pid = _int(person_raw.get("id"))
            if not pid:
                continue
            person_data = await client.get(f"people/{pid}")
            person_full = (person_data.get("people") or [{}])[0]
            player_dict = parse_mlb_player(person_full, team_raw["id"], "Rookie")

            if dry_run:
                saved += 1
                continue

            async with session_factory() as session:
                await upsert_player_mlb(session, player_dict, team_db_id)
                await session.commit()
            saved += 1

    return saved


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def ingest_all_minors(
    seasons: list[int],
    levels: list[str],
    affiliate_filter: str | None,
    dry_run: bool,
) -> None:
    client = MLBStatsClient(dry_run=dry_run)
    engine = create_async_engine(settings.database_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total_teams = total_players = total_stats = 0

    try:
        for season in seasons:
            section(f"Minor League Ingestion — {season}")
            log(f"Levels   : {', '.join(levels)}")
            log(f"Affiliate: {affiliate_filter or 'all organizations'}")
            log(f"Dry run  : {dry_run}\n")

            for level_name in levels:
                if level_name == "MLB":
                    # Use fast batch path (2 calls/team vs 2 calls/player)
                    t, p, s = await ingest_mlb_fast(
                        client, session_factory, season, dry_run,
                    )
                else:
                    sport_id = LEVELS[level_name]
                    t, p, s = await ingest_level(
                        client, session_factory, level_name, sport_id,
                        season, affiliate_filter, dry_run,
                    )
                total_teams   += t
                total_players += p
                total_stats   += s

            # Draft picks for the season
            section(f"Draft Picks — {season}")
            dp = await ingest_draft_picks(client, session_factory, season, dry_run)
            log(f"Draft picks stored: {dp}")

            # International prospects
            section(f"International Prospects")
            ip = await ingest_international(client, session_factory, dry_run)
            log(f"International prospects stored: {ip}")

        section("Done")
        log(f"Total API calls : {client._call_count}")
        log(f"Teams stored    : {total_teams}")
        log(f"Players stored  : {total_players}")
        log(f"Stat lines      : {total_stats}")
        if dry_run:
            log("Dry run — nothing was written to the database.")

    finally:
        await client.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest MLB/MiLB player and stats data from the free MLB Stats API"
    )
    parser.add_argument(
        "--season", type=int, nargs="+", default=[2026],
        help="Season year(s) to ingest (default: 2026)",
    )
    parser.add_argument(
        "--level", nargs="+",
        choices=list(LEVELS.keys()),
        default=["AAA", "AA", "A+", "A", "Rookie"],
        help="Which levels to ingest (default: minor leagues only). Add MLB to include the majors.",
    )
    parser.add_argument(
        "--affiliate", type=str, default=None,
        help="Limit to one MLB parent organization, e.g. NYY, LAD, BOS",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be ingested without writing to the database",
    )
    args = parser.parse_args()

    print(f"\n  MLB/MiLB Data Ingestion  (MLB Stats API — free, no key required)")
    print(f"  Seasons   : {args.season}")
    print(f"  Levels    : {args.level}")
    print(f"  Affiliate : {args.affiliate or 'all'}")
    print(f"  Dry run   : {args.dry_run}\n")

    asyncio.run(ingest_all_minors(
        seasons=args.season,
        levels=args.level,
        affiliate_filter=args.affiliate,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
