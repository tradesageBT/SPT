"""Synthetic dynasty league used to prove the shared engines don't change."""
import random

SKILL = ["QB", "RB", "WR", "TE"]

def build(num_teams=12, seed=42):
    random.seed(seed)
    cache, pid = {}, 1
    pools = {"QB": 50, "RB": 90, "WR": 110, "TE": 50}
    for pos, n in pools.items():
        for i in range(n):
            fc = max(50, int(9000 * (0.94 ** i)))
            cache[str(pid)] = {
                "sleeper_id": str(pid), "name": f"{pos}{i+1}", "position": pos,
                "nfl_team": "XX", "age": 22 + (i % 12),
                "fc_value": fc,
                # Deliberately a different curve so a value-source bug can't hide
                "redraft_value": max(40, int(7000 * (0.93 ** i))),
                "overall_rank": pid, "pos_rank": i + 1,
                "redraft_overall_rank": pid, "redraft_pos_rank": i + 1,
            }
            pid += 1

    by_pos = {p: [k for k, v in cache.items() if v["position"] == p] for p in SKILL}
    rosters, users_map = [], {}
    for t in range(1, num_teams + 1):
        players = []
        for pos, n in (("QB", 3), ("RB", 6), ("WR", 7), ("TE", 3)):
            players += [by_pos[pos][(t - 1) * n + i] for i in range(n)]
        starters = [players[0], players[3], players[4], players[9], players[10], players[11], players[16]]
        users_map[f"u{t}"] = {"display_name": f"Team {t}", "avatar": None}
        rosters.append({
            "roster_id": t, "owner_id": f"u{t}", "players": players, "starters": starters,
            "taxi": [], "reserve": [],
            "settings": {"wins": t % 5, "losses": 4 - (t % 5), "ties": 0,
                         "fpts": 900 + t * 7, "fpts_decimal": 50},
        })

    picks_cache = {f"{2027+y}_{r}": {"season": 2027 + y, "round": r,
                                     "fc_value": 3000 - r * 600 - y * 200}
                   for y in range(3) for r in range(1, 5)}
    picks_by_roster = {
        t: [{"season": 2027 + y, "round": r, "original_roster_id": t,
             "original_owner_name": f"Team {t}", "trade_chain": [], "own_pick": True}
            for y in range(3) for r in range(1, 5)]
        for t in range(1, num_teams + 1)
    }
    roster_positions = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX",
                        "SUPER_FLEX", "K", "DEF"] + ["BN"] * 7
    return dict(rosters=rosters, users_map=users_map, players_cache=cache,
                picks_cache=picks_cache, picks_by_roster=picks_by_roster,
                roster_positions=roster_positions)
