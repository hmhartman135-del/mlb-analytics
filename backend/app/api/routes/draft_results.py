"""
draft_results.py
─────────────────
Real completed MLB draft results (distinct from draft.py's forward-looking
mock-draft planner). Data source: MLB's public Stats API.

  POST /api/v1/draft-results/{year}/ingest              — fetch + store real picks
  GET  /api/v1/draft-results/{year}                      — all picks (optionally by round/team)
  GET  /api/v1/draft-results/{year}/rounds                — distinct rounds for the year
  GET  /api/v1/draft-results/{year}/team/{team_id}        — one team's full draft class + cached grade
  POST /api/v1/draft-results/{year}/team/{team_id}/grade  — (re)generate the AI team grade
  POST /api/v1/draft-results/player/{player_id}/explain    — AI background/stats explanation for one pick
"""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...services.draft_results import (
    ingest_real_draft, list_draft_picks, list_rounds, get_team_draft_class,
    generate_pick_explanation, generate_team_draft_grade,
)

router = APIRouter(prefix="/draft-results", tags=["draft-results"])


@router.post("/{year}/ingest")
async def ingest(year: int, db: AsyncSession = Depends(get_db)):
    return await ingest_real_draft(db, year)


@router.get("/{year}")
async def list_picks(year: int, round: Optional[str] = None, team_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    return await list_draft_picks(db, year, round, team_id)


@router.get("/{year}/rounds")
async def rounds(year: int, db: AsyncSession = Depends(get_db)):
    return await list_rounds(db, year)


@router.get("/{year}/team/{team_id}")
async def team_class(year: int, team_id: str, db: AsyncSession = Depends(get_db)):
    return await get_team_draft_class(db, year, team_id)


@router.post("/{year}/team/{team_id}/grade")
async def grade_team(year: int, team_id: str, db: AsyncSession = Depends(get_db)):
    return await generate_team_draft_grade(db, year, team_id)


@router.post("/player/{player_id}/explain")
async def explain_pick(player_id: str, db: AsyncSession = Depends(get_db)):
    return await generate_pick_explanation(db, player_id)
