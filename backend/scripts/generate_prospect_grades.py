"""
generate_prospect_grades.py

Uses Claude to generate 20-80 scouting grades, scouting notes, and position
corrections for 2026 MLB draft prospects.

Usage (from backend/ with venv active):
    python -m scripts.generate_prospect_grades          # top 200 prospects
    python -m scripts.generate_prospect_grades --limit 50
    python -m scripts.generate_prospect_grades --rank-min 101 --rank-max 300
    python -m scripts.generate_prospect_grades --dry-run
"""

import asyncio
import argparse
import json
import os
import sys
import time
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set in .env")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Installing anthropic…")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "anthropic"], check=True)
    import anthropic

DB_URL = os.environ.get("DATABASE_URL_SYNC", "postgresql://postgres:password@localhost:5432/mlb_analytics")

POSITION_FULL = {
    "SP": "Starting Pitcher", "RP": "Relief Pitcher", "C": "Catcher",
    "1B": "First Baseman", "2B": "Second Baseman", "3B": "Third Baseman",
    "SS": "Shortstop", "LF": "Left Fielder", "CF": "Center Fielder",
    "RF": "Right Fielder", "DH": "Designated Hitter", "OF": "Outfielder",
}

SYSTEM = """You are an expert MLB draft analyst with knowledge of the 2026 MLB Draft class.
For each prospect given, respond with valid JSON only — no markdown, no explanation.
Use the 20-80 scouting scale: 80=elite, 70=plus-plus, 60=plus, 50=average, 40=below average, 30=well below, 20=poor.
Grade only tools that are relevant: batters get hit/power/speed/field/arm; pitchers get fastball_velo/command and optionally hit/power/speed/field/arm as N/A (omit those keys).
Overall grade should reflect draft round expected (top 10 pick = 60-65, round 1 = 55-60, round 2 = 50-55, etc.)."""

BATCH_PROMPT = """Grade these 2026 MLB draft prospects. For each, provide:
- corrected_position: the most likely MLB position (SP/RP/C/1B/2B/3B/SS/LF/CF/RF)
- scout_overall: overall grade (20-80)
- scout_hit: hit tool (batters only, else null)
- scout_power: raw power (batters only, else null)
- scout_speed: speed/baserunning (batters only, else null)
- scout_field: defense (batters only, else null)
- scout_arm: arm strength (always include)
- scout_fb_velo: fastball velocity grade (pitchers only, else null)
- scout_command: command/control grade (pitchers only, else null)
- notes: 2-3 sentence scouting note describing strengths, weaknesses, and ceiling

Prospects:
{prospects_json}

Respond with a JSON array — one object per prospect, in the same order, each with an "id" field matching the prospect's id."""


async def fetch_prospects(db_url: str, rank_min: int, rank_max: int) -> list[dict]:
    conn = await asyncpg.connect(db_url)
    rows = await conn.fetch("""
        SELECT id, full_name, position, school, school_class, draft_rank,
               height, weight, bats, throws, birth_country
        FROM players
        WHERE status = 'draft_prospect'
          AND draft_rank >= $1 AND draft_rank <= $2
        ORDER BY draft_rank
    """, rank_min, rank_max)
    await conn.close()
    return [dict(r) for r in rows]


async def update_prospect(conn, row_id: str, grades: dict, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] would update {row_id}")
        return

    pos = grades.get("corrected_position")
    await conn.execute("""
        UPDATE players SET
            position         = COALESCE($2, position),
            scout_overall    = COALESCE($3, scout_overall),
            scout_hit        = COALESCE($4, scout_hit),
            scout_power      = COALESCE($5, scout_power),
            scout_speed      = COALESCE($6, scout_speed),
            scout_field      = COALESCE($7, scout_field),
            scout_arm        = COALESCE($8, scout_arm),
            scout_fb_velo    = COALESCE($9, scout_fb_velo),
            scout_command    = COALESCE($10, scout_command),
            scout_notes      = COALESCE($11, scout_notes)
        WHERE id = $1
    """,
        row_id,
        pos or None,
        _int(grades.get("scout_overall")),
        _int(grades.get("scout_hit")),
        _int(grades.get("scout_power")),
        _int(grades.get("scout_speed")),
        _int(grades.get("scout_field")),
        _int(grades.get("scout_arm")),
        _int(grades.get("scout_fb_velo")),
        _int(grades.get("scout_command")),
        grades.get("notes") or None,
    )


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _prospect_summary(p: dict) -> dict:
    return {
        "id": str(p["id"]),
        "name": p["full_name"],
        "rank": p["draft_rank"],
        "position": p["position"] or "unknown",
        "school": p["school"] or "unknown",
        "school_class": p["school_class"] or "unknown",
        "height": p["height"] or "unknown",
        "weight": p["weight"] or "unknown",
        "bats": p["bats"] or "unknown",
        "throws": p["throws"] or "unknown",
    }


async def grade_batch(client: anthropic.Anthropic, prospects: list[dict]) -> list[dict]:
    summaries = [_prospect_summary(p) for p in prospects]
    prompt = BATCH_PROMPT.format(prospects_json=json.dumps(summaries, indent=2))

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    return json.loads(text)


async def main(rank_min: int, rank_max: int, batch_size: int, dry_run: bool) -> None:
    print(f"Fetching prospects ranked {rank_min}–{rank_max}…")
    prospects = await fetch_prospects(DB_URL, rank_min, rank_max)
    print(f"Found {len(prospects)} prospects to grade")

    if not prospects:
        print("Nothing to do.")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    if not dry_run:
        conn = await asyncpg.connect(DB_URL)
    else:
        conn = None

    total_updated = 0
    errors = 0

    for i in range(0, len(prospects), batch_size):
        batch = prospects[i : i + batch_size]
        names = [p["full_name"] for p in batch]
        print(f"\n[{i+1}–{i+len(batch)}] Grading: {', '.join(names[:3])}{'…' if len(names) > 3 else ''}")

        try:
            results = await grade_batch(client, batch)
            # Index by id for lookup
            by_id = {r["id"]: r for r in results if "id" in r}

            for p in batch:
                pid = str(p["id"])
                grades = by_id.get(pid)
                if not grades:
                    print(f"  ✗ No result for {p['full_name']}")
                    errors += 1
                    continue

                pos_before = p["position"] or "???"
                pos_after = grades.get("corrected_position") or pos_before
                overall = grades.get("scout_overall") or "?"
                notes_len = len(grades.get("notes") or "")
                pos_note = f" → {pos_after}" if pos_after != pos_before else ""
                print(f"  ✓ #{p['draft_rank']} {p['full_name']:<26} {pos_before}{pos_note}  OVR:{overall}  notes:{notes_len}ch")

                await update_prospect(conn, pid, grades, dry_run)
                total_updated += 1

        except Exception as exc:
            print(f"  ✗ Batch error: {exc}")
            errors += 1

        # Brief pause between batches to respect rate limits
        if i + batch_size < len(prospects):
            time.sleep(0.5)

    if conn:
        await conn.close()

    print(f"\n{'─'*55}")
    print(f"  Updated: {total_updated}   Errors: {errors}")
    if dry_run:
        print("  (dry-run — no changes saved)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rank-min", type=int, default=1)
    parser.add_argument("--rank-max", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--limit", type=int, help="Override rank-max (grade top N)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.limit:
        args.rank_max = args.rank_min + args.limit - 1

    asyncio.run(main(args.rank_min, args.rank_max, args.batch_size, args.dry_run))
