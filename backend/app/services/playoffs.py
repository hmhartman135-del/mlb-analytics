"""
Playoff picture and bracket predictions, grounded in real data.

Two modes, auto-detected:
  - Regular season (no real postseason schedule set yet): serve the
    mechanical current playoff field (division leaders + wild cards + bubble,
    same logic as the Standings page) plus a cached AI "outlook" write-up.
  - Postseason (MLB has published the real bracket): serve the real series
    matchups/scores/status from the free MLB Stats API, with a cached AI
    winner prediction for any series that hasn't started yet.
"""
import re
from datetime import datetime

import anthropic
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import engine, Base
from ..models.playoff_projection import PlayoffProjection
from ..models.series_prediction import SeriesPrediction
from ..api.routes.standings import _get_standings

settings = get_settings()
MLB_API = "https://statsapi.mlb.com/api/v1"

ROUND_LABEL = {"F": "Wild Card Series", "D": "Division Series", "L": "Championship Series", "W": "World Series"}
ROUND_ORDER = {"F": 0, "D": 1, "L": 2, "W": 3}


async def ensure_schema():
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[PlayoffProjection.__table__, SeriesPrediction.__table__], checkfirst=True
            )
        )


# ── Regular-season playoff field ─────────────────────────────────────────────

def _compute_field(standings: dict) -> list[dict]:
    """Mirror the Standings page's playoff picture: top 6 per league (3 division
    leaders + 3 wild cards) ranked by league_rank, next 5 as the bubble."""
    leagues = []
    for conf in standings["conferences"]:
        all_teams = []
        div_leaders = set()
        for div in conf["divisions"]:
            for t in div["teams"]:
                all_teams.append({**t, "division": div["alias"]})
                if t["division_rank"] == 1:
                    div_leaders.add(t["id"])
        all_teams.sort(key=lambda t: (t["league_rank"], -t["pct"]))

        seeds = [
            {**t, "seed": i + 1, "is_wild_card": t["id"] not in div_leaders}
            for i, t in enumerate(all_teams[:6])
        ]
        bubble = all_teams[6:11]
        leagues.append({"league": conf["alias"], "league_name": conf["name"], "seeds": seeds, "bubble": bubble})
    return leagues


async def get_field(db: AsyncSession, season: int) -> dict:
    await ensure_schema()
    standings = await _get_standings(season)
    leagues = _compute_field(standings)

    row = (
        await db.execute(select(PlayoffProjection).where(PlayoffProjection.season == season))
    ).scalar_one_or_none()
    outlook = {"summary": row.summary, "generated_at": row.generated_at.isoformat()} if row else None

    return {"season": season, "leagues": leagues, "outlook": outlook}


async def generate_outlook(db: AsyncSession, season: int) -> dict:
    await ensure_schema()
    standings = await _get_standings(season)
    leagues = _compute_field(standings)

    lines = []
    for lg in leagues:
        lines.append(f"{lg['league_name']}:")
        for s in lg["seeds"]:
            tag = "WC" if s["is_wild_card"] else "DIV"
            lines.append(
                f"  #{s['seed']} ({tag}) {s['full_name']} — {s['win']}-{s['loss']}, "
                f"streak {s['streak_kind'] or '-'}{s['streak_length'] or ''}, last10 {s['last10_win']}-{s['last10_loss']}"
            )
        lines.append("  On the bubble:")
        for b in lg["bubble"]:
            gb = b["games_back"] if b["games_back"] is not None else 0
            lines.append(f"    {b['full_name']} — {b['win']}-{b['loss']}, {gb} back of the last playoff spot")
    context = "\n".join(lines)

    prompt = f"""You are a sharp MLB playoff-race analyst. Here is the current {season} playoff picture:

{context}

Write a grounded playoff outlook: which teams look like true locks, which division/wild-card leaders are
vulnerable to collapse, and which bubble teams have the best real shot at overtaking a seed. Be decisive
and specific — cite the actual records and streaks above. 4-6 sentences, tight and analytical, no headers
or bullet points, no hedging."""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=500,
        system="You are a sharp, opinionated MLB playoff-race analyst. Be decisive — never hedge.",
        messages=[{"role": "user", "content": prompt}],
    )
    summary = message.content[0].text.strip()

    row = (
        await db.execute(select(PlayoffProjection).where(PlayoffProjection.season == season))
    ).scalar_one_or_none()
    now = datetime.utcnow()
    if row:
        row.summary = summary
        row.generated_at = now
    else:
        db.add(PlayoffProjection(season=season, summary=summary, generated_at=now))
    await db.commit()

    return {"summary": summary, "generated_at": now.isoformat()}


# ── Real postseason bracket ──────────────────────────────────────────────────

async def _fetch_postseason_raw(season: int) -> list[dict]:
    url = f"{MLB_API}/schedule/postseason"
    params = {"season": season, "hydrate": "team,seriesStatus"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    games = []
    for d in data.get("dates", []):
        games.extend(d.get("games", []))
    return games


def _series_key(season: int, game_type: str, id_a: int, id_b: int) -> str:
    lo, hi = sorted([id_a, id_b])
    return f"{season}-{game_type}-{lo}-{hi}"


def _group_series(games: list[dict], season: int) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for g in games:
        away = g["teams"]["away"]["team"]
        home = g["teams"]["home"]["team"]
        key = _series_key(season, g["gameType"], away["id"], home["id"])
        buckets.setdefault(key, []).append(g)

    out = []
    for key, raw_games in buckets.items():
        raw_games.sort(key=lambda g: g["gameDate"])
        first, last = raw_games[0], raw_games[-1]
        away0, home0 = first["teams"]["away"]["team"], first["teams"]["home"]["team"]
        pair = sorted(
            [
                {"id": away0["id"], "name": away0["name"], "abbr": away0["abbreviation"]},
                {"id": home0["id"], "name": home0["name"], "abbr": home0["abbreviation"]},
            ],
            key=lambda t: t["id"],
        )
        team_a, team_b = pair[0], pair[1]

        games_out = []
        for g in raw_games:
            away, home = g["teams"]["away"], g["teams"]["home"]
            games_out.append({
                "game_pk": g["gamePk"],
                "game_date": g["gameDate"],
                "status": (g.get("status") or {}).get("abstractGameState"),
                "away_team": away["team"]["name"], "away_abbr": away["team"]["abbreviation"], "away_score": away.get("score"),
                "home_team": home["team"]["name"], "home_abbr": home["team"]["abbreviation"], "home_score": home.get("score"),
            })

        started = any(g["status"] in ("Live", "Final") for g in games_out)
        last_ss = last.get("seriesStatus") or {}

        out.append({
            "series_key": key,
            "game_type": first["gameType"],
            "round_label": ROUND_LABEL.get(first["gameType"], first.get("seriesDescription") or "Series"),
            "games_in_series": first.get("gamesInSeries"),
            "team_a": team_a["name"], "team_a_abbr": team_a["abbr"], "team_a_id": team_a["id"],
            "team_b": team_b["name"], "team_b_abbr": team_b["abbr"], "team_b_id": team_b["id"],
            "started": started,
            "is_over": bool(last_ss.get("isOver")),
            "result_text": last_ss.get("result"),
            "winner": (last_ss.get("winningTeam") or {}).get("name") if last_ss.get("isOver") else None,
            "games": games_out,
        })

    out.sort(key=lambda s: (ROUND_ORDER.get(s["game_type"], 9), s["games"][0]["game_date"]))
    return out


async def get_bracket(db: AsyncSession, season: int) -> dict:
    await ensure_schema()
    games = await _fetch_postseason_raw(season)
    if not games:
        return {"season": season, "has_bracket": False, "rounds": []}

    series_list = _group_series(games, season)

    series_keys = [s["series_key"] for s in series_list]
    rows = (
        await db.execute(select(SeriesPrediction).where(SeriesPrediction.series_key.in_(series_keys)))
    ).scalars().all()
    preds = {
        r.series_key: {
            "predicted_winner": r.predicted_winner,
            "confidence": r.confidence,
            "reasoning": r.reasoning,
            "generated_at": r.generated_at.isoformat(),
        }
        for r in rows
    }
    for s in series_list:
        s["prediction"] = preds.get(s["series_key"]) if not s["started"] else None

    rounds_map: dict[str, dict] = {}
    for s in series_list:
        r = rounds_map.setdefault(s["round_label"], {"round_label": s["round_label"], "game_type": s["game_type"], "series": []})
        r["series"].append(s)
    rounds = sorted(rounds_map.values(), key=lambda r: ROUND_ORDER.get(r["game_type"], 9))

    return {"season": season, "has_bracket": True, "rounds": rounds}


async def generate_series_prediction(db: AsyncSession, season: int, series_key: str) -> dict:
    await ensure_schema()
    games = await _fetch_postseason_raw(season)
    series_list = _group_series(games, season)
    series = next((s for s in series_list if s["series_key"] == series_key), None)
    if series is None:
        raise ValueError(f"Series {series_key} not found")
    if series["started"]:
        raise ValueError("This series has already started; predictions are only for series that haven't begun")

    standings = await _get_standings(season)
    records = {
        t["full_name"]: f"{t['win']}-{t['loss']}"
        for conf in standings["conferences"]
        for div in conf["divisions"]
        for t in div["teams"]
    }

    context = (
        f"{series['team_a']} ({records.get(series['team_a'], '?')}) vs "
        f"{series['team_b']} ({records.get(series['team_b'], '?')}) — "
        f"{series['round_label']}, best-of-{series['games_in_series']}"
    )

    prompt = f"""You are a sharp MLB playoff analyst predicting a postseason series winner.

{context}

Weigh regular-season record, roster strength, and postseason experience. Make a real, decisive call — never
call it a coin flip.

Respond in EXACTLY this format, no extra text:
WINNER: <team full name, must exactly match one of the two teams above>
CONFIDENCE: <one word: Lean, Solid, or Strong>
REASONING: <2-3 punchy sentences>"""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=300,
        system="You are a decisive MLB playoff analyst. Never hedge; always pick a winner.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text

    winner_m = re.search(r"WINNER:\s*(.+)", text)
    conf_m = re.search(r"CONFIDENCE:\s*(.+)", text)
    reason_m = re.search(r"REASONING:\s*(.+)", text, re.DOTALL)

    predicted_winner = winner_m.group(1).strip() if winner_m else series["team_a"]
    confidence = conf_m.group(1).strip() if conf_m else "Lean"
    reasoning = reason_m.group(1).strip() if reason_m else text.strip()

    existing = (
        await db.execute(select(SeriesPrediction).where(SeriesPrediction.series_key == series_key))
    ).scalar_one_or_none()
    now = datetime.utcnow()
    if existing:
        existing.predicted_winner = predicted_winner
        existing.confidence = confidence
        existing.reasoning = reasoning
        existing.generated_at = now
    else:
        db.add(SeriesPrediction(
            series_key=series_key,
            season=season,
            predicted_winner=predicted_winner,
            confidence=confidence,
            reasoning=reasoning,
            generated_at=now,
        ))
    await db.commit()

    return {
        "predicted_winner": predicted_winner,
        "confidence": confidence,
        "reasoning": reasoning,
        "generated_at": now.isoformat(),
    }
