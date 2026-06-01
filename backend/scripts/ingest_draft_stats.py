"""
ingest_draft_stats.py
─────────────────────
Fetches amateur stats for every draft prospect in the DB.

Phase 1 — MLB Stats API (college / JUCO / some HS & INTL)
  Batches up to 100 players per request using the hydrate endpoint:
    GET /people?personIds=…&hydrate=stats(group=[hitting,pitching],
                                          type=[yearByYear],
                                          sportId=22,586,6005)
  Stores one BattingStats / PitchingStats row per player per season
  using split="pre_draft" so future MLB rows never collide.

Phase 2 — MaxPreps (HS players with no API stats)
  Playwright search+scrape for players with school_class='HS SR'
  that had zero splits in Phase 1.  Only fetches most-recent (senior)
  season stats.

Run from backend/:
    .venv/bin/python3 -m scripts.ingest_draft_stats
"""

import asyncio
import os
import re
from datetime import date

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics"
)

from app.models.player import Player  # noqa
from app.models.stats import BattingStats, PitchingStats  # noqa
from app.models.team import Team  # noqa

STATS_BASE = "https://statsapi.mlb.com/api/v1"
SPLIT = "pre_draft"          # unique tag for all amateur stats rows
BATCH_SIZE = 100             # players per API request
MAX_CONCURRENCY = 8          # simultaneous HTTP requests

# ── Field mappings ──────────────────────────────────────────────────────────

def _f(s: dict, key: str) -> float | None:
    v = s.get(key)
    if v is None:
        return None
    sv = str(v).strip()
    if sv in ("", ".---", "-.--", "---", "-.---"):
        return None
    try:
        return float(sv)
    except (ValueError, TypeError):
        return None

def _i(s: dict, key: str) -> int:
    v = s.get(key)
    return int(v) if v is not None else 0

def _ip(raw) -> float:
    """Convert MLB innings-pitched string '7.2' → 7.667 (7 full + 2 outs)."""
    if raw is None:
        return 0.0
    try:
        parts = str(raw).split(".")
        full = int(parts[0])
        outs = int(parts[1]) if len(parts) > 1 else 0
        return round(full + outs / 3, 3)
    except (ValueError, IndexError):
        return float(raw) if raw else 0.0


def batting_from_stat(s: dict) -> dict:
    games = _i(s, "gamesPlayed")
    pa    = _i(s, "plateAppearances")
    ab    = _i(s, "atBats")
    hits  = _i(s, "hits")
    hr    = _i(s, "homeRuns")
    bb    = _i(s, "baseOnBalls")
    k     = _i(s, "strikeOuts")
    return dict(
        games=games,
        plate_appearances=pa,
        at_bats=ab,
        hits=hits,
        doubles=_i(s, "doubles"),
        triples=_i(s, "triples"),
        home_runs=hr,
        rbi=_i(s, "rbi"),
        runs=_i(s, "runs"),
        walks=bb,
        strikeouts=k,
        stolen_bases=_i(s, "stolenBases"),
        caught_stealing=_i(s, "caughtStealing"),
        hit_by_pitch=_i(s, "hitByPitch"),
        sacrifice_flies=_i(s, "sacFlies"),
        avg=_f(s, "avg"),
        obp=_f(s, "obp"),
        slg=_f(s, "slg"),
        ops=_f(s, "ops"),
        babip=_f(s, "babip"),
    )


def pitching_from_stat(s: dict) -> dict:
    ip = _ip(s.get("inningsPitched"))
    return dict(
        games=_i(s, "gamesPlayed"),
        games_started=_i(s, "gamesStarted"),
        wins=_i(s, "wins"),
        losses=_i(s, "losses"),
        saves=_i(s, "saves"),
        innings_pitched=ip,
        hits_allowed=_i(s, "hits"),
        runs_allowed=_i(s, "runs"),
        earned_runs=_i(s, "earnedRuns"),
        walks=_i(s, "baseOnBalls"),
        strikeouts=_i(s, "strikeOuts"),
        home_runs_allowed=_i(s, "homeRuns"),
        era=_f(s, "era"),
        whip=_f(s, "whip"),
        k_per_9=_f(s, "strikeOutsPer9Inn"),
        bb_per_9=_f(s, "walksPer9Inn"),
        hr_per_9=_f(s, "homeRunsPer9"),
        k_pct=_f(s, "strikeoutPercentage"),
        bb_pct=_f(s, "walkPercentage"),
    )


# ── Season aggregation ───────────────────────────────────────────────────────

def best_splits_for_season(splits: list[dict]) -> dict | None:
    """
    From all splits in one season, return the aggregate row (team absent)
    or the single team row if only one team.
    """
    if not splits:
        return None
    agg = [sp for sp in splits if not (sp.get("team") or {}).get("name")]
    if agg:
        return agg[-1]
    # One team only — that IS the season total
    if len(splits) == 1:
        return splits[0]
    # Multiple teams, no provided aggregate — sum counting stats
    combined = dict(splits[0]["stat"])
    for sp in splits[1:]:
        s2 = sp["stat"]
        for k in ("gamesPlayed", "plateAppearances", "atBats", "hits", "doubles",
                  "triples", "homeRuns", "rbi", "runs", "baseOnBalls", "strikeOuts",
                  "stolenBases", "caughtStealing", "hitByPitch", "sacFlies",
                  "wins", "losses", "saves", "earnedRuns",
                  "strikeOutsAllowed", "inningsPitchedAsDecimal"):
            combined[k] = combined.get(k, 0) + (s2.get(k) or 0)
    # Recalculate rate stats from counting stats
    ab = combined.get("atBats") or 0
    h  = combined.get("hits")   or 0
    bb = combined.get("baseOnBalls") or 0
    hbp= combined.get("hitByPitch")  or 0
    sf = combined.get("sacFlies")    or 0
    tb = (h + combined.get("doubles",0) + 2*combined.get("triples",0) + 3*combined.get("homeRuns",0))
    pa = ab + bb + hbp + sf
    combined["avg"] = f"{h/ab:.3f}" if ab else None
    combined["obp"] = f"{(h+bb+hbp)/(ab+bb+hbp+sf):.3f}" if (ab+bb+hbp+sf) else None
    combined["slg"] = f"{tb/ab:.3f}" if ab else None
    ops_v = (_f(combined, "obp") or 0) + (_f(combined, "slg") or 0)
    combined["ops"] = f"{ops_v:.3f}" if ops_v else None
    # Build a fake split dict
    fake = dict(splits[0])
    fake["stat"] = combined
    fake.pop("team", None)
    return fake


# ── DB upsert ────────────────────────────────────────────────────────────────

async def upsert_batting(session: AsyncSession, player_id, season: int, data: dict):
    stmt = pg_insert(BattingStats).values(
        player_id=player_id,
        season=season,
        split=SPLIT,
        **data,
    ).on_conflict_do_update(
        index_elements=["player_id", "season", "split"],
        set_={k: data[k] for k in data if data[k] is not None},
    )
    await session.execute(stmt)


async def upsert_pitching(session: AsyncSession, player_id, season: int, data: dict):
    stmt = pg_insert(PitchingStats).values(
        player_id=player_id,
        season=season,
        split=SPLIT,
        **data,
    ).on_conflict_do_update(
        index_elements=["player_id", "season", "split"],
        set_={k: data[k] for k in data if data[k] is not None},
    )
    await session.execute(stmt)


# ── Phase 1: MLB Stats API ────────────────────────────────────────────────────

async def process_batch(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker,
    player_rows: list[tuple],  # (uuid, mlb_id, position)
    sem: asyncio.Semaphore,
) -> tuple[int, int]:
    """Fetch yearByYear for a batch and upsert. Returns (batting_rows, pitching_rows)."""
    id_map = {r[1]: r[0] for r in player_rows}   # mlb_id → uuid
    pos_map = {r[1]: (r[2] or "") for r in player_rows}

    async with sem:
        try:
            resp = await client.get(
                f"{STATS_BASE}/people",
                params={
                    "personIds": ",".join(str(r[1]) for r in player_rows),
                    "hydrate": "stats(group=[hitting,pitching],type=[yearByYear],sportId=22,586,6005)",
                },
                timeout=30,
            )
            resp.raise_for_status()
            people = resp.json().get("people", [])
        except Exception as e:
            print(f"  Batch fetch error ({type(e).__name__}): {e}")
            return 0, 0

    bat_rows = pit_rows = 0

    async with session_factory() as session:
        for person in people:
            mlb_id = person.get("id")
            player_uuid = id_map.get(mlb_id)
            if not player_uuid:
                continue
            position = pos_map.get(mlb_id, "")

            for stat_block in person.get("stats", []):
                grp = stat_block["group"]["displayName"]  # "hitting" or "pitching"
                splits = stat_block.get("splits", [])

                # Group by season
                by_season: dict[str, list] = {}
                for sp in splits:
                    sea = sp.get("season", "0")
                    by_season.setdefault(sea, []).append(sp)

                for sea, season_splits in by_season.items():
                    best = best_splits_for_season(season_splits)
                    if not best:
                        continue
                    stat = best["stat"]
                    season_int = int(sea)

                    if grp == "hitting":
                        await upsert_batting(session, player_uuid, season_int, batting_from_stat(stat))
                        bat_rows += 1
                    elif grp == "pitching":
                        await upsert_pitching(session, player_uuid, season_int, pitching_from_stat(stat))
                        pit_rows += 1

        await session.commit()
    return bat_rows, pit_rows


async def phase1_mlb_api(S: async_sessionmaker) -> set[int]:
    """Run Phase 1. Returns set of mlb_ids that received at least one stats row."""
    print("=== Phase 1: MLB Stats API (yearByYear) ===")

    async with S() as session:
        r = await session.execute(
            select(Player.id, Player.mlb_id, Player.position)
            .where(Player.status == "draft_prospect", Player.mlb_id.isnot(None))
        )
        rows = r.all()
    print(f"  Draft prospects with mlb_id: {len(rows):,}")

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    total_bat = total_pit = 0
    ids_with_stats: set[int] = set()

    async with httpx.AsyncClient() as client:
        batches = [rows[i : i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
        tasks = [process_batch(client, S, batch, sem) for batch in batches]
        results = await asyncio.gather(*tasks)

    for bat, pit in results:
        total_bat += bat
        total_pit += pit

    print(f"  Batting rows written : {total_bat:,}")
    print(f"  Pitching rows written: {total_pit:,}")

    # Identify which mlb_ids actually got stats
    async with S() as session:
        r2 = await session.execute(
            select(Player.mlb_id)
            .join(BattingStats, BattingStats.player_id == Player.id)
            .where(Player.status == "draft_prospect", BattingStats.split == SPLIT)
        )
        ids_with_stats.update(row[0] for row in r2.all() if row[0])
        r3 = await session.execute(
            select(Player.mlb_id)
            .join(PitchingStats, PitchingStats.player_id == Player.id)
            .where(Player.status == "draft_prospect", PitchingStats.split == SPLIT)
        )
        ids_with_stats.update(row[0] for row in r3.all() if row[0])
    print(f"  Players with at least one stats row: {len(ids_with_stats):,}")
    return ids_with_stats


# ── Phase 2: MaxPreps (HS players) ───────────────────────────────────────────

async def dismiss_consent(page):
    for sel in ["#onetrust-accept-btn-handler", 'button:has-text("Accept")',
                'button:has-text("OK")', '[class*="consent"] button']:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2_000):
                await btn.click()
                await page.wait_for_timeout(600)
                break
        except Exception:
            pass


async def scrape_maxpreps_player(page, name: str, school: str) -> dict | None:
    """
    Search MaxPreps and return most recent season stats for the player.
    MaxPreps renders stats in two <table> elements on the career stats page.
    """
    first = name.split()[0].lower()
    last  = name.split()[-1].lower()
    search_url = f"https://www.maxpreps.com/search/?q={first}+{last}&sport=baseball"

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)
        await dismiss_consent(page)

        # All links on search results page
        all_links = await page.eval_on_selector_all(
            "a",
            "els => els.map(el => ({href: el.href || '', text: el.innerText.trim()}))",
        )

        school_words = set((school or "").lower().split())
        target_href = None

        for link in all_links:
            href = link.get("href", "")
            text = link.get("text", "").lower()
            # MaxPreps athlete URL pattern: /{state}/{city}/{school-slug}/athletes/{name-slug}/
            if "/athletes/" not in href:
                continue
            name_match = last in href.lower() or last in text
            if not name_match:
                continue
            # Prefer match with school keywords
            school_match = any(w in href.lower() or w in text for w in school_words if len(w) > 3)
            if school_match or not target_href:
                target_href = href
                if school_match:
                    break

        if not target_href:
            return None

        # Build stats URL: replace trailing slash / query with /baseball/stats/
        base = re.sub(r'\?.*$', '', target_href).rstrip("/")
        # Ensure it ends at the player slug, not a sub-page
        base = re.sub(r'/(baseball|football|volleyball)(/.*)$', '', base)
        stats_url = f"{base}/baseball/stats/"
        # Preserve careerid if present
        if "careerid=" in target_href:
            cid = re.search(r'careerid=([^&]+)', target_href)
            if cid:
                stats_url += f"?careerid={cid.group(1)}"

        await page.goto(stats_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_500)

        return await _parse_maxpreps_tables(page)

    except Exception as e:
        print(f"    MaxPreps error for {name}: {type(e).__name__}: {str(e)[:60]}")
        return None


async def _parse_maxpreps_tables(page) -> dict | None:
    """
    MaxPreps career stats page has two <table> elements:
      Table 1 headers: GP  Avg  PA  AB  R  H  RBI  2B  3B  HR  GS
      Table 2 headers: GP  SF  SH/B  BB  K  HBP  ROE  FC  LOB  OBP  SLG  OPS

    The "Varsity Total" row has career totals; we want the LAST season row
    that corresponds to the player's senior year.
    """
    tables = await page.query_selector_all("table")
    if not tables:
        return None

    result: dict = {}

    for t in tables[:4]:
        raw = (await t.inner_text()).strip()
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]

        # Find the header row
        header_line = None
        data_line   = None
        for i, ln in enumerate(lines):
            cols = [c.strip() for c in ln.split("\t")]
            if "Avg" in cols or "ERA" in cols or "GP" in cols:
                header_line = cols
                # Next non-empty line with numbers is the first data row
                for j in range(i + 1, len(lines)):
                    candidate = [c.strip() for c in lines[j].split("\t")]
                    if any(re.match(r'^[\d.]+$', c) for c in candidate):
                        data_line = candidate
                        # Keep scanning for "Varsity Total" as the authoritative row
                    if "Varsity Total" in lines[j] or "Career Total" in lines[j]:
                        vtcols = [c.strip() for c in lines[j].split("\t")]
                        nums = [c for c in vtcols if re.match(r'^[\d.]+$', c)]
                        if nums:
                            data_line = vtcols
                        break
                break

        if not header_line or not data_line:
            continue

        # Align data columns to header by finding first numeric column index
        # Headers like ['GD', 'Team', 'Year', '', 'GP', 'Avg', ...] have prefix columns
        # Data like ['Sr.', 'Var', '', '25-26', '', '28', '.532', ...]
        # Align by stripping empty tokens and mapping positionally
        h_clean = [c for c in header_line if c]
        d_clean = [c for c in data_line   if c]

        # Find GP in header and map remaining values
        def get(hdr_key):
            if hdr_key in h_clean:
                idx = h_clean.index(hdr_key)
                if idx < len(d_clean):
                    v = d_clean[idx]
                    try:
                        return float(v)
                    except ValueError:
                        pass
            return None

        if "Avg" in h_clean:
            # Table 1: batting main
            gp  = get("GP")
            avg = get("Avg")
            pa  = get("PA")
            ab  = get("AB")
            h   = get("H")
            r   = get("R")
            rbi = get("RBI")
            d2  = get("2B")
            d3  = get("3B")
            hr  = get("HR")
            if gp is not None:
                result.update(games=int(gp) if gp else 0,
                               avg=avg, plate_appearances=int(pa) if pa else None,
                               at_bats=int(ab) if ab else None, hits=int(h) if h else None,
                               runs=int(r) if r else None, rbi=int(rbi) if rbi else None,
                               doubles=int(d2) if d2 else None,
                               triples=int(d3) if d3 else None,
                               home_runs=int(hr) if hr else None)
        elif "OBP" in h_clean:
            # Table 2: batting secondary
            bb  = get("BB")
            k   = get("K")
            hbp = get("HBP")
            obp = get("OBP")
            slg = get("SLG")
            ops = get("OPS")
            sf  = get("SF")
            result.update(walks=int(bb) if bb else None,
                           strikeouts=int(k) if k else None,
                           hit_by_pitch=int(hbp) if hbp else None,
                           sacrifice_flies=int(sf) if sf else None,
                           obp=obp, slg=slg, ops=ops)
            if obp and slg:
                result["ops"] = round(obp + slg, 3)
        elif "ERA" in h_clean:
            # Pitching table
            result.update(
                era=get("ERA"),
                innings_pitched=_ip(get("IP")),
                wins=int(get("W") or 0),
                losses=int(get("L") or 0),
                strikeouts=int(get("K") or 0),
                walks=int(get("BB") or 0),
                whip=get("WHIP"),
            )
            result["_is_pitching"] = True

    return result if result else None


async def phase2_maxpreps(S: async_sessionmaker, ids_with_stats: set[int]):
    """
    Scrape MaxPreps for HS players who got no stats from Phase 1.
    """
    print("\n=== Phase 2: MaxPreps (HS players) ===")

    async with S() as session:
        r = await session.execute(
            select(Player.id, Player.mlb_id, Player.full_name, Player.school, Player.position)
            .where(
                Player.status == "draft_prospect",
                Player.school_class == "HS SR",
            )
        )
        all_hs = r.all()

    # Filter to those WITHOUT stats
    needs_stats = [p for p in all_hs if not p[1] or p[1] not in ids_with_stats]
    print(f"  HS SR players needing stats: {len(needs_stats):,}")

    if not needs_stats:
        print("  All HS players already have stats — skipping.")
        return

    # Limit to top-ranked or those with valid school names for scraping
    candidates = [p for p in needs_stats if p[3]]  # must have school name
    print(f"  Candidates with school info: {len(candidates):,}")

    if not candidates:
        return

    hit = miss = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        )
        # Block heavy assets to speed up
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,mp4}", lambda r: r.abort())
        await ctx.route("**/doubleclick.net/**", lambda r: r.abort())
        await ctx.route("**/googletagmanager.com/**", lambda r: r.abort())

        page = await ctx.new_page()

        for i, (uuid, mlb_id, name, school, pos) in enumerate(candidates):
            if (i + 1) % 20 == 0:
                print(f"  … {i+1}/{len(candidates)} — hit={hit} miss={miss}")

            stats = await scrape_maxpreps_player(page, name, school or "")
            if not stats:
                miss += 1
                continue

            # Determine current / most recent senior year
            season = date.today().year

            # Separate batting vs pitching stats
            bat_data = {k: v for k, v in stats.items()
                        if k not in ("era", "innings_pitched", "strikeouts_p")}
            pit_data = {k: v for k, v in stats.items()
                        if k in ("era", "innings_pitched")}
            if "strikeouts_p" in stats:
                pit_data["strikeouts"] = stats["strikeouts_p"]

            saved = False
            is_pitcher = stats.pop("_is_pitching", False) or pos in ("SP", "RP")
            bat_keys = {"games","plate_appearances","at_bats","hits","doubles","triples",
                        "home_runs","rbi","runs","walks","strikeouts","stolen_bases",
                        "caught_stealing","hit_by_pitch","sacrifice_flies","avg","obp","slg","ops","babip"}
            pit_keys = {"games","games_started","wins","losses","saves","innings_pitched",
                        "hits_allowed","runs_allowed","earned_runs","walks","strikeouts",
                        "home_runs_allowed","era","whip","k_per_9","bb_per_9","hr_per_9"}

            async with S() as db:
                if not is_pitcher and any(k in stats for k in bat_keys):
                    bat_data = {k: v for k, v in stats.items() if k in bat_keys and v is not None}
                    if bat_data:
                        await upsert_batting(db, uuid, season, bat_data)
                        await db.commit()
                        saved = True
                elif is_pitcher and any(k in stats for k in pit_keys):
                    pit_data = {k: v for k, v in stats.items() if k in pit_keys and v is not None}
                    if pit_data:
                        await upsert_pitching(db, uuid, season, pit_data)
                        await db.commit()
                        saved = True
            hit += 1 if saved else 0
            miss += 0 if saved else 1

            await page.wait_for_timeout(800)  # polite delay

        await browser.close()

    print(f"  MaxPreps: scraped={hit} not found={miss}")


# ── Summary ───────────────────────────────────────────────────────────────────

async def print_summary(S: async_sessionmaker):
    from sqlalchemy import text
    async with S() as session:
        r = await session.execute(text(f"SELECT COUNT(DISTINCT player_id) FROM batting_stats WHERE split='{SPLIT}'"))
        bat_players = r.scalar()
        r = await session.execute(text(f"SELECT COUNT(DISTINCT player_id) FROM pitching_stats WHERE split='{SPLIT}'"))
        pit_players = r.scalar()
        r = await session.execute(text(f"SELECT COUNT(*) FROM batting_stats WHERE split='{SPLIT}'"))
        bat_rows = r.scalar()
        r = await session.execute(text(f"SELECT COUNT(*) FROM pitching_stats WHERE split='{SPLIT}'"))
        pit_rows = r.scalar()

        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"  Batting rows  : {bat_rows:,}  ({bat_players:,} unique players)")
        print(f"  Pitching rows : {pit_rows:,}  ({pit_players:,} unique players)")

        r = await session.execute(text(f"""
            SELECT p.full_name, p.position, p.school, p.draft_rank,
                   b.season, b.games, b.avg, b.home_runs, b.strikeouts, b.walks
            FROM players p
            JOIN batting_stats b ON b.player_id = p.id
            WHERE p.draft_rank IS NOT NULL AND b.split='{SPLIT}'
            ORDER BY p.draft_rank, b.season DESC
            LIMIT 15
        """))
        print("\n  Top ranked hitter stats (most recent season):")
        seen = set()
        for row in r.fetchall():
            if row[0] not in seen:
                print(f"    #{row[3]:3d} {row[0]:26s} {row[4]} G={row[5]} AVG={row[6]} HR={row[7]} K={row[8]} BB={row[9]}")
                seen.add(row[0])


# ── Main ──────────────────────────────────────────────────────────────────────

async def run():
    engine = create_async_engine(DATABASE_URL, echo=False)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    ids_with_stats = await phase1_mlb_api(S)
    await phase2_maxpreps(S, ids_with_stats)
    await print_summary(S)

    await engine.dispose()
    print("\nDone ✓")


if __name__ == "__main__":
    asyncio.run(run())
