"""
Spotrac Salary Ingestion Script
Scrapes 2026 MLB salary data from Spotrac and stores real contract figures
(salary, service_time, contract_years) in the players table.

Usage (from backend/ directory):
    .venv/bin/python3 -m scripts.ingest_salaries
    .venv/bin/python3 -m scripts.ingest_salaries --team NYY   # one team only
    .venv/bin/python3 -m scripts.ingest_salaries --dry-run    # preview only
"""

import asyncio
import argparse
import re
import sys
from typing import Any

import asyncpg
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────

DB_URL = "postgresql://postgres:password@localhost:5432/mlb_analytics"

REQUEST_DELAY = 1.2   # Spotrac is generous but let's be polite
CURRENT_SEASON = 2026  # Used to compute years remaining on contracts

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Spotrac team URL slugs — keyed by MLB abbreviation
TEAM_SLUGS: dict[str, str] = {
    "AZ":  "arizona-diamondbacks",
    "ATL": "atlanta-braves",
    "BAL": "baltimore-orioles",
    "BOS": "boston-red-sox",
    "CHC": "chicago-cubs",
    "CWS": "chicago-white-sox",
    "CIN": "cincinnati-reds",
    "CLE": "cleveland-guardians",
    "COL": "colorado-rockies",
    "DET": "detroit-tigers",
    "HOU": "houston-astros",
    "KC":  "kansas-city-royals",
    "LAA": "los-angeles-angels",
    "LAD": "los-angeles-dodgers",
    "MIA": "miami-marlins",
    "MIL": "milwaukee-brewers",
    "MIN": "minnesota-twins",
    "NYM": "new-york-mets",
    "NYY": "new-york-yankees",
    "ATH": "athletics",
    "PHI": "philadelphia-phillies",
    "PIT": "pittsburgh-pirates",
    "SD":  "san-diego-padres",
    "SF":  "san-francisco-giants",
    "SEA": "seattle-mariners",
    "STL": "st-louis-cardinals",
    "TB":  "tampa-bay-rays",
    "TEX": "texas-rangers",
    "TOR": "toronto-blue-jays",
    "WSH": "washington-nationals",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(msg, flush=True)


def parse_salary(text: str) -> float | None:
    """'$37,116,666' → 37.116666 (millions)"""
    cleaned = re.sub(r"[^\d]", "", text)
    if not cleaned:
        return None
    val = int(cleaned)
    return round(val / 1_000_000, 4) if val > 0 else None


def parse_service_time(text: str) -> float | None:
    """'14.070' → 14.07 (years.days in service-time format)"""
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_name(name: str) -> str:
    """
    Normalise a player name for fuzzy matching:
      - Strip accents  (Martínez → Martinez)
      - Remove periods (T.J. → TJ, A.J. → AJ)
      - Collapse whitespace and lowercase
    """
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_str = ascii_str.replace(".", "").replace("  ", " ")
    return ascii_str.lower().strip()


def name_tokens(name: str) -> set[str]:
    return set(normalize_name(name).split())


# ── Spotrac scraper ───────────────────────────────────────────────────────────

def _scrape_standard_table(table) -> list[dict]:
    """Parse the standard 9-column Spotrac payroll table."""
    players: list[dict] = []
    for row in table.find("tbody").find_all("tr"):  # type: ignore[union-attr]
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        # Cell 0: player name (inside an <a> tag)
        name_tag = cells[0].find("a", href=re.compile(r"/mlb/player/"))
        if not name_tag:
            continue
        full_name = name_tag.get_text(strip=True)

        # Cell 1: position
        pos = cells[1].get_text(strip=True)

        # Cell 2: experience / service time (e.g. "14.070")
        svc_text = cells[2].get_text(strip=True)
        service_time = parse_service_time(svc_text)

        # Cell 4: contract status (Pre-Arbitration, Arbitration 1/2/3, Veteran)
        status_text = cells[4].get_text(strip=True) if len(cells) > 4 else ""

        # Cell 5: "Payroll Salary" — the actual 2026 salary number.
        # (Cells 6-8 are Adjusted Salary, Base Salary, Signing Bonus — we skip those.)
        salary_m = None
        if len(cells) > 5:
            salary_m = parse_salary(cells[5].get_text(strip=True))

        if not full_name or salary_m is None:
            continue

        players.append({
            "name": full_name,
            "pos": pos,
            "salary_m": salary_m,
            "service_time": service_time,
            "contract_status": status_text,
        })
    return players


def _scrape_compact_table(table) -> list[dict]:
    """
    Parse the compact 3-column Spotrac table used by some teams (e.g. Padres).
    Columns: RK | Player (name + pos + age) | Adj. Payroll
    """
    players: list[dict] = []
    for row in table.find("tbody").find_all("tr"):  # type: ignore[union-attr]
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        # Cell 1: player name (inside an <a> tag)
        name_tag = cells[1].find("a", href=re.compile(r"/mlb/player/"))
        if not name_tag:
            continue
        full_name = name_tag.get_text(strip=True)

        # Cell 2: salary
        salary_m = parse_salary(cells[2].get_text(strip=True))

        if not full_name or salary_m is None:
            continue

        players.append({
            "name": full_name,
            "pos": "",
            "salary_m": salary_m,
            "service_time": None,
            "contract_status": "",
        })
    return players


async def scrape_team_payroll(client: httpx.AsyncClient, slug: str) -> list[dict]:
    """Return list of {name, salary_m, service_time, contract_status} dicts."""
    url = f"https://www.spotrac.com/mlb/{slug}/payroll/"
    await asyncio.sleep(REQUEST_DELAY)
    try:
        r = await client.get(url)
        r.raise_for_status()
    except Exception as exc:
        log(f"  ⚠ Could not fetch {url}: {exc}")
        return []

    soup = BeautifulSoup(r.text, "lxml")
    all_tables = soup.find_all("table")
    if not all_tables:
        log(f"  ⚠ No table found on {url}")
        return []

    # Spotrac pages have multiple tables:
    #   Table 0 = 26-man active roster
    #   Table 1 = 10/15/60-day IL players
    #   Table 2+ = retained contracts, non-roster invitees, etc.
    # We scrape ALL tables with the right structure so IL players are included.

    seen_names: set[str] = set()
    players: list[dict] = []

    for table in all_tables:
        header_cells = table.find("thead").find_all("th") if table.find("thead") else []  # type: ignore[union-attr]
        num_cols = len(header_cells)

        if num_cols <= 4:
            # Compact format (e.g. Padres): RK | Player | Adj. Payroll
            rows = _scrape_compact_table(table)
        elif num_cols >= 6:
            # Standard 9-column format
            rows = _scrape_standard_table(table)
        else:
            continue  # skip payroll-summary or unrecognised tables

        for row in rows:
            if row["name"] not in seen_names:
                seen_names.add(row["name"])
                players.append(row)

    return players


# ── Contracts scraper ─────────────────────────────────────────────────────────

async def scrape_team_contracts(
    client: httpx.AsyncClient, slug: str
) -> dict[str, dict]:
    """
    Scrape /contracts/ for a team.

    Returns {normalised_player_name: {end_year, total_yrs, value_m, aav_m}}.

    Columns on the page:
      Player | Pos | Start Year | Type | Age At Signing | Start | End | Yrs | Value | AAV
    """
    url = f"https://www.spotrac.com/mlb/{slug}/contracts/"
    await asyncio.sleep(REQUEST_DELAY)
    try:
        r = await client.get(url)
        r.raise_for_status()
    except Exception as exc:
        log(f"  ⚠ Could not fetch contracts for {slug}: {exc}")
        return {}

    soup = BeautifulSoup(r.text, "lxml")
    result: dict[str, dict] = {}

    for table in soup.find_all("table"):
        tbody = table.find("tbody")
        if not tbody:
            continue
        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 9:
                continue
            name_tag = cells[0].find("a", href=re.compile(r"/mlb/player/"))
            if not name_tag:
                continue
            full_name = name_tag.get_text(strip=True)
            try:
                end_year    = int(cells[6].get_text(strip=True))
                total_yrs   = int(cells[7].get_text(strip=True))
                value_m     = parse_salary(cells[8].get_text(strip=True)) or 0.0
                aav_m       = parse_salary(cells[9].get_text(strip=True)) if len(cells) > 9 else 0.0
            except (ValueError, IndexError):
                continue
            result[normalize_name(full_name)] = {
                "end_year":  end_year,
                "total_yrs": total_yrs,
                "value_m":   value_m,
                "aav_m":     aav_m or 0.0,
            }

    return result


# ── DB matching & update ──────────────────────────────────────────────────────

def _find_contract(
    sp_name: str,
    contracts: dict[str, dict],
) -> dict | None:
    """Look up a player's contract entry by exact or token match."""
    norm = normalize_name(sp_name)
    if norm in contracts:
        return contracts[norm]
    # Token fallback (handles middle names, Jr., accents, etc.)
    sp_tok = name_tokens(sp_name)
    for ct_norm, info in contracts.items():
        if len(sp_tok & set(ct_norm.split())) >= 2:
            return info
    return None


async def match_and_update(
    conn: asyncpg.Connection,
    team_abbr: str,
    players: list[dict],
    contracts: dict[str, dict],
    dry_run: bool,
) -> tuple[int, int]:
    """Match Spotrac rows to DB players and update salary, service_time, contract_years."""
    # Fetch all players on this MLB team (40-man members)
    db_players = await conn.fetch(
        """
        SELECT p.id, p.full_name, p.salary, p.service_time
        FROM players p
        JOIN teams t ON p.team_id = t.id
        WHERE t.abbreviation = $1
          AND t.level = 'MLB'
          AND p.roster_status IS NOT NULL
        """,
        team_abbr,
    )

    # Build lookup by normalised full name
    db_by_name: dict[str, Any] = {}
    for p in db_players:
        db_by_name[normalize_name(p["full_name"])] = p

    matched = 0
    unmatched_names = []

    for sp in players:
        norm = normalize_name(sp["name"])

        # 1. Exact match
        db_row = db_by_name.get(norm)

        # 2. Token overlap (handles middle names, Jr., accents, etc.)
        if db_row is None:
            sp_tokens = name_tokens(sp["name"])
            best_score = 0
            best_row = None
            for db_norm, db_row_candidate in db_by_name.items():
                overlap = len(sp_tokens & name_tokens(db_row_candidate["full_name"]))
                if overlap >= 2 and overlap > best_score:
                    best_score = overlap
                    best_row = db_row_candidate
            db_row = best_row

        if db_row is None:
            unmatched_names.append(sp["name"])
            continue

        # Calculate years remaining on contract (None = no negotiated deal / pre-arb)
        ct = _find_contract(sp["name"], contracts)
        contract_years: int | None = None
        if ct:
            contract_years = max(0, ct["end_year"] - CURRENT_SEASON)

        if dry_run:
            ct_str = f"  {contract_years}yr left" if contract_years is not None else ""
            log(f"    {sp['name']:30s} → ${sp['salary_m']:.2f}M  svc={sp['service_time']}{ct_str}")
            matched += 1
            continue

        await conn.execute(
            """
            UPDATE players
            SET salary = $1, service_time = $2, contract_years = $3
            WHERE id = $4
            """,
            sp["salary_m"],
            sp["service_time"],
            contract_years,
            db_row["id"],
        )
        matched += 1

    if unmatched_names:
        log(f"  ⚠ Unmatched ({len(unmatched_names)}): {', '.join(unmatched_names[:5])}"
            + (" ..." if len(unmatched_names) > 5 else ""))

    return matched, len(players) - matched


# ── Entry point ───────────────────────────────────────────────────────────────

async def ingest_all(team_filter: str | None, dry_run: bool) -> None:
    teams = (
        {team_filter.upper(): TEAM_SLUGS[team_filter.upper()]}
        if team_filter
        else TEAM_SLUGS
    )

    conn = await asyncpg.connect(DB_URL)
    client = httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True)

    total_matched = total_unmatched = 0

    try:
        for abbr, slug in teams.items():
            log(f"\n→ {abbr}  ({slug})")

            # Payroll page: salary + service time
            players = await scrape_team_payroll(client, slug)
            log(f"  Payroll: {len(players)} players")
            if not players:
                continue

            # Contracts page: end year → years remaining
            contracts = await scrape_team_contracts(client, slug)
            log(f"  Contracts: {len(contracts)} entries")

            m, u = await match_and_update(conn, abbr, players, contracts, dry_run)
            log(f"  Matched/updated: {m}  |  Unmatched: {u}")
            total_matched += m
            total_unmatched += u

        log(f"\n{'─'*55}")
        log(f"Done. Matched {total_matched} players, {total_unmatched} unmatched.")
        if dry_run:
            log("Dry-run — nothing written to the database.")
    finally:
        await client.aclose()
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest real salary data from Spotrac")
    parser.add_argument("--team", type=str, default=None,
                        help="Only process one team (e.g. NYY, LAD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing to the database")
    args = parser.parse_args()

    if args.team and args.team.upper() not in TEAM_SLUGS:
        print(f"Unknown team '{args.team}'. Valid: {', '.join(TEAM_SLUGS)}")
        sys.exit(1)

    asyncio.run(ingest_all(args.team, args.dry_run))


if __name__ == "__main__":
    main()
