"""
Computes per-team value profiles from Sleeper roster data + cached FC values.
"""
from cache_manager import resolve_pick_value

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]


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


def build_picks_by_roster(
    traded_picks: list[dict],
    num_teams: int,
    current_season: int,
    draft_rounds: int = 4,
    future_years: int = 3,
    roster_display_map: dict | None = None,
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
                    # Build trade chain: original → (previous holders) → current
                    chain = [rmap.get(orig_roster, f"Team {orig_roster}")]
                    if prev_id and int(prev_id) != orig_roster and int(prev_id) != current_owner:
                        chain.append(rmap.get(int(prev_id), f"Team {prev_id}"))
                    by_roster[current_owner].append({
                        "season": season,
                        "round": rnd,
                        "original_roster_id": orig_roster,
                        "original_owner_name": rmap.get(orig_roster, f"Team {orig_roster}"),
                        "trade_chain": chain,
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

    player_ids: list[str] = [
        pid for pid in (roster.get("players") or [])
        if pid and pid != "0"
    ]
    starter_ids: set[str] = set(
        pid for pid in (roster.get("starters") or [])
        if pid and pid != "0"
    )
    taxi_ids: set[str] = set(roster.get("taxi") or [])
    reserve_ids: set[str] = set(roster.get("reserve") or [])
    picks: list[dict] = roster_picks or []

    player_value = 0
    starter_value = 0
    bench_value = 0
    positional: dict[str, int] = {p: 0 for p in SKILL_POSITIONS}
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
        "positional_surplus": {},  # filled after league-wide pass
        "contention_score": round(contention_score, 3),
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

    # League-average positional values
    league_avg: dict[str, float] = {p: 0.0 for p in SKILL_POSITIONS}
    n = len(profiles)
    if n:
        for pos in SKILL_POSITIONS:
            league_avg[pos] = sum(
                t["positional_breakdown"].get(pos, 0) for t in profiles
            ) / n

    for profile in profiles:
        surplus: dict[str, float] = {}
        for pos in SKILL_POSITIONS:
            avg = league_avg[pos]
            team_val = profile["positional_breakdown"].get(pos, 0)
            if avg > 0:
                surplus[pos] = round((team_val - avg) / avg * 100, 1)
            else:
                surplus[pos] = 0.0
        profile["positional_surplus"] = surplus

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
