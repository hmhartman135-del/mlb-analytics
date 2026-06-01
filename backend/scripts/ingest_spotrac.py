"""
ingest_spotrac.py
─────────────────
Scrapes spotrac.com/mlb/free-agents for two FA classes and stores them
in the spotrac_fas table.

  season=2026  →  /mlb/free-agents/_/year/2026   (current offseason FAs)
  season=2027  →  /mlb/free-agents               (upcoming post-2026 FAs)

Run from backend/:
    .venv/bin/python3 -m scripts.ingest_spotrac
"""

import asyncio
import os
import re
import sys
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics",
)

from app.models.spotrac_fa import SpotracFA  # noqa
from app.models.player import Player         # noqa
from app.models.stats import BattingStats, PitchingStats  # noqa — keeps mapper happy
from app.models.team import Team             # noqa

# ── Position normalisation ────────────────────────────────────────────────────

_POS = {
    "starting pitcher": "SP", "relief pitcher": "RP", "pitcher": "P",
    "pitchers": "P",
    "catcher": "C",
    "first base": "1B", "1st base": "1B",
    "second base": "2B", "2nd base": "2B",
    "third base": "3B", "3rd base": "3B",
    "shortstop": "SS",
    "left field": "LF", "center field": "CF", "right field": "RF",
    "outfield": "OF", "outfielder": "OF",
    "infield": "IF", "infielder": "IF",
    "designated hitter": "DH",
    # short forms already correct
    "sp": "SP", "rp": "RP", "p": "P",
    "c": "C", "1b": "1B", "2b": "2B", "3b": "3B", "ss": "SS",
    "lf": "LF", "cf": "CF", "rf": "RF", "of": "OF", "dh": "DH",
}

# All known position abbreviations — checked BEFORE the team-abbreviation logic
_POS_ABBREVS = frozenset({
    "SP", "RP", "P",                            # pitchers
    "C", "1B", "2B", "3B", "SS",                # infield
    "LF", "CF", "RF", "OF", "IF", "DH", "UTIL", # outfield / DH
})


def _norm_pos(raw: str | None) -> str | None:
    if not raw:
        return None
    return _POS.get(raw.strip().lower(), raw.strip()[:16])


# ── Row parsers ───────────────────────────────────────────────────────────────

def _parse_money(s: str) -> int | None:
    """'$60,000,000' → 60000000"""
    m = re.search(r"\$([0-9,]+)", s)
    return int(m.group(1).replace(",", "")) if m else None


def _parse_contract(s: str) -> tuple[int | None, int | None]:
    """'4 yr, $240,000,000' → (4, 240000000)"""
    m = re.match(r"(\d+)\s+yr[s]?,\s+\$([0-9,]+)", s.strip(), re.I)
    if m:
        return int(m.group(1)), int(m.group(2).replace(",", ""))
    return None, None


def _parse_table0_row(row_text: str) -> dict | None:
    """
    Table 0 row format (tab-delimited columns):
      col0: team logo (text empty)
      col1: "Name\nPosition\nAge: XX.X"
      col2: "N yr, $XXX\nAAV: $XXX"   OR   "Unsigned" / empty
    """
    cols = row_text.split("\t")
    if len(cols) < 2:
        return None

    player_lines = [l.strip() for l in cols[1].split("\n") if l.strip()]
    if not player_lines:
        return None

    rec: dict = {
        "full_name": player_lines[0],
        "position": _norm_pos(player_lines[1]) if len(player_lines) > 1 else None,
        "age": None,
        "signed": False,
        "contract_years": None,
        "contract_value": None,
        "aav": None,
        "former_team": None,
        "fa_type": None,
    }

    for line in player_lines:
        if line.lower().startswith("age:"):
            try:
                rec["age"] = float(line.split(":")[1].strip())
            except ValueError:
                pass

    if len(cols) >= 3:
        contract_lines = [l.strip() for l in cols[2].split("\n") if l.strip()]
        for line in contract_lines:
            if re.match(r"\d+\s+yr", line, re.I):
                yrs, val = _parse_contract(line)
                rec["contract_years"] = yrs
                rec["contract_value"] = val
                rec["signed"] = True
            elif line.lower().startswith("aav:"):
                rec["aav"] = _parse_money(line)

    return rec


def _parse_table1_row(row_text: str) -> dict | None:
    """
    Table 1 rows appear in two formats depending on the page:

    Format A (2026 signed tracker):
      "UFA\nFrankie Montas, SP\nNYM\nYOE: 8.015\nAge: 31.5"

    Format B (2027 upcoming FAs — player still on roster):
      "A.J. Minter\nATL\nL\nYOE: 4.5\nAge: 29"
      "Alec Bohm\n3rd Base\nPHI\nR\nYOE: 5.3\nAge: 28.4"

    Single-letter tokens (L / R / S) are pitcher/batter handedness — NOT teams.
    MLB team abbreviations are always 2-3 uppercase letters.
    """
    parts = [p.strip() for p in re.split(r"[\t\n]+", row_text) if p.strip()]
    if len(parts) < 2:
        return None

    # Skip header rows
    if parts[0].lower() in ("players", "player", "team", "details", "previous aav"):
        return None

    rec: dict = {
        "fa_type": None,
        "full_name": "",
        "position": None,
        "age": None,
        "former_team": None,
        "signed": False,
        "contract_years": None,
        "contract_value": None,
        "aav": None,
    }

    # Optional leading FA type ("UFA", "ARFA", "MiLBFA")
    if parts[0].upper() in ("UFA", "ARFA", "MILBFA", "FA"):
        rec["fa_type"] = parts[0].upper()
        parts = parts[1:]

    if not parts:
        return None

    # First remaining part = player name, possibly with ", POS"
    name_part = parts[0]
    if "," in name_part:
        name_bits = name_part.split(",", 1)
        rec["full_name"] = name_bits[0].strip()
        rec["position"] = _norm_pos(name_bits[1].strip())
    else:
        rec["full_name"] = name_part

    # Walk remaining parts; order may vary across page formats
    for part in parts[1:]:
        low = part.lower()

        if low.startswith("yoe:"):
            pass  # service time — not stored

        elif low.startswith("age:"):
            try:
                rec["age"] = float(part.split(":")[1].strip())
            except ValueError:
                pass

        elif re.match(r"\d+\s+yr", part, re.I):
            yrs, val = _parse_contract(part)
            rec["contract_years"] = yrs
            rec["contract_value"] = val
            rec["signed"] = True

        elif low.startswith("aav:"):
            rec["aav"] = _parse_money(part)

        elif part in ("L", "R", "S", "B"):
            pass  # pitcher/batter handedness — skip

        elif part.upper() in _POS_ABBREVS:
            # Known position code (C, SP, RP, 3B, CF, DH, OF, SS…)
            if rec["position"] is None:
                rec["position"] = part.upper()

        elif 2 <= len(part) <= 4 and part.upper() == part and part.isalpha():
            # Remaining 2-4 uppercase alphabetic tokens → MLB team abbreviation
            if rec["former_team"] is None:
                rec["former_team"] = part

        else:
            # Try to parse as a spelled-out position ("3rd Base", "Starting Pitcher")
            if rec["position"] is None:
                pos = _norm_pos(part)
                if pos and pos != part:  # _norm_pos changed it → known position
                    rec["position"] = pos

    if not rec["full_name"]:
        return None
    return rec


# ── Playwright scraper ────────────────────────────────────────────────────────

HEADERS = {
    "user_agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

URLS = {
    2026: "https://www.spotrac.com/mlb/free-agents/_/year/2026",
    2027: "https://www.spotrac.com/mlb/free-agents",
}


async def scrape_season(season: int) -> list[dict]:
    """Scrape one FA-class page and return a list of parsed player dicts."""
    from playwright.async_api import async_playwright

    url = URLS[season]
    print(f"  Scraping {url}")

    for attempt in range(3):
        if attempt:
            wait = 30 * attempt
            print(f"  Rate-limited, waiting {wait}s before retry {attempt+1}/3…")
            await asyncio.sleep(wait)

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    user_agent=HEADERS["user_agent"],
                    viewport={"width": 1280, "height": 900},
                )
                page = await ctx.new_page()
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await asyncio.sleep(5)  # let JS finish rendering

                if resp is None or resp.status == 429:
                    await browser.close()
                    continue

                tables = await page.query_selector_all("table")
                if not tables:
                    body = await page.inner_text("body")
                    if "429" in body or "too fast" in body.lower():
                        await browser.close()
                        continue
                    print(f"  Warning: no tables found on {url}")
                    await browser.close()
                    return []

                players: list[dict] = []

                # Table 0 — signed deals with full contract info
                if tables:
                    rows = await tables[0].query_selector_all("tr")
                    for row in rows[1:]:   # skip header
                        txt = await row.inner_text()
                        rec = _parse_table0_row(txt)
                        if rec and rec["full_name"]:
                            players.append(rec)

                # Table 1 — unsigned / tracker list (different column structure)
                if len(tables) > 1:
                    rows = await tables[1].query_selector_all("tr")
                    for row in rows[1:]:
                        txt = await row.inner_text()
                        rec = _parse_table1_row(txt)
                        if rec and rec["full_name"]:
                            # Avoid duplicating already-captured signed players
                            existing_names = {p["full_name"] for p in players}
                            if rec["full_name"] not in existing_names:
                                players.append(rec)

                await browser.close()
                print(f"  Parsed {len(players)} players for season {season}")
                return players

        except Exception as e:
            print(f"  Scrape attempt {attempt+1} failed: {type(e).__name__}: {e}")

    print(f"  All retries exhausted for season {season}")
    return []


# ── DB upsert ─────────────────────────────────────────────────────────────────

async def upsert_season(
    S: async_sessionmaker, season: int, players: list[dict]
) -> None:
    if not players:
        return

    now = datetime.utcnow()
    inserted = updated = 0

    async with S() as session:
        for rec in players:
            result = await session.execute(
                select(SpotracFA).where(
                    SpotracFA.season == season,
                    SpotracFA.full_name == rec["full_name"],
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.position = rec.get("position") or existing.position
                existing.age = rec.get("age") or existing.age
                existing.former_team = rec.get("former_team") or existing.former_team
                existing.fa_type = rec.get("fa_type") or existing.fa_type
                existing.signed = rec.get("signed", existing.signed)
                existing.contract_years = rec.get("contract_years") or existing.contract_years
                existing.contract_value = rec.get("contract_value") or existing.contract_value
                existing.aav = rec.get("aav") or existing.aav
                existing.scraped_at = now
                updated += 1
            else:
                session.add(SpotracFA(
                    season=season,
                    fa_type=rec.get("fa_type"),
                    full_name=rec["full_name"],
                    position=rec.get("position"),
                    age=rec.get("age"),
                    former_team=rec.get("former_team"),
                    signed=rec.get("signed", False),
                    contract_years=rec.get("contract_years"),
                    contract_value=rec.get("contract_value"),
                    aav=rec.get("aav"),
                    scraped_at=now,
                ))
                inserted += 1

        await session.commit()

    print(f"  Season {season}: {inserted} inserted, {updated} updated")


# ── Summary ───────────────────────────────────────────────────────────────────

async def print_summary(S: async_sessionmaker) -> None:
    from sqlalchemy import text
    async with S() as session:
        for season in (2026, 2027):
            r = await session.execute(
                text(f"SELECT COUNT(*) FROM spotrac_fas WHERE season={season}")
            )
            total = r.scalar()
            r2 = await session.execute(
                text(f"SELECT COUNT(*) FROM spotrac_fas WHERE season={season} AND signed=true")
            )
            signed = r2.scalar()
            print(f"  Season {season}: {total:,} total, {signed:,} signed, {total-signed:,} unsigned")


# ── Main ──────────────────────────────────────────────────────────────────────

async def run() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Ensure table exists
    async with engine.begin() as conn:
        from app.core.database import Base
        await conn.run_sync(Base.metadata.create_all)

    print("\n=== Spotrac FA Ingestion ===")

    # 2026 first, then wait to avoid rate limiting before 2027
    print("\n--- 2026 Free Agents (current offseason) ---")
    players_2026 = await scrape_season(2026)
    await upsert_season(S, 2026, players_2026)

    print("\n--- 2027 Free Agents (upcoming post-2026) ---")
    await asyncio.sleep(5)   # polite delay between pages
    players_2027 = await scrape_season(2027)
    await upsert_season(S, 2027, players_2027)

    print("\n" + "=" * 50)
    await print_summary(S)

    await engine.dispose()
    print("\nDone ✓")


if __name__ == "__main__":
    asyncio.run(run())
