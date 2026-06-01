"""
compute_prospect_ranks.py
─────────────────────────
Scores every minor leaguer and assigns:
  - prospect_rank       : overall top-100 across all orgs
  - org_prospect_rank   : top-30 within each MLB org
  - parent_org_mlb_id   : MLB parent org mlb_id
  - parent_org_abbr     : MLB parent org abbreviation

Scoring formula (0-100 scale):
  Age factor   : younger = higher multiplier
  Performance  : wOBA (batters) / FIP (pitchers) from most recent stats
  WAR bonus    : up to +20
  Draft rank   : MLB Pipeline pre-draft rank bonus (up to +20)
  Scout overall: 20-80 grade bonus (up to +20)

Run from backend/:
    .venv/bin/python3 -m scripts.compute_prospect_ranks
"""

import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, update

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics")

from app.models.stats import BattingStats, PitchingStats  # noqa
from app.models.player import Player                       # noqa
from app.models.team import Team                           # noqa


# ── Scoring ───────────────────────────────────────────────────────────────────

def _age_multiplier(age: int | None) -> float:
    if not age:
        return 1.0
    if age <= 19: return 3.0
    if age <= 21: return 2.5
    if age <= 23: return 2.0
    if age <= 25: return 1.5
    if age <= 27: return 1.0
    return 0.6


def _batting_score(s) -> float:
    if not s:
        return 0.0
    score = 0.0
    # wOBA: league avg ~.320, elite .420
    if s.woba:
        score += max(0.0, (float(s.woba) - 0.200) / 0.220 * 40)
    elif s.ops:
        score += max(0.0, (float(s.ops) - 0.550) / 0.450 * 30)
    elif s.avg:
        score += max(0.0, (float(s.avg) - 0.200) / 0.150 * 20)
    # WAR bonus
    if s.war:
        score += min(20.0, max(0.0, float(s.war) * 5))
    # wRC+
    if s.wrc_plus:
        score += max(0.0, (float(s.wrc_plus) - 80) / 80 * 10)
    return min(score, 70.0)


def _pitching_score(s) -> float:
    if not s:
        return 0.0
    score = 0.0
    # FIP: league avg ~4.00, elite 2.00
    if s.fip:
        score += max(0.0, (5.5 - float(s.fip)) / 3.5 * 40)
    elif s.era:
        score += max(0.0, (6.0 - float(s.era)) / 4.0 * 30)
    # WAR bonus
    if s.war:
        score += min(20.0, max(0.0, float(s.war) * 5))
    # K bonus
    if s.k_pct:
        score += max(0.0, (float(s.k_pct) - 0.15) / 0.20 * 10)
    return min(score, 70.0)


def _tools_bonus(player: Player) -> float:
    bonus = 0.0
    if player.scout_overall:
        bonus += max(0.0, (player.scout_overall - 30) / 50 * 20)
    if player.draft_rank:
        bonus += max(0.0, (250 - player.draft_rank) / 250 * 20)
    return min(bonus, 30.0)


def _prospect_score(player: Player, bat_stat, pit_stat) -> float:
    is_pitcher = player.position in ("SP", "RP")
    perf = _pitching_score(pit_stat) if is_pitcher else _batting_score(bat_stat)
    tools = _tools_bonus(player)
    age_mult = _age_multiplier(player.age)
    raw = (perf + tools) * age_mult
    return round(raw, 2)


# ── Main ──────────────────────────────────────────────────────────────────────

async def run():
    engine = create_async_engine(DATABASE_URL, echo=False)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with S() as session:
        # ── Step 1: Build team → parent org mapping ───────────────────────────
        print("Building org map…")
        team_rows = await session.execute(select(Team))
        teams = team_rows.scalars().all()

        # team.id (UUID) → (affiliate_mlb_id, abbreviation)
        team_to_org: dict = {}
        org_mlb_to_abbr: dict = {}

        for t in teams:
            if t.level == "MLB":
                org_mlb_to_abbr[t.mlb_id] = t.abbreviation
            elif t.affiliate_mlb_id:
                team_to_org[t.id] = t.affiliate_mlb_id

        print(f"  {len(team_to_org)} MiLB teams → {len(set(team_to_org.values()))} orgs")

        # ── Step 2: Load all minor leaguers ───────────────────────────────────
        print("Loading minor leaguers…")
        player_rows = await session.execute(
            select(Player).where(Player.status == "minors")
        )
        players = player_rows.scalars().all()
        print(f"  {len(players)} players")

        # ── Step 3: Batch load stats ──────────────────────────────────────────
        print("Loading stats…")
        hitter_ids = [p.id for p in players if p.position not in ("SP", "RP")]
        pitcher_ids = [p.id for p in players if p.position in ("SP", "RP")]

        bat_map: dict = {}
        for chunk in [hitter_ids[i:i+500] for i in range(0, len(hitter_ids), 500)]:
            rows = await session.execute(
                select(BattingStats).where(
                    BattingStats.player_id.in_(chunk),
                    BattingStats.split == "overall",
                ).order_by(BattingStats.season.desc())
            )
            for s in rows.scalars().all():
                if s.player_id not in bat_map:
                    bat_map[s.player_id] = s

        pit_map: dict = {}
        for chunk in [pitcher_ids[i:i+500] for i in range(0, len(pitcher_ids), 500)]:
            rows = await session.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id.in_(chunk),
                    PitchingStats.split == "overall",
                ).order_by(PitchingStats.season.desc())
            )
            for s in rows.scalars().all():
                if s.player_id not in pit_map:
                    pit_map[s.player_id] = s

        print(f"  {len(bat_map)} batting stat rows | {len(pit_map)} pitching stat rows")

        # ── Step 4: Score every player ────────────────────────────────────────
        print("Scoring players…")
        scored: list[tuple[float, Player]] = []

        for p in players:
            score = _prospect_score(p, bat_map.get(p.id), pit_map.get(p.id))
            org_mlb_id = team_to_org.get(p.team_id)
            p.parent_org_mlb_id = org_mlb_id
            p.parent_org_abbr = org_mlb_to_abbr.get(org_mlb_id) if org_mlb_id else None
            scored.append((score, p))

        # ── Step 5: Top-100 overall ───────────────────────────────────────────
        sorted_all = sorted(scored, key=lambda x: x[0], reverse=True)

        # Clear old ranks
        for _, p in scored:
            p.prospect_rank = None
            p.org_prospect_rank = None

        for rank, (score, p) in enumerate(sorted_all[:100], start=1):
            p.prospect_rank = rank

        # ── Step 6: Top-30 per org ────────────────────────────────────────────
        org_buckets: dict[int, list] = {}
        for score, p in scored:
            if p.parent_org_mlb_id:
                org_buckets.setdefault(p.parent_org_mlb_id, []).append((score, p))

        for org_id, players_in_org in org_buckets.items():
            sorted_org = sorted(players_in_org, key=lambda x: x[0], reverse=True)
            for rank, (score, p) in enumerate(sorted_org[:30], start=1):
                p.org_prospect_rank = rank

        await session.commit()
        print("Saved ranks.")

        # ── Summary ───────────────────────────────────────────────────────────
        print("\n── Overall Top 20 Prospects ──────────────────────────────")
        top20 = [(s, p) for s, p in sorted_all[:20]]
        for rank, (score, p) in enumerate(top20, 1):
            org = p.parent_org_abbr or "?"
            print(f"  #{rank:3d}  {p.full_name:25s}  {p.position:3s}  Age {p.age or '?':2}  "
                  f"{org:5s}  {p.minor_league_level or '?':6s}  score={score:.1f}")

        print("\n── NYY Top 10 ───────────────────────────────────────────")
        nyy_id = next((mid for mid, abbr in org_mlb_to_abbr.items() if abbr == "NYY"), None)
        if nyy_id:
            nyy = sorted(org_buckets.get(nyy_id, []), key=lambda x: x[0], reverse=True)[:10]
            for rank, (score, p) in enumerate(nyy, 1):
                print(f"  #{rank:2d}  {p.full_name:25s}  {p.position:3s}  Age {p.age or '?':2}  "
                      f"{p.minor_league_level or '?':6s}  score={score:.1f}")

        # Count orgs with top-30
        orgs_with_30 = sum(1 for v in org_buckets.values() if len(v) >= 30)
        print(f"\n  Orgs with 30+ prospects: {orgs_with_30}/30")

    await engine.dispose()
    print("\nDone ✓")


if __name__ == "__main__":
    asyncio.run(run())
