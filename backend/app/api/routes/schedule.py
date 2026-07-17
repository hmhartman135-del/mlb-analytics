"""
schedule.py
─────────────────
Day-by-day MLB schedule with AI winner predictions for upcoming games and
real box scores for live/final games.

  GET  /api/v1/schedule?date=YYYY-MM-DD              — games for that day
  POST /api/v1/schedule/game/{game_pk}/predict        — (re)generate AI prediction
  GET  /api/v1/schedule/game/{game_pk}/boxscore        — real box score
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...services.schedule import generate_prediction, get_boxscore, get_schedule

router = APIRouter(prefix="/api/v1/schedule", tags=["schedule"])


@router.get("")
async def read_schedule(date: str = Query(...), db: AsyncSession = Depends(get_db)):
    return await get_schedule(db, date)


@router.post("/game/{game_pk}/predict")
async def predict_game(game_pk: int, db: AsyncSession = Depends(get_db)):
    try:
        return await generate_prediction(db, game_pk)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/game/{game_pk}/boxscore")
async def read_boxscore(game_pk: int):
    return await get_boxscore(game_pk)
