from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, case
from uuid import UUID
from ...core.database import get_db
from ...models.player import Player
from ...models.team import Team
from ...models.stats import BattingStats, PitchingStats

router = APIRouter(prefix="/players", tags=["players"])


@router.get("/")
async def list_players(
    status: str | None = Query(None),
    position: str | None = Query(None),
    team_id: UUID | None = Query(None),
    level: str | None = Query(None, description="MLB, AAA, AA, A+, A, Rookie"),
    search: str | None = Query(None),
    limit: int = Query(100, le=5000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    q = select(Player)
    if status:
        q = q.where(Player.status == status)
    if position:
        q = q.where(Player.position == position)
    if team_id:
        q = q.where(Player.team_id == team_id)
    if level:
        if level.upper() == "MLB":
            q = q.where(Player.minor_league_level == None)  # noqa: E711
        else:
            q = q.where(Player.minor_league_level == level)
    if search:
        q = q.where(Player.full_name.ilike(f"%{search}%"))

    # Always sort MLB first, then AAA → AA → A+ → A → Rookie, then by name
    level_rank = case(
        (Player.minor_league_level == None, 0),   # noqa: E711  MLB
        (Player.minor_league_level == "AAA",   1),
        (Player.minor_league_level == "AA",    2),
        (Player.minor_league_level == "A+",    3),
        (Player.minor_league_level == "A",     4),
        (Player.minor_league_level == "Rookie", 5),
        else_=6,
    )
    q = q.order_by(level_rank, Player.full_name)
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    players = result.scalars().all()
    return {"players": [_player_to_dict(p) for p in players], "total": len(players)}


@router.get("/free-agents")
async def list_free_agents(
    position: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Player).where(Player.status == "free_agent")
    if position:
        q = q.where(Player.position == position)
    result = await db.execute(q)
    players = result.scalars().all()
    return {"free_agents": [_player_to_dict(p) for p in players]}


@router.get("/draft-prospects")
async def list_draft_prospects(
    position: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Player).where(Player.status == "draft_prospect")
    if position:
        q = q.where(Player.position == position)
    result = await db.execute(q)
    players = result.scalars().all()
    return {"prospects": [_player_to_dict(p) for p in players]}


LEVEL_ORDER = ["MLB", "AAA", "AA", "A+", "A", "Rookie"]

POS_ORDER = {
    "C": 0, "1B": 1, "2B": 2, "3B": 3, "SS": 4,
    "LF": 5, "CF": 6, "RF": 7, "DH": 8, "SP": 9, "RP": 10,
}


@router.get("/org/{team_id}")
async def org_roster(
    team_id: UUID,
    season: int = Query(2026),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all players in a full MLB organization — MLB roster + all minor league affiliates —
    grouped by level with inline season stats.
    """
    # 1. Get the selected team (should be an MLB club)
    team_result = await db.execute(select(Team).where(Team.id == team_id))
    mlb_team = team_result.scalar_one_or_none()
    if not mlb_team:
        raise HTTPException(status_code=404, detail="Team not found")

    # 2. Collect parent team + all affiliate teams
    all_teams: list[Team] = [mlb_team]
    if mlb_team.mlb_id:
        aff_result = await db.execute(
            select(Team).where(Team.affiliate_mlb_id == mlb_team.mlb_id)
        )
        all_teams += list(aff_result.scalars().all())

    # Build affiliate map for EVERY team we found — used even when levels have no players,
    # so the front-end can always show the actual affiliate team name at each level.
    affiliate_map: dict[str, dict] = {}
    for t in all_teams:
        lvl = t.level or "MLB"
        affiliate_map[lvl] = {
            "level": lvl,
            "team_name": t.name,
            "city": t.city or "",
            "team_id": str(t.id),
        }

    all_team_ids = [t.id for t in all_teams]

    # 3. All players on any of those teams
    players_result = await db.execute(
        select(Player).where(Player.team_id.in_(all_team_ids))
    )
    players = players_result.scalars().all()

    if not players:
        return {
            "org_name": mlb_team.name,
            "affiliate_map": affiliate_map,
            "groups": [],
        }

    # 4. Batch-fetch season stats for every player in one query each
    player_ids = [p.id for p in players]

    bat_result = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id.in_(player_ids),
            BattingStats.season == season,
            BattingStats.split == "overall",
        )
    )
    batting_by_player = {s.player_id: s for s in bat_result.scalars().all()}

    pit_result = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id.in_(player_ids),
            PitchingStats.season == season,
            PitchingStats.split == "overall",
        )
    )
    pitching_by_player = {s.player_id: s for s in pit_result.scalars().all()}

    # 5. Build lookup maps and group players by level
    team_by_id = {t.id: t for t in all_teams}
    groups: dict[str, dict] = {}

    for p in players:
        level = p.minor_league_level or "MLB"
        team = team_by_id.get(p.team_id)

        if level not in groups:
            groups[level] = {
                "level": level,
                "team_name": team.name if team else "Unknown",
                "city": team.city if team else "",
                "team_id": str(p.team_id) if p.team_id else "",
                "players": [],
            }

        pdict = _player_to_dict(p)
        bat = batting_by_player.get(p.id)
        pit = pitching_by_player.get(p.id)

        if p.position in ("SP", "RP") and pit:
            pdict["stats"] = {
                "type": "pitching",
                "games": pit.games,
                "games_started": pit.games_started,
                "innings_pitched": pit.innings_pitched,
                "era": pit.era,
                "fip": pit.fip,
                "whip": pit.whip,
                "k_pct": pit.k_pct,
                "bb_pct": pit.bb_pct,
                "war": pit.war,
            }
        elif bat:
            pdict["stats"] = {
                "type": "batting",
                "games": bat.games,
                "plate_appearances": bat.plate_appearances,
                "avg": bat.avg,
                "obp": bat.obp,
                "slg": bat.slg,
                "ops": bat.ops,
                "home_runs": bat.home_runs,
                "rbi": bat.rbi,
                "stolen_bases": bat.stolen_bases,
                "woba": bat.woba,
                "wrc_plus": bat.wrc_plus,
                "war": bat.war,
            }
        else:
            pdict["stats"] = None

        groups[level]["players"].append(pdict)

    # 6. Sort within each level: by position order then name
    for g in groups.values():
        g["players"].sort(
            key=lambda p: (POS_ORDER.get(p["position"], 99), p["full_name"])
        )

    return {
        "org_name": mlb_team.name,
        "affiliate_map": affiliate_map,
        "groups": [groups[lvl] for lvl in LEVEL_ORDER if lvl in groups],
    }


@router.get("/league-roster")
async def league_roster(
    level: str  = Query("26man", description="26man | AAA | AA | A+ | A | Rookie"),
    position: str | None = Query(None),
    search:   str | None = Query(None),
    season:   int        = Query(2026),
    db: AsyncSession = Depends(get_db),
):
    """
    All players at a given level across every MLB organization, with inline stats.
    level='26man' returns only players with roster_status='A' (active 26-man).
    Other levels match on minor_league_level.
    """
    # ── Player query ──────────────────────────────────────────────────────────
    q = select(Player).where(Player.team_id != None)  # noqa: E711

    if level == "26man":
        q = q.where(
            Player.minor_league_level == None,   # noqa: E711  MLB player
            Player.roster_status == "A",         # active roster
        )
    else:
        q = q.where(Player.minor_league_level == level)

    if position:
        q = q.where(Player.position == position)
    if search:
        q = q.where(Player.full_name.ilike(f"%{search}%"))

    q = q.order_by(Player.full_name)
    players = (await db.execute(q)).scalars().all()

    if not players:
        return {"players": [], "level": level, "total": 0}

    # ── Batch-fetch teams ─────────────────────────────────────────────────────
    team_ids = list({p.team_id for p in players if p.team_id})
    teams_res = await db.execute(select(Team).where(Team.id.in_(team_ids)))
    team_by_id = {t.id: t for t in teams_res.scalars().all()}

    # ── Batch-fetch stats ─────────────────────────────────────────────────────
    player_ids = [p.id for p in players]

    bat_res = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id.in_(player_ids),
            BattingStats.season == season,
            BattingStats.split == "overall",
        )
    )
    bat_by = {s.player_id: s for s in bat_res.scalars().all()}

    pit_res = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id.in_(player_ids),
            PitchingStats.season == season,
            PitchingStats.split == "overall",
        )
    )
    pit_by = {s.player_id: s for s in pit_res.scalars().all()}

    # ── Build response ─────────────────────────────────────────────────────────
    result = []
    for p in players:
        team = team_by_id.get(p.team_id)
        pdict = _player_to_dict(p)
        pdict["team_name"]  = f"{team.city} {team.name}".strip() if team else "Unknown"
        pdict["team_abbr"]  = team.abbreviation if team else "?"

        bat = bat_by.get(p.id)
        pit = pit_by.get(p.id)

        if p.position in ("SP", "RP") and pit:
            pdict["stats"] = {
                "type": "pitching",
                "games": pit.games,
                "games_started": pit.games_started,
                "innings_pitched": pit.innings_pitched,
                "era":  pit.era,
                "fip":  pit.fip,
                "whip": pit.whip,
                "k_pct":  pit.k_pct,
                "bb_pct": pit.bb_pct,
                "war":  pit.war,
            }
        elif bat:
            pdict["stats"] = {
                "type": "batting",
                "games": bat.games,
                "plate_appearances": bat.plate_appearances,
                "avg": bat.avg,
                "obp": bat.obp,
                "slg": bat.slg,
                "home_runs":    bat.home_runs,
                "rbi":          bat.rbi,
                "stolen_bases": bat.stolen_bases,
                "woba":         bat.woba,
                "wrc_plus":     bat.wrc_plus,
                "war":          bat.war,
            }
        else:
            pdict["stats"] = None

        result.append(pdict)

    return {"players": result, "level": level, "total": len(result)}


@router.get("/{player_id}")
async def get_player(player_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return _player_to_dict(player)


@router.get("/{player_id}/batting-stats")
async def get_batting_stats(
    player_id: UUID,
    season: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(BattingStats).where(BattingStats.player_id == player_id)
    if season:
        q = q.where(BattingStats.season == season)
    result = await db.execute(q)
    stats = result.scalars().all()
    return {"batting_stats": [_batting_to_dict(s) for s in stats]}


@router.get("/{player_id}/pitching-stats")
async def get_pitching_stats(
    player_id: UUID,
    season: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(PitchingStats).where(PitchingStats.player_id == player_id)
    if season:
        q = q.where(PitchingStats.season == season)
    result = await db.execute(q)
    stats = result.scalars().all()
    return {"pitching_stats": [_pitching_to_dict(s) for s in stats]}


def _player_to_dict(p: Player) -> dict:
    return {
        "id": str(p.id),
        "sportradar_id": p.sportradar_id,
        "mlb_id": p.mlb_id,
        "full_name": p.full_name,
        "age": p.age,
        "position": p.position,
        "secondary_positions": p.secondary_positions,
        "level": p.minor_league_level or "MLB",
        "minor_league_level": p.minor_league_level,
        "bats": p.bats,
        "throws": p.throws,
        "status": p.status,
        "roster_status": p.roster_status,
        "team_id": str(p.team_id) if p.team_id else None,
        "jersey_number": p.jersey_number,
        "salary": p.salary,
        "contract_years": p.contract_years,
        "service_time": p.service_time,
        "scouting": {
            "hit": p.scout_hit,
            "power": p.scout_power,
            "speed": p.scout_speed,
            "field": p.scout_field,
            "arm": p.scout_arm,
            "fb_velo": p.scout_fb_velo,
            "command": p.scout_command,
            "overall": p.scout_overall,
            "notes": p.scout_notes,
        },
    }


def _batting_to_dict(s: BattingStats) -> dict:
    return {
        "id": str(s.id),
        "season": s.season,
        "split": s.split,
        "games": s.games,
        "plate_appearances": s.plate_appearances,
        "at_bats": s.at_bats,
        "hits": s.hits,
        "doubles": s.doubles,
        "triples": s.triples,
        "home_runs": s.home_runs,
        "rbi": s.rbi,
        "walks": s.walks,
        "strikeouts": s.strikeouts,
        "stolen_bases": s.stolen_bases,
        "avg": s.avg,
        "obp": s.obp,
        "slg": s.slg,
        "ops": s.ops,
        "ops_plus": s.ops_plus,
        "woba": s.woba,
        "wrc_plus": s.wrc_plus,
        "babip": s.babip,
        "iso": s.iso,
        "xba": s.xba,
        "xwoba": s.xwoba,
        "barrel_pct": s.barrel_pct,
        "hard_hit_pct": s.hard_hit_pct,
        "sprint_speed": s.sprint_speed,
        "war": s.war,
    }


def _pitching_to_dict(s: PitchingStats) -> dict:
    return {
        "id": str(s.id),
        "season": s.season,
        "split": s.split,
        "games": s.games,
        "games_started": s.games_started,
        "wins": s.wins,
        "losses": s.losses,
        "saves": s.saves,
        "innings_pitched": s.innings_pitched,
        "era": s.era,
        "fip": s.fip,
        "xfip": s.xfip,
        "whip": s.whip,
        "k_per_9": s.k_per_9,
        "bb_per_9": s.bb_per_9,
        "k_pct": s.k_pct,
        "bb_pct": s.bb_pct,
        "era_plus": s.era_plus,
        "siera": s.siera,
        "babip_against": s.babip_against,
        "lob_pct": s.lob_pct,
        "gb_pct": s.gb_pct,
        "avg_fastball_velo": s.avg_fastball_velo,
        "xera": s.xera,
        "war": s.war,
    }
