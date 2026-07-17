"""
Real completed MLB draft results (as opposed to the forward-looking mock-draft
planner in api/routes/draft.py, which covers next year's speculative class).

Data source: MLB's own public Stats API (statsapi.mlb.com/api/v1/draft/{year})
— free, no key required, includes real picks, teams, blurbs, signing bonuses.
"""
import re
from datetime import datetime

import anthropic
import httpx
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import engine, Base
from ..models.player import Player
from ..models.team import Team
from ..models.draft_team_grade import DraftTeamGrade

settings = get_settings()

POS_MAP = {
    "TWP": "SP", "P": "SP", "SP": "SP", "RP": "RP",
    "C": "C", "1B": "1B", "2B": "2B", "3B": "3B",
    "SS": "SS", "LF": "LF", "CF": "CF", "RF": "RF",
    "OF": "CF", "DH": "DH", "IF": "3B", "UTIL": "DH",
}


def _parse_pos(abbr: str | None) -> str | None:
    if not abbr:
        return None
    return POS_MAP.get(abbr.upper(), abbr[:8])


def _parse_bd(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


async def ensure_schema(db: AsyncSession):
    """Add the new draft-results columns/table if they don't exist yet.
    This app has no Alembic migrations wired up — new columns on an existing
    table need a raw ALTER TABLE, same pattern as adding the new table."""
    for stmt in [
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS draft_team_id UUID REFERENCES teams(id)",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS draft_round VARCHAR(10)",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS ai_draft_blurb VARCHAR(4000)",
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS ai_draft_blurb_generated_at TIMESTAMP",
    ]:
        await db.execute(text(stmt))
    await db.commit()
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[DraftTeamGrade.__table__], checkfirst=True))


async def fetch_real_draft_picks(year: int) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://statsapi.mlb.com/api/v1/draft/{year}", params={"limit": 2000}, timeout=30)
        r.raise_for_status()
        data = r.json()
    return [
        {**p, "pickRound": rnd["round"]}
        for rnd in data["drafts"]["rounds"]
        for p in rnd["picks"]
        if p.get("isDrafted") and p.get("person")
    ]


async def ingest_real_draft(db: AsyncSession, year: int) -> dict:
    """Insert/update real completed draft picks for `year`, resolving each
    pick's drafting team via Team.mlb_id. Distinct from the mock-draft
    prospect pool: tags status='drafted_{year}' so it never overlaps with
    the forward-looking planner's draft_prospect pool."""
    await ensure_schema(db)

    picks = await fetch_real_draft_picks(year)

    team_by_mlb_id = {
        t.mlb_id: t.id for t in (await db.execute(select(Team))).scalars().all()
    }

    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    for pick in picks:
        person = pick.get("person", {})
        mlb_id = person.get("id")
        if not mlb_id:
            counts["skipped"] += 1
            continue

        existing = (await db.execute(select(Player).where(Player.mlb_id == mlb_id))).scalar_one_or_none()
        team_mlb_id = (pick.get("team") or {}).get("id")
        draft_team_id = team_by_mlb_id.get(team_mlb_id)
        school_info = pick.get("school", {})
        blurb = (pick.get("blurb") or "")[:2048] or None
        bonus_str = pick.get("signingBonus")

        fields = dict(
            draft_team_id=draft_team_id,
            draft_round=str(pick.get("pickRound")),
            draft_year=year,
            draft_pick=pick.get("displayPickNumber"),
            draft_rank=pick.get("rank"),
            school=school_info.get("name"),
            school_class=school_info.get("schoolClass"),
            signing_bonus=float(bonus_str) if bonus_str else None,
            scout_notes=blurb,
        )

        if existing:
            for k, v in fields.items():
                if v is not None:
                    setattr(existing, k, v)
            existing.status = f"drafted_{year}"
            counts["updated"] += 1
        else:
            pos_abbr = person.get("primaryPosition", {}).get("abbreviation")
            db.add(Player(
                mlb_id=mlb_id,
                full_name=person.get("fullName", "Unknown"),
                first_name=person.get("firstName", ""),
                last_name=person.get("lastName", ""),
                birth_date=_parse_bd(person.get("birthDate")),
                age=person.get("currentAge"),
                position=_parse_pos(pos_abbr),
                bats=person.get("batSide", {}).get("code"),
                throws=person.get("pitchHand", {}).get("code"),
                status=f"drafted_{year}",
                height=person.get("height"),
                weight=person.get("weight"),
                birth_city=pick.get("home", {}).get("city"),
                birth_country=pick.get("home", {}).get("country", "USA"),
                **fields,
            ))
            counts["inserted"] += 1

    await db.commit()
    return {"year": year, "total_picks": len(picks), **counts}


def _pick_dict(p: Player) -> dict:
    return {
        "id": str(p.id),
        "mlb_id": p.mlb_id,
        "full_name": p.full_name,
        "position": p.position,
        "bats": p.bats,
        "throws": p.throws,
        "age": p.age,
        "height": p.height,
        "weight": p.weight,
        "birth_city": p.birth_city,
        "birth_country": p.birth_country,
        "school": p.school,
        "school_class": p.school_class,
        "draft_year": p.draft_year,
        "draft_round": p.draft_round,
        "draft_pick": p.draft_pick,
        "draft_rank": p.draft_rank,
        "signing_bonus": p.signing_bonus,
        "draft_team_id": str(p.draft_team_id) if p.draft_team_id else None,
        "scout_notes": p.scout_notes,
        "ai_draft_blurb": p.ai_draft_blurb,
        "ai_draft_blurb_generated_at": p.ai_draft_blurb_generated_at.isoformat() if p.ai_draft_blurb_generated_at else None,
    }


_ROUND_SORT_OVERRIDES = {"PPI": 1.1, "CB-A": 1.5, "SUP-2": 2.5, "CB-B": 2.7, "2C": 2.9, "4C": 4.5}


def _round_sort_key(rnd: str) -> float:
    if rnd in _ROUND_SORT_OVERRIDES:
        return _ROUND_SORT_OVERRIDES[rnd]
    try:
        return float(rnd)
    except (TypeError, ValueError):
        return 999.0


async def list_draft_picks(db: AsyncSession, year: int, round_: str | None = None, team_id: str | None = None) -> list[dict]:
    query = select(Player).where(Player.draft_year == year, Player.status == f"drafted_{year}")
    if round_:
        query = query.where(Player.draft_round == round_)
    if team_id:
        query = query.where(Player.draft_team_id == team_id)
    players = (await db.execute(query)).scalars().all()
    picks = [_pick_dict(p) for p in players]
    picks.sort(key=lambda p: (p["draft_pick"] is None, p["draft_pick"] or 0))
    return picks


async def list_rounds(db: AsyncSession, year: int) -> list[str]:
    rounds = (await db.execute(
        select(Player.draft_round).where(Player.draft_year == year, Player.status == f"drafted_{year}").distinct()
    )).scalars().all()
    return sorted({r for r in rounds if r}, key=_round_sort_key)


async def get_team_draft_class(db: AsyncSession, year: int, team_id: str) -> dict:
    picks = await list_draft_picks(db, year, team_id=team_id)
    grade_row = (await db.execute(
        select(DraftTeamGrade).where(DraftTeamGrade.team_id == team_id, DraftTeamGrade.draft_year == year)
    )).scalar_one_or_none()
    return {
        "year": year,
        "team_id": team_id,
        "picks": picks,
        "grade": grade_row.grade if grade_row else None,
        "analysis": grade_row.analysis if grade_row else None,
        "grade_generated_at": grade_row.generated_at.isoformat() if grade_row else None,
    }


def _player_context(p: Player) -> str:
    lines = [
        f"Name: {p.full_name}",
        f"Position: {p.position or 'N/A'}  |  Bats/Throws: {p.bats or '?'}/{p.throws or '?'}",
        f"Age at draft: {p.age or 'N/A'}  |  Height/Weight: {p.height or 'N/A'} / {p.weight or 'N/A'} lbs",
        f"Hometown: {p.birth_city or 'N/A'}, {p.birth_country or ''}".strip(),
        f"School: {p.school or 'N/A'} ({p.school_class or 'N/A'})",
        f"Draft: Round {p.draft_round}, Pick #{p.draft_pick}, Year {p.draft_year}"
        + (f", Pre-draft rank #{p.draft_rank}" if p.draft_rank else ""),
    ]
    if p.signing_bonus:
        lines.append(f"Signing bonus: ${p.signing_bonus:,.0f}")
    if p.scout_notes:
        lines.append(f"\nScouting report (MLB.com):\n{p.scout_notes}")
    return "\n".join(lines)


async def generate_pick_explanation(db: AsyncSession, player_id: str) -> dict:
    """AI-written explanation of a drafted player's background and stats,
    grounded in the real MLB.com scouting blurb + bio data. Cached on the
    Player row — regenerate by calling again (no separate force flag needed,
    this is cheap enough and rarely re-requested)."""
    player = (await db.execute(select(Player).where(Player.id == player_id))).scalar_one_or_none()
    if not player:
        return {"error": "not found"}

    if player.ai_draft_blurb:
        return {"player_id": str(player.id), "explanation": player.ai_draft_blurb,
                "generated_at": player.ai_draft_blurb_generated_at.isoformat() if player.ai_draft_blurb_generated_at else None}

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    context = _player_context(player)

    prompt = f"""You are a baseball writer explaining a draft pick to fans.

Player drafted:
{context}

Write a 2-3 paragraph explanation covering: who this player is (background, school), why they were drafted where they were (tools/stats/projection based on the scouting report above), and what fans should expect. Ground everything in the real information given — don't invent stats or accomplishments not mentioned above. Plain paragraphs, no bullet points, no markdown headers or titles — start directly with the first paragraph."""

    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=768,
        system="You are a knowledgeable baseball draft analyst writing for team fans. Be specific and grounded in the real scouting info provided.",
        messages=[{"role": "user", "content": prompt}],
    )
    explanation = message.content[0].text
    player.ai_draft_blurb = explanation[:4000]
    player.ai_draft_blurb_generated_at = datetime.utcnow()
    await db.commit()
    return {"player_id": str(player.id), "explanation": explanation, "generated_at": player.ai_draft_blurb_generated_at.isoformat()}


async def generate_team_draft_grade(db: AsyncSession, year: int, team_id: str) -> dict:
    """AI-written letter grade + analysis for a team's full draft class."""
    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if not team:
        return {"error": "team not found"}

    picks = await list_draft_picks(db, year, team_id=team_id)
    if not picks:
        return {"error": "no picks found for this team/year"}

    picks_summary = "\n".join(
        f"  Round {p['draft_round']}, Pick #{p['draft_pick']}: {p['full_name']} ({p['position'] or '?'}) — "
        f"{p['school'] or 'N/A'}"
        + (f", pre-draft rank #{p['draft_rank']}" if p['draft_rank'] else "")
        + (f"\n    Scout notes: {p['scout_notes'][:300]}" if p['scout_notes'] else "")
        for p in picks[:20]  # first 20 picks (top of the class) is plenty of signal
    )

    prompt = f"""You are a front office analyst grading a team's MLB Draft class.

Team: {team.city} {team.name}
Draft Year: {year}
Picks ({len(picks)} total):
{picks_summary}

Assign an overall letter grade (A+ through F) for this draft class and write a 3-4 paragraph analysis covering:
best value picks, overall strategy (best-player-available vs. need-based, high school vs. college mix), and risk profile.
Ground your analysis in the real picks and scouting notes given — don't invent details not present above.
Plain paragraphs, no bullet points, no markdown headers or titles — start directly with the first paragraph.

End your response with a final line in exactly this format: GRADE: <letter grade>"""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system="You are a sharp, direct MLB front office draft analyst.",
        messages=[{"role": "user", "content": prompt}],
    )
    text_out = message.content[0].text
    match = re.search(r"GRADE:\s*([A-F][+-]?)", text_out)
    grade = match.group(1) if match else "N/A"
    analysis = text_out[:match.start()].strip() if match else text_out

    existing = (await db.execute(
        select(DraftTeamGrade).where(DraftTeamGrade.team_id == team_id, DraftTeamGrade.draft_year == year)
    )).scalar_one_or_none()
    now = datetime.utcnow()
    if existing:
        existing.grade = grade
        existing.analysis = analysis[:4000]
        existing.generated_at = now
    else:
        db.add(DraftTeamGrade(team_id=team_id, draft_year=year, grade=grade, analysis=analysis[:4000], generated_at=now))
    await db.commit()

    return {"team_id": team_id, "year": year, "grade": grade, "analysis": analysis, "generated_at": now.isoformat()}
