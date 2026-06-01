from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...core.database import get_db
from ...models.team import Team

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("/")
async def list_teams(
    level: str = Query("MLB"),
    db: AsyncSession = Depends(get_db),
):
    q = select(Team).where(Team.level == level).order_by(Team.division, Team.name)
    result = await db.execute(q)
    teams = result.scalars().all()
    return {
        "teams": [
            {
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
            for t in teams
        ]
    }
