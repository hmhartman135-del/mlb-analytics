"""
trades.py
─────────────────
AI-powered trade evaluator & trade finder.

  POST /api/v1/trades/evaluate   — user-built 2-4 team trade grader
  POST /api/v1/trades/finder     — pick one player, AI generates 4 realistic proposals

Evaluate: accepts 2-4 team legs, fetches player context, asks Claude to grade.
Finder: accepts a single player_id, fetches player + standings context, asks Claude
        to generate 4 realistic trade scenarios weighted toward contender-need vs
        seller-rebuild dynamics.
"""

import re

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.database import get_db
from ...models.player import Player
from ...models.stats import BattingStats, PitchingStats

router = APIRouter(prefix="/trades", tags=["trades"])


# ── WAR helpers (mirrors offseason.py) ────────────────────────────────────────

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


# ── Request / Response models ─────────────────────────────────────────────────

class TradePlayerInput(BaseModel):
    player_id: str
    player_name: str   # for display / fallback if DB lookup fails


class TradeLegInput(BaseModel):
    team_id: str
    team_name: str
    team_abbr: str
    players_sending: list[TradePlayerInput]


class TradeEvaluateRequest(BaseModel):
    legs: list[TradeLegInput]   # 2-4 teams


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _fmt_bat(s: BattingStats | None) -> str:
    if not s:
        return "no stats"
    parts = []
    if s.avg is not None:
        parts.append(f".{int(s.avg * 1000):03d}/{int((s.obp or 0)*1000):03d}/{int((s.slg or 0)*1000):03d}")
    if s.wrc_plus is not None:
        parts.append(f"wRC+ {s.wrc_plus}")
    if s.home_runs is not None:
        parts.append(f"{s.home_runs} HR")
    return "  ".join(parts) if parts else "no hitting stats"


def _fmt_pit(s: PitchingStats | None) -> str:
    if not s:
        return "no stats"
    parts = []
    if s.era is not None:
        parts.append(f"ERA {s.era:.2f}")
    if s.fip is not None:
        parts.append(f"FIP {s.fip:.2f}")
    if s.innings_pitched is not None:
        parts.append(f"{s.innings_pitched:.1f} IP")
    if s.k_pct is not None:
        parts.append(f"K% {s.k_pct*100:.1f}")
    return "  ".join(parts) if parts else "no pitching stats"


def _player_block(p: Player, bat: BattingStats | None, pit: PitchingStats | None) -> str:
    is_pit = p.position in ("SP", "RP")
    war = _war_pit(pit) if is_pit else _war_bat(bat)
    salary_str = f"${p.salary:.1f}M" if p.salary else "arb/pre-arb"
    yrs_str = f"{p.contract_years}yr left" if p.contract_years else "expiring"
    stats_str = _fmt_pit(pit) if is_pit else _fmt_bat(bat)
    return (
        f"    • {p.full_name} ({p.position or '?'}, Age {p.age or '?'}) — "
        f"{salary_str} / {yrs_str} / WAR {war:+.1f} / {stats_str}"
    )


def _build_trade_prompt(
    legs: list[TradeLegInput],
    player_data: dict[str, tuple[Player, BattingStats | None, PitchingStats | None]],
) -> str:
    num_teams = len(legs)

    # Build per-team sending/receiving sections
    sections: list[str] = []
    for i, leg in enumerate(legs):
        # What this team sends
        sending_lines = []
        for pp in leg.players_sending:
            if pp.player_id in player_data:
                p, bat, pit = player_data[pp.player_id]
                sending_lines.append(_player_block(p, bat, pit))
            else:
                sending_lines.append(f"    • {pp.player_name} (data unavailable)")

        # What this team receives (aggregate of all other teams' sends)
        receiving_lines = []
        for j, other_leg in enumerate(legs):
            if j == i:
                continue
            for pp in other_leg.players_sending:
                if pp.player_id in player_data:
                    p, bat, pit = player_data[pp.player_id]
                    receiving_lines.append(f"    • {p.full_name} [{other_leg.team_abbr}]")
                else:
                    receiving_lines.append(f"    • {pp.player_name} [{other_leg.team_abbr}]")

        send_block = "\n".join(sending_lines) if sending_lines else "    (nothing)"
        recv_block = "\n".join(receiving_lines) if receiving_lines else "    (nothing)"

        sections.append(
            f"TEAM {i+1}: {leg.team_name} ({leg.team_abbr})\n"
            f"  Trading away:\n{send_block}\n"
            f"  Receiving:\n{recv_block}"
        )

    trade_block = "\n\n".join(sections)

    team_names = " / ".join(leg.team_name for leg in legs)

    return f"""You are a sharp MLB trade analyst evaluating a {num_teams}-team trade.

=== PROPOSED TRADE ===
{trade_block}

=== YOUR TASK ===
Analyse this trade from every angle: player value, salary/contract fit, positional need, win-now vs. rebuild context, and realistic feasibility (would real GMs approve this?).

Respond in EXACTLY this format:

DOABLE: [Yes | Likely | Unlikely | No]
REASON: [one sentence on whether this trade would actually happen]
---
{chr(10).join(f'TEAM: {leg.team_name}' + chr(10) + 'GRADE: [A+/A/A-/B+/B/B-/C+/C/C-/D/F]' + chr(10) + 'ANALYSIS: [2-3 sentences on what this team gains, loses, and whether it makes sense for them]' for leg in legs)}
---
OVERALL: [2-3 sentences summarising the trade, its balance, and any deal-breakers]

Be direct, specific, and use real MLB front-office language."""


# ── Route ──────────────────────────────────────────────────────────────────────

@router.post("/evaluate")
async def evaluate_trade(
    req: TradeEvaluateRequest,
    db: AsyncSession = Depends(get_db),
):
    if len(req.legs) < 2:
        raise HTTPException(status_code=422, detail="A trade requires at least 2 teams.")
    if len(req.legs) > 4:
        raise HTTPException(status_code=422, detail="A trade can involve at most 4 teams.")

    # Ensure every team is trading something
    for leg in req.legs:
        if not leg.players_sending:
            raise HTTPException(
                status_code=422,
                detail=f"{leg.team_name} must include at least one player.",
            )

    settings = get_settings()

    # ── 1. Collect all player IDs ─────────────────────────────────────────────
    all_ids: list[str] = []
    for leg in req.legs:
        all_ids.extend(pp.player_id for pp in leg.players_sending)

    if not all_ids:
        raise HTTPException(status_code=422, detail="No players found in trade.")

    # ── 2. Fetch player records ───────────────────────────────────────────────
    from uuid import UUID
    uuid_ids = [UUID(pid) for pid in all_ids if _is_uuid(pid)]

    players_res = await db.execute(
        select(Player).where(Player.id.in_(uuid_ids))
    )
    players_by_id = {str(p.id): p for p in players_res.scalars().all()}

    # ── 3. Fetch 2026 batting stats ───────────────────────────────────────────
    bat_res = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id.in_(uuid_ids),
            BattingStats.season == 2026,
            BattingStats.split == "overall",
        )
    )
    bat_by = {str(s.player_id): s for s in bat_res.scalars().all()}

    pit_res = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id.in_(uuid_ids),
            PitchingStats.season == 2026,
            PitchingStats.split == "overall",
        )
    )
    pit_by = {str(s.player_id): s for s in pit_res.scalars().all()}

    # ── 4. Combine into lookup dict ───────────────────────────────────────────
    player_data: dict[str, tuple[Player, BattingStats | None, PitchingStats | None]] = {}
    for pid in all_ids:
        if pid in players_by_id:
            p = players_by_id[pid]
            player_data[pid] = (p, bat_by.get(pid), pit_by.get(pid))

    # ── 5. Build prompt & call Claude ─────────────────────────────────────────
    prompt = _build_trade_prompt(req.legs, player_data)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1200,
        system=(
            "You are a veteran MLB trade analyst. "
            "Be direct and specific. Use the exact output format requested. "
            "Never use filler phrases."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # ── 6. Parse structured response ──────────────────────────────────────────
    doable_m   = re.search(r"^DOABLE:\s*(.+)$",  raw, re.MULTILINE)
    reason_m   = re.search(r"^REASON:\s*(.+)$",  raw, re.MULTILINE)
    overall_m  = re.search(r"^OVERALL:\s*(.+)$", raw, re.MULTILINE | re.DOTALL)

    doable = doable_m.group(1).strip() if doable_m else "Unlikely"
    reason = reason_m.group(1).strip() if reason_m else ""
    overall = overall_m.group(1).strip().split("\n---")[0].strip() if overall_m else ""

    # Parse per-team grades
    team_grades = []
    for leg in req.legs:
        # Find the TEAM block for this team
        escaped = re.escape(leg.team_name)
        grade_m = re.search(
            rf"TEAM:\s*{escaped}.*?GRADE:\s*([^\n]+).*?ANALYSIS:\s*(.+?)(?=\nTEAM:|\n---|\Z)",
            raw, re.DOTALL | re.IGNORECASE,
        )
        if grade_m:
            team_grades.append({
                "team_name": leg.team_name,
                "team_abbr": leg.team_abbr,
                "grade":    grade_m.group(1).strip(),
                "analysis": grade_m.group(2).strip(),
            })
        else:
            team_grades.append({
                "team_name": leg.team_name,
                "team_abbr": leg.team_abbr,
                "grade":    "N/A",
                "analysis": "Could not parse grade.",
            })

    return {
        "doable":       doable,
        "reason":       reason,
        "team_grades":  team_grades,
        "overall":      overall,
        "num_teams":    len(req.legs),
    }


def _is_uuid(s: str) -> bool:
    try:
        from uuid import UUID
        UUID(s)
        return True
    except ValueError:
        return False


# ── Trade Finder ───────────────────────────────────────────────────────────────

class TradeFinderRequest(BaseModel):
    player_id: str


def _standings_snapshot(standings: dict) -> tuple[list[dict], list[dict]]:
    """Return (buyers, sellers) sorted by win pct."""
    all_teams: list[dict] = []
    for div in standings.get("divisions", []):
        for t in div.get("teams", []):
            all_teams.append(t)
    all_teams.sort(key=lambda t: t.get("pct", 0.0), reverse=True)
    buyers  = all_teams[:10]   # top 10 = contenders
    sellers = all_teams[-10:]  # bottom 10 = rebuilders
    return buyers, sellers


async def _prospects_by_org(db: AsyncSession, top_n: int = 8) -> dict[str, list[dict]]:
    """Real, current farm-system prospects grouped by parent MLB org (abbr),
    top N per org by org_prospect_rank. Used to ground AI-proposed trade
    packages in actual minor leaguers instead of invented names."""
    res = await db.execute(
        select(Player).where(
            Player.status.in_(["minors", "draft_prospect"]),
            Player.org_prospect_rank.isnot(None),
            Player.parent_org_abbr.isnot(None),
        ).order_by(Player.parent_org_abbr, Player.org_prospect_rank.asc())
    )
    by_org: dict[str, list[dict]] = {}
    for p in res.scalars().all():
        bucket = by_org.setdefault(p.parent_org_abbr, [])
        if len(bucket) < top_n:
            bucket.append({
                "name": p.full_name,
                "position": p.position or "?",
                "age": p.age,
                "level": p.minor_league_level or "?",
                "org_rank": p.org_prospect_rank,
            })
    return by_org


def _prospects_block(by_org: dict[str, list[dict]]) -> str:
    lines = ["=== REAL FARM SYSTEM PROSPECTS BY TEAM ===",
             "When a return package includes a prospect, you MUST pick an actual name from that "
             "team's list below and describe them with their real position/age/level — never invent "
             "a prospect name or description. If a fitting prospect isn't in the list, build the "
             "package from MLB-ready players or draft picks instead."]
    for org, prospects in sorted(by_org.items()):
        entries = ", ".join(
            f"{pr['name']} ({pr['position']}, {pr['age'] or '?'}, {pr['level']}, #{pr['org_rank']} org)"
            for pr in prospects
        )
        lines.append(f"{org}: {entries}")
    return "\n".join(lines)


def _build_finder_prompt(
    p,
    bat: "BattingStats | None",
    pit: "PitchingStats | None",
    team_name: str,
    standings: dict | None,
    prospects_block: str = "",
) -> str:
    is_pit = p.position in ("SP", "RP")
    war        = _war_pit(pit) if is_pit else _war_bat(bat)
    salary_str = f"${p.salary:.1f}M" if p.salary else "arb/pre-arb"
    yrs_str    = f"{p.contract_years} years remaining" if p.contract_years else "expiring/arb"
    stats_str  = _fmt_pit(pit) if is_pit else _fmt_bat(bat)

    standings_block = ""
    if standings:
        buyers, sellers = _standings_snapshot(standings)
        buyer_names  = ", ".join(
            f"{t.get('full_name','?')} ({t.get('win',0)}-{t.get('loss',0)})" for t in buyers[:8]
        )
        seller_names = ", ".join(
            f"{t.get('full_name','?')} ({t.get('win',0)}-{t.get('loss',0)})" for t in sellers[:8]
        )
        # Classify player's own team
        all_teams = buyers + sellers
        match = next(
            (t for t in all_teams
             if t.get("alias","").upper() in team_name.upper()
             or t.get("full_name","").lower() in team_name.lower()
             or team_name.lower() in t.get("full_name","").lower()),
            None
        )
        if match:
            w, l, pct = match.get("win",0), match.get("loss",0), match.get("pct",0.0)
            if pct >= 0.560:
                context = f"{team_name} is a contender ({w}-{l}); they'd only deal for a massive haul."
            elif pct <= 0.440:
                context = f"{team_name} is in full sell mode ({w}-{l}); a trade is highly realistic."
            else:
                context = f"{team_name} is on the bubble ({w}-{l}); they'd deal for an elite return only."
        else:
            context = f"{team_name}'s exact record is unknown — use your knowledge of their 2026 situation."

        standings_block = f"""
=== 2026 MLB STANDINGS CONTEXT ===
Top contenders (buyers): {buyer_names}
Likely sellers (rebuilding): {seller_names}
{team_name} context: {context}
"""

    return f"""You are a veteran MLB trade analyst and front-office executive.

=== PLAYER BEING TRADED ===
  {p.full_name} ({p.position or "?"}, Age {p.age or "?"}) — currently on {team_name}
  Contract: {salary_str} / {yrs_str}
  2026 stats: {stats_str}
  Estimated WAR: {war:+.1f}
{standings_block}
{prospects_block}

=== YOUR TASK ===
Generate exactly 4 realistic trade proposals for {p.full_name}. For each:
  1. Identify a specific MLB team that genuinely needs this player (position, skill set, playoff window).
  2. Construct a fair return package that {team_name} would realistically receive — a real prospect
     from the acquiring team's list above (named, with real position/age/level), a cost-controlled
     MLB player, or a draft pick.
  3. Factor in standings: buyers pay more to win now; sellers demand premium youth.
  4. Make each proposal represent a distinct scenario (best offer / fair market / team-friendly / dark-horse).

Respond in EXACTLY this format (4 proposals separated by ---):

PROPOSAL 1
ACQUIRING: [Full Team Name] ([ABBR])
WHY: [one sentence: why this team specifically wants this player right now]
PACKAGE: [what {team_name} receives — items separated by " ; ", each described as "Name (detail)"]
BUYER_GRADE: [A+/A/A-/B+/B/B-/C+/C/C-/D/F]
SELLER_GRADE: [A+/A/A-/B+/B/B-/C+/C/C-/D/F]
ANALYSIS: [2-3 sentences on deal balance, what each side gains, and real-world feasibility]
---
PROPOSAL 2
ACQUIRING: [Full Team Name] ([ABBR])
WHY: [one sentence]
PACKAGE: [...]
BUYER_GRADE: [...]
SELLER_GRADE: [...]
ANALYSIS: [...]
---
PROPOSAL 3
ACQUIRING: [Full Team Name] ([ABBR])
WHY: [one sentence]
PACKAGE: [...]
BUYER_GRADE: [...]
SELLER_GRADE: [...]
ANALYSIS: [...]
---
PROPOSAL 4
ACQUIRING: [Full Team Name] ([ABBR])
WHY: [one sentence]
PACKAGE: [...]
BUYER_GRADE: [...]
SELLER_GRADE: [...]
ANALYSIS: [...]

Use 4 different acquiring teams. Be specific with prospect descriptions (position, age, tier). Think like a real GM."""


@router.post("/finder")
async def find_trades(
    req: TradeFinderRequest,
    db: AsyncSession = Depends(get_db),
):
    if not _is_uuid(req.player_id):
        raise HTTPException(status_code=422, detail="Invalid player ID.")

    from uuid import UUID
    from ...models.team import Team as TeamModel

    settings = get_settings()

    # ── 1. Fetch player ────────────────────────────────────────────────────────
    p_res = await db.execute(select(Player).where(Player.id == UUID(req.player_id)))
    p = p_res.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Player not found.")

    # ── 2. Fetch stats ─────────────────────────────────────────────────────────
    bat_res = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id == UUID(req.player_id),
            BattingStats.season == 2026,
            BattingStats.split == "overall",
        )
    )
    bat = bat_res.scalar_one_or_none()

    pit_res = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id == UUID(req.player_id),
            PitchingStats.season == 2026,
            PitchingStats.split == "overall",
        )
    )
    pit = pit_res.scalar_one_or_none()

    # ── 3. Team name ───────────────────────────────────────────────────────────
    team_name = "Unknown Team"
    if p.team_id:
        t_res = await db.execute(
            select(TeamModel).where(TeamModel.id == UUID(str(p.team_id)))
        )
        team = t_res.scalar_one_or_none()
        if team:
            team_name = f"{team.city} {team.name}"

    # ── 4. Live standings (best-effort) ───────────────────────────────────────
    standings: dict | None = None
    try:
        from .standings import _get_standings
        standings = await _get_standings(2026)
    except Exception:
        pass  # Claude will fall back to built-in baseball knowledge

    # ── 5. Real farm-system prospects, grouped by org ─────────────────────────
    prospects_by_org = await _prospects_by_org(db)
    prospects_block = _prospects_block(prospects_by_org)

    # ── 6. Call Claude ─────────────────────────────────────────────────────────
    prompt = _build_finder_prompt(p, bat, pit, team_name, standings, prospects_block)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2400,
        system=(
            "You are a veteran MLB trade analyst with front-office experience. "
            "Generate realistic, specific trade proposals grounded in actual team needs and standings. "
            "Be direct and use real MLB trade market language."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # ── 6. Parse proposals ─────────────────────────────────────────────────────
    proposals = []
    blocks = re.split(r"\n---\n", raw)
    for block in blocks:
        block = block.strip()
        if not block or "ACQUIRING" not in block:
            continue

        acq_m  = re.search(r"^ACQUIRING:\s*(.+)$", block, re.MULTILINE)
        why_m  = re.search(r"^WHY:\s*(.+)$", block, re.MULTILINE)
        pkg_m  = re.search(r"^PACKAGE:\s*(.+)$", block, re.MULTILINE)
        bgr_m  = re.search(r"^BUYER_GRADE:\s*([^\n]+)$", block, re.MULTILINE)
        sgr_m  = re.search(r"^SELLER_GRADE:\s*([^\n]+)$", block, re.MULTILINE)
        ana_m  = re.search(
            r"^ANALYSIS:\s*(.+?)(?=\n[A-Z_]+:|\Z)", block, re.DOTALL | re.MULTILINE
        )

        if not acq_m:
            continue

        acq_raw  = acq_m.group(1).strip()
        abbr_m   = re.search(r"\(([A-Z]{2,4})\)", acq_raw)
        team_abbr_out = abbr_m.group(1) if abbr_m else ""
        acquiring_team = re.sub(r"\s*\([A-Z]{2,4}\)\s*$", "", acq_raw).strip()

        package_raw   = pkg_m.group(1).strip() if pkg_m else ""
        package_items = [s.strip() for s in package_raw.split(";") if s.strip()]

        proposals.append({
            "acquiring_team":      acquiring_team,
            "acquiring_team_abbr": team_abbr_out,
            "why":           why_m.group(1).strip() if why_m else "",
            "return_package": package_items,
            "buyer_grade":   bgr_m.group(1).strip() if bgr_m else "N/A",
            "seller_grade":  sgr_m.group(1).strip() if sgr_m else "N/A",
            "analysis":      ana_m.group(1).strip() if ana_m else "",
        })

    is_pit = p.position in ("SP", "RP")
    war = _war_pit(pit) if is_pit else _war_bat(bat)

    return {
        "player": {
            "id":             str(p.id),
            "name":           p.full_name,
            "position":       p.position,
            "age":            p.age,
            "team":           team_name,
            "salary":         p.salary,
            "contract_years": p.contract_years,
            "war":            war,
            "stats":          (_fmt_pit(pit) if is_pit else _fmt_bat(bat)),
        },
        "proposals": proposals,
    }


# ── Team Advisor ───────────────────────────────────────────────────────────────

class TeamAdvisorRequest(BaseModel):
    team_id: str


def _build_advisor_prompt(
    team_name: str,
    team_abbr: str,
    players: list,         # list of (Player, bat | None, pit | None)
    standings: dict | None,
    prospects_block: str = "",
) -> str:
    # ── Standing context ───────────────────────────────────────────────────────
    standing_block = ""
    direction_hint = ""
    if standings:
        all_teams: list[dict] = []
        for div in standings.get("divisions", []):
            for t in div.get("teams", []):
                all_teams.append(t)
        match = next(
            (t for t in all_teams
             if t.get("alias", "").upper() == team_abbr.upper()
             or t.get("full_name", "").lower() in team_name.lower()
             or team_name.lower() in t.get("full_name", "").lower()),
            None
        )
        if match:
            w, l, pct = match.get("win", 0), match.get("loss", 0), match.get("pct", 0.0)
            gb = match.get("games_back", 0)
            wc_back = match.get("wild_card_back", "")
            if pct >= 0.580:
                ctx = f"CONTENDER — first place or comfortably in playoff position ({w}-{l}). Should be aggressive buyers."
                direction_hint = "BUY"
            elif pct >= 0.520:
                ctx = f"FRINGE CONTENDER — in the playoff race but not secure ({w}-{l}, {gb} GB). Buy selectively or stand pat."
                direction_hint = "MIXED"
            elif pct >= 0.460:
                ctx = f"ON THE BUBBLE — marginal .500 team ({w}-{l}). Evaluate sell vs. hold based on age/contract."
                direction_hint = "HOLD"
            else:
                ctx = f"SELLER — well below .500 ({w}-{l}, {gb} GB behind). Should aggressively sell veterans for prospects."
                direction_hint = "SELL"
            standing_block = f"\n=== STANDINGS ===\n{team_name}: {ctx}\n"

    # ── Roster block ───────────────────────────────────────────────────────────
    hitters  = [(p, b, pi) for p, b, pi in players if p.position not in ("SP", "RP")]
    pitchers = [(p, b, pi) for p, b, pi in players if p.position in ("SP", "RP")]

    def player_line(p, bat, pit) -> str:
        is_pit = p.position in ("SP", "RP")
        war    = _war_pit(pit) if is_pit else _war_bat(bat)
        sal    = f"${p.salary:.1f}M" if p.salary else "arb"
        yrs    = f"{p.contract_years}yr" if p.contract_years else "exp"
        stats  = _fmt_pit(pit) if is_pit else _fmt_bat(bat)
        return (
            f"  • {p.full_name} ({p.position or '?'}, {p.age or '?'}) "
            f"— {sal}/{yrs} — WAR {war:+.1f} — {stats}"
        )

    hit_lines = "\n".join(player_line(p, b, pi) for p, b, pi in hitters) or "  (none)"
    pit_lines = "\n".join(player_line(p, b, pi) for p, b, pi in pitchers) or "  (none)"

    expiring = [
        p for p, _, __ in players
        if (p.contract_years is not None and p.contract_years <= 1)
    ]
    exp_block = ""
    if expiring:
        exp_lines = ", ".join(
            f"{p.full_name} ({p.position or '?'}, exp after 2026)" for p in expiring
        )
        exp_block = f"\n=== EXPIRING CONTRACTS (sell candidates) ===\n  {exp_lines}\n"

    hint_txt = f" (likely {direction_hint})" if direction_hint else ""

    return f"""You are a veteran MLB GM advisor. Analyze what {team_name} should do at the 2026 trade deadline.
{standing_block}{exp_block}
=== 40-MAN ROSTER ===
Position Players:
{hit_lines}

Pitchers:
{pit_lines}

{prospects_block}

=== YOUR TASK{hint_txt} ===
Based on the team's record, roster composition, and contract situations:
1. Decide their overall trade direction.
2. Identify 3 specific players to consider trading away (be realistic — value surplus, expiring contracts, positional depth).
3. Identify 3 positions/types to target via trade.
4. Write a strategic analysis.

When SELL_RETURN mentions a prospect coming back, pick an actual name from the real farm-system list
above (any team could plausibly be the trade partner) and describe them with their real position/age/
level — never invent a prospect name.

Respond in EXACTLY this format:

DIRECTION: [BUY | SELL | HOLD | REBUILD | MIXED]
SUMMARY: [one direct sentence on what this team must do]
---
SELL: [exact player name from roster]
SELL_WHY: [1-2 sentences: contract situation, trade value, why now]
SELL_RETURN: [what they realistically get back]
---
SELL: [exact player name]
SELL_WHY: [...]
SELL_RETURN: [...]
---
SELL: [exact player name]
SELL_WHY: [...]
SELL_RETURN: [...]
---
TARGET: [position or player archetype needed]
TARGET_WHY: [why this addresses a roster gap]
TARGET_EXAMPLE: [1-2 real teams that might have this and could be trade partners]
---
TARGET: [...]
TARGET_WHY: [...]
TARGET_EXAMPLE: [...]
---
TARGET: [...]
TARGET_WHY: [...]
TARGET_EXAMPLE: [...]
---
ANALYSIS: [3-4 sentences on the big picture: competitive window, farm system leverage, and one specific bold recommendation]

Be direct, specific, and use front-office language."""


@router.post("/team-advisor")
async def team_advisor(
    req: TeamAdvisorRequest,
    db: AsyncSession = Depends(get_db),
):
    if not _is_uuid(req.team_id):
        raise HTTPException(status_code=422, detail="Invalid team ID.")

    from uuid import UUID
    from ...models.team import Team as TeamModel

    settings = get_settings()

    # ── 1. Fetch team ──────────────────────────────────────────────────────────
    t_res = await db.execute(select(TeamModel).where(TeamModel.id == UUID(req.team_id)))
    team  = t_res.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")
    team_name = f"{team.city} {team.name}"
    team_abbr = team.abbreviation or ""

    # ── 2. Fetch 40-man roster ─────────────────────────────────────────────────
    roster_res = await db.execute(
        select(Player).where(
            Player.team_id == UUID(req.team_id),
            Player.roster_status != None,  # noqa: E711
        )
    )
    roster = roster_res.scalars().all()

    if not roster:
        raise HTTPException(status_code=404, detail="No 40-man roster found for this team.")

    player_ids = [p.id for p in roster]

    # ── 3. Fetch stats ─────────────────────────────────────────────────────────
    bat_res = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id.in_(player_ids),
            BattingStats.season == 2026,
            BattingStats.split == "overall",
        )
    )
    bat_by = {str(s.player_id): s for s in bat_res.scalars().all()}

    pit_res = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id.in_(player_ids),
            PitchingStats.season == 2026,
            PitchingStats.split == "overall",
        )
    )
    pit_by = {str(s.player_id): s for s in pit_res.scalars().all()}

    players_ctx = [
        (p, bat_by.get(str(p.id)), pit_by.get(str(p.id)))
        for p in roster
    ]

    # ── 4. Standings ───────────────────────────────────────────────────────────
    standings: dict | None = None
    try:
        from .standings import _get_standings
        standings = await _get_standings(2026)
    except Exception:
        pass

    # ── 5. Real farm-system prospects, grouped by org ─────────────────────────
    prospects_block = _prospects_block(await _prospects_by_org(db))

    # ── 6. Call Claude ─────────────────────────────────────────────────────────
    prompt = _build_advisor_prompt(team_name, team_abbr, players_ctx, standings, prospects_block)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2000,
        system=(
            "You are a veteran MLB GM and trade analyst. "
            "Give specific, actionable trade advice grounded in real roster construction principles. "
            "Reference actual player names from the roster provided. Be direct."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # ── 6. Parse ───────────────────────────────────────────────────────────────
    dir_m     = re.search(r"^DIRECTION:\s*(.+)$",  raw, re.MULTILINE)
    summ_m    = re.search(r"^SUMMARY:\s*(.+)$",    raw, re.MULTILINE)
    analysis_m = re.search(
        r"^ANALYSIS:\s*(.+?)(?=\n[A-Z_]+:|\Z)", raw, re.DOTALL | re.MULTILINE
    )

    direction = dir_m.group(1).strip()  if dir_m     else "HOLD"
    summary   = summ_m.group(1).strip() if summ_m    else ""
    analysis  = analysis_m.group(1).strip() if analysis_m else ""

    # Parse SELL blocks
    sells: list[dict] = []
    for block in re.finditer(
        r"^SELL:\s*(.+?)\nSELL_WHY:\s*(.+?)\nSELL_RETURN:\s*(.+?)(?=\n[A-Z_]+:|\n---|\Z)",
        raw, re.DOTALL | re.MULTILINE
    ):
        sells.append({
            "player":  block.group(1).strip(),
            "why":     block.group(2).strip(),
            "returns": block.group(3).strip(),
        })

    # Parse TARGET blocks
    targets: list[dict] = []
    for block in re.finditer(
        r"^TARGET:\s*(.+?)\nTARGET_WHY:\s*(.+?)\nTARGET_EXAMPLE:\s*(.+?)(?=\n[A-Z_]+:|\n---|\Z)",
        raw, re.DOTALL | re.MULTILINE
    ):
        targets.append({
            "need":    block.group(1).strip(),
            "why":     block.group(2).strip(),
            "example": block.group(3).strip(),
        })

    return {
        "team_name": team_name,
        "team_abbr": team_abbr,
        "direction": direction,
        "summary":   summary,
        "sells":     sells,
        "targets":   targets,
        "analysis":  analysis,
    }
