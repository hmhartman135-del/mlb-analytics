"""
MLB lineup optimizer — full 26-man roster breakdown.

Given the 26-man active roster, produces:
  • Starting lineup (9) with batting order and platoon indicators
  • Bench (remaining position players) with role descriptions
  • Rotation (all SPs ranked by quality)
  • Bullpen (all RPs with assigned roles)
"""
from dataclasses import dataclass, field
from .analytics import calculate_platoon_advantage, WOBA_WEIGHTS


BATTING_ORDER_MULTIPLIERS = [1.05, 1.08, 1.10, 1.08, 1.05, 1.03, 1.01, 0.99, 0.97]
FIELD_POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class LineupSlot:
    batting_order: int
    position: str
    player_id: str
    player_name: str
    wrc_plus: float
    woba: float
    bats: str
    adjusted_score: float = 0.0
    platoon: str = "neutral"          # "advantage" | "disadvantage" | "neutral"


@dataclass
class BenchSlot:
    player_id: str
    player_name: str
    position: str
    bats: str
    wrc_plus: float
    woba: float
    role: str                         # "Backup Catcher" | "Platoon Bat" | "Bench Bat" | "Utility"
    use_when: str


@dataclass
class PitcherSlot:
    player_id: str
    player_name: str
    throws: str
    era: float
    fip: float
    ip: float
    games: int
    saves: int
    role: str
    use_when: str


@dataclass
class FullRosterResult:
    starting_lineup: list[LineupSlot] = field(default_factory=list)
    bench: list[BenchSlot] = field(default_factory=list)
    rotation: list[PitcherSlot] = field(default_factory=list)
    bullpen: list[PitcherSlot] = field(default_factory=list)
    total_score: float = 0.0
    opposing_pitcher_hand: str = "R"
    park_factor: float = 100.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def slot_d(s: LineupSlot) -> dict:
            return {
                "order": s.batting_order,
                "position": s.position,
                "player_id": s.player_id,
                "player_name": s.player_name,
                "wrc_plus": s.wrc_plus,
                "woba": s.woba,
                "bats": s.bats,
                "adjusted_score": s.adjusted_score,
                "platoon": s.platoon,
            }

        def bench_d(b: BenchSlot) -> dict:
            return {
                "player_id": b.player_id,
                "player_name": b.player_name,
                "position": b.position,
                "bats": b.bats,
                "wrc_plus": b.wrc_plus,
                "woba": b.woba,
                "role": b.role,
                "use_when": b.use_when,
            }

        def pit_d(p: PitcherSlot) -> dict:
            return {
                "player_id": p.player_id,
                "player_name": p.player_name,
                "throws": p.throws,
                "era": p.era,
                "fip": p.fip,
                "ip": p.ip,
                "games": p.games,
                "saves": p.saves,
                "role": p.role,
                "use_when": p.use_when,
            }

        return {
            "starting_lineup": [slot_d(s) for s in sorted(self.starting_lineup, key=lambda x: x.batting_order)],
            "bench": [bench_d(b) for b in self.bench],
            "pitching_staff": {
                "rotation": [pit_d(p) for p in self.rotation],
                "bullpen": [pit_d(p) for p in self.bullpen],
            },
            "total_score": round(self.total_score, 2),
            "park_factor": self.park_factor,
            "opposing_pitcher_hand": self.opposing_pitcher_hand,
            "warnings": self.warnings,
        }


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _player_score(player: dict, opposing_pitcher_hand: str, park_factor: float) -> float:
    """Platoon + park-adjusted wRC+ score."""
    wrc = player.get("wrc_plus") or 100.0
    platoon = calculate_platoon_advantage(player.get("bats", "R"), opposing_pitcher_hand)
    platoon_adj = 1.0 + (platoon["woba_delta"] / WOBA_WEIGHTS["lg_woba"])
    park_adj = park_factor / 100.0
    return wrc * platoon_adj * park_adj


def _platoon_label(bats: str, opposing_hand: str) -> str:
    p = calculate_platoon_advantage(bats, opposing_hand)
    return p["advantage"]   # "batter" | "pitcher" | "neutral"


def _bench_role(player: dict, opposing_hand: str) -> tuple[str, str]:
    """Return (role_label, use_when) for a bench player."""
    pos = player.get("position", "")
    bats = player.get("bats", "R")

    if pos == "C":
        return "Backup Catcher", "Rest day for starter or late-game defense"

    platoon_adv = _platoon_label(bats, opposing_hand)
    opp_str = "RHP" if opposing_hand == "R" else "LHP"
    flip_str = "LHP" if opposing_hand == "R" else "RHP"

    if platoon_adv == "batter":
        return "Platoon Bat", f"Pinch hit vs today's {opp_str} — platoon advantage"
    elif platoon_adv == "pitcher":
        return "Platoon Bat", f"Start on days vs {flip_str} — sits today (same-hand matchup)"

    return "Bench Bat", "Available in any matchup"


# ── Bullpen role assignment ───────────────────────────────────────────────────

def _assign_bullpen_roles(relievers: list[dict]) -> list[PitcherSlot]:
    if not relievers:
        return []

    by_saves = sorted(relievers, key=lambda x: x.get("saves") or 0, reverse=True)
    by_fip   = sorted(relievers, key=lambda x: x.get("fip") or 4.50)

    used: set[str] = set()
    result: list[PitcherSlot] = []

    def make_slot(p: dict, role: str, use_when: str) -> PitcherSlot:
        return PitcherSlot(
            player_id=p["id"],
            player_name=p["full_name"],
            throws=p.get("throws", "R"),
            era=round(p.get("era") or 0.0, 2),
            fip=round(p.get("fip") or 0.0, 2),
            ip=round(p.get("ip") or 0.0, 1),
            games=p.get("games") or 0,
            saves=p.get("saves") or 0,
            role=role,
            use_when=use_when,
        )

    # 1. Closer — most saves; fall back to best FIP
    closer = by_saves[0] if (by_saves[0].get("saves") or 0) > 0 else by_fip[0]
    used.add(closer["id"])
    result.append(make_slot(closer, "Closer", "Save situations, 9th inning"))

    # 2. Setup — best FIP remaining
    for p in by_fip:
        if p["id"] not in used:
            used.add(p["id"])
            result.append(make_slot(p, "Setup", "7th–8th inning, protect leads"))
            break

    # 3. Lefty Specialist — best LHP not yet assigned
    lhp = [p for p in by_fip if p.get("throws") == "L" and p["id"] not in used]
    if lhp:
        p = lhp[0]
        used.add(p["id"])
        result.append(make_slot(p, "Lefty Specialist", "Key LHH matchups with runners on"))

    # 4. High-Leverage — next best FIP
    for p in by_fip:
        if p["id"] not in used:
            used.add(p["id"])
            result.append(make_slot(p, "High-Leverage", "6th–7th inning, game on the line"))
            break

    # 5. Remaining — Middle Relief or Long Man
    for p in by_fip:
        if p["id"] not in used:
            used.add(p["id"])
            gs = p.get("games_started") or 0
            ip = p.get("ip") or 0.0
            if gs > 0 or ip > 20:
                role, when = "Long Man", "Early starter exit or doubleheaders"
            else:
                role, when = "Middle Relief", "5th–7th inning, eat innings"
            result.append(make_slot(p, role, when))

    return result


# ── Batting order ─────────────────────────────────────────────────────────────

def _assign_batting_order(players: list[dict]) -> dict[str, int]:
    """
    Sabermetric batting order.
    1-2: Best OBP men (get on base most, see most PAs)
    3-5: Best overall hitters (most RBI opportunities)
    6-8: Remaining, descending quality
    9:   Worst hitter
    """
    if not players:
        return {}

    by_obp   = sorted(players, key=lambda p: p.get("obp") or 0.319, reverse=True)
    by_score = sorted(players, key=lambda p: p["_score"], reverse=True)
    by_power = sorted(players, key=lambda p: (
        (p.get("slg") or 0.400) - (p.get("avg") or 0.250)
    ), reverse=True)

    used: set[str] = set()
    order: list[dict] = []

    def pick(pool: list[dict]) -> dict | None:
        for p in pool:
            if p["id"] not in used:
                used.add(p["id"])
                return p
        return None

    # 1-2: OBP
    for _ in range(2):
        p = pick(by_obp)
        if p:
            order.append(p)

    # 3-5: Overall score (best hitters)
    for _ in range(3):
        p = pick(by_score)
        if p:
            order.append(p)

    # 6-8: Remaining by score
    for _ in range(3):
        p = pick(by_score)
        if p:
            order.append(p)

    # 9: Last remaining
    p = pick(by_score)
    if p:
        order.append(p)

    return {p["id"]: i + 1 for i, p in enumerate(order)}


# ── Main entry point ──────────────────────────────────────────────────────────

def optimize_full_roster(
    position_players: list[dict],
    starters: list[dict],
    relievers: list[dict],
    opposing_pitcher_hand: str = "R",
    park_factor: float = 100.0,
    locked_positions: dict[str, str] | None = None,
    exclude_player_ids: list[str] | None = None,
) -> FullRosterResult:
    """
    Build the full 26-man game plan:
      - Optimal 9-man starting lineup with batting order
      - Bench with role descriptions
      - Rotation and bullpen with roles

    Each position_player dict must have: id, full_name, position, bats,
    wrc_plus, woba, obp, slg, avg.

    Each starter/reliever dict must have: id, full_name, throws,
    era, fip, ip, games, games_started, saves.
    """
    exclude_ids = set(exclude_player_ids or [])
    locked = locked_positions or {}
    result = FullRosterResult(
        opposing_pitcher_hand=opposing_pitcher_hand,
        park_factor=park_factor,
    )

    # ── Position players ──────────────────────────────────────────────────────
    eligible = [p for p in position_players if p["id"] not in exclude_ids]

    for p in eligible:
        p["_score"] = _player_score(p, opposing_pitcher_hand, park_factor)

    assigned: dict[str, dict] = {}   # field_position → player
    used_ids: set[str] = set()

    # Honour locked positions first
    for pos, pid in locked.items():
        match = next((p for p in eligible if p["id"] == pid), None)
        if match:
            assigned[pos] = match
            used_ids.add(pid)
        else:
            result.warnings.append(f"Locked player {pid} for {pos} not found")

    # Assign each field position to the best available player
    for pos in FIELD_POSITIONS:
        if pos in assigned:
            continue
        candidates = sorted(
            [p for p in eligible if p.get("position") == pos and p["id"] not in used_ids],
            key=lambda p: p["_score"],
            reverse=True,
        )
        if candidates:
            assigned[pos] = candidates[0]
            used_ids.add(candidates[0]["id"])
        else:
            result.warnings.append(f"No player found for {pos}")

    # DH: best remaining position player
    remaining = sorted(
        [p for p in eligible if p["id"] not in used_ids],
        key=lambda p: p["_score"],
        reverse=True,
    )
    if remaining:
        assigned["DH"] = remaining[0]
        used_ids.add(remaining[0]["id"])
        bench_players = remaining[1:]
    else:
        bench_players = []

    # ── Batting order ─────────────────────────────────────────────────────────
    order_map = _assign_batting_order(list(assigned.values()))

    total = 0.0
    for pos, player in assigned.items():
        bat_order = order_map.get(player["id"], 9)
        platoon = _platoon_label(player.get("bats", "R"), opposing_pitcher_hand)
        # map "batter" → "advantage", "pitcher" → "disadvantage"
        platoon_str = "advantage" if platoon == "batter" else ("disadvantage" if platoon == "pitcher" else "neutral")

        slot = LineupSlot(
            batting_order=bat_order,
            position=pos,
            player_id=player["id"],
            player_name=player["full_name"],
            wrc_plus=round(player.get("wrc_plus") or 100.0, 1),
            woba=round(player.get("woba") or WOBA_WEIGHTS["lg_woba"], 3),
            bats=player.get("bats", "R"),
            adjusted_score=round(player["_score"], 2),
            platoon=platoon_str,
        )
        idx = bat_order - 1
        multiplier = BATTING_ORDER_MULTIPLIERS[idx] if 0 <= idx < len(BATTING_ORDER_MULTIPLIERS) else 1.0
        total += slot.adjusted_score * multiplier
        result.starting_lineup.append(slot)

    result.total_score = total

    # ── Bench ─────────────────────────────────────────────────────────────────
    for p in bench_players:
        role, use_when = _bench_role(p, opposing_pitcher_hand)
        result.bench.append(BenchSlot(
            player_id=p["id"],
            player_name=p["full_name"],
            position=p.get("position", ""),
            bats=p.get("bats", "R"),
            wrc_plus=round(p.get("wrc_plus") or 100.0, 1),
            woba=round(p.get("woba") or WOBA_WEIGHTS["lg_woba"], 3),
            role=role,
            use_when=use_when,
        ))

    # ── Pitching staff ────────────────────────────────────────────────────────
    # Rotation: SPs sorted best-FIP first
    for sp in sorted(starters, key=lambda x: x.get("fip") or 4.50):
        result.rotation.append(PitcherSlot(
            player_id=sp["id"],
            player_name=sp["full_name"],
            throws=sp.get("throws", "R"),
            era=round(sp.get("era") or 0.0, 2),
            fip=round(sp.get("fip") or 0.0, 2),
            ip=round(sp.get("ip") or 0.0, 1),
            games=sp.get("games") or 0,
            saves=0,
            role="Starting Pitcher",
            use_when="Regular rotation turn",
        ))

    result.bullpen = _assign_bullpen_roles(relievers)

    return result


# ── Legacy shim (keeps old callers working) ───────────────────────────────────

@dataclass
class LineupResult:
    """Backward-compat wrapper — delegates to FullRosterResult."""
    slots: list[LineupSlot] = field(default_factory=list)
    total_score: float = 0.0
    opposing_pitcher_hand: str = "R"
    park_factor: float = 100.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "lineup": [
                {
                    "order": s.batting_order,
                    "position": s.position,
                    "player_id": s.player_id,
                    "player_name": s.player_name,
                    "wrc_plus": s.wrc_plus,
                    "woba": s.woba,
                    "bats": s.bats,
                    "adjusted_score": s.adjusted_score,
                }
                for s in sorted(self.slots, key=lambda x: x.batting_order)
            ],
            "total_score": round(self.total_score, 2),
            "park_factor": self.park_factor,
            "opposing_pitcher_hand": self.opposing_pitcher_hand,
            "warnings": self.warnings,
        }


def optimize_lineup(
    available_players: list[dict],
    opposing_pitcher_hand: str = "R",
    park_factor: float = 100.0,
    locked_positions: dict[str, str] | None = None,
    exclude_player_ids: list[str] | None = None,
) -> LineupResult:
    """Legacy entry point — wraps optimize_full_roster for old callers."""
    pos_players = [p for p in available_players if p.get("position") not in ("SP", "RP")]
    full = optimize_full_roster(
        position_players=pos_players,
        starters=[],
        relievers=[],
        opposing_pitcher_hand=opposing_pitcher_hand,
        park_factor=park_factor,
        locked_positions=locked_positions,
        exclude_player_ids=exclude_player_ids,
    )
    result = LineupResult(
        opposing_pitcher_hand=opposing_pitcher_hand,
        park_factor=park_factor,
        warnings=full.warnings,
        total_score=full.total_score,
    )
    result.slots = full.starting_lineup
    return result
