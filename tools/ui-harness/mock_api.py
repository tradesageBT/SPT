"""
Mock SPT API for the screenshot harness.

Serves plausible canned data on :8000 so the real frontend renders full pages
with no network and no database. Shapes are copied from the real endpoints —
anything that drifts shows up immediately as a blank or broken screenshot,
which is itself useful signal.

    python3 mock_api.py
"""
import json
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

random.seed(7)

POSITIONS = ["QB", "RB", "WR", "TE"]
NAMES = [
    "Josh Allen", "Jahmyr Gibbs", "Bijan Robinson", "Jaxon Smith-Njigba",
    "Ja'Marr Chase", "Amon-Ra St. Brown", "Brock Bowers", "Puka Nacua",
    "CeeDee Lamb", "Lamar Jackson", "Kenneth Walker", "Ashton Jeanty",
    "Drake London", "Garrett Wilson", "Malik Nabers", "Trey McBride",
    "De'Von Achane", "Breece Hall", "Nico Collins", "Jayden Daniels",
]
TEAMS = ["dblair84", "turtleman763", "DMcManus41", "MChakiry", "Boneil518",
         "EvanCoartney", "AAlsup", "Chakmeister", "oneiltjp", "jpearl22",
         "WillieCam", "tradesage"]
NFL = ["BUF", "DET", "ATL", "SEA", "CIN", "KC", "LV", "LAR", "DAL", "BAL"]
CONTENTION = ["Championship Window", "Sustainable Contender", "Retooling",
              "Full Rebuild", "Treading Water", "All-In", "Ascending"]


def player(i, dynasty=True):
    pos = POSITIONS[i % 4]
    val = max(200, 11000 - i * 430)
    return {
        "sleeper_id": str(1000 + i),
        "name": NAMES[i % len(NAMES)],
        "position": pos,
        "nfl_team": NFL[i % len(NFL)],
        "age": 22 + (i % 10),
        "fc_value": val,
        "redraft_value": int(val * 0.8),
        "overall_rank": i + 1,
        "pos_rank": i // 4 + 1,
        "redraft_overall_rank": i + 1,
        "redraft_pos_rank": i // 4 + 1,
        "is_starter": i % 3 != 2,
        "on_taxi": False,
        "on_ir": False,
        "acquisition_type": ["drafted", "traded", "claimed"][i % 3],
        "faab_bid": 14 if i % 3 == 2 else None,
    }


def picks_for(rid):
    out = []
    for yr in (2027, 2028, 2029):
        for rnd in (1, 2, 3, 4):
            base = {1: 2930, 2: 1576, 3: 1062, 4: 849}[rnd] - (yr - 2027) * 300
            lo, hi = max(1, rid - 1), min(12, rid + 1)
            out.append({
                "season": str(yr), "round": rnd,
                "original_roster_id": rid,
                "original_owner_name": TEAMS[rid - 1],
                "own_pick": rid % 4 != 0,
                "fc_value": base,
                "projected_slot": f"{rnd}.{lo:02d}–{rnd}.{hi:02d}",
                "trade_chain": [], "trade_history": [],
            })
    return out


def team(rid):
    i = rid - 1
    pl = [player(i * 2 + k) for k in range(18)]
    pv = sum(p["fc_value"] for p in pl)
    pk = picks_for(rid)
    pkv = sum(p["fc_value"] for p in pk)
    return {
        "roster_id": rid,
        "owner_id": f"u{rid}",
        "display_name": TEAMS[i],
        "avatar": None,
        "total_value": pv + pkv,
        "player_value": pv,
        "pick_value": pkv,
        "starter_value": int(pv * 0.62),
        "bench_value": int(pv * 0.38),
        "redraft_starter_value": int(pv * 0.5),
        "wins": (12 - i) // 2, "losses": i // 2, "ties": 0,
        "fpts": 1515 - i * 28,
        "positional_breakdown": {p: 20000 - i * 900 for p in POSITIONS},
        "positional_surplus": {p: round(12.5 - i * 2, 1) for p in POSITIONS},
        "positional_need": {p: ["Strength", "Adequate", "Need"][(i + k) % 3]
                            for k, p in enumerate(POSITIONS)},
        "positional_rank": {"n": 12, **{p: ((i + k) % 12) + 1
                                        for k, p in enumerate(POSITIONS)}},
        "contention_score": round(0.2 + i * 0.06, 2),
        "contention_category": CONTENTION[i % len(CONTENTION)],
        "strength_tier": ["Contender", "Middle", "Weak"][i // 4],
        "strength_rank": rid,
        "players": pl,
        "picks": pk,
        "roster_data": {"players": pl, "picks": pk},
    }


TEAMS_OUT = [team(r) for r in range(1, 13)]
SETTINGS = {
    "ppr": 1, "num_qbs": 2, "superflex": True,
    "starters": {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "K": 1, "DEF": 1},
    "flex": {"flex": 1, "sflex": 1, "wr_rb_flex": 0, "rec_flex": 0},
    "bench": 7,
    "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX",
                         "SUPER_FLEX", "K", "DEF"] + ["BN"] * 7,
}
LEAGUE = {
    "league_id": "1", "league_name": "All Knowers Only", "season": "2026",
    "num_teams": 12, "teams": TEAMS_OUT, "settings": SETTINGS,
    "num_qbs": 2, "ppr": 1.0, "tep": 0.5, "scoring_settings": {"rec": 1},
    "roster_positions": SETTINGS["roster_positions"],
    "last_synced_at": "2026-11-01T12:00:00Z",
}


def a_trade(i):
    g = TEAMS_OUT[i % 12]
    r = TEAMS_OUT[(i + 5) % 12]
    gave = [{"name": NAMES[i % len(NAMES)], "position": POSITIONS[i % 4],
             "fc_value": 1400 - i * 60}]
    got = [{"name": f"202{7 + i % 3} {['1st','2nd','3rd'][i % 3]}",
            "position": "PK", "fc_value": 1900 - i * 40}]
    gv = sum(a["fc_value"] for a in gave)
    rv = sum(a["fc_value"] for a in got)
    return {
        "date": f"Sep {28 - i:02d}, 2026", "ts": 1759000000 - i * 86400,
        "value_delta": abs(rv - gv), "winner": g["display_name"],
        "sides": [
            {"team_name": g["display_name"], "gave": gave, "received": got,
             "total_value": gv, "net_value": rv - gv, "grade": "A",
             "reason": "Received significantly more value."},
            {"team_name": r["display_name"], "gave": got, "received": gave,
             "total_value": rv, "net_value": gv - rv, "grade": "D",
             "reason": "Gave up the best piece."},
        ],
    }


TRADE_FEED = [a_trade(i) for i in range(8)]


def an_idea(i):
    a, b = TEAMS_OUT[i % 12], TEAMS_OUT[(i + 3) % 12]
    return {
        "team_a": {"roster_id": a["roster_id"], "display_name": a["display_name"],
                   "contention_category": a["contention_category"],
                   "positional_rank": a["positional_rank"]},
        "team_b": {"roster_id": b["roster_id"], "display_name": b["display_name"],
                   "contention_category": b["contention_category"],
                   "positional_rank": b["positional_rank"]},
        "a_gives": [player(i), player(i + 7)],
        "b_gives": [player(i + 3)],
        "value_delta": 120 + i * 30,
        "lineup_delta_a": 400 - i * 30, "lineup_delta_b": 250 + i * 10,
        "grade": "A", "reason": "Balanced on value and fills a need both ways.",
        "is_win_win": i % 2 == 0,
    }


IDEAS = [an_idea(i) for i in range(12)]
ALL_PLAYERS = [{**player(i), "roster_id": i % 12 + 1,
                "display_name": TEAMS[i % 12]} for i in range(60)]


def lineup_slots():
    toks = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"]
    lbl = {"SUPER_FLEX": "SFLEX"}
    out = []
    for i, t in enumerate(toks):
        p = player(i)
        out.append({"slot": t, "slot_label": lbl.get(t, t),
                    "player_id": p["sleeper_id"], "points": 22.4 - i * 1.3,
                    "optimizable": True, "unavailable_reason": None,
                    "player": {"player_id": p["sleeper_id"], "name": p["name"],
                               "position": p["position"], "nfl_team": p["nfl_team"],
                               "points": 22.4 - i * 1.3, "injury_status": None}})
    return out


def weekly_lineup():
    cur = lineup_slots()
    opt = lineup_slots()
    return {
        "league_id": "1", "league_name": "All Knowers Only", "mode": "dynasty",
        "season": 2026, "week": 9, "is_current_week": True, "roster_id": 1,
        "team_name": "MChakiry", "ppr": 1, "min_delta": 1.0,
        "sources_ok": {"sleeper": True, "espn": True, "espn_coverage": 0.93},
        "current": {"slots": cur, "total": 118.4},
        "optimal": {"slots": opt, "total": 131.2},
        "delta": 12.8,
        "changes": [{"slot": "FLEX", "slot_label": "FLEX", "gain": 6.1,
                     "start": {"player_id": "1", "name": NAMES[2], "position": "RB", "nfl_team": "ATL"},
                     "sit": {"player_id": "2", "name": NAMES[8], "position": "WR", "nfl_team": "DAL"}}],
        "bench": [{"player_id": str(900 + i), "name": NAMES[i], "position": POSITIONS[i % 4],
                   "nfl_team": NFL[i % 10], "points": 9.2 - i} for i in range(5)],
        "unavailable": [{"player_id": "99", "name": NAMES[5], "position": "WR", "reason": "Out"}],
        "disagreements": [{"player": {"player_id": "7", "name": NAMES[7], "position": "WR",
                                      "nfl_team": "LAR"},
                           "sleeper_rank": 28, "espn_rank": 12, "gap": 16,
                           "sleeper_label": "WR28", "espn_label": "WR12", "favors": "espn"}],
        "notes": ["Kicker and defense points are approximate."],
    }


ROUTES = {}


def route(path):
    def deco(fn):
        ROUTES[path] = fn
        return fn
    return deco


@route("/api/leagues/1")
def _league(q): return LEAGUE


@route("/api/leagues/1/teams/1")
def _team(q): return {**TEAMS_OUT[0], "league_name": "All Knowers Only",
                      "num_teams": 12, "settings": SETTINGS}


@route("/api/leagues/1/players")
def _players(q): return ALL_PLAYERS


@route("/api/leagues/1/trades")
def _trades(q): return IDEAS


@route("/api/leagues/1/recent-transactions")
def _txns(q): return TRADE_FEED


@route("/api/redraft-league/1")
def _rl(q): return {"league_id": "1", "league_name": "All Knowers Only",
                    "season": "2026", "num_teams": 12, "settings": SETTINGS,
                    "teams": TEAMS_OUT}


@route("/api/redraft-league/1/teams/1")
def _rlteam(q):
    t = TEAMS_OUT[0]
    return {**t, "league_name": "All Knowers Only", "num_teams": 12,
            "settings": SETTINGS,
            "lineup": [{"slot": s["slot_label"], "player": player(i)}
                       for i, s in enumerate(lineup_slots())],
            "bench": [player(20 + i) for i in range(7)]}


@route("/api/redraft-league/1/trades")
def _rltrades(q): return {"trades": IDEAS, "computed_at": "2026-11-01T12:00:00Z"}


@route("/api/redraft-league/1/players")
def _rlplayers(q): return ALL_PLAYERS


@route("/api/weekly/state")
def _wstate(q): return {"season": 2026, "week": 9, "display_week": 9,
                        "season_type": "regular"}


@route("/api/weekly/league/1/lineup")
def _wlineup(q): return weekly_lineup()


@route("/api/weekly/league/1/waivers")
def _wwaivers(q):
    return {"league_id": "1", "league_name": "All Knowers Only", "mode": "dynasty",
            "season": 2026, "week": 9, "roster_id": 1,
            "needs": {"gaps": {"RB": 2.4}, "ordered": ["RB", "WR", "TE"],
                      "top_need": "RB", "urgent": ["RB"]},
            "baseline_points": 131.2,
            "sources_ok": {"sleeper": True, "trending": True, "dynasty_values": True},
            "targets": [
                {"player_id": str(500 + i), "name": NAMES[i], "position": POSITIONS[i % 4],
                 "nfl_team": NFL[i % 10], "opponent": "DEN", "injury_status": None,
                 "adds_24h": 48000 - i * 5200, "proj_points": 14.2 - i * 1.1,
                 "would_start": i < 3, "lineup_gain": max(0, 8.0 - i * 2.5),
                 "dynasty_value": 4200 - i * 300, "dynasty_pos_rank": 14 + i,
                 "fills_need": i % 2 == 0}
                for i in range(10)]}


@route("/api/weekly/user/tradesage")
def _wuser(q): return {"user_id": "u1", "username": "tradesage",
                       "display_name": "tradesage", "avatar": None}


@route("/api/weekly/user/u1/leagues")
def _wleagues(q):
    return {"user_id": "u1", "season": 2026, "leagues": [
        {"league_id": "1", "name": "All Knowers Only", "season": "2026",
         "avatar": None, "total_rosters": 12, "mode": "dynasty",
         "roster_id": None, "status": "in_season"},
        {"league_id": "2", "name": "Work Redraft", "season": "2026",
         "avatar": None, "total_rosters": 10, "mode": "redraft",
         "roster_id": None, "status": "in_season"}]}


@route("/api/weekly/league/1/summary")
def _wsum(q): return {"league_id": "1", "league_name": "All Knowers Only",
                      "mode": "dynasty", "season": 2026, "week": 9, "roster_id": 1,
                      "record": {"wins": 6, "losses": 2, "ties": 0},
                      "points_for": 1515.4, "current_points": 118.4,
                      "optimal_points": 131.2, "bench_points_left": 12.8,
                      "bench_points_basis": "projected", "change_count": 1,
                      "top_change": None}


@route("/api/espn-draft/players/search")
def _search(q):
    n = int((q.get("limit") or ["20"])[0])
    return [player(i) for i in range(min(n, 40))]


@route("/api/espn-draft/picks")
def _picks(q):
    return [{"sleeper_id": f"pick_{y}_{r}",
             "name": f"{y} {['1st','2nd','3rd','4th'][r-1]}", "position": "PK",
             "nfl_team": "", "fc_value": {1: 2930, 2: 1576, 3: 1062, 4: 849}[r],
             "redraft_value": 0}
            for y in (2027, 2028) for r in (1, 2, 3, 4)]


@route("/api/sleeper-draft/state")
def _sd(q):
    avail = [{"player_id": p["sleeper_id"], "name": p["name"],
              "position": p["position"], "nfl_team": p["nfl_team"],
              "redraft_value": p["redraft_value"], "redraft_pos_rank": p["pos_rank"],
              "tier": i // 6 + 1, "vor": 3000 - i * 90, "last_pts": 210 - i * 4,
              "proj": None, "last": None, "meta": None,
              "fills_need": i % 3 == 0, "need_weight": 0.6}
             for i, p in enumerate(player(k) for k in range(40))]
    return {"draft_id": "d1", "league_name": "All Knowers Only",
            "league_settings": {"ppr": 1, "num_qbs": 2, "superflex": True,
                                "starters": SETTINGS["starters"],
                                "flex": SETTINGS["flex"], "bench": 7,
                                "idp": 0, "unknown_slots": []},
            "status": "drafting", "is_auction": False, "picks_made": 26,
            "total_picks": 180, "num_teams": 12, "rounds": 15,
            "reversal_round": 3, "order_verified": True,
            "on_the_clock_roster_id": 10, "on_the_clock_name": TEAMS[9],
            "teams": [{"roster_id": r, "name": TEAMS[r - 1], "draft_slot": r,
                       "counts": {"QB": 1, "RB": 2, "WR": 2},
                       "needs": {"ordered": ["RB", "WR"], "top_need": "RB",
                                 "urgent": ["RB"], "gaps": {"RB": 2.0},
                                 "prop": {"RB": 0.6}}}
                      for r in range(1, 13)],
            "upcoming": [{"pick_no": 27 + i, "pick_in_round": 3 + i, "round": 3,
                          "roster_id": 10 - i, "team_name": TEAMS[9 - i],
                          "top_need": POSITIONS[i % 4], "urgent": [],
                          "counts": {"QB": 1}} for i in range(8)],
            "my_needs": {"ordered": ["RB", "WR", "TE"], "top_need": "RB",
                         "urgent": ["RB"], "gaps": {"RB": 2.0},
                         "prop": {"RB": 0.63}},
            "best_fit_id": avail[3]["player_id"],
            "targets": {"QB": 2.45, "RB": 5.35, "WR": 6.37, "TE": 1.83},
            "seasons": {"projected": 2026, "actual": 2025},
            "return_rates": {}, "picks": [], "all_picks": [],
            "available": avail}


@route("/api/yahoo-draft/status")
def _ystatus(q): return {"connected": False}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        fn = ROUTES.get(u.path)
        if fn is None:
            # Unknown route: 404 with a clear body so a blank screenshot is
            # traceable to a missing mock rather than a CSS bug.
            self._send(404, {"detail": f"mock: no route for {u.path}"})
            return
        self._send(200, fn(q))

    def do_POST(self):
        self._send(200, {"ok": True, "teams_synced": 12,
                         "computed_at": "2026-11-01T12:00:00Z"})

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("mock API on http://localhost:8000")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
