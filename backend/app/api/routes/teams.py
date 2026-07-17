from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from ...core.database import get_db
from ...models.team import Team

router = APIRouter(prefix="/teams", tags=["teams"])

# Reporting order for an org's minor-league affiliates, majors down to rookie ball
_MINOR_LEVEL_ORDER = ["AAA", "AA", "A+", "A", "Rookie"]


def _team_dict(t: Team) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "city": t.city,
        "full_name": f"{t.city} {t.name}",
        "abbreviation": t.abbreviation,
        "division": t.division,
        "league": t.league,
        "level": t.level,
        "ballpark": t.ballpark,
        "park_factor_runs": t.park_factor_runs,
    }


@router.get("/")
async def list_teams(
    level: str = Query("MLB"),
    db: AsyncSession = Depends(get_db),
):
    q = select(Team).where(Team.level == level).order_by(Team.division, Team.name)
    result = await db.execute(q)
    teams = result.scalars().all()
    return {"teams": [_team_dict(t) for t in teams]}


@router.get("/{team_id}/affiliates")
async def list_affiliates(team_id: UUID, db: AsyncSession = Depends(get_db)):
    """Minor-league affiliate teams (AAA down to Rookie) for an MLB organization."""
    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if not team:
        raise HTTPException(404, "Team not found")

    result = await db.execute(select(Team).where(Team.affiliate_mlb_id == team.mlb_id))
    affiliates = result.scalars().all()
    affiliates.sort(key=lambda t: _MINOR_LEVEL_ORDER.index(t.level) if t.level in _MINOR_LEVEL_ORDER else 99)

    return {"parent_team": _team_dict(team), "affiliates": [_team_dict(t) for t in affiliates]}
