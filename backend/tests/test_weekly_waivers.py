"""
Waiver assistant: trending adds narrowed to who is actually free in your league.

Sleeper's trending endpoint is league-agnostic, so the value this adds is the
filtering — a raw trending list is mostly players you cannot have.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import projections
import sleeper_client
import sleeper_data
import weekly as weekly_engine
from routers import weekly as weekly_router


LID = "L1"
ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"] + ["BN"] * 5
SCORING = {"rec": 1, "pass_td": 6}

MY_PLAYERS = ["qb1", "rb1", "rb2", "wr1", "wr2", "te1", "wr3"]
OTHER_TEAM = ["qb9", "rb9"]
# Free agents, none rostered anywhere.
FREE = {"stud": ("RB", 19.0), "meh": ("WR", 2.0), "kick": ("K", 7.0)}

ALL = {
    "qb1": ("QB", 20.0), "rb1": ("RB", 15.0), "rb2": ("RB", 12.0),
    "wr1": ("WR", 14.0), "wr2": ("WR", 11.0), "te1": ("TE", 8.0), "wr3": ("WR", 5.0),
    "qb9": ("QB", 18.0), "rb9": ("RB", 10.0), **FREE,
}


def _payload():
    return [{
        "player_id": pid,
        "team": "KC", "opponent": "DEN",
        "stats": {"pts_ppr": pts, "pts_half_ppr": pts, "pts_std": pts},
        "player": {"player_id": pid, "position": pos, "first_name": pid,
                   "last_name": "", "fantasy_positions": [pos]},
    } for pid, (pos, pts) in ALL.items()]


@pytest.fixture
def client(monkeypatch):
    projections._weekly_cache.clear()
    projections._state_cache = None

    async def state(): return {"season": "2026", "week": 5, "display_week": 5}
    async def league(lid): return {
        "name": "L", "season": "2026", "settings": {"type": 0},
        "roster_positions": ROSTER_POSITIONS, "scoring_settings": SCORING,
    }
    async def rosters(lid): return [
        {"roster_id": 1, "owner_id": "u1", "players": MY_PLAYERS,
         "starters": MY_PLAYERS[:7], "taxi": [], "reserve": []},
        {"roster_id": 2, "owner_id": "u2", "players": OTHER_TEAM,
         "starters": OTHER_TEAM, "taxi": [], "reserve": []},
    ]
    async def users(lid): return [{"user_id": "u1", "display_name": "Me"},
                                  {"user_id": "u2", "display_name": "Them"}]
    async def matchups(lid, wk): return [
        {"roster_id": 1, "players": MY_PLAYERS, "starters": MY_PLAYERS[:7]},
        {"roster_id": 2, "players": OTHER_TEAM, "starters": OTHER_TEAM},
    ]
    # Deliberately includes a player rostered on the OTHER team.
    async def trending(kind="add", lookback_hours=24, limit=200):
        return [{"player_id": "stud", "count": 50000},
                {"player_id": "rb9", "count": 40000},
                {"player_id": "meh", "count": 900},
                {"player_id": "kick", "count": 300},
                {"player_id": "ghost", "count": 10}]

    monkeypatch.setattr(sleeper_client, "get_nfl_state", state)
    monkeypatch.setattr(sleeper_client, "get_league", league)
    monkeypatch.setattr(sleeper_client, "get_rosters", rosters)
    monkeypatch.setattr(sleeper_client, "get_users", users)
    monkeypatch.setattr(sleeper_client, "get_matchups", matchups)
    monkeypatch.setattr(sleeper_client, "get_trending", trending)

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


def _get(client, **params):
    r = client.get(f"/api/weekly/league/{LID}/waivers", params={"roster_id": 1, **params})
    r.raise_for_status()
    return r.json()


def test_only_free_agents_are_offered(client):
    ids = [t["player_id"] for t in _get(client)["targets"]]
    assert "rb9" not in ids           # rostered on the other team
    assert "qb1" not in ids           # on my own roster
    assert "ghost" not in ids         # no projection and no meta — an opaque id
    assert set(ids) == {"stud", "meh", "kick"}


def test_order_follows_sleeper_trending(client):
    ids = [t["player_id"] for t in _get(client)["targets"]]
    assert ids[0] == "stud"           # 50k adds


def test_lineup_gain_says_whether_a_pickup_would_actually_start(client):
    by_id = {t["player_id"]: t for t in _get(client)["targets"]}
    # 19.0 RB beats wr3 (5.0) for the FLEX spot.
    assert by_id["stud"]["would_start"] is True
    assert by_id["stud"]["lineup_gain"] == pytest.approx(14.0)
    # A 2.0 WR cracks nothing.
    assert by_id["meh"]["would_start"] is False
    assert by_id["meh"]["lineup_gain"] == 0.0


def test_dynasty_value_is_absent_in_redraft(client):
    for t in _get(client)["targets"]:
        assert t["dynasty_value"] is None
    assert _get(client)["mode"] == "redraft"


def test_dynasty_value_is_labelled_separately_in_dynasty(client, monkeypatch):
    """A streamer and a stash are different decisions, so both are shown."""
    monkeypatch.setattr(weekly_engine, "_dynasty_values",
                        lambda: {"stud": {"fc_value": 4200, "pos_rank": 14}})
    got = _get(client, mode="dynasty")
    by_id = {t["player_id"]: t for t in got["targets"]}
    assert got["mode"] == "dynasty"
    assert by_id["stud"]["dynasty_value"] == 4200
    assert by_id["stud"]["dynasty_pos_rank"] == 14
    assert by_id["stud"]["proj_points"] == 19.0        # weekly value still there
    assert by_id["meh"]["dynasty_value"] is None       # not in the cache


def test_needs_come_through(client):
    got = _get(client)
    assert "ordered" in got["needs"] and "gaps" in got["needs"]
    assert all(isinstance(t["fills_need"], bool) for t in got["targets"])


def test_limit_is_respected(client):
    assert len(_get(client, limit=1)["targets"]) == 1


def test_trending_outage_degrades_to_an_empty_list(client, monkeypatch):
    async def none(kind="add", lookback_hours=24, limit=200): return []
    monkeypatch.setattr(sleeper_client, "get_trending", none)
    got = _get(client)
    assert got["targets"] == []
    assert got["sources_ok"]["trending"] is False


def test_dynasty_value_lookup_failure_does_not_break_the_page(client, monkeypatch):
    """The values cache lives in Postgres; the waiver list must survive it being down."""
    monkeypatch.setattr(weekly_engine, "_dynasty_values", lambda: {})
    got = _get(client, mode="dynasty")
    assert got["targets"]
    assert got["sources_ok"]["dynasty_values"] is False
