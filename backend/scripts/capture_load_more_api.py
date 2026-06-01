"""
capture_load_more_api.py
─────────────────────────
Dismisses cookie consent, then clicks load-more-button and captures
all API calls to find the prospect data endpoint.
"""

import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright

OUTPUT_DIR = Path(__file__).parent / "pipeline_data"
OUTPUT_DIR.mkdir(exist_ok=True)


async def run():
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
        # Block ads/analytics to speed things up and reduce noise
        await ctx.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2}", lambda r: r.abort())
        await ctx.route("**/doubleclick.net/**", lambda r: r.abort())
        await ctx.route("**/googletagmanager.com/**", lambda r: r.abort())
        await ctx.route("**/chartbeat.net/**", lambda r: r.abort())
        await ctx.route("**/flashtalking.com/**", lambda r: r.abort())
        await ctx.route("**/datadoghq.com/**", lambda r: r.abort())
        await ctx.route("**/adtrafficquality.google/**", lambda r: r.abort())

        page = await ctx.new_page()

        all_responses: list[dict] = []

        async def on_resp(resp):
            ct = resp.headers.get("content-type", "")
            try:
                body = await resp.body()
                text = body.decode("utf-8", errors="replace")
                entry = {
                    "url": resp.url[:200],
                    "status": resp.status,
                    "content_type": ct,
                    "size": len(text),
                    "preview": text[:200],
                }
                all_responses.append(entry)
                # Save anything that looks like prospect/player data
                if (resp.status == 200 and len(text) > 500 and
                    any(kw in text for kw in ("rank", "player", "prospect", "Made", "position", "mlbId"))):
                    if "cookielaw" not in resp.url and "adobe" not in resp.url:
                        fname = OUTPUT_DIR / f"resp_{len(all_responses):03d}.txt"
                        fname.write_text(text[:50000])
                        print(f"  [SAVED] {resp.url[:100]} → {fname.name} ({len(text)} chars)")
            except Exception:
                pass

        page.on("response", on_resp)

        print("Loading page...")
        await page.goto("https://www.mlb.com/milb/prospects",
                        wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(4_000)

        # Dismiss cookie consent
        print("Dismissing cookie consent...")
        for selector in [
            '#onetrust-accept-btn-handler',
            'button:has-text("OK")',
            'button:has-text("Accept")',
            'button:has-text("I Accept")',
            '.save-preference-btn-handler',
            '[id*="onetrust"] button',
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=2_000):
                    await btn.click()
                    print(f"  Clicked: {selector}")
                    await page.wait_for_timeout(1_500)
                    break
            except Exception:
                pass

        # Also try to remove the overlay via JS
        await page.evaluate("""
            var el = document.getElementById('onetrust-consent-sdk');
            if (el) el.remove();
            var overlay = document.querySelector('.onetrust-pc-dark-filter');
            if (overlay) overlay.remove();
        """)
        await page.wait_for_timeout(500)

        # Count initial rows
        initial_rows = await page.query_selector_all('[data-testid="table-row"]')
        print(f"Initial table rows: {len(initial_rows)}")

        # Now click load-more
        print("Clicking load-more-button via JS...")
        all_responses.clear()  # Reset to only capture post-click calls

        # Use JS click to bypass overlay
        await page.evaluate("""
            var btn = document.querySelector('[data-testid="load-more-button"]');
            if (btn) btn.click();
            else console.log('Button not found');
        """)
        print("  Clicked via JS!")
        await page.wait_for_timeout(8_000)

        rows_after = await page.query_selector_all('[data-testid="table-row"]')
        print(f"Table rows after click: {len(rows_after)}")

        # Print all post-click responses
        print(f"\nPost-click responses captured: {len(all_responses)}")
        for r in all_responses:
            if r['status'] == 200 and r['size'] > 100:
                print(f"  [{r['status']}] {r['size']:6d}b  {r['url'][:120]}")

        # Get page text to see all prospect data
        text = await page.inner_text('[data-testid="rankings__table"]')
        print(f"\nTable text length: {len(text)}")
        print(text[:2000])
        Path(OUTPUT_DIR / "table_text_full.txt").write_text(text)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
