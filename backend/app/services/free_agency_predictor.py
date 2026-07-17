"""
AI free-agent signing predictor — speculative "who should/will sign this
player" prediction grounded in real 2026 standings (competitive window,
division fit). Explicitly framed as a guess that will be tested/outdated
once real free agency happens — not a caching/persisted forecast.
"""
import re
import anthropic
from ..core.config import get_settings
from ..api.routes.standings import _get_standings

settings = get_settings()


async def _team_landscape_text(season: int = 2026) -> str:
    data = await _get_standings(season)
    lines = []
    for conf in data["conferences"]:
        for div in conf["divisions"]:
            for t in div["teams"]:
                lines.append(
                    f"  {t['full_name']} ({div['alias']}): {t['win']}-{t['loss']}"
                    f", GB {t['games_back'] if t['games_back'] is not None else '-'}"
                    f", div rank #{t['division_rank']}"
                )
    return "\n".join(lines)


async def generate_signing_prediction(player_context: str) -> dict[str, str]:
    """AI-written prediction of which team a free agent is most likely to
    sign with, grounded in real current-season standings. Speculative by
    nature — the answer is expected to age out once real signings happen."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    team_context = await _team_landscape_text()

    prompt = f"""You are an MLB front-office insider predicting where a free agent will sign.

Player:
{player_context}

Current 2026 MLB standings (division, record, games back, division rank) — use this to judge
which teams are contenders needing to add now vs. rebuilding teams unlikely to spend big,
and which teams have an obvious positional/roster fit:
{team_context}

This is a speculative, informed guess — real free agency hasn't happened yet, and the actual
outcome will differ once the season ends and real negotiations occur. Make your best call anyway.

Respond in exactly this format:
TEAM: <one real MLB team, full name — e.g. "New York Yankees">
REASONING: <3-5 sentences on why this team fits: competitive window, positional need, market/payroll fit. Ground it in the standings context above.>"""

    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        system="You are a sharp MLB front-office and free-agency insider. Be specific and decisive — commit to one team.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text

    team_match = re.search(r"TEAM:\s*(.+)", text)
    reasoning_match = re.search(r"REASONING:\s*(.+)", text, flags=re.DOTALL)

    return {
        "predicted_team": team_match.group(1).strip() if team_match else "Unknown",
        "reasoning": reasoning_match.group(1).strip() if reasoning_match else text.strip(),
    }
