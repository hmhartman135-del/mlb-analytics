"""
Full Stats Ingestion — Baseball Reference (via PyBaseball)
==========================================================
Uses Baseball Reference through PyBaseball to load complete 2026 stats
for EVERY MLB player who has appeared — not just qualified ones.

No API keys needed. Data includes:
  • All batters: H, 2B, 3B, HR, BB, K, SB, BA, OBP, SLG, OPS
    → wOBA, wRC+, BABIP, ISO calculated automatically
  • All pitchers: IP, ERA, WHIP, K, BB, HR + FIP, K/9, BB/9 calculated
  • Statcast optional: barrel%, hard-hit%, sprint speed (--statcast flag)

Usage (from backend/ with venv active):
    python -m scripts.ingest_stats               # 2026 season
    python -m scripts.ingest_stats --season 2025 # historical
    python -m scripts.ingest_stats --statcast     # also pull Statcast
"""

import asyncio
import argparse
import sys
import warnings
warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import get_settings
from app.core.database import Base
from app.models.team import Team          # must import so SQLAlchemy resolves Player→Team relationship
from app.models.player import Player
from app.models.stats import BattingStats, PitchingStats
from app.services.analytics import calculate_woba, calculate_fip, calculate_wrc_plus, calculate_babip_batting

settings = get_settings()


# ── helpers ───────────────────────────────────────────────────────────────────

def log(msg, indent=0):
    print("  " * indent + msg, flush=True)

def ok(msg, indent=1):
    log(f"✓  {msg}", indent)

def warn(msg, indent=1):
    log(f"⚠  {msg}", indent)

def section(msg):
    print(f"\n{'─'*55}", flush=True)
    print(f"  {msg}", flush=True)
    print(f"{'─'*55}", flush=True)

def _f(v):
    """Safe float — returns None for NaN/Inf."""
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else round(f, 4)
    except (TypeError, ValueError):
        return None

def _i(v):
    """Safe int."""
    try:
        f = float(v)
        return None if np.isnan(f) else int(f)
    except (TypeError, ValueError):
        return None

def _parse_ip(ip_str) -> float:
    """
    Baseball Reference stores IP as true decimal (45.333 = 45 1/3 IP).
    Just cast to float.
    """
    try:
        return round(float(ip_str), 3)
    except (TypeError, ValueError):
        return 0.0


# ── player map ────────────────────────────────────────────────────────────────

async def build_id_map(session_factory) -> dict[int, str]:
    """Return {mlb_id -> db_uuid_str} for all active players."""
    async with session_factory() as session:
        result = await session.execute(
            select(Player.id, Player.mlb_id).where(
                Player.status == "active",
                Player.mlb_id.isnot(None),
            )
        )
        return {row[1]: str(row[0]) for row in result.all()}


# ── Baseball Reference batting ────────────────────────────────────────────────

async def ingest_bref_batting(season, id_map, session_factory, dry_run) -> int:
    import pybaseball
    pybaseball.cache.enable()

    section(f"Baseball Reference — Batting {season}")
    log("Fetching all batters (every player who appeared)…")

    try:
        df = pybaseball.batting_stats_bref(season)
    except Exception as e:
        warn(f"Fetch failed: {e}")
        return 0

    # Filter to MLB level only (Lev contains "Maj")
    df = df[df["Lev"].str.contains("Maj", na=False)].copy()
    log(f"  {len(df)} MLB batter rows received")

    saved = skipped = 0
    for _, row in df.iterrows():
        mlb_id = _i(row.get("mlbID"))
        db_id  = id_map.get(mlb_id)
        if not db_id:
            skipped += 1
            continue

        ab  = _i(row.get("AB")) or 0
        h   = _i(row.get("H"))  or 0
        d   = _i(row.get("2B")) or 0
        t   = _i(row.get("3B")) or 0
        hr  = _i(row.get("HR")) or 0
        bb  = _i(row.get("BB")) or 0
        hbp = _i(row.get("HBP")) or 0
        sf  = _i(row.get("SF")) or 0
        sh  = _i(row.get("SH")) or 0
        k   = _i(row.get("SO")) or 0
        sb  = _i(row.get("SB")) or 0
        cs  = _i(row.get("CS")) or 0
        rbi = _i(row.get("RBI")) or 0
        r   = _i(row.get("R"))  or 0
        g   = _i(row.get("G"))  or 0
        pa  = _i(row.get("PA")) or (ab + bb + hbp + sf + sh)

        avg = _f(row.get("BA"))
        obp = _f(row.get("OBP"))
        slg = _f(row.get("SLG"))
        ops = _f(row.get("OPS"))

        raw = {
            "hits": h, "doubles": d, "triples": t, "home_runs": hr,
            "walks": bb, "hit_by_pitch": hbp, "sacrifice_flies": sf,
            "at_bats": ab, "strikeouts": k,
        }
        woba     = calculate_woba(raw) if ab > 0 else None
        wrc_plus = calculate_wrc_plus(woba) if woba else None
        babip    = calculate_babip_batting(raw) if ab > 0 else None
        iso      = round(slg - avg, 4) if slg and avg else None

        stat_data = {
            "player_id": db_id,
            "season": season,
            "split": "overall",
            "games": g,
            "plate_appearances": pa,
            "at_bats": ab,
            "hits": h,
            "doubles": d,
            "triples": t,
            "home_runs": hr,
            "rbi": rbi,
            "runs": r,
            "walks": bb,
            "strikeouts": k,
            "stolen_bases": sb,
            "caught_stealing": cs,
            "hit_by_pitch": hbp,
            "sacrifice_flies": sf,
            "avg": avg,
            "obp": obp,
            "slg": slg,
            "ops": ops,
            "woba": woba,
            "wrc_plus": wrc_plus,
            "babip": babip,
            "iso": iso,
        }

        if dry_run:
            saved += 1
            continue

        try:
            async with session_factory() as session:
                stmt = pg_insert(BattingStats).values(**stat_data).on_conflict_do_update(
                    index_elements=["player_id", "season", "split"],
                    set_={k: v for k, v in stat_data.items()
                          if k not in ("player_id", "season", "split")},
                )
                await session.execute(stmt)
                await session.commit()
            saved += 1
        except Exception as exc:
            warn(f"DB error (mlbID={mlb_id}): {exc}")

    ok(f"{saved} batting rows saved  |  {skipped} players not in DB (minor-leaguers, etc.)")
    return saved


# ── Baseball Reference pitching ───────────────────────────────────────────────

async def ingest_bref_pitching(season, id_map, session_factory, dry_run) -> int:
    import pybaseball
    pybaseball.cache.enable()

    section(f"Baseball Reference — Pitching {season}")
    log("Fetching all pitchers (every pitcher who appeared)…")

    try:
        df = pybaseball.pitching_stats_bref(season)
    except Exception as e:
        warn(f"Fetch failed: {e}")
        return 0

    df = df[df["Lev"].str.contains("Maj", na=False)].copy()
    log(f"  {len(df)} MLB pitcher rows received")

    saved = skipped = 0
    for _, row in df.iterrows():
        mlb_id = _i(row.get("mlbID"))
        db_id  = id_map.get(mlb_id)
        if not db_id:
            skipped += 1
            continue

        ip  = _parse_ip(row.get("IP"))
        g   = _i(row.get("G"))  or 0
        gs  = _i(row.get("GS")) or 0
        w   = _i(row.get("W"))  or 0
        l   = _i(row.get("L"))  or 0
        sv  = _i(row.get("SV")) or 0
        h   = _i(row.get("H"))  or 0
        r   = _i(row.get("R"))  or 0
        er  = _i(row.get("ER")) or 0
        bb  = _i(row.get("BB")) or 0
        k   = _i(row.get("SO")) or 0
        hr  = _i(row.get("HR")) or 0
        hbp = _i(row.get("HBP")) or 0
        bf  = _i(row.get("BF")) or 0

        era  = _f(row.get("ERA"))
        whip = _f(row.get("WHIP"))
        babip_p = _f(row.get("BAbip"))

        fip_raw = {"innings_pitched": ip, "home_runs_allowed": hr,
                   "walks": bb, "strikeouts": k, "hits_allowed": h}
        fip  = calculate_fip(fip_raw) if ip > 0 else None

        k9   = round(k  * 9 / ip, 2) if ip > 0 else None
        bb9  = round(bb * 9 / ip, 2) if ip > 0 else None
        hr9  = round(hr * 9 / ip, 2) if ip > 0 else None
        kpct = round(k  / bf, 3) if bf > 0 else None
        bbpct= round(bb / bf, 3) if bf > 0 else None

        stat_data = {
            "player_id": db_id,
            "season": season,
            "split": "overall",
            "games": g,
            "games_started": gs,
            "wins": w,
            "losses": l,
            "saves": sv,
            "innings_pitched": ip,
            "hits_allowed": h,
            "runs_allowed": r,
            "earned_runs": er,
            "walks": bb,
            "strikeouts": k,
            "home_runs_allowed": hr,
            "era": era,
            "whip": whip,
            "fip": fip,
            "k_per_9": k9,
            "bb_per_9": bb9,
            "hr_per_9": hr9,
            "k_pct": kpct,
            "bb_pct": bbpct,
        }

        if dry_run:
            saved += 1
            continue

        try:
            async with session_factory() as session:
                stmt = pg_insert(PitchingStats).values(**stat_data).on_conflict_do_update(
                    index_elements=["player_id", "season", "split"],
                    set_={k: v for k, v in stat_data.items()
                          if k not in ("player_id", "season", "split")},
                )
                await session.execute(stmt)
                await session.commit()
            saved += 1
        except Exception as exc:
            warn(f"DB error (mlbID={mlb_id}): {exc}")

    ok(f"{saved} pitching rows saved  |  {skipped} players not in DB")
    return saved


# ── Baseball Savant Statcast ──────────────────────────────────────────────────

async def ingest_statcast(season, id_map, session_factory, dry_run) -> int:
    import pybaseball
    pybaseball.cache.enable()

    section(f"Baseball Savant Statcast — {season}")
    saved = 0

    # ── Sprint speed ──────────────────────────────────────────────────────
    log("Fetching sprint speed…")
    try:
        speed_df = pybaseball.statcast_sprint_speed(season)
        log(f"  {len(speed_df)} sprint speed entries")
        for _, row in speed_df.iterrows():
            mlb_id = _i(row.get("player_id"))
            db_id  = id_map.get(mlb_id)
            if not db_id:
                continue
            sprint = _f(row.get("sprint_speed") or row.get("hp_to_1b"))
            if sprint is None or dry_run:
                continue
            try:
                async with session_factory() as session:
                    s = (await session.execute(
                        select(BattingStats).where(
                            BattingStats.player_id == db_id,
                            BattingStats.season == season,
                            BattingStats.split == "overall",
                        )
                    )).scalar_one_or_none()
                    if s:
                        s.sprint_speed = sprint
                        await session.commit()
                        saved += 1
            except Exception:
                pass
        ok(f"Sprint speed: {saved} players updated")
    except Exception as e:
        warn(f"Sprint speed unavailable: {e}")

    # ── Barrel % and hard-hit % ───────────────────────────────────────────
    log("Fetching expected stats (barrel%, hard-hit%)…")
    try:
        xs_df = pybaseball.statcast_batter_expected_stats(season)
        log(f"  {len(xs_df)} expected-stats entries")
        xs_saved = 0
        for _, row in xs_df.iterrows():
            mlb_id = _i(row.get("player_id"))
            db_id  = id_map.get(mlb_id)
            if not db_id:
                continue
            barrel   = _f(row.get("barrel_batted_rate"))
            hard_hit = _f(row.get("hard_hit_percent"))
            if dry_run:
                continue
            try:
                async with session_factory() as session:
                    s = (await session.execute(
                        select(BattingStats).where(
                            BattingStats.player_id == db_id,
                            BattingStats.season == season,
                            BattingStats.split == "overall",
                        )
                    )).scalar_one_or_none()
                    if s:
                        if barrel   is not None: s.barrel_pct   = barrel
                        if hard_hit is not None: s.hard_hit_pct = hard_hit
                        await session.commit()
                        xs_saved += 1
            except Exception:
                pass
        saved += xs_saved
        ok(f"Barrel/hard-hit: {xs_saved} players updated")
    except Exception as e:
        warn(f"Expected stats unavailable: {e}")

    return saved


# ── entry point ───────────────────────────────────────────────────────────────

async def run_all(season, include_statcast, dry_run):
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print(f"\n  Stats Ingestion — {season}  (Baseball Reference via PyBaseball)")
    print(f"  Dry run : {dry_run}\n")

    log("Building player ID map…")
    id_map = await build_id_map(session_factory)
    log(f"  {len(id_map)} active MLB players mapped by MLB ID\n")

    bat = await ingest_bref_batting(season, id_map, session_factory, dry_run)
    pit = await ingest_bref_pitching(season, id_map, session_factory, dry_run)

    sc = 0
    if include_statcast:
        sc = await ingest_statcast(season, id_map, session_factory, dry_run)

    section("Done")
    log(f"Batting stat lines  : {bat}")
    log(f"Pitching stat lines : {pit}")
    if include_statcast:
        log(f"Statcast updates    : {sc}")
    if dry_run:
        log("Dry run — nothing written to database.")

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Load complete MLB stats from Baseball Reference (free, no key required)"
    )
    parser.add_argument("--season", type=int, default=2026,
                        help="Season year (default: 2026)")
    parser.add_argument("--statcast", action="store_true",
                        help="Also pull Statcast sprint speed, barrel pct, hard-hit pct from Baseball Savant")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to the database")
    args = parser.parse_args()

    asyncio.run(run_all(
        season=args.season,
        include_statcast=args.statcast,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
