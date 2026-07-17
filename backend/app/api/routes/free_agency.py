"""
Free Agency routes
  GET /api/v1/free-agents               — current free agents (Sportradar)
  GET /api/v1/free-agents/upcoming      — 2027 FA class scraped from Spotrac
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...models.player import Player
from ...models.stats import BattingStats, PitchingStats
from ...models.team import Team
from ...models.spotrac_fa import SpotracFA
from ...services.free_agency_predictor import generate_signing_prediction

router = APIRouter(prefix="/api/v1/free-agents", tags=["free-agency"])

CURRENT_SEASON = 2026
UPCOMING_SEASON = 2027


# ── Shared helpers ────────────────────────────────────────────────────────────

def _player_base(p: Player, team_name: str | None = None) -> dict:
    return {
        "id": str(p.id),
        "mlb_id": p.mlb_id,
        "full_name": p.full_name,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "age": p.age,
        "position": p.position,
        "bats": p.bats,
        "throws": p.throws,
        "height": p.height,
        "weight": p.weight,
        "birth_country": p.birth_country,
        "status": p.status,
        "salary": p.salary,
        "contract_years": p.contract_years,
        "service_time": p.service_time,
        "team_id": str(p.team_id) if p.team_id else None,
        "team_name": team_name,
    }


def _batting(b: BattingStats) -> dict:
    return {
        "type": "batting",
        "season": b.season,
        "games": b.games,
        "plate_appearances": b.plate_appearances,
        "avg": b.avg,
        "obp": b.obp,
        "slg": b.slg,
        "ops": b.ops,
        "home_runs": b.home_runs,
        "rbi": b.rbi,
        "stolen_bases": b.stolen_bases,
        "strikeouts": b.strikeouts,
        "walks": b.walks,
        "war": b.war,
        "wrc_plus": b.wrc_plus,
        "xba": b.xba,
        "xwoba": b.xwoba,
    }


def _pitching(s: PitchingStats) -> dict:
    return {
        "type": "pitching",
        "season": s.season,
        "games": s.games,
        "games_started": s.games_started,
        "wins": s.wins,
        "losses": s.losses,
        "saves": s.saves,
        "innings_pitched": s.innings_pitched,
        "era": s.era,
        "whip": s.whip,
        "k_per_9": s.k_per_9,
        "bb_per_9": s.bb_per_9,
        "fip": s.fip,
        "war": s.war,
        "k_pct": s.k_pct,
        "bb_pct": s.bb_pct,
    }


async def _attach_stats(db: AsyncSession, players: list[Player]) -> dict:
    """Return {player_id: stat_dict} for the most recent season."""
    ids = [p.id for p in players]
    pitchers = {p.id for p in players if p.position in ("SP", "RP")}

    stats: dict = {}

    # Batting
    hitter_ids = [i for i in ids if i not in pitchers]
    if hitter_ids:
        bat_rows = await db.execute(
            select(BattingStats)
            .where(BattingStats.player_id.in_(hitter_ids),
                   BattingStats.split == "overall")
        )
        for b in bat_rows.scalars().all():
            pid = b.player_id
            if pid not in stats or b.season > stats[pid].season:
                stats[pid] = b

    # Pitching
    if pitchers:
        pit_rows = await db.execute(
            select(PitchingStats)
            .where(PitchingStats.player_id.in_(pitchers),
                   PitchingStats.split == "overall")
        )
        for s in pit_rows.scalars().all():
            pid = s.player_id
            if pid not in stats or s.season > stats[pid].season:
                stats[pid] = s

    return stats


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_current_free_agents(
    position:  str | None = Query(None),
    search:    str | None = Query(None),
    country:   str | None = Query(None),
    min_svc:   float = Query(0.0, description="Min service time (years)"),
    offset:    int = Query(0, ge=0),
    limit:     int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = select(Player).where(Player.status == "free_agent")

    if position:
        q = q.where(Player.position == position)
    if search:
        q = q.where(Player.full_name.ilike(f"%{search}%"))
    if country:
        q = q.where(Player.birth_country.ilike(f"%{country}%"))
    if min_svc > 0:
        q = q.where(Player.service_time >= min_svc)

    total = (await db.execute(
        select(func.count()).select_from(q.subquery())
    )).scalar()

    q = q.order_by(
        Player.service_time.desc().nulls_last(),
        Player.full_name,
    ).offset(offset).limit(limit)

    players = (await db.execute(q)).scalars().all()

    # Team names
    team_ids = {p.team_id for p in players if p.team_id}
    team_map: dict = {}
    if team_ids:
        t_rows = await db.execute(select(Team).where(Team.id.in_(team_ids)))
        for t in t_rows.scalars().all():
            team_map[t.id] = t.name

    stats = await _attach_stats(db, players)

    def _fmt_stats(p):
        s = stats.get(p.id)
        if s is None:
            return None
        if isinstance(s, BattingStats):
            return _batting(s)
        return _pitching(s)

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "free_agents": [
            {**_player_base(p, team_map.get(p.team_id)), "stats": _fmt_stats(p)}
            for p in players
        ],
    }


@router.get("/upcoming")
async def list_upcoming_free_agents(
    position: str | None = Query(None),
    team:     str | None = Query(None, description="Former team abbreviation (e.g. NYY)"),
    search:   str | None = Query(None),
    signed:   bool | None = Query(None, description="true=signed, false=unsigned, omit=all"),
    offset:   int = Query(0, ge=0),
    limit:    int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    Players who will become free agents after the 2026 season.
    Data sourced from spotrac.com/mlb/free-agents (2027 FA class).
    Run scripts/ingest_spotrac.py to refresh.
    """
    q = select(SpotracFA).where(SpotracFA.season == UPCOMING_SEASON)

    if position:
        q = q.where(SpotracFA.position == position)
    if search:
        q = q.where(SpotracFA.full_name.ilike(f"%{search}%"))
    if team:
        q = q.where(SpotracFA.former_team.ilike(f"%{team}%"))
    if signed is not None:
        q = q.where(SpotracFA.signed == signed)

    total = (await db.execute(
        select(func.count()).select_from(q.subquery())
    )).scalar()

    q = q.order_by(
        SpotracFA.aav.desc().nulls_last(),
        SpotracFA.contract_value.desc().nulls_last(),
        SpotracFA.full_name,
    ).offset(offset).limit(limit)

    rows = (await db.execute(q)).scalars().all()

    def _fmt(fa: SpotracFA) -> dict:
        return {
            "id": str(fa.id),
            "full_name": fa.full_name,
            "position": fa.position,
            "age": fa.age,
            "former_team": fa.former_team,
            "fa_type": fa.fa_type,
            "signed": fa.signed,
            "contract_years": fa.contract_years,
            "contract_value": fa.contract_value,
            "aav": fa.aav,
            "scraped_at": fa.scraped_at.isoformat() if fa.scraped_at else None,
        }

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "source": "spotrac.com",
        "upcoming": [_fmt(fa) for fa in rows],
    }


# ── AI signing prediction ────────────────────────────────────────────────────
# Speculative "who will/should sign this player" — grounded in real current
# standings, but inherently a guess that will be superseded once real free
# agency plays out. Not cached/persisted; regenerate on demand.

@router.post("/player/{player_id}/predict-signing")
async def predict_signing_current(player_id: UUID, db: AsyncSession = Depends(get_db)):
    """For a current (already-unsigned) free agent — real Player row with real stats."""
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    stats_map = await _attach_stats(db, [player])
    s = stats_map.get(player.id)
    stat_line = ""
    if s is not None:
        d = _batting(s) if isinstance(s, BattingStats) else _pitching(s)
        stat_line = ", ".join(f"{k}: {v}" for k, v in d.items() if k not in ("type", "season") and v is not None)

    context = (
        f"Name: {player.full_name}\n"
        f"Position: {player.position} | Bats/Throws: {player.bats}/{player.throws}\n"
        f"Age: {player.age} | Service time: {player.service_time} years\n"
    )
    if player.salary:
        context += f"Last known salary: ${player.salary:,.0f}\n"
    if stat_line:
        context += f"Most recent season stats: {stat_line}\n"

    prediction = await generate_signing_prediction(context)
    return {"player_id": str(player.id), "player_name": player.full_name, **prediction}


@router.post("/upcoming/{fa_id}/predict-signing")
async def predict_signing_upcoming(fa_id: UUID, db: AsyncSession = Depends(get_db)):
    """For a post-2026 upcoming free agent (Spotrac-sourced) — lighter bio-only context,
    since these rows aren't linked to a Player record with stats history."""
    result = await db.execute(select(SpotracFA).where(SpotracFA.id == fa_id))
    fa = result.scalar_one_or_none()
    if not fa:
        raise HTTPException(status_code=404, detail="Free agent not found")

    context = (
        f"Name: {fa.full_name}\n"
        f"Position: {fa.position}\n"
        f"Age: {fa.age}\n"
        f"Current team (will become a free agent after the 2026 season): {fa.former_team}\n"
        f"Free agency type: {fa.fa_type or 'Unknown'}\n"
    )
    if fa.aav:
        context += f"Expected market value: ~${fa.aav:,.0f}/yr AAV\n"
    if fa.contract_value:
        context += f"Expected total contract value: ~${fa.contract_value:,.0f}M\n"

    prediction = await generate_signing_prediction(context)
    return {"player_id": str(fa.id), "player_name": fa.full_name, **prediction}
