"""
Scouting report generator — combines stat comps with Claude AI narrative.
"""
import re
import anthropic
from ..core.config import get_settings
from .analytics import WOBA_WEIGHTS

settings = get_settings()


GRADE_SCALE = {
    (70, 80): "Plus-Plus (80)",
    (60, 70): "Plus (60-70)",
    (50, 60): "Average-to-Plus (50-60)",
    (40, 50): "Fringe-Average (40-50)",
    (30, 40): "Below Average (30-40)",
    (20, 30): "Poor (20-30)",
}


def grade_label(score: int | None) -> str:
    if score is None:
        return "N/A"
    for (lo, hi), label in GRADE_SCALE.items():
        if lo <= score <= hi:
            return label
    return str(score)


def _build_player_context(player: dict, stats: dict | None = None) -> str:
    """Assemble structured player data for the AI prompt."""
    lines = [
        f"Name: {player.get('full_name')}",
        f"Position: {player.get('position')}",
        f"Age: {player.get('age')}",
        f"Bats/Throws: {player.get('bats')}/{player.get('throws')}",
        f"Status: {player.get('status')}",
    ]

    grades = {
        "Hit": player.get("scout_hit"),
        "Power": player.get("scout_power"),
        "Speed": player.get("scout_speed"),
        "Field": player.get("scout_field"),
        "Arm": player.get("scout_arm"),
        "FB Velo": player.get("scout_fb_velo"),
        "Command": player.get("scout_command"),
    }
    grade_lines = [f"  {k}: {grade_label(v)}" for k, v in grades.items() if v is not None]
    if grade_lines:
        lines.append("Scouting Grades (20-80):")
        lines.extend(grade_lines)

    if stats:
        is_pitcher = player.get("position") in ("SP", "RP")
        if is_pitcher:
            lines.append("Pitching Stats:")
            lines.append(f"  ERA: {stats.get('era', 'N/A')}, FIP: {stats.get('fip', 'N/A')}, WHIP: {stats.get('whip', 'N/A')}")
            lines.append(f"  K%: {stats.get('k_pct', 'N/A')}, BB%: {stats.get('bb_pct', 'N/A')}")
            lines.append(f"  Avg FB Velo: {stats.get('avg_fastball_velo', 'N/A')}, WAR: {stats.get('war', 'N/A')}")
        else:
            lines.append("Batting Stats:")
            lines.append(f"  AVG/OBP/SLG: {stats.get('avg', 'N/A')}/{stats.get('obp', 'N/A')}/{stats.get('slg', 'N/A')}")
            lines.append(f"  wOBA: {stats.get('woba', 'N/A')}, wRC+: {stats.get('wrc_plus', 'N/A')}")
            lines.append(f"  HR: {stats.get('home_runs', 'N/A')}, SB: {stats.get('stolen_bases', 'N/A')}, WAR: {stats.get('war', 'N/A')}")

    if player.get("scout_notes"):
        lines.append(f"Scout Notes: {player['scout_notes']}")

    return "\n".join(lines)


async def generate_scouting_report(
    player: dict,
    stats: dict | None = None,
    report_type: str = "full",  # full | brief | draft | trade
) -> str:
    """Generate an AI-written scouting report using Claude."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    player_context = _build_player_context(player, stats)

    report_instructions = {
        "full": "Write a comprehensive 4-6 paragraph professional scouting report covering tools, performance, projection, risks, and fit.",
        "brief": "Write a concise 2-paragraph scouting summary covering strengths, weaknesses, and overall grade.",
        "draft": "Write a draft scouting report focusing on present tools, projection ceiling, floor, and recommended draft position.",
        "trade": "Write a trade value assessment covering current production, contract value, positional versatility, and acquisition fit.",
    }

    prompt = f"""You are a professional MLB scout writing an internal scouting report.

Player Information:
{player_context}

Task: {report_instructions.get(report_type, report_instructions['full'])}

Use baseball terminology naturally. Be analytical and specific. Reference stats where relevant.
Do not use filler phrases. Format as plain paragraphs, no bullet points."""

    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system="You are a veteran MLB scout with 20 years of experience evaluating talent across all levels.",
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _build_career_context(player: dict, db_history: list[dict], minor_history: list[dict]) -> str:
    """Assemble a full multi-year career picture (bio + every season on record,
    majors and minors) for the AI player-background prompt."""
    lines = [
        f"Name: {player.get('full_name')}",
        f"Position: {player.get('position')}  |  Bats/Throws: {player.get('bats')}/{player.get('throws')}",
        f"Age: {player.get('age')}  |  Height/Weight: {player.get('height') or 'N/A'} / {player.get('weight') or 'N/A'} lbs",
        f"Birth country: {player.get('birth_country') or 'N/A'}",
        f"Status: {player.get('status')}",
    ]
    if player.get("school"):
        lines.append(f"School: {player['school']}")

    is_pitcher = player.get("position") in ("SP", "RP")

    if db_history:
        lines.append("\nMLB season-by-season stats (most recent first):")
        for s in db_history:
            if is_pitcher:
                lines.append(
                    f"  {s['season']}: {s.get('games','?')}G, {s.get('innings_pitched','?')}IP, "
                    f"ERA {s.get('era','—')}, FIP {s.get('fip','—')}, WHIP {s.get('whip','—')}, "
                    f"K% {s.get('k_pct','—')}, BB% {s.get('bb_pct','—')}, WAR {s.get('war','—')}"
                )
            else:
                lines.append(
                    f"  {s['season']}: {s.get('games','?')}G, {s.get('plate_appearances','?')}PA, "
                    f"{s.get('avg','—')}/{s.get('obp','—')}/{s.get('slg','—')}, "
                    f"{s.get('home_runs','—')}HR, {s.get('rbi','—')}RBI, wRC+ {s.get('wrc_plus','—')}, WAR {s.get('war','—')}"
                )

    if minor_history:
        lines.append("\nFull career history including minor leagues (most recent first):")
        for s in minor_history[:15]:  # cap — full career can be 10+ seasons across levels
            team = s.get("team", "")
            level = s.get("level", "")
            if s.get("type") == "pitching":
                lines.append(
                    f"  {s['season']} {level} ({team}): {s.get('games','?')}G, {s.get('innings_pitched','?')}IP, "
                    f"ERA {s.get('era','—')}, WHIP {s.get('whip','—')}, {s.get('strikeouts','—')}K"
                )
            else:
                lines.append(
                    f"  {s['season']} {level} ({team}): {s.get('games','?')}G, {s.get('plate_appearances','?')}PA, "
                    f"{s.get('avg','—')}/{s.get('obp','—')}/{s.get('slg','—')}, "
                    f"{s.get('home_runs','—')}HR, {s.get('stolen_bases','—')}SB"
                )

    if player.get("scout_notes"):
        lines.append(f"\nScouting notes on file: {player['scout_notes']}")

    return "\n".join(lines)


async def generate_player_bio_analysis(
    player: dict,
    db_history: list[dict],
    minor_history: list[dict],
) -> dict[str, str]:
    """AI-written player background + career + strengths/concerns breakdown,
    grounded in the player's actual multi-year, multi-level stat history."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    context = _build_career_context(player, db_history, minor_history)

    prompt = f"""You are a professional baseball analyst profiling a player for fans/front-office use.

Player data (real, from official MLB records):
{context}

Write a profile with exactly these five sections. Respond in plain text using this exact
format — one section per line-start marker, each followed by 2-4 sentences of plain prose
(no bullet points, no markdown headers, no asterisks):

BACKGROUND: <who this player is — bio, how they came up, notable background>
CAREER: <career progression — how they've developed across levels/years, trajectory>
CURRENT: <analysis of their current/most recent production and what the numbers say>
LIKES: <what scouts and analysts like about this player — real strengths grounded in the stats/notes above>
CONCERNS: <what scouts and analysts are concerned about — real weaknesses, risks, or open questions grounded in the data above>

Only use the real data given above — do not invent stats, teams, or accomplishments not present in it."""

    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system="You are a veteran baseball analyst. Be specific and grounded in the real data provided — never fabricate.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text

    sections = {"background": "", "career": "", "current": "", "likes": "", "concerns": ""}
    pattern = r"(BACKGROUND|CAREER|CURRENT|LIKES|CONCERNS):\s*(.*?)(?=(?:BACKGROUND|CAREER|CURRENT|LIKES|CONCERNS):|\Z)"
    for key, body in re.findall(pattern, text, flags=re.DOTALL):
        sections[key.lower()] = body.strip()

    return sections


async def generate_roster_recommendation(
    team: dict,
    roster: list[dict],
    team_needs: list[str],
    free_agents: list[dict],
    budget_remaining_m: float,
) -> str:
    """Generate an AI-written roster construction recommendation."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    roster_summary = "\n".join([
        f"  {p['position']}: {p['full_name']} — WAR {p.get('war', 'N/A')}, wRC+ {p.get('wrc_plus', 'N/A')}"
        for p in roster[:25]
    ])

    fa_candidates = "\n".join([
        f"  {p['full_name']} ({p['position']}) — WAR {p.get('war', 'N/A')}, ${p.get('salary', '?')}M"
        for p in free_agents[:15]
    ])

    prompt = f"""You are a major league front office analyst.

Team: {team.get('name')}
Budget Remaining: ${budget_remaining_m:.1f}M
Identified Needs: {', '.join(team_needs)}

Current 25-Man Roster:
{roster_summary}

Top Free Agent Candidates:
{fa_candidates}

Provide a 3-4 paragraph roster construction recommendation. Prioritize which needs to address,
which specific free agents best fit the team's profile and budget, and flag any positional depth
concerns. Be direct — this is an internal front office memo."""

    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system="You are a sharp MLB front office analyst. Be concise, data-driven, and direct.",
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
