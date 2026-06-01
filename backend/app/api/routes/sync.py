"""
sync.py — Live roster & stats sync.

Uses the free MLB Stats API (statsapi.mlb.com, no key needed) to refresh:
  • 40-man roster membership + status codes (A / D10 / D60 / RM / …)
  • Season batting and pitching stats for all active players
  • Free-agent status (players no longer on any 40-man)

Runs automatically at app startup if data is >12 hours old.
Can also be triggered manually via POST /api/v1/sync/run.

GET  /api/v1/sync/status  — staleness, last run, change counts
POST /api/v1/sync/run     — kick off an immediate background sync
"""

import asyncio
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import AsyncSessionLocal
from app.models.player import Player
from app.models.team import Team
from app.models.stats import BattingStats, PitchingStats
from app.services.analytics import (
    calculate_woba, calculate_fip, calculate_iso,
    calculate_babip_batting, calculate_babip_pitching, calculate_wrc_plus,
)

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])

MLB_API = "https://statsapi.mlb.com/api/v1"
SEASON = 2026
_STALE_SECS = 12 * 3600   # 12 hours

# ── In-memory sync state ──────────────────────────────────────────────────────
_state: dict[str, Any] = {
    "status":       "idle",   # "idle" | "running" | "error"
    "last_run_ts":  0.0,      # epoch seconds of last completed run
    "last_run_iso": None,     # human-readable ISO string
    "roster_updates": 0,
    "stat_updates":   0,
    "teams_synced":   0,
    "last_error":   None,
}
_lock = asyncio.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _int(v) -> int | None:
    try:    return int(v)
    except: return None  # noqa: E722

def _float(v) -> float | None:
    try:    return float(v)
    except: return None  # noqa: E722

def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None

_POS_MAP = {
    "P": "SP", "SP": "SP", "RP": "RP", "CP": "RP",
    "C": "C", "1B": "1B", "2B": "2B", "3B": "3B",
    "SS": "SS", "LF": "LF", "CF": "CF", "RF": "RF",
    "DH": "DH", "OF": "CF", "TWP": "SP",
}

_RS_TO_STATUS = {
    "A": "active", "D7": "injured", "D10": "injured",
    "D15": "injured", "D25": "injured", "D60": "injured",
    "ILF": "injured", "RM": "active",
}


def _norm_pos(p: str | None) -> str | None:
    return _POS_MAP.get((p or "").upper()) or p


async def _fetch(http: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
    r = await http.get(f"{MLB_API}/{path}", params=params, timeout=15.0)
    r.raise_for_status()
    return r.json()


# ── Core sync logic ───────────────────────────────────────────────────────────

async def _sync_all() -> None:
    """Refresh rosters + stats for all 30 MLB teams. Updates _state in-place."""
    if _lock.locked():
        return   # another sync is already running

    async with _lock:
        _state["status"] = "running"
        _state["last_error"] = None
        roster_updates = 0
        stat_updates = 0
        teams_synced = 0

        try:
            async with httpx.AsyncClient() as http:
                # ── get all MLB teams from DB ──────────────────────────────
                async with AsyncSessionLocal() as session:
                    res = await session.execute(
                        select(Team).where(Team.level == "MLB", Team.mlb_id.isnot(None))
                    )
                    mlb_teams = res.scalars().all()

                for team in mlb_teams:
                    try:
                        ru, su = await _sync_team(http, team)
                        roster_updates += ru
                        stat_updates += su
                        teams_synced += 1
                    except Exception as exc:
                        print(f"[sync] {team.city} {team.name}: {exc}")
                        continue

        except Exception as exc:
            _state["status"] = "error"
            _state["last_error"] = str(exc)
            return

        now = time.time()
        _state.update({
            "status":       "idle",
            "last_run_ts":  now,
            "last_run_iso": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "roster_updates": roster_updates,
            "stat_updates":   stat_updates,
            "teams_synced":   teams_synced,
            "last_error":     None,
        })
        print(f"[sync] ✓ {teams_synced} teams · {roster_updates} roster · {stat_updates} stat updates")


async def _sync_team(http: httpx.AsyncClient, team: Team) -> tuple[int, int]:
    """Sync one team. Returns (roster_updates, stat_updates)."""
    roster_updates = 0
    stat_updates = 0

    # ── 1. 40-man roster with status codes ────────────────────────────────
    roster_data = await _fetch(
        http,
        f"teams/{team.mlb_id}/roster",
        {
            "season": SEASON,
            "rosterType": "40Man",
            "hydrate": "person(batSide,pitchHand,birthDate,primaryPosition,currentAge)",
        },
    )

    current_mlb_ids: set[int] = set()

    async with AsyncSessionLocal() as session:
        for entry in roster_data.get("roster", []):
            person = entry.get("person", {})
            mlb_id = _int(person.get("id"))
            if not mlb_id:
                continue
            current_mlb_ids.add(mlb_id)

            rs_code = entry.get("status", {}).get("code")
            player_status = _RS_TO_STATUS.get(rs_code, "active")
            pos_raw = (person.get("primaryPosition") or {})
            pos = _norm_pos(pos_raw.get("abbreviation") or pos_raw.get("code"))

            res = await session.execute(select(Player).where(Player.mlb_id == mlb_id))
            player = res.scalar_one_or_none()

            if player:
                changed = False
                if player.roster_status != rs_code:
                    player.roster_status = rs_code
                    changed = True
                if str(player.team_id) != str(team.id):
                    player.team_id = team.id
                    changed = True
                if player.status != player_status:
                    player.status = player_status
                    changed = True
                # Fill in missing position (don't overwrite scouted data)
                if pos and player.position is None:
                    player.position = pos
                    changed = True
                if changed:
                    roster_updates += 1
            else:
                # Brand new 40-man member — insert minimal record
                birth = _parse_date(person.get("birthDate"))
                today = date.today()
                age = None
                if birth:
                    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
                session.add(Player(
                    mlb_id=mlb_id,
                    full_name=person.get("fullName") or f"Player {mlb_id}",
                    first_name=person.get("firstName"),
                    last_name=person.get("lastName"),
                    birth_date=birth,
                    age=age,
                    position=pos,
                    bats=person.get("batSide", {}).get("code"),
                    throws=person.get("pitchHand", {}).get("code"),
                    jersey_number=_int(person.get("primaryNumber")),
                    status=player_status,
                    roster_status=rs_code,
                    team_id=team.id,
                ))
                roster_updates += 1

        # Players who LEFT the 40-man: clear roster_status, mark as minors
        res2 = await session.execute(
            select(Player).where(
                Player.team_id == team.id,
                Player.roster_status.isnot(None),
            )
        )
        for p in res2.scalars().all():
            if p.mlb_id and p.mlb_id not in current_mlb_ids:
                p.roster_status = None
                p.status = "minors"
                roster_updates += 1

        await session.commit()

    # ── 2. Batting stats ──────────────────────────────────────────────────
    try:
        bat_data = await _fetch(
            http, "stats",
            {"stats": "season", "season": SEASON, "group": "hitting",
             "sportIds": 1, "teamId": team.mlb_id, "limit": 200},
        )
        async with AsyncSessionLocal() as session:
            for sg in bat_data.get("stats", []):
                for split in sg.get("splits", []):
                    mlb_pid = _int((split.get("player") or {}).get("id"))
                    if not mlb_pid:
                        continue
                    res = await session.execute(select(Player).where(Player.mlb_id == mlb_pid))
                    p = res.scalar_one_or_none()
                    if not p:
                        continue
                    bstats = _batting_dict(split, SEASON, p.id)
                    if bstats:
                        await session.execute(
                            pg_insert(BattingStats)
                            .values(**bstats)
                            .on_conflict_do_update(
                                index_elements=["player_id", "season", "split"],
                                set_={k: v for k, v in bstats.items()
                                      if k not in ("player_id", "season", "split")},
                            )
                        )
                        stat_updates += 1
            await session.commit()
    except Exception:
        pass

    # ── 3. Pitching stats ─────────────────────────────────────────────────
    try:
        pit_data = await _fetch(
            http, "stats",
            {"stats": "season", "season": SEASON, "group": "pitching",
             "sportIds": 1, "teamId": team.mlb_id, "limit": 200},
        )
        async with AsyncSessionLocal() as session:
            for sg in pit_data.get("stats", []):
                for split in sg.get("splits", []):
                    mlb_pid = _int((split.get("player") or {}).get("id"))
                    if not mlb_pid:
                        continue
                    res = await session.execute(select(Player).where(Player.mlb_id == mlb_pid))
                    p = res.scalar_one_or_none()
                    if not p:
                        continue
                    pstats = _pitching_dict(split, SEASON, p.id)
                    if pstats:
                        await session.execute(
                            pg_insert(PitchingStats)
                            .values(**pstats)
                            .on_conflict_do_update(
                                index_elements=["player_id", "season", "split"],
                                set_={k: v for k, v in pstats.items()
                                      if k not in ("player_id", "season", "split")},
                            )
                        )
                        stat_updates += 1
            await session.commit()
    except Exception:
        pass

    return roster_updates, stat_updates


def _batting_dict(split: dict, season: int, player_id) -> dict | None:
    s = split.get("stat", {})
    ab = _int(s.get("atBats")) or 0
    g  = _int(s.get("gamesPlayed")) or 0
    if ab == 0 and g == 0:
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
    pa  = _int(s.get("plateAppearances")) or (ab + bb + hbp + sf)
    avg = _float(s.get("avg"))
    obp = _float(s.get("obp"))
    slg = _float(s.get("slg"))
    ops = _float(s.get("ops"))

    woba_row = {"hits": h, "doubles": d, "triples": t, "home_runs": hr,
                "walks": bb, "hit_by_pitch": hbp, "sacrifice_flies": sf,
                "at_bats": ab, "strikeouts": k}
    woba  = calculate_woba(woba_row) if ab > 0 else None
    iso   = calculate_iso(avg or 0, slg or 0) if avg and slg else None
    babip = calculate_babip_batting(woba_row) if ab > 0 else None
    wrc   = calculate_wrc_plus(woba) if woba else None

    return {
        "player_id": player_id, "season": season, "split": "overall",
        "games": g, "plate_appearances": pa, "at_bats": ab,
        "hits": h, "doubles": d, "triples": t, "home_runs": hr,
        "walks": bb, "hit_by_pitch": hbp, "sacrifice_flies": sf,
        "strikeouts": k, "stolen_bases": sb, "caught_stealing": cs,
        "rbi": rbi, "runs": runs,
        "avg": avg, "obp": obp, "slg": slg, "ops": ops,
        "woba": woba, "iso": iso, "babip": babip, "wrc_plus": wrc,
    }


def _pitching_dict(split: dict, season: int, player_id, _unused=None) -> dict | None:
    s = split.get("stat", {})
    ip = _float(s.get("inningsPitched")) or 0.0
    g  = _int(s.get("gamesPlayed")) or 0
    if ip == 0 and g == 0:
        return None

    gs    = _int(s.get("gamesStarted")) or 0
    wins  = _int(s.get("wins")) or 0
    losses= _int(s.get("losses")) or 0
    saves = _int(s.get("saves")) or 0
    k     = _int(s.get("strikeOuts")) or 0
    bb    = _int(s.get("baseOnBalls")) or 0
    hbp   = _int(s.get("hitByPitch")) or 0
    h     = _int(s.get("hits")) or 0
    hr    = _int(s.get("homeRuns")) or 0
    er    = _int(s.get("earnedRuns")) or 0
    runs  = _int(s.get("runs")) or 0
    era   = _float(s.get("era"))
    whip  = _float(s.get("whip"))

    fip_row   = {"strikeouts": k, "walks": bb, "hit_by_pitch": hbp,
                 "home_runs": hr, "innings_pitched": ip}
    babip_row = {"strikeouts": k, "home_runs": hr, "hits": h, "innings_pitched": ip}
    fip   = calculate_fip(fip_row) if ip > 0 else None
    babip = calculate_babip_pitching(babip_row) if ip > 0 else None

    k9 = round(k / ip * 9, 2) if ip > 0 else None
    bb9= round(bb / ip * 9, 2) if ip > 0 else None
    hr9= round(hr / ip * 9, 2) if ip > 0 else None
    total_bf = k + bb + h + _int(s.get("sacFlies") or 0)
    k_pct  = round(k  / total_bf * 100, 1) if total_bf > 0 else None
    bb_pct = round(bb / total_bf * 100, 1) if total_bf > 0 else None

    return {
        "player_id": player_id, "season": season, "split": "overall",
        "games": g, "games_started": gs,
        "wins": wins, "losses": losses, "saves": saves,
        "innings_pitched": ip,
        "hits_allowed": h, "runs_allowed": runs, "earned_runs": er,
        "walks": bb, "strikeouts": k, "home_runs_allowed": hr,
        "era": era, "whip": whip, "fip": fip, "babip_against": babip,
        "k_per_9": k9, "bb_per_9": bb9, "hr_per_9": hr9,
        "k_pct": k_pct, "bb_pct": bb_pct,
    }


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/status")
async def sync_status():
    """Return current sync state and staleness info."""
    stale = (time.time() - _state["last_run_ts"]) > _STALE_SECS
    elapsed = int(time.time() - _state["last_run_ts"])

    if _state["last_run_ts"] == 0:
        age_str = "never"
    elif elapsed < 60:
        age_str = f"{elapsed}s ago"
    elif elapsed < 3600:
        age_str = f"{elapsed // 60}m ago"
    else:
        age_str = f"{elapsed // 3600}h {(elapsed % 3600) // 60}m ago"

    return {
        "status":       _state["status"],
        "last_run_iso": _state["last_run_iso"],
        "age_display":  age_str,
        "is_stale":     stale,
        "roster_updates": _state["roster_updates"],
        "stat_updates":   _state["stat_updates"],
        "teams_synced":   _state["teams_synced"],
        "last_error":     _state["last_error"],
    }


@router.post("/run")
async def trigger_sync(background: BackgroundTasks):
    """Kick off a background sync immediately."""
    if _state["status"] == "running":
        return {"queued": False, "message": "Sync already running"}
    background.add_task(_sync_all)
    return {"queued": True, "message": "Sync started in background"}


# ── Called by main.py at startup ──────────────────────────────────────────────

async def maybe_auto_sync() -> None:
    """Run sync at startup if data is stale (>12 h old)."""
    if (time.time() - _state["last_run_ts"]) > _STALE_SECS:
        print("[sync] Data is stale — running startup sync…")
        asyncio.create_task(_sync_all())
    else:
        print("[sync] Data is fresh — skipping startup sync.")
