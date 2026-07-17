"""
AI-generated MLB power rankings — all 30 teams, ranked and justified.
Grounded in real current standings (record, division rank, games back,
streak, last 10). Cached per season; regenerated on request via the
POST endpoint, not auto-refreshed.
"""
import re
from datetime import datetime
import anthropic
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import engine, Base
from ..models.power_ranking import PowerRanking
from ..api.routes.standings import _get_standings

settings = get_settings()


async def ensure_schema():
    """This app has no Alembic migrations wired up — create the table on
    first use, same pattern as the other ad hoc AI-cache tables."""
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[PowerRanking.__table__], checkfirst=True)
        )


async def _team_landscape(season: int) -> list[dict]:
    data = await _get_standings(season)
    teams = []
    for conf in data["conferences"]:
        for div in conf["divisions"]:
            for t in div["teams"]:
                teams.append({
                    "full_name": t["full_name"],
                    "abbr": t["alias"],
                    "division": div["alias"],
                    "win": t["win"],
                    "loss": t["loss"],
                    "pct": t["pct"],
                    "games_back": t["games_back"],
                    "division_rank": t["division_rank"],
                    "streak_kind": t["streak_kind"],
                    "streak_length": t["streak_length"],
                    "last10_win": t["last10_win"],
                    "last10_loss": t["last10_loss"],
                })
    return teams


async def generate_power_rankings(db: AsyncSession, season: int) -> dict:
    await ensure_schema()

    teams = await _team_landscape(season)
    if not teams:
        return {"error": f"No standings data available for {season}"}

    lines = "\n".join(
        f"  {t['full_name']} ({t['division']}): {t['win']}-{t['loss']} ({t['pct']:.3f}), "
        f"GB {t['games_back'] if t['games_back'] is not None else '-'}, div rank #{t['division_rank']}, "
        f"streak {t['streak_kind'] or '-'}{t['streak_length'] or ''}, last10 {t['last10_win']}-{t['last10_loss']}"
        for t in teams
    )

    prompt = f"""You are a veteran MLB analyst writing this week's power rankings — all 30 teams ranked
1 (best) through 30 (worst), like a national baseball writer's weekly column.

Current {season} standings (record, games back, division rank, recent streak, last 10 games):
{lines}

Power rankings are not just standings order — factor in recent form (streak, last 10), strength of
record, and which teams look like real contenders vs. teams whose record is misleading. Use your
judgment the way a real analyst would, but stay grounded in the real data above — don't invent
information not implied by it.

Respond with EXACTLY 30 lines, one per team, in this exact format (rank 1 to 30, no header, no extra text):
1. Team Full Name — one punchy sentence on why they're here (max 20 words)
2. Team Full Name — one punchy sentence on why they're here (max 20 words)
...continue through 30."""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1536,
        system="You are a sharp, opinionated MLB power rankings columnist. Be decisive and specific — never hedge.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text

    team_by_name = {t["full_name"]: t for t in teams}
    rankings = []
    for m in re.finditer(r"^\s*(\d{1,2})\.\s*(.+?)\s*—\s*(.+)$", text, flags=re.MULTILINE):
        rank = int(m.group(1))
        name = m.group(2).strip()
        blurb = m.group(3).strip()
        t = team_by_name.get(name)
        rankings.append({
            "rank": rank,
            "team_name": name,
            "team_abbr": t["abbr"] if t else None,
            "division": t["division"] if t else None,
            "record": f"{t['win']}-{t['loss']}" if t else None,
            "blurb": blurb,
        })
    rankings.sort(key=lambda r: r["rank"])

    await db.execute(delete(PowerRanking).where(PowerRanking.season == season))
    now = datetime.utcnow()
    db.add(PowerRanking(season=season, rankings=rankings, generated_at=now))
    await db.commit()

    return {"season": season, "rankings": rankings, "generated_at": now.isoformat()}


async def get_power_rankings(db: AsyncSession, season: int) -> dict:
    await ensure_schema()
    row = (await db.execute(select(PowerRanking).where(PowerRanking.season == season))).scalar_one_or_none()
    if not row:
        return {"season": season, "rankings": [], "generated_at": None}
    return {"season": season, "rankings": row.rankings, "generated_at": row.generated_at.isoformat()}
