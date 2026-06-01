"""Debug a single team top-30 page."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

DATA_DIR = Path(__file__).parent / "pipeline_data"

async def run():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        # First load the main page and dismiss consent (sets cookie)
        print("Loading main page to set consent cookie...")
        await page.goto("https://www.mlb.com/milb/prospects", wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(3_000)

        # Dismiss consent
        for sel in ['#onetrust-accept-btn-handler', 'button:has-text("OK")']:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2_000):
                    await btn.click()
                    await page.wait_for_timeout(1_000)
                    break
            except Exception:
                pass

        # Now navigate to NYY team page
        print("\nNavigating to NYY team page...")
        await page.goto("https://www.mlb.com/milb/prospects/team-top-30/new-york-yankees",
                        wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(5_000)

        # Check what's there
        testids = await page.evaluate("""
            Array.from(document.querySelectorAll('[data-testid]'))
                 .map(el => el.getAttribute('data-testid'))
        """)
        print(f"data-testid values found: {len(testids)}")
        unique = list(dict.fromkeys(testids))
        for t in unique[:30]:
            print(f"  {t}")

        table_rows = await page.query_selector_all('[data-testid="table-row"]')
        print(f"\ntable-row elements: {len(table_rows)}")

        # Get page text
        text = await page.inner_text("body")
        print(f"Body text length: {len(text)}")

        # Save debug files
        (DATA_DIR / "nyy_page_text.txt").write_text(text)
        html = await page.content()
        (DATA_DIR / "nyy_page.html").write_text(html)
        await page.screenshot(path=str(DATA_DIR / "nyy_page.png"))

        print("\nFirst 1000 chars of body text:")
        print(text[:1000])

        await browser.close()

asyncio.run(run())
