"""
find_pipeline_api.py
────────────────────
Captures ALL network calls made when loading mlb.com/milb/prospects,
including after clicking "Show Full List". Saves everything to inspect.

Run from backend/:
    .venv/bin/python3 -m scripts.find_pipeline_api
"""

import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
OUTPUT_DIR = Path(__file__).parent / "pipeline_data"
OUTPUT_DIR.mkdir(exist_ok=True)


async def run():
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
        page = await context.new_page()

        all_requests: list[dict] = []
        json_responses: dict[str, object] = {}

        async def on_request(request):
            all_requests.append({
                "url": request.url,
                "method": request.method,
                "resource_type": request.resource_type,
            })

        async def on_response(response):
            ct = response.headers.get("content-type", "")
            if ("json" in ct or "javascript" in ct) and response.status == 200:
                try:
                    body = await response.body()
                    text = body.decode("utf-8", errors="replace")
                    # Only save if it looks like prospect data
                    if any(kw in text for kw in (
                        "prospect", "Prospect", "ranking", "Ranking",
                        "Made", "De Vries", "Willits", "Yesavage",
                    )):
                        json_responses[response.url] = text[:5000]
                        print(f"  [MATCH] {response.url[:100]} ({len(text)} chars)")
                    elif "json" in ct and len(text) > 200:
                        # Log all JSON calls for inspection
                        all_requests.append({
                            "url": response.url,
                            "type": "json_response",
                            "size": len(text),
                            "preview": text[:100],
                        })
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        print("Phase 1: loading page…")
        await page.goto("https://www.mlb.com/milb/prospects", wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(6_000)

        print("Phase 2: clicking Show Full List…")
        for selector in [
            'button:has-text("Show Full List")',
            'a:has-text("Show Full List")',
            'button:has-text("Show All")',
            '[data-testid*="show-more"]',
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible(timeout=2_000):
                    print(f"  Clicking: {selector}")
                    await btn.click()
                    await page.wait_for_timeout(8_000)
                    print("  Done waiting after click")
                    break
            except Exception:
                pass

        # Phase 3: scroll to bottom to trigger any lazy loading
        print("Phase 3: scrolling…")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(4_000)

        print("\n── All JSON responses matching prospect data ──")
        for url, text in json_responses.items():
            print(f"\nURL: {url}")
            print(f"Preview: {text[:300]}")
            print("---")

        # Save full log
        with open(OUTPUT_DIR / "all_requests.json", "w") as f:
            json.dump(all_requests[-200:], f, indent=2)

        with open(OUTPUT_DIR / "prospect_api_responses.json", "w") as f:
            json.dump(json_responses, f, indent=2)

        # Also get the page HTML to look for embedded data
        html = await page.content()
        with open(OUTPUT_DIR / "page_full.html", "w") as f:
            f.write(html)
        print(f"\nPage HTML saved ({len(html)} chars)")

        # Count visible prospect rows
        rows = await page.query_selector_all("tr")
        print(f"Table rows: {len(rows)}")

        # Try to get ALL text from prospect-related elements
        for sel in [
            "[class*='prospect']", "[class*='ranking']",
            "[class*='Prospect']", "[class*='Ranking']",
            "[class*='player-row']", "[class*='PlayerRow']",
        ]:
            els = await page.query_selector_all(sel)
            if els:
                print(f"Elements matching '{sel}': {len(els)}")
                if els:
                    sample = (await els[0].inner_text()).strip()[:100]
                    print(f"  Sample: {sample}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
