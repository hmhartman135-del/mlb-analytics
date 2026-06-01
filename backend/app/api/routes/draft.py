"""
draft.py
─────────────────
AI-powered draft planner + mock draft simulator.

  POST /api/v1/draft/plan   — per-team draft strategy memo
  POST /api/v1/draft/mock   — full mock draft (all 30 teams, 1-5 rounds)
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
from ...models.stats import BattingStats, PitchingStats
from ...models.team import Team

router = APIRouter(prefix="/draft", tags=["draft"])

# Canonical position order for display
_POSITIONS = ["SP", "RP", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
_LEVELS    = ["AAA", "AA", "A+", "A", "Rookie"]


# ── WAR helpers (shared with offseason.py) ────────────────────────────────────

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


# ── Request model ─────────────────────────────────────────────────────────────

class DraftPlanRequest(BaseModel):
    team_id: UUID


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_prompt(
    team: Team,
    mlb_roster: list[dict],
    system_depth: dict[str, dict[str, list[dict]]],   # pos → level → [player dicts]
    org_prospects: list[dict],
    draft_prospects: list[dict],
) -> str:
    full_name = f"{team.city} {team.name}"
    division  = team.division or "MLB"

    # ── Section 1: MLB roster by position ──
    mlb_by_pos: dict[str, list[dict]] = {}
    for p in mlb_roster:
        pos = p["position"] or "UNK"
        mlb_by_pos.setdefault(pos, []).append(p)

    mlb_lines = []
    for pos in _POSITIONS:
        players = mlb_by_pos.get(pos, [])
        if players:
            names = ", ".join(
                f"{p['name']} (WAR {p['war']:+.1f}"
                + (", EXP" if p["contract_years"] == 0 else
                   f", {p['contract_years']}yr" if p["contract_years"] is not None else "")
                + ")"
                for p in players
            )
            mlb_lines.append(f"  {pos:4s}: {names}")
        else:
            mlb_lines.append(f"  {pos:4s}: (no MLB player)")
    mlb_block = "\n".join(mlb_lines)

    # ── Section 2: System depth matrix ──
    header = f"  {'POS':5s}" + "".join(f" {lvl:>5s}" for lvl in _LEVELS) + "  Top prospect"
    rows = []
    for pos in _POSITIONS:
        counts = []
        top_name = ""
        for lvl in _LEVELS:
            players_at = system_depth.get(pos, {}).get(lvl, [])
            counts.append(len(players_at))
            # Find best prospect at this level for this position
            if not top_name and players_at:
                best = sorted(
                    players_at,
                    key=lambda x: (x.get("org_rank") or 999, -(x.get("overall") or 0)),
                )[0]
                if best.get("org_rank") or best.get("overall"):
                    top_name = (
                        f"{best['name']} "
                        f"({'#' + str(best['org_rank']) + ' org' if best.get('org_rank') else ''}"
                        f"{', ' + str(best['overall']) + ' OVR' if best.get('overall') else ''}"
                        f", {lvl})"
                    )
        count_str = "".join(f" {c:>5d}" for c in counts)
        rows.append(f"  {pos:5s}{count_str}  {top_name}")
    depth_block = header + "\n" + "\n".join(rows)

    # ── Section 3: Top 30 org prospects ──
    if org_prospects:
        org_lines = "\n".join(
            f"  #{p['org_rank']:2d}  {p['name']:<25s} {p['position'] or '?':4s}  "
            f"Age {p['age'] or '?':2}  {p['level'] or '?':6s}"
            + (f"  OVR {p['overall']}" if p.get("overall") else "")
            for p in org_prospects[:30]
        )
    else:
        org_lines = "  (no org prospect rankings loaded)"

    # ── Section 4: Draft prospects by position ──
    draft_by_pos: dict[str, list[dict]] = {}
    for p in draft_prospects:
        pos = p["position"] or "UNK"
        draft_by_pos.setdefault(pos, []).append(p)

    draft_sections = []
    for pos in _POSITIONS:
        dp = draft_by_pos.get(pos, [])
        if dp:
            names = ", ".join(
                f"{'#' + str(p['rank']) + ' ' if p.get('rank') else ''}"
                f"{p['name']}"
                f"{' (' + p['school'] + ')' if p.get('school') else ''}"
                for p in dp[:8]
            )
            draft_sections.append(f"  {pos:4s}: {names}")
    draft_block = "\n".join(draft_sections) if draft_sections else "  (no draft class data)"

    return f"""You are a veteran MLB Director of Scouting writing the 2026 MLB Draft strategy memo for the {full_name}.

=== ORGANIZATION OVERVIEW ===
Team: {full_name} ({division})

=== MLB 40-MAN ROSTER — POSITIONAL SNAPSHOT ===
(WAR = 2026 season; EXP = contract expires after 2026; yr = years remaining)
{mlb_block}

=== MINOR LEAGUE SYSTEM DEPTH (player counts by position × level) ===
{depth_block}

=== TOP-30 ORG PROSPECTS ===
{org_lines}

=== 2026 MLB DRAFT CLASS (available prospects by position) ===
{draft_block}

=== YOUR TASK ===
Write a clear, actionable 2026 MLB Draft strategy memo for the {full_name}. Structure your response as follows:

## System Analysis
Evaluate the organization's current minor league depth. Which positions are well-stocked? Which are barren? Where are the pipeline gaps by level (e.g., "strong at AAA but no impact bats below AA at SS")?

## Priority Positions
List the 3–5 positions most in need of draft investment, ranked. For each, explain the gap: MLB roster situation, system depth, and prospect quality.

## Draft Philosophy
Given the team's position in the competitive cycle, recommend an approach: Best Player Available (BPA) vs. need-based, college vs. high school, pitching vs. bats. Justify it.

## Round-by-Round Targets
For the first 5 rounds, recommend a specific player type (not just position — e.g., "college LHP with elite command", "prep SS with 70-grade arm") and name 1–2 specific prospects from the 2026 class above who fit that profile. Include why they fit this org specifically.

## High-Ceiling Targets
Name 2–3 high-upside prospects (could be prep players or international-style talent) worth reaching for if they fall.

## Risk & Contingency
If top targets are unavailable, what positional pivots or player types serve as fallbacks?

Use professional front-office language. Be specific — name actual prospects, reference real system gaps, and calibrate to whether this org should be drafting for immediate impact or long-term development."""


# ── Route ──────────────────────────────────────────────────────────────────────

@router.post("/plan")
async def generate_draft_plan(
    req: DraftPlanRequest,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()

    # ── 1. Team ────────────────────────────────────────────────────────────────
    team_res = await db.execute(select(Team).where(Team.id == req.team_id))
    team = team_res.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # ── 2. Collect affiliate teams ─────────────────────────────────────────────
    all_teams: list[Team] = [team]
    if team.mlb_id:
        aff_res = await db.execute(
            select(Team).where(Team.affiliate_mlb_id == team.mlb_id)
        )
        all_teams += list(aff_res.scalars().all())

    all_team_ids = [t.id for t in all_teams]

    # ── 3. All players across the org ─────────────────────────────────────────
    players_res = await db.execute(
        select(Player).where(Player.team_id.in_(all_team_ids))
    )
    all_players = players_res.scalars().all()

    if not all_players:
        raise HTTPException(status_code=404, detail="No roster data found for this team")

    player_ids = [p.id for p in all_players]

    # ── 4. Batch-fetch 2026 stats ──────────────────────────────────────────────
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

    # ── 5. Partition into MLB vs minor league ─────────────────────────────────
    mlb_roster: list[dict] = []
    system_depth: dict[str, dict[str, list[dict]]] = {}  # pos → level → [players]

    for p in all_players:
        is_pitcher = p.position in ("SP", "RP")
        war = _war_pit(pit_by.get(p.id)) if is_pitcher else _war_bat(bat_by.get(p.id))

        pdict = {
            "id": str(p.id),
            "name": p.full_name,
            "position": p.position,
            "age": p.age,
            "level": p.minor_league_level or "MLB",
            "contract_years": p.contract_years,
            "org_rank": p.org_prospect_rank,
            "overall": p.scout_overall,
            "war": war,
        }

        if p.minor_league_level is None and p.roster_status is not None:
            # MLB 40-man
            mlb_roster.append(pdict)
        elif p.minor_league_level:
            # Minor league
            pos = p.position or "UNK"
            lvl = p.minor_league_level
            system_depth.setdefault(pos, {}).setdefault(lvl, []).append(pdict)

    # ── 6. Org top-30 prospects (ranked) ──────────────────────────────────────
    org_prospects = sorted(
        [p for p in mlb_roster + [
            v for pos_d in system_depth.values()
            for lvl_list in pos_d.values()
            for v in lvl_list
        ] if p.get("org_rank")],
        key=lambda x: x["org_rank"],
    )

    # ── 7. 2026 draft prospects ─────────────────────────────────────────────────
    dp_res = await db.execute(
        select(Player)
        .where(Player.status == "draft_prospect")
        .order_by(Player.draft_rank.nullslast())
        .limit(120)
    )
    draft_players = dp_res.scalars().all()

    draft_prospects = [
        {
            "id": str(p.id),
            "name": p.full_name,
            "position": p.position,
            "age": p.age,
            "rank": p.draft_rank,
            "school": p.school,
            "school_class": p.school_class,
            "bats": p.bats,
            "throws": p.throws,
            "overall": p.scout_overall,
        }
        for p in draft_players
    ]

    # ── 8. Build prompt & call Claude ─────────────────────────────────────────
    prompt = _build_prompt(
        team=team,
        mlb_roster=mlb_roster,
        system_depth=system_depth,
        org_prospects=org_prospects,
        draft_prospects=draft_prospects,
    )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        system=(
            "You are a veteran MLB Director of Scouting. "
            "Write concise, specific, data-driven draft memos. "
            "Name actual prospects. Reference real system gaps. "
            "Never use filler phrases."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    plan_text: str = message.content[0].text

    # ── 9. Build depth summary for the response ───────────────────────────────
    depth_summary: list[dict] = []
    for pos in _POSITIONS:
        row: dict = {"position": pos}
        for lvl in _LEVELS:
            players_at = system_depth.get(pos, {}).get(lvl, [])
            row[lvl] = len(players_at)
            # Include top prospect name if there is one
            if players_at:
                best = sorted(
                    players_at,
                    key=lambda x: (x.get("org_rank") or 999, -(x.get("overall") or 0)),
                )[0]
                row[f"{lvl}_top"] = best["name"] if (best.get("org_rank") or best.get("overall")) else None
            else:
                row[f"{lvl}_top"] = None
        row["total"] = sum(row.get(lvl, 0) for lvl in _LEVELS)
        depth_summary.append(row)

    # ── 10. Return structured response ────────────────────────────────────────
    return {
        "team": {
            "id": str(team.id),
            "name": team.name,
            "city": team.city,
            "full_name": f"{team.city} {team.name}",
            "division": team.division,
        },
        "context": {
            "mlb_roster_size": len(mlb_roster),
            "minor_league_count": sum(
                len(v)
                for pos_d in system_depth.values()
                for v in pos_d.values()
            ),
            "org_prospects_ranked": len(org_prospects),
            "draft_class_size": len(draft_prospects),
        },
        "depth_summary": depth_summary,
        "org_prospects": org_prospects[:30],
        "draft_prospects": draft_prospects[:60],
        "plan": plan_text,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Mock Draft
# ═══════════════════════════════════════════════════════════════════════════════

class MockDraftRequest(BaseModel):
    rounds: int = 3   # 1–5


# Official 2026 MLB Draft — Round 1 (picks 1-25 only).
# Source: mlb.com/draft/2026/order
# Only 25 teams pick in Round 1. The 5 CBT-penalised teams skip R1:
#   Mets → PPI pick 27, Yankees/Phillies → CBA picks 35-36,
#   Blue Jays/Dodgers → R2 picks 39-40.
_R1_ORDER_2026 = [
    "Chicago White Sox",      #  1
    "Tampa Bay Rays",         #  2
    "Minnesota Twins",        #  3
    "San Francisco Giants",   #  4
    "Pittsburgh Pirates",     #  5
    "Kansas City Royals",     #  6
    "Baltimore Orioles",      #  7
    "Athletics",              #  8
    "Atlanta Braves",         #  9
    "Colorado Rockies",       # 10
    "Washington Nationals",   # 11
    "Los Angeles Angels",     # 12
    "St. Louis Cardinals",    # 13
    "Miami Marlins",          # 14
    "Arizona Diamondbacks",   # 15
    "Texas Rangers",          # 16
    "Houston Astros",         # 17
    "Cincinnati Reds",        # 18
    "Cleveland Guardians",    # 19
    "Boston Red Sox",         # 20
    "San Diego Padres",       # 21
    "Detroit Tigers",         # 22
    "Chicago Cubs",           # 23
    "Seattle Mariners",       # 24
    "Milwaukee Brewers",      # 25
]

# 30-team order for Round 2 and all subsequent rounds.
# Rockies lead (worst overall record). Blue Jays / Dodgers are picks 2-3
# because their CBT penalty pushed them out of R1 entirely into R2.
_DRAFT_ORDER_2026 = [
    "Colorado Rockies",       # R2  1 (overall #38)
    "Toronto Blue Jays",      # R2  2 (CBT penalty — skipped R1)
    "Los Angeles Dodgers",    # R2  3 (CBT penalty — skipped R1)
    "Chicago White Sox",      # R2  4
    "Washington Nationals",   # R2  5
    "Minnesota Twins",        # R2  6
    "Pittsburgh Pirates",     # R2  7
    "Los Angeles Angels",     # R2  8
    "Baltimore Orioles",      # R2  9
    "Athletics",              # R2 10
    "Atlanta Braves",         # R2 11
    "Tampa Bay Rays",         # R2 12
    "St. Louis Cardinals",    # R2 13
    "Miami Marlins",          # R2 14
    "Arizona Diamondbacks",   # R2 15
    "Texas Rangers",          # R2 16
    "San Francisco Giants",   # R2 17
    "Kansas City Royals",     # R2 18
    "Houston Astros",         # R2 19
    "Cincinnati Reds",        # R2 20
    "Cleveland Guardians",    # R2 21
    "Boston Red Sox",         # R2 22
    "San Diego Padres",       # R2 23
    "Detroit Tigers",         # R2 24
    "Chicago Cubs",           # R2 25
    "New York Yankees",       # R2 26 (CBT — picks in CBA, then normal R2+)
    "Philadelphia Phillies",  # R2 27 (CBT — picks in CBA, then normal R2+)
    "Seattle Mariners",       # R2 28
    "Milwaukee Brewers",      # R2 29
    "New York Mets",          # R2 30 (CBT — PPI pick, then normal R2+)
]

# Prospect Promotion Incentive picks — after Round 1, before Comp. Balance A.
# picks 26-28 overall.
_PPI_2026 = [
    "Atlanta Braves",         # 26  (Drake Baldwin NL Rookie of the Year)
    "New York Mets",          # 27  (CBT penalty placed pick in PPI zone)
    "Houston Astros",         # 28  (Hunter Brown AL Cy Young top-3)
]

# Competitive Balance Round A — picks 29-37 (after PPI).
# 7 eligible small-market teams + 2 CBT-penalised teams (Yankees, Phillies).
_CBA_2026 = [
    "Cleveland Guardians",    # 29  (original holder; traded to SF Giants in reality)
    "Kansas City Royals",     # 30
    "Arizona Diamondbacks",   # 31
    "St. Louis Cardinals",    # 32
    "Baltimore Orioles",      # 33  (original holder; traded to TB Rays in reality)
    "Pittsburgh Pirates",     # 34
    "New York Yankees",       # 35  CBT penalty — first pick lands here
    "Philadelphia Phillies",  # 36  CBT penalty
    "Colorado Rockies",       # 37
]

# Competitive Balance Round B — picks 68-75 (after Round 2).
# 8 eligible small-market teams (some picks traded).
_CBB_2026 = [
    "Milwaukee Brewers",      # 68  (traded to BOS in reality)
    "Seattle Mariners",       # 69  (traded to STL in reality)
    "Detroit Tigers",         # 70
    "Cincinnati Reds",        # 71
    "Miami Marlins",          # 72
    "Tampa Bay Rays",         # 73  (traded to STL in reality)
    "Athletics",              # 74
    "Minnesota Twins",        # 75
]


def _sort_teams_by_draft_order(teams: list[Team]) -> list[Team]:
    def _rank(t: Team) -> int:
        full = f"{t.city} {t.name}".strip()
        try:
            return _DRAFT_ORDER_2026.index(full)
        except ValueError:
            return 999
    return sorted(teams, key=_rank)


async def _build_team_needs(
    mlb_teams: list[Team],
    db: AsyncSession,
) -> dict[str, list[str]]:
    """
    For each MLB team, query their 40-man roster and return a list of
    positions where they are thin (0-1 players on the active/40-man roster).
    Returns {team_abbr: [needed_positions]}.
    """
    from collections import defaultdict

    team_ids = [t.id for t in mlb_teams]

    res = await db.execute(
        select(Player.team_id, Player.position).where(
            Player.team_id.in_(team_ids),
            Player.roster_status.isnot(None),
            Player.position.isnot(None),
        )
    )
    rows = res.all()

    # Count how many 40-man players each team has at each position
    pos_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for team_id, pos in rows:
        pos_counts[str(team_id)][pos] += 1

    id_to_abbr = {str(t.id): t.abbreviation for t in mlb_teams}

    HITTING_POS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
    SP_MIN, RP_MIN = 4, 3   # thresholds below which a pitching slot is a "need"

    needs_by_abbr: dict[str, list[str]] = {}
    for t in mlb_teams:
        counts = pos_counts.get(str(t.id), {})
        needs: list[str] = []

        # Hitting positions — flag if 0 or 1 player
        for pos in HITTING_POS:
            n = counts.get(pos, 0)
            if n == 0:
                needs.append(f"{pos}!")     # critical gap
            elif n <= 1:
                needs.append(pos)

        # Pitching
        if counts.get("SP", 0) < SP_MIN:
            needs.append("SP" if counts.get("SP", 0) >= 1 else "SP!")
        if counts.get("RP", 0) < RP_MIN:
            needs.append("RP")

        needs_by_abbr[t.abbreviation] = needs[:6]   # cap at 6 for prompt brevity

    return needs_by_abbr


def _build_mock_prompt(
    mlb_teams: list[Team],
    prospects: list[dict],
    rounds: int,
    team_needs: dict[str, list[str]] | None = None,
) -> str:
    # ── Build abbr lookup ─────────────────────────────────────────────────────
    abbr_map = {f"{t.city} {t.name}".strip(): t.abbreviation for t in mlb_teams}
    abbr_map.update({t.name: t.abbreviation for t in mlb_teams})

    def _abbr(full_name: str) -> str:
        return abbr_map.get(full_name, full_name[:3].upper())

    # ── Round 1 team block (25 non-CBT teams) ─────────────────────────────────
    # Map R1 names to Team objects for needs lookup
    name_to_team = {f"{t.city} {t.name}".strip(): t for t in mlb_teams}
    name_to_team.update({t.name: t for t in mlb_teams})

    r1_lines = []
    for i, name in enumerate(_R1_ORDER_2026):
        t = name_to_team.get(name)
        abbr = _abbr(name)
        if t and t.abbreviation:
            abbr = t.abbreviation
        if i < 8:
            window = "REBUILD"
        elif i < 18:
            window = "MID"
        else:
            window = "COMPETE"
        needs_str = ""
        if team_needs and t:
            needs = team_needs.get(abbr, [])
            needs_str = f"  | needs: {', '.join(needs) if needs else 'flexible'}"
        r1_lines.append(f"  {i+1:2d}. {abbr:<4s} {name:<28s} [{window}]{needs_str}")
    r1_block = "\n".join(r1_lines)

    # ── Round 2+ team block (all 30 teams) ────────────────────────────────────
    r2_lines = []
    for i, name in enumerate(_DRAFT_ORDER_2026):
        t = name_to_team.get(name)
        abbr = _abbr(name)
        if t and t.abbreviation:
            abbr = t.abbreviation
        needs_str = ""
        if team_needs and t:
            needs = team_needs.get(abbr, [])
            needs_str = f"  | needs: {', '.join(needs) if needs else 'flexible'}"
        r2_lines.append(f"  {i+1:2d}. {abbr:<4s} {name:<28s}{needs_str}")
    r2_block = "\n".join(r2_lines)

    # ── PPI / CBA / CBB blocks ────────────────────────────────────────────────
    ppi_lines  = "\n".join(f"  {i+1}. {name} ({_abbr(name)})" for i, name in enumerate(_PPI_2026))
    cba_lines  = "\n".join(f"  {i+1}. {name} ({_abbr(name)})" for i, name in enumerate(_CBA_2026))
    cbb_lines  = "\n".join(f"  {i+1}. {name} ({_abbr(name)})" for i, name in enumerate(_CBB_2026))

    # ── Prospect block ────────────────────────────────────────────────────────
    prospect_lines = []
    for p in prospects:
        rank   = f"#{p['rank']:3d}" if p.get("rank") else "  NR"
        school = (p.get("school") or "Intl")[:28]
        hand   = f"{p.get('bats','?')}/{p.get('throws','?')}"
        prospect_lines.append(
            f"  {rank} | {p['name']:<28s} | {p['position'] or '?':4s} | {school:<28s} | {hand}"
        )
    prospect_block = "\n".join(prospect_lines)

    # ── Pick counts ───────────────────────────────────────────────────────────
    r1_count  = len(_R1_ORDER_2026)           # 25
    ppi_count = len(_PPI_2026)                # 3
    cba_count = len(_CBA_2026)                # 9
    r2_count  = len(_DRAFT_ORDER_2026)        # 30
    cbb_count = len(_CBB_2026)                # 8
    bonus = ppi_count + cba_count + (cbb_count if rounds >= 2 else 0)
    r1_end  = r1_count                        # 25
    ppi_end = r1_end  + ppi_count             # 28
    cba_end = ppi_end + cba_count             # 37
    r2_end  = cba_end + (r2_count if rounds >= 2 else 0)     # 67
    cbb_end = r2_end  + (cbb_count if rounds >= 2 else 0)    # 75
    total_picks = r1_count + bonus + (rounds - 1) * r2_count if rounds >= 2 else r1_count + ppi_count + cba_count

    cbb_section = ""
    if rounds >= 2:
        cbb_section = f"""
=== COMPETITIVE BALANCE ROUND B (CBB) — {cbb_count} picks after Round 2 (overall #{r2_end+1}–{cbb_end}) ===
Output these {cbb_count} lines AFTER all {r2_count} Round 2 lines, using ROUND="CBB":
{cbb_lines}
"""

    return f"""You are the AI GM for all 30 MLB teams simulating the real 2026 MLB Draft ({rounds} rounds).
Make REALISTIC, INTELLIGENT picks — do NOT simply pick by ranking order.

=== OFFICIAL 2026 DRAFT STRUCTURE ===
- Round 1 (R1): picks  1–{r1_end}    — {r1_count} teams (no CBT-penalised teams in R1)
- PPI         : picks {r1_end+1}–{ppi_end}    — {ppi_count} Prospect Promotion Incentive award picks
- CBA         : picks {ppi_end+1}–{cba_end}    — {cba_count} Competitive Balance Round A (incl. 2 CBT teams)
- Round 2 (R2): picks {cba_end+1}–{r2_end}   — {r2_count} teams (Blue Jays & Dodgers lead — skipped R1 due to CBT)
- CBB         : picks {r2_end+1}–{cbb_end}   — {cbb_count} Competitive Balance Round B (if rounds≥2)
- Rounds 3+   : {r2_count} picks each
Total lines to output: {total_picks}

=== ROUND 1 TEAMS (picks 1–{r1_end}) ===
REBUILD = 1-8, MID = 9-18, COMPETE = 19-25
{r1_block}

=== PPI PICKS ({ppi_count} picks, overall #{r1_end+1}–{ppi_end}) ===
Awarded for 2025 season achievements. Output AFTER Round 1 using ROUND="PPI":
{ppi_lines}

=== COMPETITIVE BALANCE ROUND A ({cba_count} picks, overall #{ppi_end+1}–{cba_end}) ===
7 small-market + 2 CBT-penalised teams (Yankees, Phillies skip R1 — first pick is here).
Output AFTER PPI picks using ROUND="CBA":
{cba_lines}

=== ROUND 2+ TEAMS ({r2_count} teams per round) ===
Blue Jays & Dodgers lead R2 (CBT penalty pushed them out of R1 entirely).
All 30 teams repeat this order for Round 2 and all subsequent rounds:
{r2_block}
{cbb_section}
=== 2026 DRAFT PROSPECT POOL ===
  Rank | Name                         | Pos  | School                       | B/T
{prospect_block}

=== HOW TO MAKE EACH PICK ===
1. Round 1 + PPI + CBA: balance need vs. talent (BPA within 8 spots → take need; 9+ spots → BPA).
2. Rounds 2+ + CBB: fill secondary needs and pitching depth.
3. Rounds 4+: pure upside — best athlete or arm remaining.
4. REBUILD teams (picks 1-8): lean high ceiling; HS players OK.
   COMPETE teams (picks 19-25+): lean proven college players.
5. NEVER draft the same player twice.

=== OUTPUT FORMAT — EXACTLY {total_picks} lines ===
ORDER: {r1_count} R1 lines → {ppi_count} PPI → {cba_count} CBA → {r2_count} R2 → {cbb_count} CBB → {r2_count} R3 → …

Each line: ROUND|PICK_IN_ROUND|TEAM_NAME|TEAM_ABBR|PLAYER_NAME|POSITION|SCHOOL|NOTE
- ROUND: "1","2","3"… / "PPI" / "CBA" / "CBB"
- PICK_IN_ROUND: 1–{r1_count} for R1; 1–{ppi_count} PPI; 1–{cba_count} CBA; 1–{r2_count} R2+; 1–{cbb_count} CBB
- POSITION: SP, RP, C, 1B, 2B, 3B, SS, LF, CF, RF, or DH
- NOTE: 6-8 words explaining WHY this pick was made

Output ONLY pipe-delimited lines. No headers, no commentary, no blank lines.

Examples:
1|1|Chicago White Sox|CWS|Roch Cholowsky|SS|UCLA|Top talent fits rebuild perfectly
1|25|Milwaukee Brewers|MIL|Player Name|POS|School|Last R1 slot, fills need
PPI|1|Atlanta Braves|ATL|Player Name|POS|School|Award pick, premium talent
PPI|2|New York Mets|NYM|Player Name|POS|School|CBT-penalty PPI slot
PPI|3|Houston Astros|HOU|Player Name|POS|School|Award pick, pitching depth
CBA|1|Cleveland Guardians|CLE|Player Name|POS|School|Small-market bonus pick
CBA|7|New York Yankees|NYY|Player Name|POS|School|CBT first pick, CBA slot
CBA|9|Colorado Rockies|COL|Player Name|POS|School|Last CBA pick
2|1|Colorado Rockies|COL|Player Name|POS|School|Worst record, leads R2
2|2|Toronto Blue Jays|TOR|Player Name|POS|School|CBT pushed to R2, top value"""


def _parse_mock_draft(raw: str) -> list[dict]:
    """Parse Claude's pipe-delimited mock draft output into structured dicts.

    Handles both numeric rounds ("1", "2", …) and compensatory round labels
    ("CBA", "CBB").
    """
    picks: list[dict] = []
    seen_players: set[str] = set()
    overall = 0

    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 7:
            continue
        try:
            round_label    = parts[0].upper()           # "1", "2", "CBA", "CBB" …
            pick_in_round  = int(parts[1])
            team_name      = parts[2]
            team_abbr      = parts[3]
            player_name    = parts[4]
            position       = parts[5]
            school         = parts[6]
            note           = parts[7] if len(parts) > 7 else ""
        except (ValueError, IndexError):
            continue

        # Skip duplicated players (Claude occasionally slips)
        key = player_name.lower().strip()
        if key in seen_players or not key:
            continue
        seen_players.add(key)

        # Skip lines that look like headers
        if re.search(r"^(round|pick|team|player)$", key, re.I):
            continue

        overall += 1
        picks.append({
            "overall":       overall,
            "round":         round_label,
            "pick_in_round": pick_in_round,
            "team_name":     team_name,
            "team_abbr":     team_abbr,
            "player_name":   player_name,
            "position":      position,
            "school":        school,
            "note":          note,
        })

    return picks


@router.post("/mock")
async def generate_mock_draft(
    req: MockDraftRequest,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    rounds = max(1, min(5, req.rounds))

    # ── 1. All 30 MLB teams (sorted into official 2026 draft order) ──────────────
    teams_res = await db.execute(
        select(Team).where(Team.level == "MLB")
    )
    mlb_teams = _sort_teams_by_draft_order(list(teams_res.scalars().all()))
    if len(mlb_teams) < 20:
        raise HTTPException(status_code=404, detail="Not enough MLB team data")

    # ── 2. Top draft prospects ─────────────────────────────────────────────────
    # R1=25, PPI=3, CBA=9, R2+=30/round, CBB=8
    r1_picks = len(_R1_ORDER_2026)
    bonus    = len(_PPI_2026) + len(_CBA_2026) + (len(_CBB_2026) if rounds >= 2 else 0)
    r2plus   = max(0, rounds - 1) * len(_DRAFT_ORDER_2026)
    prospect_limit = min(r1_picks + bonus + r2plus + 60, 200)
    dp_res = await db.execute(
        select(Player)
        .where(Player.status == "draft_prospect")
        .order_by(Player.draft_rank.nullslast())
        .limit(prospect_limit)
    )
    raw_prospects = dp_res.scalars().all()

    prospects = [
        {
            "name":     p.full_name,
            "position": p.position,
            "rank":     p.draft_rank,
            "school":   p.school,
            "bats":     p.bats,
            "throws":   p.throws,
            "age":      p.age,
            "overall":  p.scout_overall,
        }
        for p in raw_prospects
    ]

    if len(prospects) < rounds * 10:
        raise HTTPException(
            status_code=422,
            detail="Not enough draft prospect data to run a mock draft. "
                   "Run the draft prospect ingestion script first.",
        )

    # ── 3. Fetch team needs from 40-man rosters ────────────────────────────────
    team_needs = await _build_team_needs(mlb_teams, db)

    # ── 4. Build prompt & call Claude ─────────────────────────────────────────
    prompt = _build_mock_prompt(mlb_teams, prospects, rounds, team_needs=team_needs)

    # More tokens for multi-round drafts so Claude doesn't get cut off
    max_tok = min(4096 + rounds * 800, 8192)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=max_tok,
        system=(
            "You are an intelligent MLB draft analyst simulating a realistic draft. "
            "Make thoughtful picks based on each team's needs and competitive window — "
            "do NOT simply pick players in ranking order. "
            "Output ONLY pipe-delimited pick lines. No headers, no prose, no blank lines. "
            "Every prospect is used at most once."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text: str = message.content[0].text

    # ── 4. Parse & return ──────────────────────────────────────────────────────
    picks = _parse_mock_draft(raw_text)

    return {
        "rounds":      rounds,
        "total_picks": len(picks),
        "picks":       picks,
    }


# ── Draft Grade endpoint ───────────────────────────────────────────────────────

class DraftPickInput(BaseModel):
    round: str | int           # "1", "2", "CBA", "CBB" or numeric
    pick_in_round: int
    player_name: str
    position: str | None = None
    school: str | None = None
    rank: int | None = None


class DraftGradeRequest(BaseModel):
    team_abbr: str
    team_name: str
    picks: list[DraftPickInput]


@router.post("/grade")
async def grade_mock_draft(req: DraftGradeRequest):
    """Grade a user's manual mock draft haul for their chosen team."""
    if not req.picks:
        raise HTTPException(status_code=422, detail="No picks provided to grade.")

    settings = get_settings()

    pick_lines = "\n".join(
        f"  Rd {p.round}, Pick {p.pick_in_round}: {p.player_name}"
        f" ({p.position or '?'}"
        f"{', ' + p.school if p.school else ''}"
        f"{', Rank #' + str(p.rank) if p.rank else ''})"
        for p in req.picks
    )

    prompt = f"""You are an MLB draft analyst grading a mock draft class.

TEAM: {req.team_name} ({req.team_abbr})
LAST ROUND: {req.picks[-1].round}
TOTAL PICKS: {len(req.picks)}

PICKS:
{pick_lines}

Grade each pick and the overall class. Output EXACTLY in this format — one line per pick, then the overall:

PICK|[round]|[player_name]|[grade]|[one-sentence note, max 12 words]

After all picks:
OVERALL|[grade]|[2–3 sentence summary of the class]

Use letter grades: A+, A, A-, B+, B, B-, C+, C, C-, D, F
Consider value at the pick slot, positional need, upside, and class fit."""

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        system=(
            "You are an expert MLB draft analyst. "
            "Always output EXACTLY the format requested — PICK lines then OVERALL line. "
            "Be specific and direct."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # Parse PICK lines — round may be numeric ("1") or a label ("CBA", "CBB")
    pick_grades = []
    for line in raw.splitlines():
        m = re.match(r"^PICK\|([^|]+)\|([^|]+)\|([^|]+)\|(.+)$", line.strip())
        if m:
            pick_grades.append({
                "round":       m.group(1).strip(),
                "player_name": m.group(2).strip(),
                "grade":       m.group(3).strip(),
                "note":        m.group(4).strip(),
            })

    # Parse OVERALL line
    overall_m = re.search(r"^OVERALL\|([^|]+)\|(.+)$", raw, re.MULTILINE)
    overall_grade   = overall_m.group(1).strip() if overall_m else "B"
    overall_summary = overall_m.group(2).strip() if overall_m else raw

    return {
        "team_abbr":    req.team_abbr,
        "team_name":    req.team_name,
        "overall_grade": overall_grade,
        "summary":      overall_summary,
        "pick_grades":  pick_grades,
    }
