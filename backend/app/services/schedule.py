"""
Day-by-day MLB schedule, backed by the free MLB Stats API
(statsapi.mlb.com — no key required). For scheduled games, Claude predicts
a winner grounded in real records and probable pitchers (cached per game).
For live/final games, a real box score is served straight from the Stats API.
"""
import re
from datetime import datetime

import anthropic
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import engine, Base
from ..models.game_prediction import GamePrediction

settings = get_settings()
MLB_API = "https://statsapi.mlb.com/api/v1"


async def ensure_schema():
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[GamePrediction.__table__], checkfirst=True)
        )


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ── MLB Stats API fetch ──────────────────────────────────────────────────────

async def _fetch_schedule_raw(date: str) -> list[dict]:
    url = f"{MLB_API}/schedule"
    params = {"sportId": 1, "date": date, "hydrate": "team,linescore,probablePitcher,decisions"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    dates = data.get("dates") or []
    return dates[0]["games"] if dates else []


async def _fetch_game_raw(game_pk: int) -> dict | None:
    url = f"{MLB_API}/schedule"
    params = {"sportId": 1, "gamePk": game_pk, "hydrate": "team,linescore,probablePitcher,decisions"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    dates = data.get("dates") or []
    games = dates[0]["games"] if dates else []
    return games[0] if games else None


def _status(g: dict) -> str:
    abstract = (g.get("status") or {}).get("abstractGameState") or ""
    return {"Preview": "scheduled", "Live": "live", "Final": "final"}.get(abstract, abstract.lower())


def _game_dict(g: dict, prediction: dict | None) -> dict:
    away, home = g["teams"]["away"], g["teams"]["home"]
    decisions = g.get("decisions") or {}
    away_rec, home_rec = away.get("leagueRecord") or {}, home.get("leagueRecord") or {}
    return {
        "game_pk": g["gamePk"],
        "game_date": g["gameDate"],
        "status": _status(g),
        "detailed_state": (g.get("status") or {}).get("detailedState"),
        "venue": (g.get("venue") or {}).get("name"),
        "away_team": away["team"]["name"],
        "away_abbr": away["team"]["abbreviation"],
        "home_team": home["team"]["name"],
        "home_abbr": home["team"]["abbreviation"],
        "away_score": away.get("score"),
        "home_score": home.get("score"),
        "away_record": f"{away_rec['wins']}-{away_rec['losses']}" if away_rec else None,
        "home_record": f"{home_rec['wins']}-{home_rec['losses']}" if home_rec else None,
        "away_probable_pitcher": (away.get("probablePitcher") or {}).get("fullName"),
        "home_probable_pitcher": (home.get("probablePitcher") or {}).get("fullName"),
        "winning_pitcher": (decisions.get("winner") or {}).get("fullName"),
        "losing_pitcher": (decisions.get("loser") or {}).get("fullName"),
        "save_pitcher": (decisions.get("save") or {}).get("fullName"),
        "prediction": prediction,
    }


def _prediction_dict(row: GamePrediction) -> dict:
    return {
        "predicted_winner": row.predicted_winner,
        "confidence": row.confidence,
        "reasoning": row.reasoning,
        "generated_at": row.generated_at.isoformat(),
    }


# ── Schedule ──────────────────────────────────────────────────────────────────

async def get_schedule(db: AsyncSession, date: str) -> dict:
    await ensure_schema()
    games_raw = await _fetch_schedule_raw(date)
    game_pks = [g["gamePk"] for g in games_raw]

    preds: dict[int, dict] = {}
    if game_pks:
        rows = (
            await db.execute(select(GamePrediction).where(GamePrediction.game_pk.in_(game_pks)))
        ).scalars().all()
        preds = {row.game_pk: _prediction_dict(row) for row in rows}

    games = [_game_dict(g, preds.get(g["gamePk"])) for g in games_raw]
    games.sort(key=lambda g: g["game_date"])
    return {"date": date, "games": games}


# ── AI winner prediction ──────────────────────────────────────────────────────

async def generate_prediction(db: AsyncSession, game_pk: int) -> dict:
    await ensure_schema()

    g = await _fetch_game_raw(game_pk)
    if g is None:
        raise ValueError(f"Game {game_pk} not found")

    away, home = g["teams"]["away"], g["teams"]["home"]
    away_name, home_name = away["team"]["name"], home["team"]["name"]
    away_rec, home_rec = away.get("leagueRecord") or {}, home.get("leagueRecord") or {}
    away_pitcher = (away.get("probablePitcher") or {}).get("fullName") or "TBD"
    home_pitcher = (home.get("probablePitcher") or {}).get("fullName") or "TBD"
    venue = (g.get("venue") or {}).get("name") or "the ballpark"

    context = (
        f"Away: {away_name} ({away_rec.get('wins', '?')}-{away_rec.get('losses', '?')}), "
        f"probable pitcher {away_pitcher}\n"
        f"Home: {home_name} ({home_rec.get('wins', '?')}-{home_rec.get('losses', '?')}), "
        f"probable pitcher {home_pitcher}\n"
        f"Venue: {venue} (home-field advantage to {home_name})"
    )

    prompt = f"""You are a sharp MLB betting analyst predicting the winner of today's game.

{context}

Weigh team record, probable starting pitcher matchup, and home-field advantage. Make a real,
decisive call — never hedge or call it a coin flip.

Respond in EXACTLY this format, no extra text:
WINNER: <team full name, must exactly match one of the two teams above>
CONFIDENCE: <one word: Lean, Solid, or Strong>
REASONING: <2-3 punchy sentences grounded in the records and pitching matchup above>"""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=300,
        system="You are a decisive MLB analyst. Never hedge; always pick a winner.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text

    winner_m = re.search(r"WINNER:\s*(.+)", text)
    conf_m = re.search(r"CONFIDENCE:\s*(.+)", text)
    reason_m = re.search(r"REASONING:\s*(.+)", text, re.DOTALL)

    predicted_winner = winner_m.group(1).strip() if winner_m else away_name
    confidence = conf_m.group(1).strip() if conf_m else "Lean"
    reasoning = reason_m.group(1).strip() if reason_m else text.strip()

    existing = (
        await db.execute(select(GamePrediction).where(GamePrediction.game_pk == game_pk))
    ).scalar_one_or_none()
    now = datetime.utcnow()
    if existing:
        existing.predicted_winner = predicted_winner
        existing.confidence = confidence
        existing.reasoning = reasoning
        existing.generated_at = now
    else:
        db.add(GamePrediction(
            game_pk=game_pk,
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


# ── Box score ─────────────────────────────────────────────────────────────────

def _team_box(team: dict) -> dict:
    totals = team.get("teamStats", {}).get("batting", {})
    players = team.get("players", {})

    batters = []
    for pid in team.get("batters", []):
        p = players.get(f"ID{pid}")
        if not p:
            continue
        bat = (p.get("stats") or {}).get("batting") or {}
        if not bat:
            continue
        batters.append({
            "name": p["person"]["fullName"],
            "position": (p.get("position") or {}).get("abbreviation"),
            "ab": bat.get("atBats", 0),
            "r": bat.get("runs", 0),
            "h": bat.get("hits", 0),
            "rbi": bat.get("rbi", 0),
            "bb": bat.get("baseOnBalls", 0),
            "so": bat.get("strikeOuts", 0),
            "summary": bat.get("summary", ""),
        })

    pitchers = []
    for pid in team.get("pitchers", []):
        p = players.get(f"ID{pid}")
        if not p:
            continue
        pit = (p.get("stats") or {}).get("pitching") or {}
        if not pit:
            continue
        pitchers.append({
            "name": p["person"]["fullName"],
            "ip": pit.get("inningsPitched", "0.0"),
            "h": pit.get("hits", 0),
            "r": pit.get("runs", 0),
            "er": pit.get("earnedRuns", 0),
            "bb": pit.get("baseOnBalls", 0),
            "so": pit.get("strikeOuts", 0),
            "decision": (pit.get("note") or "").strip(),
            "summary": pit.get("summary", ""),
        })

    return {
        "runs": totals.get("runs", 0),
        "hits": totals.get("hits", 0),
        "batters": batters,
        "pitchers": pitchers,
    }


async def get_boxscore(game_pk: int) -> dict:
    box_url = f"{MLB_API}/game/{game_pk}/boxscore"
    line_url = f"{MLB_API}/game/{game_pk}/linescore"
    async with httpx.AsyncClient(timeout=20.0) as client:
        box_resp = await client.get(box_url)
        box_resp.raise_for_status()
        line_resp = await client.get(line_url)
        line_resp.raise_for_status()
    box = box_resp.json()
    line = line_resp.json()

    away_box = _team_box(box["teams"]["away"])
    home_box = _team_box(box["teams"]["home"])
    line_teams = line.get("teams") or {}
    away_line, home_line = line_teams.get("away") or {}, line_teams.get("home") or {}

    innings = [
        {"num": inn.get("num"), "away": (inn.get("away") or {}).get("runs"), "home": (inn.get("home") or {}).get("runs")}
        for inn in line.get("innings") or []
    ]

    return {
        "game_pk": game_pk,
        "innings": innings,
        "away": {**away_box, "errors": away_line.get("errors", 0), "left_on_base": away_line.get("leftOnBase", 0)},
        "home": {**home_box, "errors": home_line.get("errors", 0), "left_on_base": home_line.get("leftOnBase", 0)},
    }
