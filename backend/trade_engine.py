"""
Smash / Pass / Trash categorization and trade idea generation.
"""
from collections import defaultdict
from itertools import combinations

SMASH_VALUE = 4000
PASS_VALUE  = 1200
TRASH_VALUE = 400

FAIRNESS_PCT    = 0.15   # trades within 15% raw-value delta accepted
MIN_SIDE_VALUE  = 500    # filter out near-zero-value assets
SKILL_POS       = {"QB", "RB", "WR", "TE"}


# ---------------------------------------------------------------------------
# Smash / Pass / Trash categorization
# ---------------------------------------------------------------------------

def categorize_players(profile: dict) -> dict:
    smash, passable, trash = [], [], []

    starter_set = {p["sleeper_id"] for p in profile["players"] if p.get("is_starter")}
    players = profile["players"]  # include taxi and IR

    sorted_by_value = sorted(
        [p for p in players if not p.get("on_ir") and not p.get("on_taxi")],
        key=lambda x: x["fc_value"], reverse=True,
    )
    top_two_ids = {p["sleeper_id"] for p in sorted_by_value[:2]}

    for p in players:
        v = p["fc_value"]
        is_starter = p["sleeper_id"] in starter_set
        is_top = p["sleeper_id"] in top_two_ids
        entry = {**p, "is_top": is_top}

        if is_top or (v >= SMASH_VALUE and is_starter):
            smash.append(entry)
        elif v >= PASS_VALUE:
            passable.append(entry)
        else:
            trash.append(entry)

    return {
        "smash": sorted(smash, key=lambda x: x["fc_value"], reverse=True),
        "pass":  sorted(passable, key=lambda x: x["fc_value"], reverse=True),
        "trash": sorted(trash, key=lambda x: x["fc_value"], reverse=True),
    }


# ---------------------------------------------------------------------------
# Lineup delta — the core new metric
# ---------------------------------------------------------------------------

def _build_roster_state(team_profile: dict):
    """Return (starters, bench, slots) dicts for simulation."""
    starters: dict[str, list[int]] = defaultdict(list)
    bench:    dict[str, list[int]] = defaultdict(list)

    for p in team_profile.get("players", []):
        if p.get("on_taxi") or p.get("on_ir"):
            continue
        pos = p.get("position", "")
        if pos not in SKILL_POS:
            continue
        val = p.get("fc_value", 0)
        if p.get("is_starter"):
            starters[pos].append(val)
        else:
            bench[pos].append(val)

    for pos in starters:
        starters[pos].sort(reverse=True)
    for pos in bench:
        bench[pos].sort(reverse=True)

    slots = {pos: len(vals) for pos, vals in starters.items()}
    return starters, bench, slots


def compute_trade_breakdown(
    team_profile: dict,
    gives: list[dict],
    receives: list[dict],
) -> dict:
    """
    Detailed breakdown of a trade's impact on this team's roster.

    Returns:
      starters_lost   – value of given players who were starters
      bench_lost      – value of given players who were bench
      starters_gained – value of received players who would start
      bench_gained    – value of received players who would bench
      lineup_delta    – net change in starting lineup value after simulation
                        (accounts for bench fill-ins when starters leave)
    """
    starters, bench, slots = _build_roster_state(team_profile)

    # Categorise given players before touching the roster
    starters_lost = 0
    bench_lost    = 0

    # Build a lookup of who is currently a starter by position+value
    starter_set = {p["sleeper_id"] for p in team_profile.get("players", []) if p.get("is_starter")}

    for p in gives:
        if p.get("position") not in SKILL_POS:
            continue
        if p.get("sleeper_id") in starter_set:
            starters_lost += p.get("fc_value", 0)
        else:
            bench_lost += p.get("fc_value", 0)

    before = sum(sum(v) for v in starters.values())

    # --- Simulate removes ---
    for p in gives:
        pos = p.get("position", "")
        val = p.get("fc_value", 0)
        if pos not in SKILL_POS:
            continue
        if val in starters.get(pos, []):
            starters[pos].remove(val)
            if bench.get(pos):
                promoted = bench[pos].pop(0)
                starters[pos].append(promoted)
                starters[pos].sort(reverse=True)
        elif val in bench.get(pos, []):
            bench[pos].remove(val)

    # --- Simulate adds, tracking who starts vs benches ---
    starters_gained = 0
    bench_gained    = 0

    for p in receives:
        pos = p.get("position", "")
        val = p.get("fc_value", 0)
        if pos not in SKILL_POS:
            continue

        n_slots   = slots.get(pos, 0)
        n_current = len(starters.get(pos, []))

        if n_current < n_slots:
            starters[pos].append(val)
            starters[pos].sort(reverse=True)
            starters_gained += val
        elif starters.get(pos) and val > min(starters[pos]):
            worst = min(starters[pos])
            starters[pos].remove(worst)
            starters[pos].append(val)
            starters[pos].sort(reverse=True)
            bench[pos].append(worst)
            bench[pos].sort(reverse=True)
            starters_gained += val        # this player will start
        else:
            bench[pos].append(val)
            bench_gained += val

    after = sum(sum(v) for v in starters.values())

    return {
        "starters_lost":   starters_lost,
        "bench_lost":      bench_lost,
        "starters_gained": starters_gained,
        "bench_gained":    bench_gained,
        "lineup_delta":    after - before,
    }


def compute_lineup_delta(team_profile: dict, gives: list[dict], receives: list[dict]) -> int:
    return compute_trade_breakdown(team_profile, gives, receives)["lineup_delta"]


# ---------------------------------------------------------------------------
# Trade generation helpers
# ---------------------------------------------------------------------------

def _value(items: list[dict]) -> int:
    return sum(x.get("fc_value", 0) for x in items)


def _is_fair(v_a: int, v_b: int) -> bool:
    if v_a == 0 and v_b == 0:
        return True
    return abs(v_a - v_b) / max(v_a, v_b, 1) <= FAIRNESS_PCT


def _surplus_positions(profile: dict) -> list[str]:
    return [pos for pos, pct in profile.get("positional_surplus", {}).items() if pct > 10]


def _deficit_positions(profile: dict) -> list[str]:
    return [pos for pos, pct in profile.get("positional_surplus", {}).items() if pct < -10]


# ---------------------------------------------------------------------------
# Core trade generator
# ---------------------------------------------------------------------------

def generate_trades_between(
    team_a: dict,
    team_b: dict,
    cat_a: dict,
    cat_b: dict,
    include_smash: bool = False,
    include_picks: bool = False,
    force_mode: bool = False,
) -> list[dict]:
    trades = []

    surplus_a = set(_surplus_positions(team_a))
    deficit_a = set(_deficit_positions(team_a))
    surplus_b = set(_surplus_positions(team_b))
    deficit_b = set(_deficit_positions(team_b))

    tradeable_a = list(cat_a["pass"])
    tradeable_b = list(cat_b["pass"])

    # In force mode always include smash on both sides — needed to match high-value players
    if include_smash or force_mode:
        tradeable_a += cat_a.get("smash", [])
        tradeable_b += cat_b.get("smash", [])

    picks_a = [_pick_asset(p) for p in sorted(team_a.get("picks", []), key=lambda x: x["fc_value"], reverse=True)[:4]]
    picks_b = [_pick_asset(p) for p in sorted(team_b.get("picks", []), key=lambda x: x["fc_value"], reverse=True)[:4]]

    if include_picks or force_mode:
        tradeable_a += picks_a
        tradeable_b += picks_b

    fairness_pct = FAIRNESS_PCT * (4/3 if force_mode else 1)  # 20% window in force mode

    def _build_trade(gives_a, gives_b, reason):
        val_a = _value(gives_a)
        val_b = _value(gives_b)
        if val_a < MIN_SIDE_VALUE or val_b < MIN_SIDE_VALUE:
            return None
        if abs(val_a - val_b) / max(val_a, val_b, 1) > fairness_pct:
            return None

        breakdown_a = compute_trade_breakdown(team_a, gives_a, gives_b)
        breakdown_b = compute_trade_breakdown(team_b, gives_b, gives_a)

        return {
            "team_a": {"roster_id": team_a["roster_id"], "display_name": team_a["display_name"]},
            "team_b": {"roster_id": team_b["roster_id"], "display_name": team_b["display_name"]},
            "a_gives": gives_a,
            "b_gives": gives_b,
            "value_a_gives": val_a,
            "value_b_gives": val_b,
            "value_delta": abs(val_a - val_b),
            "lineup_delta_a": breakdown_a["lineup_delta"],
            "lineup_delta_b": breakdown_b["lineup_delta"],
            "breakdown_a": breakdown_a,
            "breakdown_b": breakdown_b,
            "reason": reason,
        }

    # --- 1-for-1 ---
    for pa in tradeable_a:
        for pb in tradeable_b:
            if not _is_fair(pa["fc_value"], pb["fc_value"]):
                continue
            pos_a = pa.get("position", "")
            pos_b = pb.get("position", "")
            is_pick_trade = pos_a == "PK" or pos_b == "PK"
            gives_sense = pos_a in (surplus_a & deficit_b)
            gets_sense  = pos_b in (surplus_b & deficit_a)
            # In force mode skip positional filter — show all value-matched 1-for-1s
            if not (force_mode or is_pick_trade or gives_sense or gets_sense):
                continue
            t = _build_trade(
                [pa], [pb],
                f"1-for-1: {team_a['display_name']} {pos_a} ↔ {team_b['display_name']} {pos_b}",
            )
            if t:
                trades.append(t)

    # --- 2-for-1 ---
    for pa1, pa2 in combinations(tradeable_a, 2):
        for pb in tradeable_b:
            if not _is_fair(_value([pa1, pa2]), pb["fc_value"]):
                continue
            t = _build_trade(
                [pa1, pa2], [pb],
                f"2-for-1: {team_a['display_name']} consolidates depth",
            )
            if t:
                trades.append(t)

    for pb1, pb2 in combinations(tradeable_b, 2):
        for pa in tradeable_a:
            if not _is_fair(pa["fc_value"], _value([pb1, pb2])):
                continue
            t = _build_trade(
                [pa], [pb1, pb2],
                f"2-for-1: {team_b['display_name']} consolidates depth",
            )
            if t:
                trades.append(t)

    # --- Pick for player (rebuilder ↔ win-now; skip when picks already in pool) ---
    if not include_picks and not force_mode:
        a_rebuild = team_a.get("contention_score", 0.5) < 0.4
        b_rebuild = team_b.get("contention_score", 0.5) < 0.4

        if a_rebuild and not b_rebuild:
            for pick in sorted(team_a.get("picks", []), key=lambda x: x["fc_value"], reverse=True)[:3]:
                for pb in tradeable_b:
                    if _is_fair(pick["fc_value"], pb["fc_value"]):
                        pk = _pick_asset(pick)
                        t = _build_trade([pk], [pb], f"Rebuild: {team_a['display_name']} pick → player")
                        if t:
                            trades.append(t)

        if b_rebuild and not a_rebuild:
            for pick in sorted(team_b.get("picks", []), key=lambda x: x["fc_value"], reverse=True)[:3]:
                for pa in tradeable_a:
                    if _is_fair(pa["fc_value"], pick["fc_value"]):
                        pk = _pick_asset(pick)
                        t = _build_trade([pa], [pk], f"Rebuild: {team_b['display_name']} pick → player")
                        if t:
                            trades.append(t)

    # --- Dedupe ---
    seen = set()
    unique = []
    for t in trades:
        key = tuple(sorted(x["sleeper_id"] for x in t["a_gives"] + t["b_gives"]))
        if key not in seen:
            seen.add(key)
            unique.append(t)

    # Sort: both-sides-upgrade first, then by combined lineup improvement, then value fairness
    def _sort_key(t):
        ld_a = t["lineup_delta_a"]
        ld_b = t["lineup_delta_b"]
        both_up   = -(ld_a > 0 and ld_b > 0)
        one_up    = -(ld_a > 0 or  ld_b > 0)
        combined  = -(ld_a + ld_b)
        return (both_up, one_up, combined, t["value_delta"])

    cap = 25 if force_mode else 10
    return sorted(unique, key=_sort_key)[:cap]


def _pick_asset(pick: dict) -> dict:
    return {
        "sleeper_id": f"pick_{pick['season']}_{pick['round']}",
        "name": f"{pick['season']} Rd {pick['round']}",
        "position": "PK",
        "fc_value": pick["fc_value"],
    }


def generate_all_trades(
    profiles: list[dict],
    include_smash: bool = False,
    include_picks: bool = False,
    force_mode: bool = False,
) -> list[dict]:
    cats = {p["roster_id"]: categorize_players(p) for p in profiles}
    all_trades = []
    for a, b in combinations(profiles, 2):
        all_trades.extend(
            generate_trades_between(
                a, b, cats[a["roster_id"]], cats[b["roster_id"]],
                include_smash=include_smash,
                include_picks=include_picks,
                force_mode=force_mode,
            )
        )
    return all_trades
