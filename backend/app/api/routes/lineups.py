from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from ...core.database import get_db
from ...models.player import Player
from ...models.stats import BattingStats, PitchingStats
from ...services.lineup_optimizer import optimize_full_roster
from ...services.analytics import calculate_platoon_advantage

router = APIRouter(prefix="/lineups", tags=["lineups"])


class LineupRequest(BaseModel):
    team_id: UUID
    opposing_pitcher_hand: str = "R"          # L or R
    opposing_pitcher_id: UUID | None = None
    park_factor: float = 100.0
    season: int = 2026
    locked_positions: dict[str, str] | None = None   # {position: player_id}
    exclude_player_ids: list[str] | None = None


@router.post("/optimize")
async def optimize_team_lineup(req: LineupRequest, db: AsyncSession = Depends(get_db)):
    """
    Build the optimal 26-man game plan for a team:
      - Starting lineup (9) with batting order and platoon indicators
      - Bench players with role descriptions
      - Starting rotation
      - Bullpen with role assignments
    """
    # Strictly: 26-man active roster only
    players_result = await db.execute(
        select(Player).where(
            Player.team_id == req.team_id,
            Player.roster_status == "A",
        )
    )
    players = players_result.scalars().all()

    if not players:
        raise HTTPException(
            status_code=404,
            detail="No 26-man roster found for this team. Make sure roster data has been loaded.",
        )

    position_players: list[dict] = []
    starters: list[dict] = []
    relievers: list[dict] = []

    for p in players:
        base = {
            "id": str(p.id),
            "full_name": p.full_name,
            "position": p.position,
            "bats": p.bats or "R",
            "throws": p.throws or "R",
        }

        if p.position in ("SP", "RP"):
            # Load pitching stats
            ps_result = await db.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id == p.id,
                    PitchingStats.season == req.season,
                    PitchingStats.split == "overall",
                )
            )
            ps = ps_result.scalar_one_or_none()

            pitcher = {
                **base,
                "era": float(ps.era) if ps and ps.era else None,
                "fip": float(ps.fip) if ps and ps.fip else None,
                "ip": float(ps.innings_pitched) if ps and ps.innings_pitched else 0.0,
                "games": ps.games if ps else 0,
                "games_started": ps.games_started if ps else 0,
                "saves": ps.saves if ps else 0,
                "strikeouts": ps.strikeouts if ps else 0,
                "k_pct": float(ps.k_pct) if ps and ps.k_pct else None,
                "war": float(ps.war) if ps and ps.war else None,
            }
            if p.position == "SP":
                starters.append(pitcher)
            else:
                relievers.append(pitcher)
        else:
            # Load batting stats
            bs_result = await db.execute(
                select(BattingStats).where(
                    BattingStats.player_id == p.id,
                    BattingStats.season == req.season,
                    BattingStats.split == "overall",
                )
            )
            bs = bs_result.scalar_one_or_none()

            position_players.append({
                **base,
                "wrc_plus": float(bs.wrc_plus) if bs and bs.wrc_plus else 100.0,
                "woba": float(bs.woba) if bs and bs.woba else 0.317,
                "obp": float(bs.obp) if bs and bs.obp else 0.319,
                "slg": float(bs.slg) if bs and bs.slg else 0.400,
                "avg": float(bs.avg) if bs and bs.avg else 0.250,
                "iso": float(bs.iso) if bs and bs.iso else 0.150,
                "sprint_speed": float(bs.sprint_speed) if bs and bs.sprint_speed else None,
                "plate_appearances": bs.plate_appearances if bs else 0,
                "war": float(bs.war) if bs and bs.war else None,
                "status": p.status,
            })

    if not position_players:
        raise HTTPException(
            status_code=404,
            detail="No position players found on the 26-man roster.",
        )

    result = optimize_full_roster(
        position_players=position_players,
        starters=starters,
        relievers=relievers,
        opposing_pitcher_hand=req.opposing_pitcher_hand,
        park_factor=req.park_factor,
        locked_positions=req.locked_positions,
        exclude_player_ids=req.exclude_player_ids,
    )
    return result.to_dict()


@router.get("/platoon-analysis")
async def get_platoon_analysis(
    batter_hand: str = Query(..., description="L, R, or S"),
    pitcher_hand: str = Query(..., description="L or R"),
):
    analysis = calculate_platoon_advantage(batter_hand, pitcher_hand)
    return {
        "batter_hand": batter_hand,
        "pitcher_hand": pitcher_hand,
        **analysis,
        "interpretation": (
            f"Expected wOBA {'boost' if analysis['woba_delta'] >= 0 else 'penalty'} "
            f"of {abs(analysis['woba_delta']):.3f} for this matchup"
        ),
    }
