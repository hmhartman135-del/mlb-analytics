"""
standings.py
─────────────────
Fetches and serves MLB standings using the FREE MLB Stats API
(statsapi.mlb.com — no API key required).

Previously used Sportradar; now fully key-free.

  GET /api/v1/standings/?season=2026

Response shape (unchanged so frontend needs no edits):
  { season, as_of, conferences: [ { name, alias, divisions: [ { name, alias, teams: [...] } ] } ] }

Responses are cached in memory for 5 minutes.
"""

import asyncio
import re
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/standings", tags=["standings"])

MLB_API = "https://statsapi.mlb.com/api/v1"

# ── In-memory cache ───────────────────────────────────────────────────────────

_cache: dict[str, dict] = {}
_cache_ts: dict[str, float] = {}
_CACHE_TTL = 300.0  # 5 minutes


# ── Helpers ───────────────────────────────────────────────────────────────────

def _int(v, default: int = 0) -> int:
    try:    return int(v)
    except: return default  # noqa: E722

def _float(v, default: float = 0.0) -> float:
    try:    return float(v)
    except: return default  # noqa: E722

def _parse_streak(code: str | None) -> tuple[str, int]:
    """'W3' → ('W', 3)   'L10' → ('L', 10)   else → ('', 0)"""
    if not code:
        return "", 0
    m = re.match(r"^([WL])(\d+)$", str(code).strip(), re.I)
    return (m.group(1).upper(), int(m.group(2))) if m else ("", 0)

def _games_back(v) -> float | None:
    """'-' or '0' → None (leader).  '2.5' → 2.5"""
    if v is None or str(v).strip() in ("-", "0", ""):
        return None
    try:
        f = float(v)
        return None if f == 0 else f
    except (TypeError, ValueError):
        return None

def _split_record(split_records: list[dict], kind: str) -> tuple[int, int]:
    """Pull wins/losses for a split type (e.g. 'home', 'away', 'lastTen')."""
    for sr in split_records:
        if sr.get("type") == kind:
            return _int(sr.get("wins")), _int(sr.get("losses"))
    return 0, 0


# ── MLB Stats API → internal format ──────────────────────────────────────────

def _transform_team_record(tr: dict) -> dict:
    team      = tr.get("team") or {}
    streak    = tr.get("streak") or {}
    records   = tr.get("records") or {}
    splits    = records.get("splitRecords") or []

    streak_kind, streak_len = _parse_streak(streak.get("streakCode"))
    home_w,  home_l  = _split_record(splits, "home")
    away_w,  away_l  = _split_record(splits, "away")
    last10_w, last10_l = _split_record(splits, "lastTen")

    # Full team name: "New York Yankees" → city = everything but last word,
    # name = last word.  Good enough for display (handles "Red Sox", etc.)
    full_name  = team.get("name") or team.get("teamName") or ""
    abbr       = team.get("abbreviation") or team.get("abbr") or ""
    name_parts = full_name.split()
    team_name  = name_parts[-1] if name_parts else full_name
    city       = " ".join(name_parts[:-1]) if len(name_parts) > 1 else ""

    wl_str = tr.get("winningPercentage") or "0"

    return {
        "id":            str(team.get("id") or ""),
        "name":          team_name,
        "city":          city,
        "full_name":     full_name,
        "alias":         abbr,
        "win":           _int(tr.get("wins")),
        "loss":          _int(tr.get("losses")),
        "pct":           _float(wl_str),
        "games_back":    _games_back(tr.get("gamesBack")),
        "home_win":      home_w,
        "home_loss":     home_l,
        "away_win":      away_w,
        "away_loss":     away_l,
        "last10_win":    last10_w,
        "last10_loss":   last10_l,
        "streak_kind":   streak_kind,
        "streak_length": streak_len,
        "division_rank": _int(tr.get("divisionRank"), 99),
        "league_rank":   _int(tr.get("leagueRank"),   99),
        "wild_card_back": str(tr.get("wildCardGamesBack") or ""),
    }


# ── Fetch from MLB Stats API ──────────────────────────────────────────────────

async def _fetch_raw(season: int) -> list[dict]:
    """Return the raw `records` list from the MLB Stats API."""
    url = f"{MLB_API}/standings"
    params = {
        "leagueId": "103,104",
        "season":   season,
        "standingsTypes": "regularSeason",
        "hydrate":  "division,conference,sport,league,team",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(5 * attempt)
            try:
                resp = await client.get(url, params=params)
            except httpx.RequestError as exc:
                if attempt == 2:
                    raise HTTPException(status_code=503, detail=f"Network error: {exc}")
                continue
            if resp.status_code == 429:
                await asyncio.sleep(10)
                continue
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail=f"No standings for season {season}")
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"MLB API returned {resp.status_code}")
            return resp.json().get("records", [])
    raise HTTPException(status_code=503, detail="MLB API unavailable; please retry")


# ── Build response + cache ────────────────────────────────────────────────────

async def _get_standings(season: int) -> dict:
    cache_key = str(season)
    now = time.monotonic()
    if cache_key in _cache and (now - _cache_ts.get(cache_key, 0.0)) < _CACHE_TTL:
        return _cache[cache_key]

    records = await _fetch_raw(season)

    # Group by league → division
    # Each record in `records` corresponds to one division.
    leagues: dict[str, dict] = {}  # alias → {name, alias, divisions}

    for record in records:
        league_obj = record.get("league") or {}
        div_obj    = record.get("division") or {}

        lg_id    = league_obj.get("id")
        lg_name  = league_obj.get("name") or ""
        lg_alias = "AL" if lg_id == 103 else "NL" if lg_id == 104 else lg_name[:2].upper()

        div_name  = div_obj.get("name") or ""
        # Shorten "American League East" → "AL East"
        short_div = div_name.replace("American League", "AL").replace("National League", "NL")
        # Alias: "ALE", "ALC", "ALW", "NLE", "NLC", "NLW"
        div_alias = ""
        if "East"    in div_name: div_alias = f"{lg_alias}E"
        elif "Central" in div_name: div_alias = f"{lg_alias}C"
        elif "West"  in div_name: div_alias = f"{lg_alias}W"

        team_records = sorted(
            record.get("teamRecords") or [],
            key=lambda t: _int(t.get("divisionRank"), 99),
        )
        teams = [_transform_team_record(t) for t in team_records]

        if lg_alias not in leagues:
            leagues[lg_alias] = {"name": lg_name, "alias": lg_alias, "divisions": []}

        leagues[lg_alias]["divisions"].append({
            "name":  short_div,
            "alias": div_alias,
            "teams": teams,
        })

    # Sort conferences: AL first, then NL
    conferences = sorted(
        leagues.values(),
        key=lambda c: 0 if c["alias"] == "AL" else 1,
    )
    # Sort divisions within each conference: East, Central, West
    _DIV_ORDER = {"E": 0, "C": 1, "W": 2}
    for conf in conferences:
        conf["divisions"].sort(key=lambda d: _DIV_ORDER.get(d["alias"][-1:], 9))

    result = {
        "season":      season,
        "as_of":       datetime.now(timezone.utc).isoformat(),
        "conferences": conferences,
    }
    _cache[cache_key] = result
    _cache_ts[cache_key] = now
    return result


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get("/")
async def get_standings(season: int = Query(2026, ge=2020, le=2030)):
    """Return division standings for the requested MLB season."""
    return await _get_standings(season)
