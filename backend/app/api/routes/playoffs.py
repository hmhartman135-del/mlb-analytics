"""
playoffs.py
─────────────────
Regular season: current playoff field (division leaders/wild cards/bubble)
plus a cached AI outlook write-up.
Postseason: real bracket from the free MLB Stats API, with a cached AI
winner prediction for any series that hasn't started yet.

  GET  /api/v1/playoffs/field?season=                        — current playoff picture + outlook
  POST /api/v1/playoffs/field/outlook?season=                 — (re)generate the AI outlook
  GET  /api/v1/playoffs/bracket?season=                       — real bracket (empty until MLB sets it)
  POST /api/v1/playoffs/bracket/series/{series_key}/predict   — (re)generate a series prediction
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...services.playoffs import generate_outlook, generate_series_prediction, get_bracket, get_field

router = APIRouter(prefix="/api/v1/playoffs", tags=["playoffs"])

DEFAULT_SEASON = 2026


@router.get("/field")
async def read_field(season: int = Query(DEFAULT_SEASON), db: AsyncSession = Depends(get_db)):
    return await get_field(db, season)


@router.post("/field/outlook")
async def refresh_outlook(season: int = Query(DEFAULT_SEASON), db: AsyncSession = Depends(get_db)):
    return await generate_outlook(db, season)


@router.get("/bracket")
async def read_bracket(season: int = Query(DEFAULT_SEASON), db: AsyncSession = Depends(get_db)):
    return await get_bracket(db, season)


@router.post("/bracket/series/{series_key}/predict")
async def predict_series(series_key: str, season: int = Query(DEFAULT_SEASON), db: AsyncSession = Depends(get_db)):
    try:
        return await generate_series_prediction(db, season, series_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
