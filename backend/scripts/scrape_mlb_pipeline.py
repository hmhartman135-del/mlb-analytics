"""
scrape_mlb_pipeline.py
──────────────────────
Uses Playwright to:
  1. Intercept network calls on mlb.com/milb/prospects to find the real API
  2. Scrape the full Top-100 list
  3. Scrape each team's Top-30 list

Run from backend/:
    .venv/bin/python3 -m scripts.scrape_mlb_pipeline
"""

import asyncio
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

TOP100_URL   = "https://www.mlb.com/milb/prospects"
OUTPUT_DIR   = Path(__file__).parent / "pipeline_data"

MLB_TEAMS = [
    ("ARI","arizona-diamondbacks"), ("ATL","atlanta-braves"),
    ("BAL","baltimore-orioles"),    ("BOS","boston-red-sox"),
    ("CHC","chicago-cubs"),         ("CWS","chicago-white-sox"),
    ("CIN","cincinnati-reds"),      ("CLE","cleveland-guardians"),
    ("COL","colorado-rockies"),     ("DET","detroit-tigers"),
    ("HOU","houston-astros"),       ("KCR","kansas-city-royals"),
    ("LAA","los-angeles-angels"),   ("LAD","los-angeles-dodgers"),
    ("MIA","miami-marlins"),        ("MIL","milwaukee-brewers"),
    ("MIN","minnesota-twins"),      ("NYM","new-york-mets"),
    ("NYY","new-york-yankees"),     ("OAK","oakland-athletics"),
    ("PHI","philadelphia-phillies"),("PIT","pittsburgh-pirates"),
    ("SDP","san-diego-padres"),     ("SFG","san-francisco-giants"),
    ("SEA","seattle-mariners"),     ("STL","st-louis-cardinals"),
    ("TBR","tampa-bay-rays"),       ("TEX","texas-rangers"),
    ("TOR","toronto-blue-jays"),    ("WSN","washington-nationals"),
]


async def intercept_and_scrape_page(page, url: str, label: str) -> dict | None:
    """Load a page, capture any JSON API calls with prospect data, then scrape DOM."""
    captured = {}

    async def on_response(response):
        try:
            ct = response.headers.get("content-type", "")
            if "json" in ct and response.status == 200:
                url_lower = response.url.lower()
                # Look for prospect-related API calls
                if any(kw in url_lower for kw in ("prospect", "ranking", "pipeline", "milb")):
                    try:
                        body = await response.json()
                        captured[response.url] = body
                        print(f"  [API] {response.url[:100]}")
                    except Exception:
                        pass
        except Exception:
            pass

    page.on("response", on_response)
    print(f"Loading {label}: {url}")
    await page.goto(url, wait_until="networkidle", timeout=60_000)
    await page.wait_for_timeout(3_000)  # extra wait for lazy content

    # If there's a "Show Full List" / "Load More" button, click it
    for selector in [
        'button:has-text("Show Full List")',
        'button:has-text("Load More")',
        'button:has-text("Show More")',
        'a:has-text("Show Full List")',
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=2_000):
                print(f"  Clicking: {selector}")
                await btn.click()
                await page.wait_for_timeout(3_000)
                break
        except Exception:
            pass

    # Scrape from DOM — prospect rows
    prospects = []
    try:
        # Try various selectors that prospect tables commonly use
        rows = await page.query_selector_all(
            "table tr[data-rank], "
            "[class*='prospect-row'], "
            "[class*='ProspectRow'], "
            "[class*='ranking-row'], "
            "tr[class*='prospect']"
        )
        print(f"  DOM rows found: {len(rows)}")

        for row in rows:
            text = await row.inner_text()
            cells = await row.query_selector_all("td, [class*='cell']")
            cell_texts = []
            for c in cells:
                t = (await c.inner_text()).strip()
                if t:
                    cell_texts.append(t)
            if cell_texts:
                prospects.append(cell_texts)
    except Exception as e:
        print(f"  DOM scrape error: {e}")

    page.remove_listener("response", on_response)
    return {"api_calls": captured, "dom_rows": prospects}


async def extract_prospects_from_dom(page) -> list[dict]:
    """Parse the rendered prospect table from mlb.com DOM."""
    results = []
    try:
        # Wait for the table or list to appear
        await page.wait_for_selector(
            "[class*='prospect'], table, [data-testid*='prospect']",
            timeout=15_000
        )
    except Exception:
        pass

    # Try to grab the full page text and parse it
    content = await page.content()

    # Look for JSON data in script tags
    json_matches = re.findall(
        r'<script[^>]*>\s*window\.__(?:PROSPECT|PIPELINE|NEXT_DATA|DATA)__\s*=\s*(\{.*?\})\s*;?\s*</script>',
        content, re.DOTALL
    )
    if json_matches:
        for m in json_matches:
            try:
                data = json.loads(m)
                print("  Found window data blob!")
                return data
            except Exception:
                pass

    return results


async def scrape_top100(page) -> list[dict]:
    print("\n=== Scraping Top 100 ===")
    await page.goto(TOP100_URL, wait_until="networkidle", timeout=60_000)
    await page.wait_for_timeout(4_000)

    # Click "Show Full List" if present
    for selector in [
        'button:has-text("Show Full List")',
        'button:has-text("Show All")',
        'a:has-text("Full List")',
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=2_000):
                print(f"  Clicking expand: {selector}")
                await btn.click()
                await page.wait_for_timeout(4_000)
                break
        except Exception:
            pass

    # Grab all text from the page and look for structured prospect data
    text = await page.inner_text("body")
    print(f"  Page body text length: {len(text)}")
    print(f"  Sample (first 500): {text[:500]}")

    # Try to find prospect table rows via various selectors
    prospects = []

    # Attempt 1: rows with rank numbers
    rows = await page.query_selector_all("tr")
    print(f"  Table rows found: {len(rows)}")
    for row in rows:
        cells = await row.query_selector_all("td")
        if len(cells) >= 3:
            cell_texts = [(await c.inner_text()).strip() for c in cells]
            # Filter for rows that start with a rank number
            if cell_texts and re.match(r'^\d+$', cell_texts[0]):
                prospects.append(cell_texts)

    if not prospects:
        # Attempt 2: list items or divs
        items = await page.query_selector_all(
            "[class*='RankingRow'], [class*='ranking-row'], "
            "[class*='ProspectCard'], [class*='prospect-card'], "
            "[class*='PlayerRow'], [class*='player-row']"
        )
        print(f"  Ranked items found: {len(items)}")
        for item in items:
            text = await item.inner_text()
            prospects.append({"raw": text.replace("\n", " | ")})

    return prospects


async def scrape_team_top30(page, abbr: str, slug: str) -> list[dict]:
    url = f"https://www.mlb.com/milb/prospects/team-top-30/{slug}"
    print(f"  {abbr}: {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(2_000)

        rows = await page.query_selector_all("tr")
        prospects = []
        for row in rows:
            cells = await row.query_selector_all("td")
            if len(cells) >= 3:
                cell_texts = [(await c.inner_text()).strip() for c in cells]
                if cell_texts and re.match(r'^\d+$', cell_texts[0]):
                    prospects.append(cell_texts)

        if not prospects:
            items = await page.query_selector_all(
                "[class*='RankingRow'], [class*='ranking-row'], "
                "[class*='ProspectCard'], [class*='prospect-card']"
            )
            for item in items:
                text = await item.inner_text()
                prospects.append({"raw": text.replace("\n", " | ")})

        return prospects
    except Exception as e:
        print(f"    Error scraping {abbr}: {e}")
        return []


async def run():
    OUTPUT_DIR.mkdir(exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        # ── Intercept all network calls ──────────────────────────────────────────
        api_calls_found: dict = {}

        async def capture_all_api(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct and response.status == 200:
                    url = response.url
                    if len(url) < 300:
                        try:
                            body = await response.json()
                            if isinstance(body, (dict, list)) and body:
                                api_calls_found[url] = body
                        except Exception:
                            pass
            except Exception:
                pass

        page = await context.new_page()
        page.on("response", capture_all_api)

        # ── Load top-100 page ─────────────────────────────────────────────────────
        print("Loading MLB Pipeline Top 100…")
        await page.goto(TOP100_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(8_000)

        # Save all captured API calls for inspection
        api_out = OUTPUT_DIR / "api_calls_top100.json"
        with open(api_out, "w") as f:
            # Save just URLs + summary, not full bodies
            summary = {url: str(type(body)) + f" len={len(body) if isinstance(body, (list, dict)) else '?'}"
                       for url, body in api_calls_found.items()}
            json.dump(summary, f, indent=2)
        print(f"Captured {len(api_calls_found)} API calls → {api_out}")

        # Also save any that look like prospect data
        for url, body in api_calls_found.items():
            key = url.split("?")[0].split("/")[-1]
            out = OUTPUT_DIR / f"api_{key[:60]}.json"
            with open(out, "w") as f:
                json.dump(body, f, indent=2)

        # ── Scrape DOM ────────────────────────────────────────────────────────────
        # Try to expand the full list
        for selector in [
            'button:has-text("Show Full List")',
            'button:has-text("Show All")',
            'a:has-text("Full List")',
            '[class*="show-more"]',
            '[class*="load-more"]',
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=1_500):
                    print(f"Clicking: {selector}")
                    await btn.click()
                    await page.wait_for_timeout(3_000)
                    break
            except Exception:
                pass

        # Take screenshot to see what we've got
        await page.screenshot(path=str(OUTPUT_DIR / "top100_page.png"), full_page=False)
        print("Screenshot saved.")

        # Get page text
        body_text = await page.inner_text("body")
        with open(OUTPUT_DIR / "top100_text.txt", "w") as f:
            f.write(body_text)
        print(f"Page text length: {len(body_text)} → top100_text.txt")

        # Scrape the table
        rows_data = []
        trs = await page.query_selector_all("tr")
        for tr in trs:
            tds = await tr.query_selector_all("td")
            if len(tds) >= 3:
                vals = [(await td.inner_text()).strip() for td in tds]
                if vals and re.match(r'^\d+$', vals[0]):
                    rows_data.append(vals)

        if not rows_data:
            # Try list/card layout
            items = await page.query_selector_all(
                "[class*='Ranking'], [class*='ranking'], "
                "[class*='ProspectRow'], [class*='PlayerRow']"
            )
            for item in items:
                t = (await item.inner_text()).strip()
                if t:
                    rows_data.append({"raw": t})

        print(f"Top-100 rows scraped: {len(rows_data)}")
        with open(OUTPUT_DIR / "top100_rows.json", "w") as f:
            json.dump(rows_data, f, indent=2)

        # ── Scrape each team's Top 30 ─────────────────────────────────────────────
        page.remove_listener("response", capture_all_api)
        all_top30: dict = {}
        print("\n=== Scraping Team Top-30 lists ===")

        for i, (abbr, slug) in enumerate(MLB_TEAMS):
            url = f"https://www.mlb.com/milb/prospects/team-top-30/{slug}"
            print(f"[{i+1}/30] {abbr} → {url}")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await page.wait_for_timeout(2_000)

                team_rows = []
                trs = await page.query_selector_all("tr")
                for tr in trs:
                    tds = await tr.query_selector_all("td")
                    if len(tds) >= 3:
                        vals = [(await td.inner_text()).strip() for td in tds]
                        if vals and re.match(r'^\d+$', vals[0]):
                            team_rows.append(vals)

                if not team_rows:
                    items = await page.query_selector_all(
                        "[class*='Ranking'], [class*='ranking'], "
                        "[class*='ProspectRow'], [class*='PlayerRow']"
                    )
                    for item in items:
                        t = (await item.inner_text()).strip()
                        if t:
                            team_rows.append({"raw": t})

                all_top30[abbr] = team_rows
                print(f"  → {len(team_rows)} rows")
            except Exception as e:
                print(f"  ERROR: {e}")
                all_top30[abbr] = []

            # Brief pause to avoid rate-limiting
            await asyncio.sleep(0.5)

        with open(OUTPUT_DIR / "team_top30.json", "w") as f:
            json.dump(all_top30, f, indent=2)
        print(f"\nTeam top-30 saved → team_top30.json")

        await browser.close()

    print("\nDone. Check scripts/pipeline_data/ for results.")


if __name__ == "__main__":
    asyncio.run(run())
