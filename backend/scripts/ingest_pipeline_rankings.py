"""
ingest_pipeline_rankings.py
────────────────────────────
Scrapes the REAL MLB Pipeline Top-100 and all 30 team Top-30 lists
from mlb.com/milb/prospects, then writes prospect_rank /
org_prospect_rank into the DB.

Matching strategy (in order):
  1. Extract mlb_id from the headshot img URL in the DOM
  2. Fall back to DB lookup by name

Run from backend/:
    .venv/bin/python3 -m scripts.ingest_pipeline_rankings
"""

import asyncio, json, os, re
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, update

load_dotenv()
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics"
)

from app.models.stats import BattingStats, PitchingStats  # noqa
from app.models.player import Player                       # noqa
from app.models.team import Team                           # noqa

DATA_DIR = Path(__file__).parent / "pipeline_data"
DATA_DIR.mkdir(exist_ok=True)

MLB_TEAMS = [
    ("ARI", "dbacks"),     ("ATL", "braves"),
    ("BAL", "orioles"),    ("BOS", "redsox"),
    ("CHC", "cubs"),       ("CWS", "whitesox"),
    ("CIN", "reds"),       ("CLE", "guardians"),
    ("COL", "rockies"),    ("DET", "tigers"),
    ("HOU", "astros"),     ("KCR", "royals"),
    ("LAA", "angels"),     ("LAD", "dodgers"),
    ("MIA", "marlins"),    ("MIL", "brewers"),
    ("MIN", "twins"),      ("NYM", "mets"),
    ("NYY", "yankees"),    ("OAK", "athletics"),
    ("PHI", "phillies"),   ("PIT", "pirates"),
    ("SDP", "padres"),     ("SFG", "giants"),
    ("SEA", "mariners"),   ("STL", "cardinals"),
    ("TBR", "rays"),       ("TEX", "rangers"),
    ("TOR", "bluejays"),   ("WSN", "nationals"),
]


# ── Scraping helpers ───────────────────────────────────────────────────────────

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
    # Force-remove overlay via JS
    await page.evaluate("""
        var el = document.getElementById('onetrust-consent-sdk');
        if (el) el.remove();
    """)


async def extract_rows(page) -> list[dict]:
    """Extract all table rows from the currently-loaded rankings page."""
    rows = await page.query_selector_all('[data-testid="table-row"]')
    results = []
    for row in rows:
        try:
            cells = await row.query_selector_all('[data-testid="table-cell"]')
            if len(cells) < 2:
                continue
            cell_texts = [(await c.inner_text()).strip() for c in cells]

            # Extract mlb_id from headshot img src
            img = await row.query_selector('img[data-testid="player-headshot"]')
            mlb_id = None
            if img:
                src = await img.get_attribute("src") or ""
                m = re.search(r'/people/(\d+)/headshot', src)
                if m:
                    mlb_id = int(m.group(1))

            # Also try srcset
            if not mlb_id and img:
                srcset = await img.get_attribute("srcset") or ""
                m = re.search(r'/people/(\d+)/headshot', srcset)
                if m:
                    mlb_id = int(m.group(1))

            # Parse structured fields from cell text
            # Cell order: rank, player-name, position, team, level, eta, age, h/w, bats, throws
            def cell(i):
                return cell_texts[i] if i < len(cell_texts) else ""

            results.append({
                "rank":     int(re.sub(r'\D', '', cell(0))) if re.sub(r'\D', '', cell(0)) else None,
                "name":     cell(1),
                "position": cell(2),
                "org_name": cell(3),
                "level":    cell(4),
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


async def scrape_top100(page) -> list[dict]:
    print("Scraping Top 100…")
    await page.goto("https://www.mlb.com/milb/prospects",
                    wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(4_000)
    await dismiss_consent(page)
    await page.wait_for_timeout(500)

    # Click "Show Full List" via JS (avoids overlay issues)
    await page.evaluate("""
        var btn = document.querySelector('[data-testid="load-more-button"]');
        if (btn) btn.click();
    """)
    await page.wait_for_timeout(5_000)

    rows = await extract_rows(page)
    print(f"  Extracted {len(rows)} rows")
    return rows


async def scrape_team_top30(page, abbr: str, slug: str) -> list[dict]:
    url = f"https://www.mlb.com/milb/prospects/{slug}"
    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    await page.wait_for_timeout(3_500)
    await dismiss_consent(page)
    # Some team pages also have a load-more button (if they list more than 30)
    await page.evaluate("""
        var btn = document.querySelector('[data-testid="load-more-button"]');
        if (btn) btn.click();
    """)
    await page.wait_for_timeout(2_000)
    rows = await extract_rows(page)
    print(f"  {abbr}: {len(rows)} rows")
    return rows


# ── DB helpers ─────────────────────────────────────────────────────────────────

async def find_player(session: AsyncSession, mlb_id: int | None, name: str) -> Player | None:
    if mlb_id:
        r = await session.execute(select(Player).where(Player.mlb_id == mlb_id))
        p = r.scalar_one_or_none()
        if p:
            return p
    # Fallback: name match
    r = await session.execute(
        select(Player).where(Player.full_name.ilike(f"%{name}%"))
    )
    return r.scalars().first()


# ── Main ───────────────────────────────────────────────────────────────────────

async def run():
    # ── Step 1: Scrape with Playwright ────────────────────────────────────────
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

        async def route_handler(route):
            url = route.request.url
            if any(x in url for x in (
                "doubleclick.net", "googletagmanager", "chartbeat",
                "flashtalking", "datadoghq", "adtrafficquality",
                "facebook.net", "googlesyndication", "twitter.com",
            )):
                await route.abort()
            else:
                await route.continue_()
        await ctx.route("**/*", route_handler)

        page = await ctx.new_page()

        print("=== Phase 1: Top 100 ===")
        top100 = await scrape_top100(page)
        (DATA_DIR / "top100_scraped.json").write_text(json.dumps(top100, indent=2, ensure_ascii=False))
        print(f"Saved top100_scraped.json ({len(top100)} entries)")

        print("\n=== Phase 2: Team Top-30 lists ===")
        all_top30: dict[str, list[dict]] = {}
        for abbr, slug in MLB_TEAMS:
            try:
                rows = await scrape_team_top30(page, abbr, slug)
                all_top30[abbr] = rows
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"  ERROR {abbr}: {e}")
                all_top30[abbr] = []

        (DATA_DIR / "team_top30_scraped.json").write_text(
            json.dumps(all_top30, indent=2, ensure_ascii=False)
        )
        print(f"Saved team_top30_scraped.json")
        await browser.close()

    # ── Step 2: Write to DB ───────────────────────────────────────────────────
    print("\n=== Phase 3: Writing to database ===")
    engine = create_async_engine(DATABASE_URL, echo=False)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with S() as session:
        # Clear old computed ranks for minors players
        await session.execute(
            update(Player)
            .where(Player.status == "minors")
            .values(prospect_rank=None, org_prospect_rank=None,
                    parent_org_abbr=None, parent_org_mlb_id=None)
        )

        # Build org name → abbreviation map from DB teams
        team_rows = await session.execute(select(Team).where(Team.level == "MLB"))
        teams: dict[str, str] = {}
        for t in team_rows.scalars().all():
            teams[t.name.lower()] = t.abbreviation
            teams[t.city.lower()] = t.abbreviation
            teams[f"{t.city} {t.name}".lower()] = t.abbreviation

        matched = 0
        not_found = []

        # ── Top 100 ───────────────────────────────────────────────────────────
        print("Applying Top 100 ranks…")
        for entry in top100:
            rank = entry.get("rank")
            if not rank:
                continue
            p = await find_player(session, entry.get("mlb_id"), entry["name"])
            if p:
                p.prospect_rank = rank
                # Set parent org from org_name
                org_name = entry.get("org_name", "").lower()
                abbr = teams.get(org_name)
                if not abbr:
                    # Try partial match
                    for k, v in teams.items():
                        if k in org_name or org_name in k:
                            abbr = v
                            break
                if abbr:
                    p.parent_org_abbr = abbr
                matched += 1
            else:
                not_found.append(f"Top100 #{rank}: {entry['name']} (mlb_id={entry.get('mlb_id')})")

        print(f"  Matched {matched}/{len(top100)}")

        # ── Team Top-30 ────────────────────────────────────────────────────────
        print("Applying org Top-30 ranks…")
        org_matched = 0
        for abbr, rows in all_top30.items():
            for entry in rows:
                rank = entry.get("rank")
                if not rank:
                    continue
                p = await find_player(session, entry.get("mlb_id"), entry["name"])
                if p:
                    p.org_prospect_rank = rank
                    p.parent_org_abbr = abbr
                    org_matched += 1
                else:
                    not_found.append(f"{abbr} #{rank}: {entry['name']} (mlb_id={entry.get('mlb_id')})")

        print(f"  Matched {org_matched} org ranks")

        await session.commit()
        print("Committed.")

        if not_found:
            print(f"\n{len(not_found)} not matched:")
            for x in not_found[:20]:
                print(f"  {x}")
            if len(not_found) > 20:
                print(f"  … and {len(not_found)-20} more")

    await engine.dispose()
    print("\nDone ✓")


if __name__ == "__main__":
    asyncio.run(run())
