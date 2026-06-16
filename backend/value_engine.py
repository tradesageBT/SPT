"""
Computes per-team value profiles from Sleeper roster data + cached FC values.
"""
import math
from cache_manager import resolve_pick_value

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]


def _percentile(sorted_vals: list[int], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = pct * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def _classify_contention(score: float, pick_ratio: float, strength_tier: str) -> str:
    """
    strength_tier (total-value rank vs. league) drives the category since a young,
    loaded roster is a great spot to be in — not a rebuild. Age/pick capital only
    shade the label within a strength tier.
    """
    if strength_tier == "top":
        if score >= 0.55:
            return "Championship Window"
        if score >= 0.4:
            return "Sustainable Contender"
        return "Ascending"
    if strength_tier == "mid":
        if score >= 0.55:
            return "Win-Now Push"
        if score >= 0.4:
            return "Treading Water"
        return "Ascending" if pick_ratio >= 1.0 else "Retooling"
    if score >= 0.55:
        return "Fire Sale"
    if score >= 0.4:
        return "Retooling"
    return "Full Rebuild" if pick_ratio >= 0.8 else "Treading Water"


def _player_entry(pid: str, players_cache: dict) -> dict:
    p = players_cache.get(pid, {})
    return {
        "sleeper_id": pid,
        "name": p.get("name", pid),
        "position": p.get("position", ""),
        "nfl_team": p.get("nfl_team", ""),
        "age": p.get("age"),
        "fc_value": p.get("fc_value", 0),
    }


_ROUND_LABEL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


def _pick_label(dp: dict, rmap: dict, ref_roster: int) -> str:
    orig = int(dp.get("roster_id", 0))
    rnd = int(dp.get("round", 0))
    season = dp.get("season", "")
    label = f"{season} {_ROUND_LABEL.get(rnd, f'Rd {rnd}')}"
    return f"{label} (own pick)" if orig == ref_roster else f"{label} ({rmap.get(orig, f'Team {orig}')})"


def _build_trade_chain(key: tuple, txn_list: list,
                       players_cache: dict, rmap: dict) -> list:
    """Return one entry per trade hop, sorted chronologically."""
    from datetime import datetime, timezone
    target_season, target_round, target_orig = str(key[0]), int(key[1]), int(key[2])
    hops = []

    for txn in sorted(txn_list, key=lambda t: t.get("created") or 0):
        pick_entry = next(
            (dp for dp in (txn.get("draft_picks") or [])
             if str(dp.get("season", "")) == target_season
             and int(dp.get("round", 0)) == target_round
             and int(dp.get("roster_id", 0)) == target_orig),
            None,
        )
        if not pick_entry:
            continue

        to_id = int(pick_entry.get("owner_id", 0))
        # Fall back to roster_id (original owner) if previous_owner_id not set
        raw_from = pick_entry.get("previous_owner_id") or pick_entry.get("roster_id")
        if not raw_from:
            continue
        from_id = int(raw_from)

        adds = txn.get("adds") or {}
        drops = txn.get("drops") or {}

        # What the acquirer (to_id) paid
        cost = []
        for pid, prev in drops.items():
            if int(prev) == to_id:
                p = players_cache.get(str(pid), {})
                name = p.get("name") or f"Player {pid}"
                pos = p.get("position", "")
                cost.append(f"{name} ({pos})" if pos else name)
        for dp in (txn.get("draft_picks") or []):
            if int(dp.get("previous_owner_id", -1)) == to_id:
                cost.append(_pick_label(dp, rmap, to_id))

        # What else the acquirer received in the same deal
        bonus = []
        for pid, new_owner in adds.items():
            if int(new_owner) == to_id:
                p = players_cache.get(str(pid), {})
                name = p.get("name") or f"Player {pid}"
                pos = p.get("position", "")
                bonus.append(f"{name} ({pos})" if pos else name)
        for dp in (txn.get("draft_picks") or []):
            if (int(dp.get("owner_id", 0)) == to_id
                    and not (str(dp.get("season", "")) == target_season
                             and int(dp.get("round", 0)) == target_round
                             and int(dp.get("roster_id", 0)) == target_orig)):
                bonus.append(_pick_label(dp, rmap, to_id))

        created = txn.get("created")
        date = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%b %d, %Y")
                if created else None)

        hops.append({
            "from": rmap.get(from_id, f"Team {from_id}"),
            "to": rmap.get(to_id, f"Team {to_id}"),
            "date": date,
            "cost": cost,
            "bonus": bonus,
        })

    return hops


def build_picks_by_roster(
    traded_picks: list[dict],
    num_teams: int,
    current_season: int,
    draft_rounds: int = 4,
    future_years: int = 3,
    roster_display_map: dict | None = None,
    transaction_map: dict | None = None,
    players_cache: dict | None = None,
) -> dict[int, list[dict]]:
    """
    Build a complete map of {roster_id: [picks_owned]} by combining:
    - Each team's own picks (implicitly owned unless traded away)
    - Any picks received in trades (from traded_picks endpoint)

    Only includes picks for seasons AFTER current_season (rookie draft for
    the current season is typically done once the league is in-season).
    """
    future_seasons = [str(current_season + i) for i in range(1, future_years + 1)]
    rmap = roster_display_map or {}

    # traded_picks tells us the CURRENT owner of every pick that changed hands.
    # roster_id = original team slot, owner_id = who holds it now.
    # Build a list of entries per pick key to capture multi-hop trades.
    traded_map: dict[tuple, dict] = {}
    for tp in traded_picks:
        key = (str(tp["season"]), int(tp["round"]), int(tp["roster_id"]))
        traded_map[key] = {
            "owner_id": int(tp["owner_id"]),
            "previous_owner_id": tp.get("previous_owner_id"),
        }

    # Also find picks that have been traded AWAY from their original owner
    # (they appear in traded_map with owner_id != roster_id)
    traded_away: set[tuple] = {
        key for key, info in traded_map.items() if info["owner_id"] != key[2]
    }

    by_roster: dict[int, list[dict]] = {i: [] for i in range(1, num_teams + 1)}

    for season in future_seasons:
        for rnd in range(1, draft_rounds + 1):
            for orig_roster in range(1, num_teams + 1):
                key = (season, rnd, orig_roster)
                if key in traded_map:
                    info = traded_map[key]
                    current_owner = info["owner_id"]
                    prev_id = info.get("previous_owner_id")
                    chain = [rmap.get(orig_roster, f"Team {orig_roster}")]
                    if prev_id and int(prev_id) != orig_roster and int(prev_id) != current_owner:
                        chain.append(rmap.get(int(prev_id), f"Team {prev_id}"))
                    trade_history = []
                    if transaction_map and players_cache:
                        trade_history = _build_trade_chain(
                            key, transaction_map.get(key, []), players_cache, rmap
                        )
                    by_roster[current_owner].append({
                        "season": season,
                        "round": rnd,
                        "original_roster_id": orig_roster,
                        "original_owner_name": rmap.get(orig_roster, f"Team {orig_roster}"),
                        "trade_chain": chain,
                        "trade_history": trade_history,
                        "own_pick": False,
                    })
                else:
                    by_roster[orig_roster].append({
                        "season": season,
                        "round": rnd,
                        "original_roster_id": orig_roster,
                        "original_owner_name": rmap.get(orig_roster, f"Team {orig_roster}"),
                        "trade_chain": [],
                        "own_pick": True,
                    })

    return by_roster


def compute_team_profile(
    roster: dict,
    users_map: dict,
    players_cache: dict,
    picks_cache: dict,
    roster_picks: list[dict] | None = None,
) -> dict:
    owner_id = roster.get("owner_id") or str(roster.get("roster_id", ""))
    user = users_map.get(owner_id, {})
    display_name = user.get("display_name", f"Team {roster['roster_id']}")
    avatar = user.get("avatar")

    taxi_ids: set[str] = set(p for p in (roster.get("taxi") or []) if p and p != "0")
    reserve_ids: set[str] = set(p for p in (roster.get("reserve") or []) if p and p != "0")

    # Sleeper keeps taxi/IR in separate arrays that may not appear in roster["players"]
    base_ids = set(pid for pid in (roster.get("players") or []) if pid and pid != "0")
    player_ids: list[str] = list(base_ids | taxi_ids | reserve_ids)

    starter_ids: set[str] = set(
        pid for pid in (roster.get("starters") or [])
        if pid and pid != "0"
    )
    picks: list[dict] = roster_picks or []

    player_value = 0
    starter_value = 0
    bench_value = 0
    positional: dict[str, int] = {p: 0 for p in SKILL_POSITIONS}
    positional_starters: dict[str, list[int]] = {p: [] for p in SKILL_POSITIONS}
    age_weighted_sum = 0.0
    age_weight_total = 0.0
    enriched_players: list[dict] = []

    for pid in player_ids:
        entry = _player_entry(pid, players_cache)
        value = entry["fc_value"]
        pos = entry["position"]
        age = entry.get("age") or 25.0

        player_value += value
        is_starter = pid in starter_ids
        on_taxi = pid in taxi_ids
        on_ir = pid in reserve_ids

        if is_starter:
            starter_value += value
        elif not on_taxi and not on_ir:
            bench_value += value

        if pos in positional:
            positional[pos] += value
            if is_starter:
                positional_starters[pos].append(value)

        if value > 0:
            age_w = max(0.0, min(1.0, (age - 22.0) / 10.0))
            age_weighted_sum += age_w * value
            age_weight_total += value

        enriched_players.append({
            **entry,
            "is_starter": is_starter,
            "on_taxi": on_taxi,
            "on_ir": on_ir,
        })

    # Pick values
    pick_value = 0
    enriched_picks: list[dict] = []
    for pick in picks:
        season = pick.get("season", "")
        rnd = pick.get("round", 1)
        pv = resolve_pick_value(picks_cache, season, rnd)
        pick_value += pv
        enriched_picks.append({
            "season": season,
            "round": rnd,
            "original_roster_id": pick.get("original_roster_id"),
            "original_owner_name": pick.get("original_owner_name", ""),
            "trade_chain": pick.get("trade_chain", []),
            "trade_history": pick.get("trade_history", []),
            "own_pick": pick.get("own_pick", True),
            "fc_value": pv,
        })

    # Sort picks by season then round for display
    enriched_picks.sort(key=lambda x: (x["season"], x["round"]))

    total_value = player_value + pick_value
    contention_score = (
        age_weighted_sum / age_weight_total if age_weight_total > 0 else 0.5
    )

    return {
        "roster_id": roster["roster_id"],
        "owner_id": owner_id,
        "display_name": display_name,
        "avatar": avatar,
        "total_value": total_value,
        "player_value": player_value,
        "pick_value": pick_value,
        "starter_value": starter_value,
        "bench_value": bench_value,
        "positional_breakdown": positional,
        "positional_starter_value": {pos: sum(vals) for pos, vals in positional_starters.items()},
        "positional_starters": positional_starters,  # raw per-slot values, stripped before persisting
        "positional_surplus": {},   # filled after league-wide pass
        "positional_need": {},      # filled after league-wide pass
        "contention_score": round(contention_score, 3),
        "contention_category": "Treading Water",  # filled after league-wide pass
        "players": enriched_players,
        "picks": enriched_picks,
    }


def compute_league_profiles(
    rosters: list[dict],
    users_map: dict,
    players_cache: dict,
    picks_cache: dict,
    picks_by_roster: dict | None = None,
) -> list[dict]:
    profiles = [
        compute_team_profile(
            r,
            users_map,
            players_cache,
            picks_cache,
            roster_picks=(picks_by_roster or {}).get(r["roster_id"]),
        )
        for r in rosters
    ]

    # Starter-value comparison: only value that actually plays each week counts,
    # so bench depth doesn't mask a thin starting lineup (or vice versa).
    n = len(profiles)
    league_avg_starters: dict[str, float] = {p: 0.0 for p in SKILL_POSITIONS}
    if n:
        for pos in SKILL_POSITIONS:
            league_avg_starters[pos] = sum(
                t["positional_starter_value"].get(pos, 0) for t in profiles
            ) / n

    # Slot-based need: where does a team's starter at this position rank against
    # every other starter league-wide at the same position?
    all_starters_by_pos: dict[str, list[int]] = {p: [] for p in SKILL_POSITIONS}
    for t in profiles:
        for pos in SKILL_POSITIONS:
            all_starters_by_pos[pos].extend(t["positional_starters"].get(pos, []))
    p25 = {pos: _percentile(sorted(vals), 0.25) for pos, vals in all_starters_by_pos.items()}
    p75 = {pos: _percentile(sorted(vals), 0.75) for pos, vals in all_starters_by_pos.items()}

    for profile in profiles:
        surplus: dict[str, float] = {}
        need: dict[str, str] = {}
        for pos in SKILL_POSITIONS:
            avg = league_avg_starters[pos]
            team_val = profile["positional_starter_value"].get(pos, 0)
            surplus[pos] = round((team_val - avg) / avg * 100, 1) if avg > 0 else 0.0

            starters_at_pos = profile["positional_starters"].get(pos, [])
            if not starters_at_pos:
                need[pos] = "Need"
            elif min(starters_at_pos) < p25[pos]:
                need[pos] = "Need"
            elif max(starters_at_pos) > p75[pos]:
                need[pos] = "Strength"
            else:
                need[pos] = "Adequate"
        profile["positional_surplus"] = surplus
        profile["positional_need"] = need
        del profile["positional_starters"]

    # Tailored contention categories — blend roster age (contention_score) with
    # future draft capital and overall roster strength rather than a flat 3-way split.
    league_avg_pick_value = sum(p["pick_value"] for p in profiles) / n if n else 0
    by_total_value = sorted(profiles, key=lambda t: t["total_value"], reverse=True)
    value_rank: dict[int, int] = {
        p["roster_id"]: rank for rank, p in enumerate(by_total_value, start=1)
    }
    top_cut = math.ceil(n / 3) if n else 0

    for profile in profiles:
        pick_ratio = (
            profile["pick_value"] / league_avg_pick_value if league_avg_pick_value > 0 else 1.0
        )
        rank = value_rank[profile["roster_id"]]
        if rank <= top_cut:
            strength_tier = "top"
        elif rank > n - top_cut:
            strength_tier = "bottom"
        else:
            strength_tier = "mid"
        profile["contention_category"] = _classify_contention(
            profile["contention_score"], pick_ratio, strength_tier
        )

    # Estimate projected pick slot using current player value as standings proxy.
    # Worst player value → picks first (slot 1). ±1 pick gives the range.
    sorted_by_strength = sorted(profiles, key=lambda t: t["player_value"])
    roster_rank: dict[int, int] = {
        p["roster_id"]: rank for rank, p in enumerate(sorted_by_strength, start=1)
    }
    num_teams = len(profiles)

    for profile in profiles:
        for pick in profile["picks"]:
            orig_id = pick.get("original_roster_id")
            rank = roster_rank.get(orig_id) if orig_id else None
            if rank is not None:
                rnd = pick["round"]
                lo = max(1, rank - 1)
                hi = min(num_teams, rank + 1)
                pick["projected_slot"] = f"{rnd}.{lo:02d}–{rnd}.{hi:02d}"

    return sorted(profiles, key=lambda t: t["total_value"], reverse=True)
