"""
Weekly projections: payload parsing, scoring, and cache isolation.

The cache-key test matters most — sleeper_data.season() caches season totals
under f"{kind}:{year}", and a weekly variant sharing that namespace would
silently hand the draft rooms one week's numbers as if they were the season's.
"""
import time

import pytest

import projections
import sleeper_data


# One row in Sleeper's weekly shape: stats plus a nested player object.
def _row(pid, pos, name, pts_ppr, **stats):
    first, _, last = name.partition(" ")
    return {
        "player_id": pid,
        "team": "KC",
        "opponent": "DEN",
        "stats": {"pts_ppr": pts_ppr, "pts_half_ppr": pts_ppr - 2,
                  "pts_std": pts_ppr - 4, **stats},
        "player": {"player_id": pid, "position": pos, "first_name": first,
                   "last_name": last, "fantasy_positions": [pos]},
    }


PAYLOAD = [
    _row("1", "QB", "Pat Mahomes", 22.0, pass_td=3, rush_att=4),
    _row("2", "TE", "Trav Kelce", 14.0, rec=8),
    _row("3", "RB", "Isiah Pacheco", 12.0, rush_att=18),
]


def test_normalize_keeps_identity_alongside_stats():
    """
    Without position on the row, slot eligibility would depend on the 10MB meta
    blob and the optimizer could compute nothing on a cold process.
    """
    got = projections.normalize(PAYLOAD)
    assert set(got) == {"1", "2", "3"}
    qb = got["1"]
    assert qb["position"] == "QB"
    assert qb["fantasy_positions"] == ["QB"]
    assert qb["name"] == "Pat Mahomes"
    assert qb["team"] == "KC" and qb["opponent"] == "DEN"
    assert qb["pts_ppr"] == 22.0 and qb["pass_td"] == 3


def test_normalize_is_total():
    assert projections.normalize(None) == {}
    assert projections.normalize([]) == {}
    assert projections.normalize(["nonsense", 42, None]) == {}
    assert projections.normalize([{"stats": {"pts_ppr": 1}}]) == {}   # no player_id


def test_normalize_normalizes_position_aliases():
    got = projections.normalize([_row("9", "DST", "KC Defense", 8.0)])
    assert got["9"]["position"] == "DEF"


def test_score_applies_league_settings_including_te_premium():
    rows = projections.normalize(PAYLOAD)
    scoring = {"pass_td": 6, "rush_att": 0.25, "bonus_rec_te": 0.5}
    pts = projections.score_all(rows, 1, scoring)
    assert pts["1"] == 29.0      # 22 + 3 TDs x 2 + 4 carries x 0.25
    assert pts["2"] == 18.0      # 14 + 8 catches x 0.5, TE only
    assert pts["3"] == 16.5      # 12 + 18 carries x 0.25


def test_score_without_settings_is_sleepers_own_number():
    rows = projections.normalize(PAYLOAD)
    assert projections.score_all(rows, 1, None) == {"1": 22.0, "2": 14.0, "3": 12.0}


def test_score_returns_none_for_unscoreable_rows():
    assert projections.score({}, 1, None) is None
    assert projections.score({"position": "QB"}, 1, None) is None   # no base points


@pytest.mark.asyncio
async def test_weekly_cache_does_not_collide_with_season_totals(monkeypatch):
    """
    The bug this guards: one shared cache key would let a weekly fetch overwrite
    the season totals the draft rooms read.
    """
    sleeper_data._stats_cache.clear()
    projections._weekly_cache.clear()
    sleeper_data._stats_cache["projections:2026"] = (time.time(), {"season": "totals"})

    # Prime the weekly cache and confirm the season entry is untouched — a
    # shared key would mean one of these clobbered the other.
    projections._weekly_cache[("projections", 2026, 3)] = (time.time(), {"week": "three"})
    got = await projections.weekly(2026, 3)

    assert got == {"week": "three"}
    assert sleeper_data._stats_cache["projections:2026"][1] == {"season": "totals"}
    assert len(projections._weekly_cache) == 1


@pytest.mark.asyncio
async def test_weekly_fails_soft(monkeypatch):
    projections._weekly_cache.clear()

    class Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise RuntimeError("sleeper down")

    monkeypatch.setattr(projections.httpx, "AsyncClient", lambda **kw: Boom())
    assert await projections.weekly(2026, 3) == {}


@pytest.mark.asyncio
async def test_weekly_failure_expires_fast(monkeypatch):
    """A blip must not poison the cache for the full 30 minutes."""
    projections._weekly_cache.clear()

    class Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise RuntimeError("sleeper down")

    monkeypatch.setattr(projections.httpx, "AsyncClient", lambda **kw: Boom())
    await projections.weekly(2026, 3)
    marker, _ = projections._weekly_cache[("projections", 2026, 3)]
    age_budget = time.time() - marker
    assert projections.WEEKLY_TTL - age_budget == pytest.approx(projections.FAIL_TTL, abs=2)


@pytest.mark.asyncio
async def test_current_week_prefers_sleeper_state_over_the_calendar(monkeypatch):
    projections._state_cache = None

    async def fake_state():
        return {"season": "2025", "week": 7, "display_week": 8}

    monkeypatch.setattr(projections.sleeper_client, "get_nfl_state", fake_state)
    assert await projections.current_week() == (2025, 8)


@pytest.mark.asyncio
async def test_current_week_falls_back_when_state_is_unavailable(monkeypatch):
    projections._state_cache = None

    async def empty():
        return {}

    monkeypatch.setattr(projections.sleeper_client, "get_nfl_state", empty)
    season, week = await projections.current_week()
    assert season == sleeper_data.current_season()
    assert week == 1
