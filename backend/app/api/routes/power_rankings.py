"""
power_rankings.py
─────────────────
AI-generated MLB power rankings — all 30 teams, ranked and justified,
grounded in real current standings.

  GET  /api/v1/power-rankings?season=   — cached rankings (empty if never generated)
  POST /api/v1/power-rankings?season=   — (re)generate via Claude
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...services.power_rankings import generate_power_rankings, get_power_rankings

router = APIRouter(prefix="/api/v1/power-rankings", tags=["power-rankings"])

DEFAULT_SEASON = 2026


@router.get("")
async def read_power_rankings(season: int = Query(DEFAULT_SEASON), db: AsyncSession = Depends(get_db)):
    return await get_power_rankings(db, season)


@router.post("")
async def refresh_power_rankings(season: int = Query(DEFAULT_SEASON), db: AsyncSession = Depends(get_db)):
    return await generate_power_rankings(db, season)
