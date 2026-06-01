"""
Quick API connection test.
Run this first to make sure your Sportradar key works and to see the
exact response structure before running the full ingest.

Usage:
    python -m scripts.test_api
"""
import asyncio
import json
import httpx
from dotenv import load_dotenv
load_dotenv()

from app.core.config import get_settings
settings = get_settings()

async def main():
    print("\n=== Sportradar API Test ===\n")

    if not settings.sportradar_api_key or "PASTE" in settings.sportradar_api_key:
        print("✗  SPORTRADAR_API_KEY is not set in backend/.env")
        print("   Open backend/.env and paste your real key")
        return

    print(f"✓  Key found: ****{settings.sportradar_api_key[-6:]}\n")

    # Try v7 trial endpoint
    endpoints_to_try = [
        "https://api.sportradar.us/mlb/trial/v7/en/league/hierarchy.json",
        "https://api.sportradar.us/mlb/trial/v8/en/league/hierarchy.json",
        "https://api.sportradar.us/mlb/production/v7/en/league/hierarchy.json",
    ]

    async with httpx.AsyncClient(timeout=15) as client:
        for url in endpoints_to_try:
            print(f"Trying: {url}")
            try:
                resp = await client.get(url, params={"api_key": settings.sportradar_api_key})
                print(f"  Status: {resp.status_code}")

                if resp.status_code == 200:
                    data = resp.json()
                    print(f"  ✓ Success!")
                    print(f"  Top-level keys: {list(data.keys())}")

                    # Dig into the structure
                    if "league" in data:
                        league = data["league"]
                        print(f"  league keys: {list(league.keys())}")
                        for k, v in league.items():
                            if isinstance(v, list):
                                print(f"    league['{k}'] has {len(v)} items")
                                if v and isinstance(v[0], dict):
                                    print(f"      first item keys: {list(v[0].keys())}")
                                    # Go one level deeper
                                    first = v[0]
                                    for k2, v2 in first.items():
                                        if isinstance(v2, list) and v2:
                                            print(f"        [{k2}] has {len(v2)} items")
                                            if isinstance(v2[0], dict):
                                                print(f"          first item keys: {list(v2[0].keys())}")
                                                # Show a sample team
                                                inner = v2[0]
                                                for k3, v3 in inner.items():
                                                    if isinstance(v3, list) and v3:
                                                        print(f"            [{k3}] sample: {json.dumps(v3[0], indent=2)[:300]}")
                    else:
                        print(f"  Full response preview:")
                        print(json.dumps(data, indent=2)[:500])

                    print(f"\n✓ Working endpoint found: {url}\n")
                    return

                elif resp.status_code == 403:
                    print(f"  ✗ 403 Forbidden — key invalid or no access to this endpoint")
                elif resp.status_code == 401:
                    print(f"  ✗ 401 Unauthorized — check your API key")
                elif resp.status_code == 429:
                    print(f"  ✗ 429 Rate limited — wait a moment and try again")
                else:
                    print(f"  ✗ Unexpected status")

            except Exception as e:
                print(f"  ✗ Error: {e}")
            print()

    print("✗  No working endpoint found.")
    print("   Check that your Sportradar trial includes MLB access.")
    print("   Log in at developer.sportradar.com and confirm your plan.")


asyncio.run(main())
