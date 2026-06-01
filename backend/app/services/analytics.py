"""
Advanced MLB metrics calculation engine.
wOBA weights sourced from FanGraphs annual constants.
"""
import pandas as pd
import numpy as np
from typing import Any


# 2024 wOBA weights (update annually from FanGraphs)
WOBA_WEIGHTS = {
    "bb": 0.690,
    "hbp": 0.722,
    "single": 0.884,
    "double": 1.261,
    "triple": 1.601,
    "hr": 2.063,
    "woba_scale": 1.157,   # wOBA to runs conversion
    "lg_woba": 0.317,
    "lg_obp": 0.319,
    "lg_runs_per_pa": 0.114,
    "lg_fip_constant": 3.17,
}


def calculate_woba(row: dict) -> float:
    w = WOBA_WEIGHTS
    singles = row["hits"] - row["doubles"] - row["triples"] - row["home_runs"]
    numerator = (
        w["bb"] * row["walks"]
        + w["hbp"] * row.get("hit_by_pitch", 0)
        + w["single"] * singles
        + w["double"] * row["doubles"]
        + w["triple"] * row["triples"]
        + w["hr"] * row["home_runs"]
    )
    denominator = (
        row["at_bats"]
        + row["walks"]
        + row.get("hit_by_pitch", 0)
        + row.get("sacrifice_flies", 0)
    )
    return round(numerator / denominator, 3) if denominator > 0 else 0.0


def calculate_fip(row: dict) -> float:
    """Fielding Independent Pitching."""
    ip = row.get("innings_pitched", 0)
    if ip == 0:
        return 0.0
    fip = (
        (13 * row["home_runs_allowed"] + 3 * row["walks"] - 2 * row["strikeouts"])
        / ip
        + WOBA_WEIGHTS["lg_fip_constant"]
    )
    return round(fip, 2)


def calculate_iso(avg: float, slg: float) -> float:
    """Isolated power."""
    return round(slg - avg, 3)


def calculate_babip_batting(row: dict) -> float:
    """BABIP for hitters: (H - HR) / (AB - K - HR + SF)."""
    numerator = row["hits"] - row["home_runs"]
    denominator = (
        row["at_bats"]
        - row["strikeouts"]
        - row["home_runs"]
        + row.get("sacrifice_flies", 0)
    )
    return round(numerator / denominator, 3) if denominator > 0 else 0.0


def calculate_babip_pitching(row: dict) -> float:
    ip = row.get("innings_pitched", 0)
    bf = ip * 3 + row.get("hits_allowed", 0) + row.get("walks", 0)
    numerator = row.get("hits_allowed", 0) - row.get("home_runs_allowed", 0)
    denominator = bf - row.get("strikeouts", 0) - row.get("home_runs_allowed", 0) - row.get("walks", 0)
    return round(numerator / denominator, 3) if denominator > 0 else 0.0


def calculate_wrc_plus(woba: float, lg_woba: float = WOBA_WEIGHTS["lg_woba"],
                        park_factor: float = 100.0, lg_runs_per_pa: float = WOBA_WEIGHTS["lg_runs_per_pa"],
                        woba_scale: float = WOBA_WEIGHTS["woba_scale"]) -> float:
    """Park and league adjusted wRC+. 100 = league average."""
    wrc_per_pa = ((woba - lg_woba) / woba_scale) + lg_runs_per_pa
    lg_wrc_per_pa = lg_runs_per_pa
    park_adj = park_factor / 100.0
    return round((wrc_per_pa / (lg_wrc_per_pa * park_adj)) * 100, 1)


def calculate_platoon_advantage(batter_hand: str, pitcher_hand: str) -> dict:
    """Returns expected wOBA boost/penalty for platoon matchup."""
    # Historical MLB platoon splits (approximate)
    same_hand_penalty = -0.020   # batter vs same-handed pitcher
    opp_hand_boost = 0.020
    if (batter_hand == "L" and pitcher_hand == "R") or (batter_hand == "R" and pitcher_hand == "L"):
        return {"advantage": "batter", "woba_delta": opp_hand_boost}
    if (batter_hand == "L" and pitcher_hand == "L") or (batter_hand == "R" and pitcher_hand == "R"):
        return {"advantage": "pitcher", "woba_delta": same_hand_penalty}
    return {"advantage": "neutral", "woba_delta": 0.0}  # switch hitter


def rank_players_by_position(players_df: pd.DataFrame, position: str, metric: str = "woba") -> pd.DataFrame:
    """Returns players at a position ranked by metric descending."""
    pos_df = players_df[
        players_df["position"].str.contains(position, na=False)
        | players_df["secondary_positions"].apply(
            lambda x: position in (x or [])
        )
    ].copy()
    return pos_df.sort_values(metric, ascending=False).reset_index(drop=True)


def value_contract(salary_millions: float, war: float, dollars_per_war: float = 8.0) -> dict:
    """
    Estimate surplus value of a player contract.
    Market value is floored at $0 — a below-replacement player can be released
    but doesn't have literal negative dollar value on the open market.
    """
    market_value = max(war * dollars_per_war, 0.0)   # floor at $0
    surplus = market_value - salary_millions
    return {
        "market_value_m": round(market_value, 2),
        "salary_m": salary_millions,
        "surplus_value_m": round(surplus, 2),
        "grade": "AAA" if surplus > 10 else "AA" if surplus > 5 else "A" if surplus > 0 else "B",
    }


def score_free_agent(player: dict, team_needs: list[str]) -> dict:
    """Score a free agent candidate against team positional needs and budget."""
    position_match = any(
        need in [player.get("position")] + (player.get("secondary_positions") or [])
        for need in team_needs
    )
    war = player.get("war", 0) or 0
    woba = player.get("woba", WOBA_WEIGHTS["lg_woba"]) or WOBA_WEIGHTS["lg_woba"]

    score = (
        (1.5 if position_match else 0.5)
        * (war * 10)
        * ((woba / WOBA_WEIGHTS["lg_woba"]) ** 2)
    )
    return {
        "player_id": player.get("id"),
        "name": player.get("full_name"),
        "position": player.get("position"),
        "position_match": position_match,
        "war": war,
        "woba": woba,
        "fit_score": round(score, 2),
    }
