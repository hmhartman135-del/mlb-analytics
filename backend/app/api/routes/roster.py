from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from ...core.database import get_db
from ...models.player import Player
from ...models.team import Team
from ...models.stats import BattingStats, PitchingStats
from ...services.analytics import score_free_agent, value_contract
from ...services.scouting import generate_roster_recommendation

router = APIRouter(prefix="/roster", tags=["roster"])

LUXURY_TAX_THRESHOLD_M = 241.0   # 2026 CBT threshold (estimated)
DOLLARS_PER_WAR = 8.0            # free-agent market rate $/WAR
LEAGUE_MIN_M = 0.74              # 2026 league minimum (~$740K)


def estimate_salary_m(war: float, service_time: float | None, age: int | None = None) -> float:
    """
    Estimate MLB salary from WAR + service time using standard arb/FA tiers.
    Pre-arb  (<3 yrs)  : league minimum
    Arb 1    (3–4 yrs) : ~15% of market value, min $1.0M
    Arb 2    (4–5 yrs) : ~25% of market value, min $1.5M
    Arb 3    (5–6 yrs) : ~40% of market value, min $2.0M
    Free agent (6+ yrs): ~75% of market value, min $2.0M

    When service_time is unknown, age is used as a proxy (rough but much better
    than defaulting everyone to league minimum):
      age ≥ 33 → assume FA (6+ yrs)
      age 30–32 → assume Arb 3 / early FA (5.5 yrs)
      age 27–29 → assume Arb 2/3 (4.5 yrs)
      age 25–26 → assume Arb 1 (3.5 yrs)
      age ≤ 24  → assume Pre-arb
    """
    svc = service_time
    if svc is None and age is not None:
        if age >= 33:
            svc = 6.5
        elif age >= 30:
            svc = 5.5
        elif age >= 27:
            svc = 4.5
        elif age >= 25:
            svc = 3.5
        else:
            svc = 1.5
    svc = svc or 0.0
    market = max(war, 0.0) * DOLLARS_PER_WAR

    if svc < 3.0:
        return LEAGUE_MIN_M
    elif svc < 4.0:
        return round(max(1.0, market * 0.15), 2)
    elif svc < 5.0:
        return round(max(1.5, market * 0.25), 2)
    elif svc < 6.0:
        return round(max(2.0, market * 0.40), 2)
    else:
        return round(max(2.0, market * 0.75), 2)


def _est_war_bat(s) -> float:
    """
    Estimate batter WAR from wOBA, projected to a full 600-PA season.
    Raw accumulated stats mid-season under-represent a player's value;
    projecting to a full season gives much more realistic salary inputs.
    The multiplier is capped at 4× so hot-start small samples don't
    inflate estimates absurdly.
    """
    if s and s.war:
        return float(s.war)
    if s and s.woba and s.plate_appearances and s.plate_appearances >= 30:
        raa = (s.woba - 0.320) / 1.15 * s.plate_appearances
        replacement = 2.0 * s.plate_appearances / 600
        raw = (raa + replacement) / 10
        # Project to a full 600-PA season, cap multiplier at 4×
        if s.plate_appearances < 550:
            raw = raw * min(600 / s.plate_appearances, 4.0)
        return round(max(min(raw, 12.0), -4.0), 1)   # clamp [-4, 12]
    return 0.0


def _est_war_pit(s) -> float:
    """
    Estimate pitcher WAR from FIP, projected to a full-season workload.
    SP target = 180 IP, RP target = 65 IP (inferred from games_started ratio).
    Multiplier capped at 4× to limit small-sample noise.
    """
    if s and s.war:
        return float(s.war)
    if s and s.fip and s.innings_pitched and s.innings_pitched >= 5:
        fip_diff = 4.20 - s.fip
        replacement = 0.5 * s.innings_pitched / 180
        raw = fip_diff * s.innings_pitched / 9 / 1.5 + replacement
        # Determine SP vs RP by games_started ratio
        gs = getattr(s, "games_started", None) or 0
        g  = getattr(s, "games", None) or 1
        is_sp = gs / g >= 0.5 if g else False
        target_ip = 180 if is_sp else 65
        if s.innings_pitched < target_ip * 0.9:
            raw = raw * min(target_ip / s.innings_pitched, 4.0)
        return round(max(min(raw, 9.0), -3.0), 1)   # clamp [-3, 9]
    return 0.0


class RosterNeedsRequest(BaseModel):
    team_id: UUID
    season: int = 2026
    budget_remaining_m: float = 20.0
    generate_ai_recommendation: bool = False


@router.get("/{team_id}")
async def get_roster(
    team_id: UUID,
    include_minors: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    statuses = ["active"]
    if include_minors:
        statuses.append("minors")

    result = await db.execute(
        select(Player).where(
            Player.team_id == team_id,
            Player.status.in_(statuses),
        )
    )
    players = result.scalars().all()
    return {"roster": [_player_summary(p) for p in players], "count": len(players)}


@router.post("/analyze-needs")
async def analyze_roster_needs(req: RosterNeedsRequest, db: AsyncSession = Depends(get_db)):
    # Get current roster
    roster_result = await db.execute(
        select(Player).where(Player.team_id == req.team_id, Player.status == "active")
    )
    roster = roster_result.scalars().all()

    # Get team info
    team_result = await db.execute(select(Team).where(Team.id == req.team_id))
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Identify covered and missing positions
    field_positions = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
    pitching_positions = ["SP", "RP"]

    covered_positions = set()
    for p in roster:
        if p.position:
            covered_positions.add(p.position)
        for sp in (p.secondary_positions or []):
            covered_positions.add(sp)

    needs = [pos for pos in field_positions + pitching_positions if pos not in covered_positions]

    # Enrich roster with latest stats
    roster_dicts = []
    for p in roster:
        stats = await _get_latest_stats(db, p, req.season)
        d = _player_summary(p)
        if stats:
            d.update(stats)
        roster_dicts.append(d)

    # Fetch and score free agents against needs
    fa_result = await db.execute(select(Player).where(Player.status == "free_agent"))
    free_agents = fa_result.scalars().all()

    fa_scores = []
    for fa in free_agents:
        fa_stats = await _get_latest_stats(db, fa, req.season)
        fa_dict = _player_summary(fa)
        if fa_stats:
            fa_dict.update(fa_stats)
        scored = score_free_agent(fa_dict, needs)
        if req.budget_remaining_m and fa.salary and fa.salary > req.budget_remaining_m:
            continue
        fa_scores.append(scored)

    fa_scores.sort(key=lambda x: x["fit_score"], reverse=True)

    response = {
        "team": {"id": str(team.id), "name": team.name},
        "roster_size": len(roster),
        "needs": needs,
        "free_agent_recommendations": fa_scores[:10],
        "budget_remaining_m": req.budget_remaining_m,
    }

    if req.generate_ai_recommendation:
        team_dict = {"id": str(team.id), "name": team.name}
        fa_dicts = [_player_summary(fa) for fa in free_agents[:15]]
        memo = await generate_roster_recommendation(
            team=team_dict,
            roster=roster_dicts,
            team_needs=needs,
            free_agents=fa_dicts,
            budget_remaining_m=req.budget_remaining_m,
        )
        response["ai_recommendation"] = memo

    return response


IL_CODES = {"D7", "D10", "D15", "D25", "D60", "ILF"}


@router.get("/{team_id}/breakdown")
async def roster_breakdown(
    team_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns three buckets for a team:
      - twenty_six: players on the 26-man active roster (roster_status='A')
      - forty_man:  remaining 40-man members (IL + reassigned, roster_status != 'A')
      - minors:     all minor league affiliates grouped by level (via org roster)
    """
    from ...models.team import Team as TeamModel

    # ── Fetch all players for the MLB team (just that team's roster) ──────────
    roster_result = await db.execute(
        select(Player).where(
            Player.team_id == team_id,
            Player.roster_status != None,  # noqa: E711  — only 40-man members
        )
    )
    mlb_roster = roster_result.scalars().all()

    twenty_six = []
    forty_extra = []   # 40-man but not 26-man (IL + RM)

    for p in mlb_roster:
        pdict = _player_summary(p)
        pdict["roster_status"] = p.roster_status
        if p.roster_status == "A":
            twenty_six.append(pdict)
        else:
            # Label: "10-Day IL", "60-Day IL", "Reassigned", etc.
            if p.roster_status in IL_CODES:
                days = p.roster_status.lstrip("D").rstrip("F")
                pdict["roster_label"] = f"{days}-Day IL" if days.isdigit() else "IL"
            elif p.roster_status == "RM":
                pdict["roster_label"] = "Reassigned to Minors"
            else:
                pdict["roster_label"] = p.roster_status
            forty_extra.append(pdict)

    # Sort: hitters first (by position order), then pitchers
    POS_SORT = {"C": 0, "1B": 1, "2B": 2, "3B": 3, "SS": 4,
                "LF": 5, "CF": 6, "RF": 7, "DH": 8, "SP": 9, "RP": 10}

    def pos_key(p): return (POS_SORT.get(p.get("position") or "", 99), p.get("full_name", ""))

    twenty_six.sort(key=pos_key)
    forty_extra.sort(key=pos_key)

    return {
        "twenty_six": twenty_six,
        "forty_extra": forty_extra,
        "twenty_six_count": len(twenty_six),
        "forty_man_count": len(twenty_six) + len(forty_extra),
    }


@router.get("/{team_id}/finances")
async def team_finances(
    team_id: UUID,
    season: int = Query(2026),
    db: AsyncSession = Depends(get_db),
):
    """Full financial picture: payroll summary + per-player contract + WAR value."""
    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # Only include actual 40-man roster members (roster_status IS NOT NULL).
    # Using status/minor_league_level would pull in stale records from prior ingestion runs.
    roster_result = await db.execute(
        select(Player).where(
            Player.team_id == team_id,
            Player.roster_status != None,  # noqa: E711  40-man members only
        )
    )
    roster = roster_result.scalars().all()

    # Batch-fetch stats in 2 queries
    player_ids = [p.id for p in roster]
    bat_result = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id.in_(player_ids),
            BattingStats.season == season,
            BattingStats.split == "overall",
        )
    )
    batting_by = {s.player_id: s for s in bat_result.scalars().all()}

    pit_result = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id.in_(player_ids),
            PitchingStats.season == season,
            PitchingStats.split == "overall",
        )
    )
    pitching_by = {s.player_id: s for s in pit_result.scalars().all()}

    contracts = []
    total_payroll = 0.0
    real_salary_count = 0
    payroll_by_group: dict[str, float] = {"SP": 0.0, "RP": 0.0, "Infield": 0.0, "Outfield": 0.0, "Other": 0.0}

    for p in roster:
        is_pitcher = p.position in ("SP", "RP")
        if is_pitcher:
            war = _est_war_pit(pitching_by.get(p.id))
        else:
            war = _est_war_bat(batting_by.get(p.id))

        # Use real salary if recorded, otherwise estimate from WAR + service time
        if p.salary and p.salary > 0:
            salary = p.salary
            is_estimated = False
            real_salary_count += 1
        else:
            salary = estimate_salary_m(war, p.service_time, p.age)
            is_estimated = True

        total_payroll += salary

        # Payroll by group (using effective salary)
        if p.position == "SP":
            payroll_by_group["SP"] += salary
        elif p.position == "RP":
            payroll_by_group["RP"] += salary
        elif p.position in ("C", "1B", "2B", "3B", "SS"):
            payroll_by_group["Infield"] += salary
        elif p.position in ("LF", "CF", "RF", "DH"):
            payroll_by_group["Outfield"] += salary
        else:
            payroll_by_group["Other"] += salary

        value = value_contract(salary, war)

        # IL / roster status label
        rs = p.roster_status or "A"
        if rs == "A":
            roster_label = "Active"
        elif rs in IL_CODES:
            days = rs.lstrip("D").rstrip("F")
            roster_label = f"{days}-Day IL" if days.isdigit() else "IL"
        elif rs == "RM":
            roster_label = "Reassigned"
        else:
            roster_label = rs

        contracts.append({
            "player_id": str(p.id),
            "name": p.full_name,
            "position": p.position,
            "level": p.minor_league_level or "MLB",
            "age": p.age,
            "roster_status": rs,
            "roster_label": roster_label,
            "salary_m": round(salary, 2),
            "is_estimated": is_estimated,
            "contract_years": p.contract_years,
            "service_time": p.service_time,
            "war": round(war, 1),
            "market_value_m": value["market_value_m"],
            "surplus_value_m": value["surplus_value_m"],
            "value_grade": value["grade"],
        })

    contracts.sort(key=lambda x: x["salary_m"], reverse=True)

    avg_salary = round(total_payroll / len(roster), 2) if roster else 0.0
    all_estimated = real_salary_count == 0

    return {
        "team": {"id": str(team.id), "name": team.name, "city": team.city, "full_name": f"{team.city} {team.name}"},
        "season": season,
        "payroll": {
            "total_m": round(total_payroll, 2),
            "luxury_tax_threshold_m": LUXURY_TAX_THRESHOLD_M,
            "gap_m": round(LUXURY_TAX_THRESHOLD_M - total_payroll, 2),
            "over_threshold": total_payroll > LUXURY_TAX_THRESHOLD_M,
            "roster_size": len(roster),
            "real_salary_count": real_salary_count,
            "avg_salary_m": avg_salary,
            "all_estimated": all_estimated,
        },
        "payroll_by_group": {k: round(v, 2) for k, v in payroll_by_group.items()},
        "contracts": contracts,
    }


@router.get("/{team_id}/contract-values")
async def get_contract_values(
    team_id: UUID,
    season: int = Query(2026),
    db: AsyncSession = Depends(get_db),
):
    roster_result = await db.execute(
        select(Player).where(Player.team_id == team_id, Player.status == "active")
    )
    roster = roster_result.scalars().all()

    values = []
    for p in roster:
        if p.salary is None:
            continue
        stats = await _get_latest_stats(db, p, season)
        war = (stats or {}).get("war") or 0.0
        value = value_contract(p.salary, war)
        values.append({
            "player_id": str(p.id),
            "player_name": p.full_name,
            "position": p.position,
            **value,
        })

    values.sort(key=lambda x: x["surplus_value_m"], reverse=True)
    return {"contract_values": values}


async def _get_latest_stats(db: AsyncSession, player: Player, season: int) -> dict | None:
    is_pitcher = player.position in ("SP", "RP")
    if is_pitcher:
        result = await db.execute(
            select(PitchingStats).where(
                PitchingStats.player_id == player.id,
                PitchingStats.season == season,
                PitchingStats.split == "overall",
            )
        )
        s = result.scalar_one_or_none()
        if not s:
            return None
        return {"era": s.era, "fip": s.fip, "whip": s.whip, "war": s.war, "k_pct": s.k_pct}
    else:
        result = await db.execute(
            select(BattingStats).where(
                BattingStats.player_id == player.id,
                BattingStats.season == season,
                BattingStats.split == "overall",
            )
        )
        s = result.scalar_one_or_none()
        if not s:
            return None
        return {
            "avg": s.avg, "obp": s.obp, "slg": s.slg,
            "woba": s.woba, "wrc_plus": s.wrc_plus, "war": s.war,
        }


def _player_summary(p: Player) -> dict:
    return {
        "id": str(p.id),
        "full_name": p.full_name,
        "position": p.position,
        "secondary_positions": p.secondary_positions,
        "bats": p.bats,
        "throws": p.throws,
        "age": p.age,
        "status": p.status,
        "roster_status": p.roster_status,
        "salary": p.salary,
        "contract_years": p.contract_years,
        "service_time": p.service_time,
        "scouting": {
            "hit": p.scout_hit,
            "power": p.scout_power,
            "speed": p.scout_speed,
            "field": p.scout_field,
            "arm": p.scout_arm,
            "fb_velo": p.scout_fb_velo,
            "command": p.scout_command,
            "overall": p.scout_overall,
            "notes": p.scout_notes,
        },
    }
