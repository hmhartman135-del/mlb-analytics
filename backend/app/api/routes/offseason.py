"""
offseason.py
─────────────────
AI-powered offseason planner.

  POST /api/v1/offseason/plan
  Body: { "team_id": "uuid" }

Gathers the selected team's full roster context — expiring contracts,
returning salaries, 2027 payroll budget, and the upcoming 2027 FA class —
then asks Claude to produce a prioritised offseason strategy with specific
free-agent targets.
"""

import re
from uuid import UUID

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.database import get_db
from ...models.player import Player
from ...models.spotrac_fa import SpotracFA
from ...models.stats import BattingStats, PitchingStats
from ...models.team import Team

router = APIRouter(prefix="/offseason", tags=["offseason"])

# 2027 CBT threshold estimate (increases ~$6-8M/yr from 2026's $241M)
CBT_2027_M = 254.0

LUXURY_TAX_THRESHOLD_M = 241.0  # 2026 reference


# ── WAR helpers (mirrors roster.py) ──────────────────────────────────────────

def _war_bat(s: BattingStats | None) -> float:
    if s and s.war:
        return float(s.war)
    if s and s.woba and s.plate_appearances and s.plate_appearances >= 30:
        raa = (s.woba - 0.320) / 1.15 * s.plate_appearances
        raw = (raa + 2.0 * s.plate_appearances / 600) / 10
        if s.plate_appearances < 550:
            raw *= min(600 / s.plate_appearances, 4.0)
        return round(max(min(raw, 12.0), -4.0), 1)
    return 0.0


def _war_pit(s: PitchingStats | None) -> float:
    if s and s.war:
        return float(s.war)
    if s and s.fip and s.innings_pitched and s.innings_pitched >= 5:
        fip_diff = 4.20 - s.fip
        raw = fip_diff * s.innings_pitched / 9 / 1.5 + 0.5 * s.innings_pitched / 180
        gs = getattr(s, "games_started", None) or 0
        g  = getattr(s, "games", None) or 1
        target = 180 if (gs / g >= 0.5 if g else False) else 65
        if s.innings_pitched < target * 0.9:
            raw *= min(target / s.innings_pitched, 4.0)
        return round(max(min(raw, 9.0), -3.0), 1)
    return 0.0


# ── Request / Response models ────────────────────────────────────────────────

class OffseasonPlanRequest(BaseModel):
    team_id: UUID


class GradeMoveRequest(BaseModel):
    team_name: str
    roster_needs: list[str]          # positions still unfilled
    player_name: str
    position: str | None = None
    age: int | None = None
    former_team: str | None = None
    contract_years: int
    contract_aav_m: float
    budget_remaining_m: float
    existing_signings: list[dict] = []   # [{player_name, position, years, aav_m, grade}]


# ── Prompt builder ────────────────────────────────────────────────────────────

_POS_ORDER = {
    "C": 0, "1B": 1, "2B": 2, "3B": 3, "SS": 4,
    "LF": 5, "CF": 6, "RF": 7, "DH": 8,
    "SP": 9, "RP": 10,
}


def _pos_key(p: dict) -> int:
    return _POS_ORDER.get(p.get("position") or "", 99)


def _build_prompt(
    team: Team,
    expiring: list[dict],
    returning: list[dict],
    payroll_2026_m: float,
    committed_2027_m: float,
    available_m: float,
    fas_by_pos: dict[str, list[str]],
) -> str:
    full_name = f"{team.city} {team.name}"
    division  = team.division or "MLB"

    # ── Section 1: expiring ──
    if expiring:
        exp_lines = "\n".join(
            f"  - {p['name']} ({p['position'] or '?'}, Age {p['age'] or '?'})"
            f"  ${p['salary_m']:.1f}M  WAR {p['war']:+.1f}"
            for p in sorted(expiring, key=_pos_key)
        )
    else:
        exp_lines = "  (none — all players under multi-year contracts)"

    # ── Section 2: returning ──
    if returning:
        ret_lines = "\n".join(
            f"  - {p['name']} ({p['position'] or '?'})  ${p['salary_m']:.1f}M"
            f"  {p['years_remaining']}yr left  WAR {p['war']:+.1f}"
            for p in sorted(returning, key=_pos_key)
        )
    else:
        ret_lines = "  (no players with guaranteed 2027 contracts)"

    # ── Section 3: FA class by position ──
    fa_sections = []
    for pos in ["SP", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "OF", "RP", "DH"]:
        names = fas_by_pos.get(pos)
        if names:
            fa_sections.append(f"  {pos}: {', '.join(names[:12])}")
    fa_block = "\n".join(fa_sections) if fa_sections else "  (no FA data available)"

    return f"""You are a sharp MLB front office analyst writing the 2026-2027 offseason strategy memo for the {full_name}.

=== TEAM CONTEXT ===
Team: {full_name} ({division})
Current 2026 payroll:  ${payroll_2026_m:.1f}M  (2026 CBT threshold: ${LUXURY_TAX_THRESHOLD_M:.0f}M)
2027 committed salary: ${committed_2027_m:.1f}M  (players still under contract for 2027)
Estimated 2027 budget: ${available_m:.1f}M  (2027 CBT threshold ~${CBT_2027_M:.0f}M minus commitments)

=== PLAYERS LEAVING AFTER 2026 (contract expires) ===
{exp_lines}

=== PLAYERS RETURNING IN 2027 (under contract) ===
{ret_lines}

=== 2027 FREE AGENT CLASS (available to sign) ===
{fa_block}

=== YOUR TASK ===
Write a clear, actionable 2026-2027 offseason strategy memo for the {full_name}. Structure your response as follows:

## Offseason Overview
Briefly summarise the team's situation heading into the offseason — what worked, what didn't, what the critical needs are.

## Priority Needs
List the 3-5 most urgent positions/roles to address, ranked by importance. For each, explain why it's a gap.

## Free Agent Targets
For each priority need, recommend 1-2 specific players from the 2027 FA class above. Be concrete — name them, explain the fit, and give a rough contract estimate (years / AAV) based on their expected market value.

## Budget Allocation
Show how the estimated ${available_m:.0f}M budget should be allocated across your recommended signings.

## Additional Moves
Any trades to consider, extensions to pursue, or internal options to develop.

## Risk & Contingency
If a top target signs elsewhere, who is the fallback?

Use professional front-office language. Be specific and direct — this is an internal decision memo, not a press release."""


# ── Shared data-fetching helper ───────────────────────────────────────────────

async def _fetch_context(team_id: UUID, db: AsyncSession) -> dict:
    """Return team + roster + FA data without calling Claude."""
    team_res = await db.execute(select(Team).where(Team.id == team_id))
    team = team_res.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    roster_res = await db.execute(
        select(Player).where(
            Player.team_id == team_id,
            Player.roster_status != None,  # noqa: E711
        )
    )
    roster = roster_res.scalars().all()
    if not roster:
        raise HTTPException(status_code=404, detail="No roster data found for this team")

    player_ids = [p.id for p in roster]

    bat_res = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id.in_(player_ids),
            BattingStats.season == 2026,
            BattingStats.split == "overall",
        )
    )
    bat_by = {s.player_id: s for s in bat_res.scalars().all()}

    pit_res = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id.in_(player_ids),
            PitchingStats.season == 2026,
            PitchingStats.split == "overall",
        )
    )
    pit_by = {s.player_id: s for s in pit_res.scalars().all()}

    def _player_dict(p: Player) -> dict:
        is_pitcher = p.position in ("SP", "RP")
        war = _war_pit(pit_by.get(p.id)) if is_pitcher else _war_bat(bat_by.get(p.id))
        return {
            "player_id": str(p.id),
            "name": p.full_name,
            "position": p.position,
            "age": p.age,
            "salary_m": round(p.salary or 0.0, 2),
            "contract_years": p.contract_years,
            "years_remaining": p.contract_years or 0,
            "war": war,
        }

    all_players = [_player_dict(p) for p in roster]
    expiring  = [p for p in all_players if p["contract_years"] is not None and p["contract_years"] == 0]
    returning = [p for p in all_players if p["contract_years"] and p["contract_years"] >= 1]

    payroll_2026_m   = round(sum(p["salary_m"] for p in all_players), 1)
    committed_2027_m = round(sum(p["salary_m"] for p in returning), 1)
    available_m      = round(max(0.0, CBT_2027_M - committed_2027_m), 1)

    fa_res = await db.execute(
        select(SpotracFA)
        .where(SpotracFA.season == 2027, SpotracFA.signed == False)  # noqa: E712
        .order_by(SpotracFA.full_name)
    )
    fas = fa_res.scalars().all()

    fas_by_pos: dict[str, list[str]] = {}
    for fa in fas:
        pos = fa.position or "UNK"
        fas_by_pos.setdefault(pos, []).append(fa.full_name)

    return dict(
        team=team,
        expiring=expiring,
        returning=returning,
        payroll_2026_m=payroll_2026_m,
        committed_2027_m=committed_2027_m,
        available_m=available_m,
        fas=fas,
        fas_by_pos=fas_by_pos,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/context")
async def get_offseason_context(
    req: OffseasonPlanRequest,
    db: AsyncSession = Depends(get_db),
):
    """Fast endpoint — returns team/roster/FA data without calling Claude."""
    ctx = await _fetch_context(req.team_id, db)
    team = ctx["team"]
    fas  = ctx["fas"]

    return {
        "team": {
            "id": str(team.id),
            "name": team.name,
            "city": team.city,
            "full_name": f"{team.city} {team.name}",
            "division": team.division,
        },
        "context": {
            "payroll_2026_m":      ctx["payroll_2026_m"],
            "committed_2027_m":    ctx["committed_2027_m"],
            "estimated_budget_m":  ctx["available_m"],
            "cbt_threshold_m":     CBT_2027_M,
            "roster_size":         len(ctx["expiring"]) + len(ctx["returning"]),
            "expiring_count":      len(ctx["expiring"]),
        },
        "expiring_contracts":  sorted(ctx["expiring"],  key=lambda x: -x["salary_m"]),
        "returning_contracts": sorted(ctx["returning"], key=lambda x: -x["salary_m"]),
        "fa_pool": [
            {
                "id":          str(fa.id),
                "full_name":   fa.full_name,
                "position":    fa.position,
                "age":         fa.age,
                "former_team": fa.former_team,
                "fa_type":     fa.fa_type,
            }
            for fa in sorted(fas, key=lambda f: (f.position or "ZZZ", f.full_name))
        ],
    }


@router.post("/grade-move")
async def grade_free_agent_move(req: GradeMoveRequest):
    """Grade a single FA signing using Claude."""
    settings = get_settings()

    needs_str = ", ".join(req.roster_needs) if req.roster_needs else "none identified"

    if req.existing_signings:
        sigs = "\n".join(
            f"  - {s.get('player_name')} ({s.get('position','?')})  "
            f"{s.get('years','?')}yr / ${s.get('aav_m',0):.1f}M AAV  Grade: {s.get('grade','?')}"
            for s in req.existing_signings
        )
    else:
        sigs = "  (none yet)"

    total_value = req.contract_years * req.contract_aav_m

    prompt = f"""You are an MLB GM evaluating a free agent signing.

TEAM: {req.team_name}
ROSTER NEEDS: {needs_str}
BUDGET REMAINING: ${req.budget_remaining_m:.1f}M

EXISTING SIGNINGS THIS OFFSEASON:
{sigs}

PROPOSED SIGNING:
Player: {req.player_name}
Position: {req.position or 'Unknown'}
Age: {req.age or 'Unknown'}
Former Team: {req.former_team or 'Unknown'}
Contract: {req.contract_years} year{'s' if req.contract_years != 1 else ''} / ${req.contract_aav_m:.1f}M AAV (${total_value:.1f}M total)

Grade this signing. Respond with EXACTLY this format and nothing else:
GRADE: [A+/A/A-/B+/B/B-/C+/C/C-/D/F]
HEADLINE: [one sharp sentence, max 12 words]
ANALYSIS: [2–3 sentences on fit, value, and risk]"""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=300,
        system=(
            "You are a sharp MLB analyst. Be direct and specific. "
            "Always use EXACTLY the format requested."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    grade    = re.search(r"^GRADE:\s*(.+)$",    raw, re.MULTILINE)
    headline = re.search(r"^HEADLINE:\s*(.+)$", raw, re.MULTILINE)
    analysis = re.search(r"^ANALYSIS:\s*(.+)$", raw, re.MULTILINE | re.DOTALL)

    return {
        "grade":    (grade.group(1).strip()    if grade    else "B"),
        "headline": (headline.group(1).strip() if headline else "Move evaluated."),
        "analysis": (analysis.group(1).strip() if analysis else raw),
    }


@router.post("/plan")
async def generate_offseason_plan(
    req: OffseasonPlanRequest,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    ctx = await _fetch_context(req.team_id, db)
    team = ctx["team"]

    prompt = _build_prompt(
        team=team,
        expiring=ctx["expiring"],
        returning=ctx["returning"],
        payroll_2026_m=ctx["payroll_2026_m"],
        committed_2027_m=ctx["committed_2027_m"],
        available_m=ctx["available_m"],
        fas_by_pos=ctx["fas_by_pos"],
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=(
            "You are a veteran MLB front office analyst. "
            "Write concise, specific, data-informed memos. "
            "Never use filler phrases. Name actual players, quote real contract comps."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    plan_text: str = message.content[0].text

    fas = ctx["fas"]
    return {
        "team": {
            "id": str(team.id),
            "name": team.name,
            "city": team.city,
            "full_name": f"{team.city} {team.name}",
            "division": team.division,
        },
        "context": {
            "payroll_2026_m":     ctx["payroll_2026_m"],
            "committed_2027_m":   ctx["committed_2027_m"],
            "estimated_budget_m": ctx["available_m"],
            "cbt_threshold_m":    CBT_2027_M,
            "roster_size":        len(ctx["expiring"]) + len(ctx["returning"]),
            "expiring_count":     len(ctx["expiring"]),
        },
        "expiring_contracts":  sorted(ctx["expiring"],  key=lambda x: -x["salary_m"]),
        "returning_contracts": sorted(ctx["returning"], key=lambda x: -x["salary_m"]),
        "top_fa_targets": [
            {
                "id":          str(fa.id),
                "full_name":   fa.full_name,
                "position":    fa.position,
                "age":         fa.age,
                "former_team": fa.former_team,
                "fa_type":     fa.fa_type,
            }
            for fa in sorted(fas, key=lambda f: (f.position or "ZZZ", f.full_name))[:60]
        ],
        "plan": plan_text,
    }
