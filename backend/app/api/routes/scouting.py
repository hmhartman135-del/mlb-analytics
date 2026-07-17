import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from uuid import UUID
from ...core.database import get_db
from ...models.player import Player
from ...models.stats import BattingStats, PitchingStats
from ...services.scouting import generate_scouting_report, generate_player_bio_analysis

router = APIRouter(prefix="/scouting", tags=["scouting"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _grade_color(g):
    if not g:
        return None
    if g >= 70:
        return "elite"
    if g >= 55:
        return "above_avg"
    if g >= 45:
        return "avg"
    return "below_avg"


def _player_bio(p: Player) -> dict:  # noqa: C901
    return {
        "id":              str(p.id),
        "mlb_id":        p.mlb_id,
        "full_name":     p.full_name,
        "position":      p.position,
        "age":           p.age,
        "bats":          p.bats,
        "throws":        p.throws,
        "status":        p.status,
        "level":         p.minor_league_level,
        "height":        p.height,
        "weight":        p.weight,
        "birth_city":    p.birth_city,
        "birth_country": p.birth_country,
        "school":        p.school,
        "school_class":  p.school_class,
        "draft_year":    p.draft_year,
        "draft_pick":    p.draft_pick,
        "draft_rank":          p.draft_rank,
        "signing_bonus":       p.signing_bonus,
        "prospect_rank":       p.prospect_rank,
        "org_prospect_rank":   p.org_prospect_rank,
        "parent_org_mlb_id":   p.parent_org_mlb_id,
        "parent_org_abbr":     p.parent_org_abbr,
        "grades": {
            "hit":     p.scout_hit,
            "power":   p.scout_power,
            "speed":   p.scout_speed,
            "field":   p.scout_field,
            "arm":     p.scout_arm,
            "fb_velo": p.scout_fb_velo,
            "command": p.scout_command,
            "overall": p.scout_overall,
        },
        "notes": p.scout_notes,
    }


# ── Pydantic models ───────────────────────────────────────────────────────────

class ScoutingReportRequest(BaseModel):
    player_id: UUID
    report_type: str = "full"   # full | brief | draft | trade
    season: int = 2026


class UpdateScoutingGradesRequest(BaseModel):
    scout_hit: int | None = None
    scout_power: int | None = None
    scout_speed: int | None = None
    scout_field: int | None = None
    scout_arm: int | None = None
    scout_fb_velo: int | None = None
    scout_command: int | None = None
    scout_overall: int | None = None
    scout_notes: str | None = None


# ── Prospect list ─────────────────────────────────────────────────────────────

@router.get("/prospects")
async def list_prospects(
    position:     str | None = Query(None),
    level:        str | None = Query(None),
    country:      str | None = Query(None),
    school:       str | None = Query(None),
    search:       str | None = Query(None),
    org:          str | None = Query(None, description="Parent org abbreviation e.g. 'NYY'"),
    min_overall:  int = Query(0),
    ranked_only:  bool = Query(False, description="MLB Pipeline draft ranked"),
    top100:       bool = Query(False, description="Show overall top-100 prospects"),
    top30_org:    str | None = Query(None, description="Top-30 for a specific org e.g. 'NYY'"),
    school_class: str | None = Query(None),
    offset:       int = Query(0, ge=0),
    limit:        int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    if top100:
        q = select(Player).where(Player.prospect_rank.isnot(None))
    elif top30_org:
        q = select(Player).where(
            Player.org_prospect_rank.isnot(None),
            Player.parent_org_abbr == top30_org.upper(),
        )
    elif ranked_only:
        q = select(Player).where(Player.draft_rank.isnot(None))
    elif level == "draft_prospect":
        # "Draft" tab = players actually just drafted (status="drafted_2026"
        # etc.), not the broader speculative draft-eligible pool used by
        # the 2027 mock-draft planner.
        q = select(Player).where(Player.status.like("drafted_%"))
    else:
        q = select(Player).where(Player.status.in_(["draft_prospect", "minors"]))

    if min_overall > 0:
        q = q.where(Player.scout_overall >= min_overall)
    if position:
        q = q.where(Player.position == position)
    if school:
        q = q.where(Player.school.ilike(f"%{school}%"))
    if school_class:
        q = q.where(Player.school_class == school_class)
    if org and not top30_org:
        q = q.where(Player.parent_org_abbr == org.upper())
    if not ranked_only and not top100 and not top30_org and level and level != "draft_prospect":
        q = q.where(Player.minor_league_level == level)
    if country:
        q = q.where(Player.birth_country.ilike(f"%{country}%"))
    if search:
        q = q.where(Player.full_name.ilike(f"%{search}%"))

    count_q = select(func.count()).select_from(q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar()

    if top100:
        q = q.order_by(Player.prospect_rank.asc())
    elif top30_org:
        q = q.order_by(Player.org_prospect_rank.asc())
    elif ranked_only:
        q = q.order_by(Player.draft_rank.asc().nulls_last(), Player.full_name)
    elif level == "draft_prospect":
        q = q.order_by(Player.draft_pick.asc().nulls_last(), Player.full_name)
    else:
        q = q.order_by(Player.scout_overall.desc().nulls_last(), Player.full_name)

    q = q.offset(offset).limit(limit)

    result = await db.execute(q)
    prospects = result.scalars().all()

    # Batch-load most recent stats
    player_ids = [p.id for p in prospects]
    bat_map: dict = {}
    pit_map: dict = {}

    if player_ids:
        hitter_ids = [p.id for p in prospects if p.position not in ("SP", "RP")]
        pitcher_ids = [p.id for p in prospects if p.position in ("SP", "RP")]

        if hitter_ids:
            bat_rows = await db.execute(
                select(BattingStats).where(
                    BattingStats.player_id.in_(hitter_ids),
                    BattingStats.split == "overall",
                ).order_by(BattingStats.season.desc())
            )
            for s in bat_rows.scalars().all():
                if s.player_id not in bat_map:
                    bat_map[s.player_id] = s

        if pitcher_ids:
            pit_rows = await db.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id.in_(pitcher_ids),
                    PitchingStats.split == "overall",
                ).order_by(PitchingStats.season.desc())
            )
            for s in pit_rows.scalars().all():
                if s.player_id not in pit_map:
                    pit_map[s.player_id] = s

    output = []
    for p in prospects:
        bio = _player_bio(p)

        # Attach most recent stats
        is_pitcher = p.position in ("SP", "RP")
        if is_pitcher:
            s = pit_map.get(p.id)
            bio["stats"] = {
                "type": "pitching",
                "season": s.season if s else None,
                "games": s.games if s else None,
                "games_started": s.games_started if s else None,
                "innings_pitched": float(s.innings_pitched) if s and s.innings_pitched else None,
                "era": float(s.era) if s and s.era else None,
                "fip": float(s.fip) if s and s.fip else None,
                "whip": float(s.whip) if s and s.whip else None,
                "k_pct": float(s.k_pct) if s and s.k_pct else None,
                "bb_pct": float(s.bb_pct) if s and s.bb_pct else None,
                "war": float(s.war) if s and s.war else None,
                "avg_fastball_velo": float(s.avg_fastball_velo) if s and s.avg_fastball_velo else None,
            } if s else None
        else:
            s = bat_map.get(p.id)
            bio["stats"] = {
                "type": "batting",
                "season": s.season if s else None,
                "games": s.games if s else None,
                "plate_appearances": s.plate_appearances if s else None,
                "avg": float(s.avg) if s and s.avg else None,
                "obp": float(s.obp) if s and s.obp else None,
                "slg": float(s.slg) if s and s.slg else None,
                "ops": float(s.ops) if s and s.ops else None,
                "home_runs": s.home_runs if s else None,
                "rbi": s.rbi if s else None,
                "stolen_bases": s.stolen_bases if s else None,
                "woba": float(s.woba) if s and s.woba else None,
                "wrc_plus": float(s.wrc_plus) if s and s.wrc_plus else None,
                "war": float(s.war) if s and s.war else None,
            } if s else None

        output.append(bio)

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "prospects": output,
    }


# ── Player career history ─────────────────────────────────────────────────────

async def _load_career_history(player_id: UUID, db: AsyncSession) -> tuple[Player, dict, list, list]:
    """Shared by /history and /ai-bio — player row + bio dict + DB stat history
    + MLB API year-by-year (majors and minors)."""
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    bio = _player_bio(player)

    # DB stats history
    is_pitcher = player.position in ("SP", "RP")
    db_history = []

    if is_pitcher:
        rows = await db.execute(
            select(PitchingStats).where(
                PitchingStats.player_id == player_id,
                PitchingStats.split == "overall",
            ).order_by(PitchingStats.season.desc())
        )
        for s in rows.scalars().all():
            db_history.append({
                "season": s.season,
                "level": "MLB",
                "games": s.games,
                "games_started": s.games_started,
                "innings_pitched": float(s.innings_pitched) if s.innings_pitched else None,
                "era": float(s.era) if s.era else None,
                "fip": float(s.fip) if s.fip else None,
                "whip": float(s.whip) if s.whip else None,
                "strikeouts": s.strikeouts,
                "k_pct": float(s.k_pct) if s.k_pct else None,
                "bb_pct": float(s.bb_pct) if s.bb_pct else None,
                "war": float(s.war) if s.war else None,
            })
    else:
        rows = await db.execute(
            select(BattingStats).where(
                BattingStats.player_id == player_id,
                BattingStats.split == "overall",
            ).order_by(BattingStats.season.desc())
        )
        for s in rows.scalars().all():
            db_history.append({
                "season": s.season,
                "level": "MLB",
                "games": s.games,
                "plate_appearances": s.plate_appearances,
                "avg": float(s.avg) if s.avg else None,
                "obp": float(s.obp) if s.obp else None,
                "slg": float(s.slg) if s.slg else None,
                "ops": float(s.ops) if s.ops else None,
                "home_runs": s.home_runs,
                "rbi": s.rbi,
                "stolen_bases": s.stolen_bases,
                "woba": float(s.woba) if s.woba else None,
                "wrc_plus": float(s.wrc_plus) if s.wrc_plus else None,
                "war": float(s.war) if s.war else None,
            })

    # MLB API year-by-year (minor league history)
    api_history = []
    if player.mlb_id:
        try:
            url = f"https://statsapi.mlb.com/api/v1/people/{player.mlb_id}"
            params = {
                "hydrate": "stats(group=[hitting,pitching],type=yearByYear,sportIds=11,12,13,14,16)"
            }
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()

            SPORT_LEVEL = {11: "AAA", 12: "AA", 13: "A+", 14: "A", 16: "Rookie"}

            for person in data.get("people", []):
                for stat_group in person.get("stats", []):
                    grp = stat_group.get("group", {}).get("displayName", "")
                    for split in stat_group.get("splits", []):
                        sport_id = split.get("sport", {}).get("id")
                        level = SPORT_LEVEL.get(sport_id, "MiLB")
                        season = split.get("season")
                        team_name = split.get("team", {}).get("name", "")
                        stat = split.get("stat", {})

                        if grp == "hitting":
                            try:
                                pa = int(stat.get("plateAppearances") or 0)
                                api_history.append({
                                    "season": int(season) if season else None,
                                    "level": level,
                                    "team": team_name,
                                    "games": int(stat.get("gamesPlayed") or 0),
                                    "plate_appearances": pa,
                                    "avg": stat.get("avg"),
                                    "obp": stat.get("obp"),
                                    "slg": stat.get("slg"),
                                    "ops": stat.get("ops"),
                                    "home_runs": int(stat.get("homeRuns") or 0),
                                    "rbi": int(stat.get("rbi") or 0),
                                    "stolen_bases": int(stat.get("stolenBases") or 0),
                                    "strikeouts": int(stat.get("strikeOuts") or 0),
                                    "walks": int(stat.get("baseOnBalls") or 0),
                                    "type": "batting",
                                })
                            except Exception:
                                pass
                        elif grp == "pitching":
                            try:
                                api_history.append({
                                    "season": int(season) if season else None,
                                    "level": level,
                                    "team": team_name,
                                    "games": int(stat.get("gamesPlayed") or 0),
                                    "games_started": int(stat.get("gamesStarted") or 0),
                                    "innings_pitched": stat.get("inningsPitched"),
                                    "era": stat.get("era"),
                                    "whip": stat.get("whip"),
                                    "strikeouts": int(stat.get("strikeOuts") or 0),
                                    "walks": int(stat.get("baseOnBalls") or 0),
                                    "type": "pitching",
                                })
                            except Exception:
                                pass

            # Sort descending
            api_history.sort(key=lambda x: x.get("season") or 0, reverse=True)
        except Exception:
            pass

    return player, bio, db_history, api_history


@router.get("/player/{player_id}/history")
async def player_career_history(
    player_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns player bio + full career stats (DB rows first, then MLB API year-by-year).
    """
    _player, bio, db_history, api_history = await _load_career_history(player_id, db)
    return {
        "player": bio,
        "db_history": db_history,
        "minor_league_history": api_history,
    }


@router.post("/player/{player_id}/ai-bio")
async def player_ai_bio(player_id: UUID, db: AsyncSession = Depends(get_db)):
    """AI-written background/career/strengths/concerns profile, grounded in the
    player's real multi-year, multi-level stat history (see /history)."""
    player, bio, db_history, api_history = await _load_career_history(player_id, db)
    sections = await generate_player_bio_analysis(bio, db_history, api_history)
    return {
        "player_id": str(player.id),
        "player_name": player.full_name,
        **sections,
    }


# ── Generate scouting report ──────────────────────────────────────────────────

@router.post("/report")
async def create_scouting_report(req: ScoutingReportRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Player).where(Player.id == req.player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    player_dict = {
        "id":            str(player.id),
        "full_name":     player.full_name,
        "position":      player.position,
        "age":           player.age,
        "bats":          player.bats,
        "throws":        player.throws,
        "status":        player.status,
        "height":        player.height,
        "weight":        player.weight,
        "birth_country": player.birth_country,
        "school":        player.school,
        "scout_hit":     player.scout_hit,
        "scout_power":   player.scout_power,
        "scout_speed":   player.scout_speed,
        "scout_field":   player.scout_field,
        "scout_arm":     player.scout_arm,
        "scout_fb_velo": player.scout_fb_velo,
        "scout_command": player.scout_command,
        "scout_overall": player.scout_overall,
        "scout_notes":   player.scout_notes,
    }

    is_pitcher = player.position in ("SP", "RP")
    stats_dict = None
    if is_pitcher:
        s_result = await db.execute(
            select(PitchingStats).where(
                PitchingStats.player_id == player.id,
                PitchingStats.split == "overall",
            ).order_by(PitchingStats.season.desc()).limit(1)
        )
        s = s_result.scalar_one_or_none()
        if s:
            stats_dict = {
                "era": s.era, "fip": s.fip, "whip": s.whip,
                "k_pct": s.k_pct, "bb_pct": s.bb_pct,
                "avg_fastball_velo": s.avg_fastball_velo, "war": s.war,
            }
    else:
        s_result = await db.execute(
            select(BattingStats).where(
                BattingStats.player_id == player.id,
                BattingStats.split == "overall",
            ).order_by(BattingStats.season.desc()).limit(1)
        )
        s = s_result.scalar_one_or_none()
        if s:
            stats_dict = {
                "avg": s.avg, "obp": s.obp, "slg": s.slg,
                "woba": s.woba, "wrc_plus": s.wrc_plus,
                "home_runs": s.home_runs, "stolen_bases": s.stolen_bases, "war": s.war,
            }

    report_text = await generate_scouting_report(
        player=player_dict, stats=stats_dict, report_type=req.report_type
    )
    return {
        "player_id":   str(player.id),
        "player_name": player.full_name,
        "report_type": req.report_type,
        "report":      report_text,
    }


# ── Update grades ─────────────────────────────────────────────────────────────

@router.put("/{player_id}/grades")
async def update_scouting_grades(
    player_id: UUID,
    req: UpdateScoutingGradesRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    for field, value in req.model_dump(exclude_none=True).items():
        setattr(player, field, value)

    await db.commit()
    return {"message": "Scouting grades updated", "player_id": str(player_id)}
