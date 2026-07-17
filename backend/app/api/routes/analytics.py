import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from ...core.database import get_db
from ...models.player import Player
from ...models.team import Team
from ...models.stats import BattingStats, PitchingStats
from ...services.analytics import (
    calculate_woba, calculate_fip, calculate_wrc_plus,
    calculate_babip_batting, calculate_babip_pitching, value_contract,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _safe(val, digits: int = 3):
    return round(float(val), digits) if val is not None else None


def _pct(num, denom, digits: int = 3):
    if not denom:
        return None
    return round(float(num) / float(denom), digits)


def _estimate_war_bat(s) -> float:
    if not s or not s.woba or not s.plate_appearances or (s.plate_appearances or 0) < 10:
        return 0.0
    raa = (s.woba - 0.320) / 1.15 * s.plate_appearances
    return round((raa + 2.0 * s.plate_appearances / 600) / 10, 1)


def _estimate_war_pitch(s) -> float:
    if not s or not s.fip or not s.innings_pitched or (s.innings_pitched or 0) < 1:
        return 0.0
    replacement = 0.5 * s.innings_pitched / 180
    return round((4.20 - s.fip) * s.innings_pitched / 9 / 1.5 + replacement, 1)


def _split_stat(raw: dict | None, key: str, cast=str) -> str | float | int | None:
    """Safely pull a value from an MLB API split stat dict."""
    if not raw:
        return None
    val = raw.get(key)
    if val is None:
        return None
    try:
        return cast(val)
    except (ValueError, TypeError):
        return None


# ── MLB API: fetch platoon splits for a full 40-man roster in one call ────────

async def _fetch_splits(team_mlb_id: int, season: int) -> dict[int, dict]:
    """
    Returns  {player_mlb_id: {
        "hit_vs_l": {...raw stat dict...},
        "hit_vs_r": {...},
        "pit_vs_l": {...},
        "pit_vs_r": {...},
    }}
    """
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_mlb_id}/roster"
    params = {
        "rosterType": "40Man",
        "season": season,
        "hydrate": (
            f"person(stats(group=[hitting,pitching],"
            f"type=statSplits,sitCodes=[vl,vr],season={season}))"
        ),
    }
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return {}

    result: dict[int, dict] = {}
    for member in data.get("roster", []):
        person  = member.get("person", {})
        mlb_id  = person.get("id")
        if not mlb_id:
            continue

        entry: dict[str, dict] = {}
        for stat_group in person.get("stats", []):
            grp  = stat_group.get("group", {}).get("displayName", "")   # "hitting" | "pitching"
            key_prefix = "hit" if grp == "hitting" else "pit"

            for split in stat_group.get("splits", []):
                desc = split.get("split", {}).get("description", "").lower()
                if "left" in desc:
                    entry[f"{key_prefix}_vs_l"] = split.get("stat", {})
                elif "right" in desc:
                    entry[f"{key_prefix}_vs_r"] = split.get("stat", {})

        if entry:
            result[mlb_id] = entry

    return result


# ── main endpoint ─────────────────────────────────────────────────────────────

@router.get("/team/{team_id}/overview")
async def team_analytics_overview(
    team_id: UUID,
    season: int = Query(2026),
    db: AsyncSession = Depends(get_db),
):
    # Load team (for mlb_id)
    team_row = await db.execute(select(Team).where(Team.id == team_id))
    team = team_row.scalar_one_or_none()
    is_mlb = bool(team and team.level == "MLB")

    # Load roster — MLB teams: 40-man only (roster_status set). Minor-league
    # affiliates don't carry a roster_status at all, so just match team_id.
    if is_mlb:
        roster_result = await db.execute(
            select(Player).where(
                Player.team_id == team_id,
                Player.roster_status.isnot(None),
            )
        )
    else:
        roster_result = await db.execute(
            select(Player).where(Player.team_id == team_id)
        )
    roster = roster_result.scalars().all()

    hitters  = [p for p in roster if p.position not in ("SP", "RP")]
    pitchers = [p for p in roster if p.position in ("SP", "RP")]

    # Batch load season stats
    hitter_ids  = [p.id for p in hitters]
    pitcher_ids = [p.id for p in pitchers]

    bat_rows = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id.in_(hitter_ids),
            BattingStats.season == season,
            BattingStats.split == "overall",
        )
    )
    bat_by = {s.player_id: s for s in bat_rows.scalars().all()}

    pit_rows = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id.in_(pitcher_ids),
            PitchingStats.season == season,
            PitchingStats.split == "overall",
        )
    )
    pit_by = {s.player_id: s for s in pit_rows.scalars().all()}

    # Fetch platoon splits from MLB Stats API (one request for whole roster).
    # Splits use rosterType=40Man, an MLB-only concept — skip for affiliates.
    splits_by_mlb: dict[int, dict] = {}
    if is_mlb and team and team.mlb_id:
        splits_by_mlb = await _fetch_splits(team.mlb_id, season)

    # ── Hitter stats ──────────────────────────────────────────────────────────
    hitter_stats = []
    for p in hitters:
        s = bat_by.get(p.id)
        if not s:
            continue

        war_val = _safe(s.war, 1) or _estimate_war_bat(s)
        pa      = s.plate_appearances or 0

        sp      = splits_by_mlb.get(p.mlb_id or -1, {})
        hvl     = sp.get("hit_vs_l")   # raw dict or None
        hvr     = sp.get("hit_vs_r")

        def hit_split(raw):
            if not raw:
                return None
            return {
                "avg": raw.get("avg"),
                "obp": raw.get("obp"),
                "slg": raw.get("slg"),
                "ops": raw.get("ops"),
                "pa":  raw.get("plateAppearances"),
                "hr":  raw.get("homeRuns"),
                "h":   raw.get("hits"),
                "bb":  raw.get("baseOnBalls"),
                "k":   raw.get("strikeOuts"),
                "rbi": raw.get("rbi"),
            }

        hitter_stats.append({
            "player_id":   str(p.id),
            "name":        p.full_name,
            "position":    p.position,
            "bats":        p.bats,
            # ── Volume / counting ─────────────────────────────────────────────
            "games":       s.games,
            "pa":          pa,
            "hits":        s.hits,
            "doubles":     s.doubles,
            "triples":     s.triples,
            "home_runs":   s.home_runs,
            "rbi":         s.rbi,
            "walks":       s.walks,
            "strikeouts":  s.strikeouts,
            # ── Rates / production ────────────────────────────────────────────
            "avg":         _safe(s.avg),
            "obp":         _safe(s.obp),
            "slg":         _safe(s.slg),
            "ops":         _safe(s.ops),
            "iso":         _safe(s.iso),
            "woba":        _safe(s.woba),
            "wrc_plus":    _safe(s.wrc_plus, 1),
            "ops_plus":    _safe(s.ops_plus, 1),
            "war":         war_val,
            # ── Plate discipline ──────────────────────────────────────────────
            "k_pct":       _pct(s.strikeouts, pa),
            "bb_pct":      _pct(s.walks, pa),
            "babip":       _safe(s.babip),
            # ── Quality of contact ────────────────────────────────────────────
            "hard_hit_pct":  _safe(s.hard_hit_pct, 1),
            "barrel_pct":    _safe(s.barrel_pct, 1),
            "xba":           _safe(s.xba),
            "xslg":          _safe(s.xslg),
            "xwoba":         _safe(s.xwoba),
            "sprint_speed":  _safe(s.sprint_speed, 1),
            # ── Platoon splits ────────────────────────────────────────────────
            "vs_lhp": hit_split(hvl),
            "vs_rhp": hit_split(hvr),
        })

    # ── Pitcher stats ─────────────────────────────────────────────────────────
    pitcher_stats = []
    for p in pitchers:
        s = pit_by.get(p.id)
        if not s:
            continue

        war_val = _safe(s.war, 1) or _estimate_war_pitch(s)
        ip = float(s.innings_pitched or 0)
        h  = float(s.hits_allowed or 0)
        baa = round(h / (ip * 3 + h), 3) if (ip * 3 + h) > 0 else None

        sp   = splits_by_mlb.get(p.mlb_id or -1, {})
        pvl  = sp.get("pit_vs_l")   # vs left-handed batters
        pvr  = sp.get("pit_vs_r")   # vs right-handed batters

        # Determine which side the pitcher dominates (lower OPS against = better)
        better_vs = None
        ops_l = float(pvl["ops"]) if pvl and pvl.get("ops") else None
        ops_r = float(pvr["ops"]) if pvr and pvr.get("ops") else None
        if ops_l is not None and ops_r is not None:
            better_vs = "LHB" if ops_l < ops_r else "RHB"
        elif ops_l is not None:
            better_vs = "LHB"
        elif ops_r is not None:
            better_vs = "RHB"

        def pit_split(raw):
            if not raw:
                return None
            return {
                "avg":    raw.get("avg"),
                "obp":    raw.get("obp"),
                "slg":    raw.get("slg"),
                "ops":    raw.get("ops"),
                "k_per_9": raw.get("strikeoutsPer9Inn"),
                "bb_per_9": raw.get("walksPer9Inn"),
                "pa":     raw.get("battersFaced"),
                "k":      raw.get("strikeOuts"),
                "bb":     raw.get("baseOnBalls"),
            }

        pitcher_stats.append({
            "player_id":       str(p.id),
            "name":            p.full_name,
            "position":        p.position,
            "throws":          p.throws,
            "games":           s.games,
            "games_started":   s.games_started,
            "ip":              _safe(s.innings_pitched, 1),
            "era":             _safe(s.era, 2),
            "fip":             _safe(s.fip, 2),
            "xfip":            _safe(s.xfip, 2),
            "siera":           _safe(s.siera, 2),
            "xera":            _safe(s.xera, 2),
            "whip":            _safe(s.whip, 3),
            "war":             war_val,
            "strikeouts":      s.strikeouts,
            "k_per_9":         _safe(s.k_per_9, 1),
            "bb_per_9":        _safe(s.bb_per_9, 1),
            "k_pct":           _safe(s.k_pct, 3),
            "bb_pct":          _safe(s.bb_pct, 3),
            "gb_pct":          _safe(s.gb_pct, 1),
            "fb_pct":          _safe(s.fb_pct, 1),
            "baa":             baa,
            "babip_against":   _safe(s.babip_against, 3),
            "hr_per_9":        _safe(s.hr_per_9, 2),
            "avg_fastball_velo": _safe(s.avg_fastball_velo, 1),
            # ── Platoon splits ─────────────────────────────────────────────────
            "vs_lhb":    pit_split(pvl),
            "vs_rhb":    pit_split(pvr),
            "better_vs": better_vs,   # "LHB" | "RHB" | null
        })

    # ── Team summaries ────────────────────────────────────────────────────────
    team_war = sum((s.get("war") or 0) for s in hitter_stats + pitcher_stats)
    avg_wrc_plus = (
        sum((s.get("wrc_plus") or 100) for s in hitter_stats) / len(hitter_stats)
        if hitter_stats else 100
    )
    team_fip = (
        sum((s.get("fip") or 4.0) for s in pitcher_stats) / len(pitcher_stats)
        if pitcher_stats else None
    )

    return {
        "season":           season,
        "team_level":       team.level if team else None,
        "team_name":        f"{team.city} {team.name}" if team else None,
        "team_war":         round(team_war, 1),
        "avg_wrc_plus":     round(avg_wrc_plus, 1),
        "team_fip":         round(team_fip, 2) if team_fip else None,
        "hitting_leaderboard":  sorted(hitter_stats,  key=lambda x: x.get("war") or 0, reverse=True),
        "pitching_leaderboard": sorted(pitcher_stats, key=lambda x: x.get("war") or 0, reverse=True),
    }


@router.get("/matchup")
async def analyze_matchup(
    batter_id: UUID = Query(...),
    pitcher_id: UUID = Query(...),
    season: int = Query(2026),
    db: AsyncSession = Depends(get_db),
):
    batter_result  = await db.execute(select(Player).where(Player.id == batter_id))
    pitcher_result = await db.execute(select(Player).where(Player.id == pitcher_id))
    batter  = batter_result.scalar_one_or_none()
    pitcher = pitcher_result.scalar_one_or_none()

    if not batter or not pitcher:
        return {"error": "Batter or pitcher not found"}

    batter_stats_res = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id == batter_id,
            BattingStats.split == f"vs_{'LHP' if pitcher.throws == 'L' else 'RHP'}",
            BattingStats.season == season,
        )
    )
    batter_vs_hand = batter_stats_res.scalar_one_or_none()

    pitcher_stats_res = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id == pitcher_id,
            PitchingStats.season == season,
            PitchingStats.split == "overall",
        )
    )
    pitcher_stats = pitcher_stats_res.scalar_one_or_none()

    from ...services.analytics import calculate_platoon_advantage
    platoon = calculate_platoon_advantage(batter.bats or "R", pitcher.throws or "R")

    return {
        "batter":  {"id": str(batter.id),  "name": batter.full_name,  "bats": batter.bats},
        "pitcher": {"id": str(pitcher.id), "name": pitcher.full_name, "throws": pitcher.throws},
        "platoon_analysis": platoon,
        "batter_vs_this_hand": {
            "woba": batter_vs_hand.woba if batter_vs_hand else None,
            "avg":  batter_vs_hand.avg  if batter_vs_hand else None,
            "obp":  batter_vs_hand.obp  if batter_vs_hand else None,
            "slg":  batter_vs_hand.slg  if batter_vs_hand else None,
        },
        "pitcher_season": {
            "era":              pitcher_stats.era              if pitcher_stats else None,
            "fip":              pitcher_stats.fip              if pitcher_stats else None,
            "k_pct":            pitcher_stats.k_pct            if pitcher_stats else None,
            "avg_fastball_velo": pitcher_stats.avg_fastball_velo if pitcher_stats else None,
        },
    }
