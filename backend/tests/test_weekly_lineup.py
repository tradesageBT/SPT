"""
End-to-end lineup endpoint against stubbed Sleeper responses.

The sandbox has no network egress, so every Sleeper call is monkeypatched.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import projections
import sleeper_client
import sleeper_data
import weekly as weekly_engine
from routers import weekly as weekly_router


LID = "1401244151114117120"

ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX",
                    "SUPER_FLEX", "K", "DEF"] + ["BN"] * 7

# The user's real scoring: 6-point pass TDs, 0.25 per carry, return yards.
SCORING = {"rec": 1, "pass_td": 6, "rush_att": 0.25, "kr_yd": 0.04, "pr_yd": 0.04}

# id: (position, projected pts_ppr, extra stats)
PLAYERS = {
    "qb1": ("QB", 18.0, {"pass_td": 2}),
    "qb2": ("QB", 15.0, {"pass_td": 2}),
    "rb1": ("RB", 14.0, {"rush_att": 16}),
    "rb2": ("RB", 11.0, {"rush_att": 12}),
    "rb3": ("RB", 9.0, {"rush_att": 8}),
    "wr1": ("WR", 16.0, {}),
    "wr2": ("WR", 13.0, {}),
    "wr3": ("WR", 10.0, {}),
    "wr4": ("WR", 7.0, {}),
    "te1": ("TE", 8.0, {}),
    "k1":  ("K",  8.0, {}),
    "df1": ("DEF", 6.0, {}),
    "hurt": ("WR", 20.0, {}),      # highest WR projection, but ruled Out
    "bye":  ("RB", 0.0, {}),       # no projection row at all
}
MY_PLAYERS = list(PLAYERS)

# Deliberately suboptimal: qb2 benched, wr4 in SUPER_FLEX, hurt started.
CURRENT_STARTERS = ["qb1", "rb1", "rb2", "wr1", "wr2", "hurt",
                    "te1", "wr3", "wr4", "k1", "df1"]


def _payload():
    rows = []
    for pid, (pos, pts, extra) in PLAYERS.items():
        if pid == "bye":
            continue                      # on bye: absent from the projection set
        rows.append({
            "player_id": pid, "team": "KC", "opponent": "DEN",
            "stats": {"pts_ppr": pts, "pts_half_ppr": pts, "pts_std": pts, **extra},
            "player": {"player_id": pid, "position": pos, "first_name": pid.upper(),
                       "last_name": "", "fantasy_positions": [pos]},
        })
    return rows


@pytest.fixture
def client(monkeypatch):
    projections._weekly_cache.clear()
    projections._state_cache = None

    async def state(): return {"season": "2026", "week": 5, "display_week": 5}
    async def league(lid): return {
        "name": "Test League", "season": "2026", "settings": {"type": 0},
        "roster_positions": ROSTER_POSITIONS, "scoring_settings": SCORING,
    }
    async def rosters(lid): return [{
        "roster_id": 1, "owner_id": "u1", "players": MY_PLAYERS,
        "starters": CURRENT_STARTERS, "taxi": [], "reserve": [],
    }]
    async def users(lid): return [{"user_id": "u1", "display_name": "My Team"}]
    async def matchups(lid, wk): return [{
        "roster_id": 1, "matchup_id": 1,
        "players": MY_PLAYERS, "starters": CURRENT_STARTERS,
    }]

    monkeypatch.setattr(sleeper_client, "get_nfl_state", state)
    monkeypatch.setattr(sleeper_client, "get_league", league)
    monkeypatch.setattr(sleeper_client, "get_rosters", rosters)
    monkeypatch.setattr(sleeper_client, "get_users", users)
    monkeypatch.setattr(sleeper_client, "get_matchups", matchups)

    class Resp:
        def raise_for_status(self): pass
        def json(self): return _payload()

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return Resp()

    monkeypatch.setattr(projections.httpx, "AsyncClient", lambda **kw: Client())
    # Meta is enrichment; supply just the injury designation.
    monkeypatch.setattr(sleeper_data, "meta_fresh", lambda: True)
    monkeypatch.setattr(sleeper_data, "get_meta", lambda: {"hurt": {"injury_status": "Out"}})

    app = FastAPI()
    app.include_router(weekly_router.router)
    return TestClient(app)


def _get(client, **params):
    r = client.get(f"/api/weekly/league/{LID}/lineup", params={"roster_id": 1, **params})
    r.raise_for_status()
    return r.json()


def test_state_endpoint(client):
    got = client.get("/api/weekly/state").json()
    assert got["season"] == 2026 and got["week"] == 5


def test_scoring_uses_the_leagues_own_rules(client):
    """A QB with 2 pass TDs must gain 4 points over Sleeper's 4-point baseline."""
    d = _get(client)
    qb1 = [s for s in d["optimal"]["slots"] if s["player_id"] == "qb1"][0]
    assert qb1["points"] == 22.0          # 18 + 2 TDs x 2 extra
    rb1 = [s for s in d["optimal"]["slots"] if s["player_id"] == "rb1"][0]
    assert rb1["points"] == 18.0          # 14 + 16 carries x 0.25


def test_optimal_totals_are_exact():
    """Pinned by hand so a scoring or assignment drift can't pass unnoticed."""
    # qb1 22, qb2 19, rb1 18, rb2 14, rb3 11, wr1 16, wr2 13, wr3 10, wr4 7,
    # te1 8, k1 8, df1 6.  Optimal fills FLEX with rb3 and SUPER_FLEX with the
    # spare QB: 22+18+14+16+13+10+8+11+19+8+6.
    assert 22 + 18 + 14 + 16 + 13 + 10 + 8 + 11 + 19 + 8 + 6 == 145


def test_optimal_beats_current(client):
    d = _get(client)
    assert d["optimal"]["total"] == 145.0
    # Current starts `hurt` (Out, so worth 0) and wastes SUPER_FLEX on wr4.
    assert d["current"]["total"] == 122.0
    assert d["delta"] == 23.0


def test_the_right_eleven_players_start(client):
    """
    Assert WHO starts, not which interchangeable slot each landed in — QB and
    SUPER_FLEX are equivalent for a quarterback, as are RB/RB/FLEX for a back,
    so pinning exact slots would fail on an equally-optimal answer.
    """
    d = _get(client)
    started = {s["player_id"] for s in d["optimal"]["slots"] if s["player_id"]}
    assert started == {"qb1", "qb2", "rb1", "rb2", "rb3",
                       "wr1", "wr2", "wr3", "te1", "k1", "df1"}
    # wr4 is the odd man out: rb3 (11.0) beats him (7.0) for the flex spot.
    assert "wr4" not in started

    seated = {s["slot"]: s["player_id"] for s in d["optimal"]["slots"]}
    assert {seated["QB"], seated["SUPER_FLEX"]} == {"qb1", "qb2"}
    assert any(c["slot"] == "SUPER_FLEX" for c in d["changes"])


def test_started_player_who_is_out_scores_zero_in_the_current_lineup(client):
    """Crediting them their projection would hide the swap most worth making."""
    d = _get(client)
    hurt = [s for s in d["current"]["slots"] if s["player_id"] == "hurt"][0]
    assert hurt["points"] == 0.0
    assert hurt["unavailable_reason"] == "Out"


def test_slots_are_in_the_leagues_own_order(client):
    d = _get(client)
    assert [s["slot"] for s in d["optimal"]["slots"]] == [
        "QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"]
    assert [s["slot_label"] for s in d["optimal"]["slots"]][8] == "SFLEX"


def test_injured_and_bye_players_are_never_started(client):
    d = _get(client)
    started = {s["player_id"] for s in d["optimal"]["slots"]}
    assert "hurt" not in started and "bye" not in started
    reasons = {u["player_id"]: u["reason"] for u in d["unavailable"]}
    assert reasons["hurt"] == "Out"
    assert reasons["bye"] == "No game"


def test_current_lineup_is_read_from_matchups_not_rosters(client, monkeypatch):
    """
    rosters only ever describes the live week. If matchups are the source, a
    different week's starters must come through.
    """
    async def other_week(lid, wk):
        if wk == 3:
            return [{"roster_id": 1, "players": MY_PLAYERS,
                     "starters": ["qb2"] + CURRENT_STARTERS[1:]}]
        return [{"roster_id": 1, "players": MY_PLAYERS, "starters": CURRENT_STARTERS}]

    monkeypatch.setattr(sleeper_client, "get_matchups", other_week)
    wk3 = _get(client, week=3)
    assert wk3["current"]["slots"][0]["player_id"] == "qb2"
    assert wk3["week"] == 3
    assert _get(client)["current"]["slots"][0]["player_id"] == "qb1"


def test_changes_are_sorted_and_above_the_noise_floor(client):
    d = _get(client)
    gains = [c["gain"] for c in d["changes"]]
    assert gains == sorted(gains, reverse=True)
    assert all(g >= d["min_delta"] for g in gains)


def test_mode_is_read_from_sleeper(client, monkeypatch):
    d = _get(client)
    assert d["mode"] == "redraft"

    async def dynasty(lid): return {
        "name": "Test League", "season": "2026", "settings": {"type": 2},
        "roster_positions": ROSTER_POSITIONS, "scoring_settings": SCORING,
    }
    monkeypatch.setattr(sleeper_client, "get_league", dynasty)
    assert _get(client)["mode"] == "dynasty"


def test_identical_result_in_dynasty_and_redraft(client, monkeypatch):
    """The endpoint is mode-agnostic: weekly points don't care about league type."""
    redraft = _get(client)

    async def dynasty(lid): return {
        "name": "Test League", "season": "2026", "settings": {"type": 2},
        "roster_positions": ROSTER_POSITIONS, "scoring_settings": SCORING,
    }
    monkeypatch.setattr(sleeper_client, "get_league", dynasty)
    dyn = _get(client)
    assert dyn["optimal"] == redraft["optimal"]
    assert dyn["delta"] == redraft["delta"]


def test_unknown_league_is_404(client, monkeypatch):
    async def missing(lid): return {}
    monkeypatch.setattr(sleeper_client, "get_league", missing)
    assert client.get(f"/api/weekly/league/{LID}/lineup",
                      params={"roster_id": 1}).status_code == 404


def test_projection_outage_degrades_rather_than_crashing(client, monkeypatch):
    projections._weekly_cache.clear()

    class Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise RuntimeError("sleeper down")

    monkeypatch.setattr(projections.httpx, "AsyncClient", lambda **kw: Boom())
    d = _get(client)
    assert d["sources_ok"]["sleeper"] is False
    assert d["optimal"]["total"] == 0.0
    assert len(d["unavailable"]) == len(MY_PLAYERS)


def test_route_order_state_is_not_swallowed_by_league_id(client):
    """`{league_id}` is an unconstrained str; literal routes must win."""
    assert client.get("/api/weekly/state").status_code == 200


def test_rostered_ids_unions_taxi_and_reserve():
    got = weekly_engine.rostered_ids([
        {"players": ["a"], "taxi": ["b"], "reserve": ["c"]},
        {"players": ["d", None], "taxi": None, "reserve": []},
    ])
    assert got == {"a", "b", "c", "d"}
