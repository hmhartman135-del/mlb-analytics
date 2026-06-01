"""
ingest_all_draft_prospects.py
──────────────────────────────
Builds a comprehensive 2026 MLB Draft prospect database:

  Phase 1  — Scrape MLB Pipeline Draft rankings (Playwright)
             URL: mlb.com/milb/prospects/draft
             Captures ranked prospects with name, school, position, mlb_id

  Phase 2  — Fetch ALL eligible players from MLB Stats API
             sportId=22  → college + JUCO  (~5,900 players)
             sportId=586 → high school seniors  (~300 players)
             sportId=6005 → international amateurs  (~700 players)

  Phase 3  — Upsert everything to DB
             • New prospects: status='draft_prospect'
             • Existing players: enrich bio/school fields
             • Pipeline-ranked: set draft_rank

Run from backend/:
    .venv/bin/python3 -m scripts.ingest_all_draft_prospects
"""

import asyncio
import json
import os
import re
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics"
)

from app.models.player import Player  # noqa
from app.models.stats import BattingStats, PitchingStats  # noqa
from app.models.team import Team  # noqa

DRAFT_YEAR = 2026
DATA_DIR = Path(__file__).parent / "pipeline_data"
DATA_DIR.mkdir(exist_ok=True)

STATS_BASE = "https://statsapi.mlb.com/api/v1"

# sport_id → school_class label used when we can't determine year
SPORT_CLASS: dict[int, str] = {
    22: "COLLEGE",
    586: "HS SR",
    6005: "INTL",
}

POS_MAP = {
    "TWP": "SP", "P": "SP", "SP": "SP", "RP": "RP",
    "C": "C", "1B": "1B", "2B": "2B", "3B": "3B",
    "SS": "SS", "LF": "LF", "CF": "CF", "RF": "RF",
    "OF": "CF", "DH": "DH", "IF": "3B", "UTIL": "DH",
    "RHP": "SP", "LHP": "SP",
}


# ── Utilities ──────────────────────────────────────────────────────────────────

def _parse_pos(abbr: str | None) -> str | None:
    if not abbr:
        return None
    return POS_MAP.get(abbr.upper().strip(), abbr[:8])


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _parse_ht(raw: str | None) -> str | None:
    """Normalise height string → '6\' 2"' format or None."""
    if not raw:
        return None
    raw = raw.strip()
    if "'" in raw or '"' in raw:
        return raw
    m = re.match(r'(\d+)-(\d+)', raw)
    if m:
        return f"{m.group(1)}' {m.group(2)}\""
    return raw[:15] if raw else None


# ── Phase 1: Playwright scrape of Pipeline Draft page ─────────────────────────

async def dismiss_consent(page):
    for sel in [
        '#onetrust-accept-btn-handler',
        'button:has-text("OK")',
        'button:has-text("Accept All")',
        'button:has-text("Accept")',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2_000):
                await btn.click()
                await page.wait_for_timeout(800)
                break
        except Exception:
            pass
    await page.evaluate("""
        var el = document.getElementById('onetrust-consent-sdk');
        if (el) el.remove();
    """)


async def extract_rows(page) -> list[dict]:
    rows = await page.query_selector_all('[data-testid="table-row"]')
    results = []
    for row in rows:
        try:
            cells = await row.query_selector_all('[data-testid="table-cell"]')
            if len(cells) < 2:
                continue
            texts = [(await c.inner_text()).strip() for c in cells]

            mlb_id = None
            img = await row.query_selector('img[data-testid="player-headshot"]')
            if img:
                for attr in ("src", "srcset"):
                    val = await img.get_attribute(attr) or ""
                    m = re.search(r'/people/(\d+)/headshot', val)
                    if m:
                        mlb_id = int(m.group(1))
                        break

            def cell(i):
                return texts[i] if i < len(texts) else ""

            rank_raw = re.sub(r'\D', '', cell(0))
            results.append({
                "rank":     int(rank_raw) if rank_raw else None,
                "name":     cell(1),
                "position": cell(2),
                "school":   cell(3),
                "level":    cell(4),   # HS / JR / SR / INTL etc.
                "eta":      cell(5),
                "age":      cell(6),
                "hw":       cell(7),
                "bats":     cell(8),
                "throws":   cell(9),
                "mlb_id":   mlb_id,
            })
        except Exception as e:
            print(f"  Row parse error: {e}")
    return results


async def scrape_pipeline_draft() -> list[dict]:
    """Scrape MLB Pipeline's 2026 Draft rankings page."""
    print("=== Phase 1: Scraping MLB Pipeline Draft page ===")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        async def _route(route):
            url = route.request.url
            if any(x in url for x in (
                "doubleclick.net", "googletagmanager", "chartbeat",
                "flashtalking", "datadoghq", "adtrafficquality",
                "facebook.net", "googlesyndication",
            )):
                await route.abort()
            else:
                await route.continue_()
        await ctx.route("**/*", _route)

        page = await ctx.new_page()

        url = "https://www.mlb.com/milb/prospects/draft"
        print(f"  Loading {url} …")
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(4_000)
        await dismiss_consent(page)
        await page.wait_for_timeout(500)

        # Expand full list
        await page.evaluate("""
            var btn = document.querySelector('[data-testid="load-more-button"]');
            if (btn) btn.click();
        """)
        await page.wait_for_timeout(5_000)

        rows = await extract_rows(page)
        print(f"  Extracted {len(rows)} ranked draft prospects")

        # Save for inspection
        (DATA_DIR / "draft_prospects_scraped.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False)
        )
        await browser.close()

    return rows


# ── Phase 2: MLB Stats API pulls ───────────────────────────────────────────────

async def fetch_sport_players(client: httpx.AsyncClient, sport_id: int) -> list[dict]:
    """Return ALL players registered under a sport for the draft year."""
    print(f"  Fetching sportId={sport_id} players …")
    players: list[dict] = []
    offset = 0
    limit = 600

    while True:
        resp = await client.get(
            f"{STATS_BASE}/sports/{sport_id}/players",
            params={
                "season": DRAFT_YEAR,
                "gameType": "R",
                "limit": limit,
                "offset": offset,
                "fields": (
                    "people,id,fullName,firstName,lastName,"
                    "birthDate,currentAge,birthCity,birthStateProvince,birthCountry,"
                    "height,weight,primaryPosition,batSide,pitchHand,"
                    "draftYear,currentTeam"
                ),
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("people", [])
        players.extend(batch)
        total = data.get("totalSize") or len(batch)
        offset += len(batch)
        if not batch or offset >= total:
            break

    print(f"    → {len(players):,} players (sportId={sport_id})")
    return players


async def fetch_college_team_names(client: httpx.AsyncClient) -> dict[int, str]:
    """Map team_id → team name for college baseball (sportId=22)."""
    resp = await client.get(
        f"{STATS_BASE}/teams",
        params={"sportId": 22, "season": DRAFT_YEAR, "limit": 500},
        timeout=30,
    )
    resp.raise_for_status()
    return {t["id"]: t["name"] for t in resp.json().get("teams", [])}


async def fetch_all_prospect_players() -> dict[int, list[dict]]:
    """Fetch players from all three draft-eligible sports."""
    async with httpx.AsyncClient() as client:
        team_names = await fetch_college_team_names(client)
        print(f"  College teams map: {len(team_names)} entries")

        # Attach resolved team name to each player
        results: dict[int, list[dict]] = {}
        for sport_id in (22, 586, 6005):
            players = await fetch_sport_players(client, sport_id)
            for p in players:
                tid = (p.get("currentTeam") or {}).get("id")
                if tid and tid in team_names:
                    p["_resolved_school"] = team_names[tid]
            results[sport_id] = players

    return results


# ── Phase 3: DB upsert ─────────────────────────────────────────────────────────

def _school_class_from_sport(sport_id: int, birth_year: int | None) -> str:
    """Derive school_class from sport + estimated graduation year."""
    if sport_id == 586:
        return "HS SR"
    if sport_id == 6005:
        return "INTL"
    # College / JUCO: use birth year to estimate year in school
    if birth_year:
        # Players born ~1904-1907 are typically FR/SO/JR/SR in 2026
        class_year = DRAFT_YEAR - birth_year - 18
        if class_year <= 1:
            return "4YR FR"
        elif class_year == 2:
            return "4YR SO"
        elif class_year == 3:
            return "4YR JR"
        else:
            return "4YR SR"
    return "COLLEGE"


async def upsert_pipeline_prospect(session: AsyncSession, entry: dict) -> str:
    mlb_id = entry.get("mlb_id")
    name = entry["name"]
    rank = entry.get("rank")
    if not name:
        return "skipped"

    # Try mlb_id first, then name fallback
    player = None
    if mlb_id:
        r = await session.execute(select(Player).where(Player.mlb_id == mlb_id))
        player = r.scalar_one_or_none()
    if not player:
        r = await session.execute(
            select(Player).where(Player.full_name.ilike(f"%{name}%"))
        )
        player = r.scalars().first()

    hw = entry.get("hw", "")
    parts = hw.split("/") if hw else []
    ht = _parse_ht(parts[0].strip()) if parts else None
    wt_raw = parts[1].strip() if len(parts) > 1 else ""
    wt = int(re.sub(r'\D', '', wt_raw)) if re.sub(r'\D', '', wt_raw) else None

    if player:
        if rank:
            player.draft_rank = rank
        # Always update position from Pipeline — it has better data than the Stats API
        new_pos = _parse_pos(entry.get("position"))
        if new_pos:
            player.position = new_pos
        if entry.get("school") and not player.school:
            player.school = entry["school"][:200]
        if ht and not player.height:
            player.height = ht
        if wt and not player.weight:
            player.weight = wt
        if entry.get("bats") and not player.bats:
            player.bats = entry["bats"][:2]
        if entry.get("throws") and not player.throws:
            player.throws = entry["throws"][:2]
        player.draft_year = DRAFT_YEAR
        player.status = "draft_prospect"
        return "updated"

    # New player from Pipeline ranking
    new = Player(
        mlb_id=mlb_id,
        full_name=name,
        first_name=name.split()[0] if name else "",
        last_name=name.split()[-1] if name else "",
        position=_parse_pos(entry.get("position")),
        school=entry.get("school", "")[:200] if entry.get("school") else None,
        draft_rank=rank,
        draft_year=DRAFT_YEAR,
        height=ht,
        weight=wt,
        bats=(entry.get("bats") or "")[:2] or None,
        throws=(entry.get("throws") or "")[:2] or None,
        status="draft_prospect",
    )
    session.add(new)
    return "inserted"


async def upsert_stats_player(
    session: AsyncSession,
    person: dict,
    sport_id: int,
) -> str:
    mlb_id = person.get("id")
    if not mlb_id:
        return "skipped"

    r = await session.execute(select(Player).where(Player.mlb_id == mlb_id))
    existing = r.scalar_one_or_none()

    # If no mlb_id match, try name — catches Pipeline-inserted players that had no mlb_id
    if not existing:
        full_name = person.get("fullName", "")
        if full_name:
            r2 = await session.execute(
                select(Player).where(
                    Player.full_name.ilike(full_name),
                    Player.mlb_id.is_(None),
                    Player.status == "draft_prospect",
                )
            )
            existing = r2.scalars().first()
            if existing:
                existing.mlb_id = mlb_id  # backfill the mlb_id now that we have it

    school = person.get("_resolved_school") or None
    bd = _parse_date(person.get("birthDate"))
    birth_year = bd.year if bd else None
    school_class = _school_class_from_sport(sport_id, birth_year)

    if existing:
        dirty = False
        updates = {
            "school": school if school and not existing.school else None,
            "height": _parse_ht(person.get("height")) if not existing.height else None,
            "weight": person.get("weight") if not existing.weight else None,
            "birth_date": bd if not existing.birth_date else None,
            "age": person.get("currentAge") if not existing.age else None,
            "birth_city": person.get("birthCity") if not existing.birth_city else None,
            "birth_country": person.get("birthCountry") if not existing.birth_country else None,
            "school_class": school_class if not existing.school_class else None,
        }
        for attr, val in updates.items():
            if val is not None:
                setattr(existing, attr, val)
                dirty = True
        return "updated" if dirty else "skipped"

    pos = (person.get("primaryPosition") or {}).get("abbreviation")
    new = Player(
        mlb_id=mlb_id,
        full_name=person.get("fullName", "Unknown"),
        first_name=person.get("firstName", ""),
        last_name=person.get("lastName", ""),
        birth_date=bd,
        age=person.get("currentAge"),
        position=_parse_pos(pos),
        bats=(person.get("batSide") or {}).get("code"),
        throws=(person.get("pitchHand") or {}).get("code"),
        status="draft_prospect",
        height=_parse_ht(person.get("height")),
        weight=person.get("weight"),
        birth_city=person.get("birthCity"),
        birth_country=person.get("birthCountry", "USA"),
        school=school,
        school_class=school_class,
        draft_year=DRAFT_YEAR,
    )
    session.add(new)
    return "inserted"


# ── Main ───────────────────────────────────────────────────────────────────────

async def run():
    # Phase 1 — Playwright
    pipeline_prospects = await scrape_pipeline_draft()

    # Phase 2 — Stats API
    print("\n=== Phase 2: MLB Stats API (college / HS / international) ===")
    sport_players = await fetch_all_prospect_players()

    # Phase 3 — DB writes
    print("\n=== Phase 3: Writing to database ===")
    engine = create_async_engine(DATABASE_URL, echo=False)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with S() as session:

        # ── Pipeline ranked prospects ──────────────────────────────────────────
        print(f"Upserting {len(pipeline_prospects)} Pipeline-ranked draft prospects…")
        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        for entry in pipeline_prospects:
            result = await upsert_pipeline_prospect(session, entry)
            counts[result] += 1
        await session.commit()
        print(f"  Pipeline: inserted={counts['inserted']} updated={counts['updated']} skipped={counts['skipped']}")

        # ── Stats API players by sport ─────────────────────────────────────────
        sport_labels = {22: "College/JUCO", 586: "High School", 6005: "International"}
        for sport_id, players in sport_players.items():
            print(f"\nUpserting {len(players):,} {sport_labels[sport_id]} players…")
            counts = {"inserted": 0, "updated": 0, "skipped": 0}
            for i, person in enumerate(players):
                result = await upsert_stats_player(session, person, sport_id)
                counts[result] += 1
                if (i + 1) % 500 == 0:
                    await session.commit()
                    print(f"  … {i+1:,}/{len(players):,} — ins={counts['inserted']:,} upd={counts['updated']:,}")
            await session.commit()
            print(f"  Done: inserted={counts['inserted']:,} updated={counts['updated']:,} skipped={counts['skipped']:,}")

        # ── Summary ───────────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        r = await session.execute(
            select(Player).where(Player.status == "draft_prospect")
        )
        total_dp = len(r.scalars().all())

        r = await session.execute(
            select(Player).where(Player.draft_rank.isnot(None), Player.status == "draft_prospect")
        )
        ranked = r.scalars().all()

        print(f"Total draft_prospect players : {total_dp:,}")
        print(f"With MLB Pipeline rank       : {len(ranked):,}")
        print(f"\nTop 10 Pipeline-ranked:")
        for p in sorted(ranked, key=lambda x: x.draft_rank)[:10]:
            print(f"  #{p.draft_rank:3d}  {p.full_name:26s}  {p.position or '?':4s}  {p.school or '':30s}  {p.school_class or ''}")

    await engine.dispose()
    print("\nDone ✓")


if __name__ == "__main__":
    asyncio.run(run())
