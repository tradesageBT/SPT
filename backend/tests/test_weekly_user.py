"""
The optional Sleeper "login" and the My Leagues glance rows.

There is no auth to test because there is none: Sleeper's API is read-only, so
a username is the whole of it.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import projections
import sleeper_client
import sleeper_data
from routers import weekly as weekly_router


ROSTER_POSITIONS = ["QB", "RB", "WR", "FLEX"] + ["BN"] * 3
MINE = ["qb1", "rb1", "wr1", "rb2"]
ALL = {"qb1": ("QB", 20.0), "rb1": ("RB", 15.0), "wr1": ("WR", 10.0), "rb2": ("RB", 12.0)}
# Deliberately suboptimal: rb2 (12.0) benched, nothing in FLEX.
CURRENT = ["qb1", "rb1", "wr1", "0"]


def _payload():
    return [{
        "player_id": pid, "team": "KC", "opponent": "DEN",
        "stats": {"pts_ppr": pts, "pts_half_ppr": pts, "pts_std": pts},
        "player": {"player_id": pid, "position": pos, "first_name": pid,
                   "last_name": "", "fantasy_positions": [pos]},
    } for pid, (pos, pts) in ALL.items()]


@pytest.fixture
def client(monkeypatch):
    projections._weekly_cache.clear()
    projections._state_cache = None

    async def state(): return {"season": "2026", "week": 5, "display_week": 5}
    async def user(username):
        return {"user_id": "u1", "username": "alec", "display_name": "Alec",
                "avatar": "abc"} if username in ("alec", "u1") else {}
    async def user_leagues(uid, season):
        return [
            {"league_id": "L1", "name": "Dynasty Home", "season": str(season),
             "total_rosters": 12, "settings": {"type": 2}, "status": "in_season"},
            {"league_id": "L2", "name": "Work Redraft", "season": str(season),
             "total_rosters": 10, "settings": {"type": 0}, "status": "in_season"},
        ]
    async def league(lid): return {
        "name": "Dynasty Home" if lid == "L1" else "Work Redraft",
        "season": "2026", "settings": {"type": 2 if lid == "L1" else 0},
        "roster_positions": ROSTER_POSITIONS, "scoring_settings": {"rec": 1},
    }
    async def rosters(lid): return [
        {"roster_id": 3, "owner_id": "u1", "players": MINE, "starters": CURRENT,
         "taxi": [], "reserve": [],
         "settings": {"wins": 3, "losses": 1, "ties": 0, "fpts": 412.5}},
        {"roster_id": 4, "owner_id": "u2", "players": [], "starters": [],
         "taxi": [], "reserve": [], "settings": {}},
    ]
    async def users(lid): return [{"user_id": "u1", "display_name": "Alec"}]
    async def matchups(lid, wk): return [
        {"roster_id": 3, "players": MINE, "starters": CURRENT, "points": 98.4}]

    for name, fn in (("get_nfl_state", state), ("get_user", user),
                     ("get_user_leagues", user_leagues), ("get_league", league),
                     ("get_rosters", rosters), ("get_users", users),
                     ("get_matchups", matchups)):
        monkeypatch.setattr(sleeper_client, name, fn)

    class Resp:
        def raise_for_status(self): pass
        def json(self): return _payload()

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return Resp()

    monkeypatch.setattr(projections.httpx, "AsyncClient", lambda **kw: Client())
    monkeypatch.setattr(sleeper_data, "meta_fresh", lambda: True)
    monkeypatch.setattr(sleeper_data, "get_meta", lambda: {})

    app = FastAPI()
    app.include_router(weekly_router.router)
    return TestClient(app)


def test_username_resolves(client):
    got = client.get("/api/weekly/user/alec")
    assert got.status_code == 200
    assert got.json()["user_id"] == "u1"
    assert got.json()["display_name"] == "Alec"


def test_unknown_username_is_404_with_a_useful_message(client):
    r = client.get("/api/weekly/user/nobody")
    assert r.status_code == 404
    assert "username, not your display name" in r.json()["detail"]


def test_user_route_is_not_swallowed_by_league_id(client):
    """`{league_id}` is an unconstrained str; literal segments must win."""
    assert client.get("/api/weekly/user/alec").status_code == 200
    assert client.get("/api/weekly/state").status_code == 200


def test_league_list_returns_without_touching_rosters(client):
    """Phase one must be fast — the page renders rows before summaries land."""
    got = client.get("/api/weekly/user/u1/leagues").json()
    assert [lg["league_id"] for lg in got["leagues"]] == ["L1", "L2"]
    assert got["season"] == 2026
    # mode is derived from Sleeper's settings.type, so nothing is asked of the user
    assert [lg["mode"] for lg in got["leagues"]] == ["dynasty", "redraft"]
    assert all(lg["roster_id"] is None for lg in got["leagues"])


def test_summary_resolves_my_roster_from_user_id(client):
    got = client.get("/api/weekly/league/L1/summary", params={"user_id": "u1"}).json()
    assert got["roster_id"] == 3
    assert got["record"] == {"wins": 3, "losses": 1, "ties": 0}
    assert got["points_for"] == 412.5


def test_summary_reports_points_left_on_the_bench(client):
    got = client.get("/api/weekly/league/L1/summary", params={"user_id": "u1"}).json()
    # Current: qb1 20 + rb1 15 + wr1 10, FLEX empty = 45. Optimal adds rb2 = 57.
    assert got["current_points"] == 45.0
    assert got["optimal_points"] == 57.0
    assert got["bench_points_left"] == 12.0
    assert got["change_count"] == 1
    assert got["top_change"]["slot"] == "FLEX"


def test_summary_labels_a_past_week_as_actual(client):
    """Showing a projection of a week already played as a forecast would lie."""
    now = client.get("/api/weekly/league/L1/summary", params={"user_id": "u1"}).json()
    assert now["bench_points_basis"] == "projected"
    past = client.get("/api/weekly/league/L1/summary",
                      params={"user_id": "u1", "week": 3}).json()
    assert past["bench_points_basis"] == "actual"


def test_summary_for_a_league_i_am_not_in(client):
    got = client.get("/api/weekly/league/L1/summary", params={"user_id": "nobody"}).json()
    assert got["roster_id"] is None
    assert "league_name" in got          # still renders a row


def test_summary_requires_an_identifier(client):
    assert client.get("/api/weekly/league/L1/summary").status_code == 422
