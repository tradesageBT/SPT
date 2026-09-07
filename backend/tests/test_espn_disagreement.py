"""
ESPN as a rank-only second opinion.

The property that matters most here is that ESPN can never make the page worse:
it is off the request path, and it is dropped wholesale rather than shown
partially.
"""
import asyncio
import time

import pytest

import espn_projections as espn
import sleeper_data


def _espn_payload(week, rows):
    """rows: {espn_id: applied_total}"""
    return {"players": [
        {"id": eid, "playerPoolEntry": {"player": {"id": eid, "stats": [
            {"statSourceId": 0, "scoringPeriodId": week, "appliedTotal": 99.0},
            {"statSourceId": 1, "scoringPeriodId": week, "appliedTotal": total},
            {"statSourceId": 1, "scoringPeriodId": week + 1, "appliedTotal": 1.0},
        ]}}}
        for eid, total in rows.items()
    ]}


def test_extract_takes_projections_for_the_right_week_only():
    got = espn._extract(_espn_payload(5, {11: 18.0, 22: 4.0}), 5)
    assert got == {11: 18.0, 22: 4.0}      # not the actuals, not next week


def test_extract_is_total():
    assert espn._extract({}, 5) == {}
    assert espn._extract({"players": [None, 3, {}]}, 5) == {}
    assert espn._extract(None, 5) == {}


def test_ranks_are_per_position_and_stable():
    pts = {"a": 20.0, "b": 10.0, "c": 30.0, "d": 5.0}
    pos = {"a": "WR", "b": "WR", "c": "RB", "d": "RB"}
    assert espn._ranks(pts, pos) == {"a": 1, "b": 2, "c": 1, "d": 2}


def test_ranks_break_ties_deterministically():
    pts = {"b": 10.0, "a": 10.0}
    pos = {"a": "WR", "b": "WR"}
    assert espn._ranks(pts, pos)["a"] == 1


def _prime(season, week, rows):
    espn._cache[(season, week)] = (time.time(), rows)


def test_cold_cache_returns_not_ok(monkeypatch):
    espn._cache.clear()
    espn._inflight.clear()
    monkeypatch.setattr(sleeper_data, "get_meta", lambda: {})
    got = espn.disagreements({"1": 10.0}, {"1": "WR"}, 2026, 5)
    assert got["ok"] is False
    assert got["by_player"] == {}


def test_disagreement_is_reported_as_a_rank_gap(monkeypatch):
    espn._cache.clear()
    espn._inflight.clear()
    # Sleeper: p1 best WR, p2 worst. ESPN: exactly reversed.
    _prime(2026, 5, {101: 5.0, 102: 25.0, 103: 15.0})
    monkeypatch.setattr(sleeper_data, "get_meta", lambda: {
        "1": {"espn_id": 101}, "2": {"espn_id": 102}, "3": {"espn_id": 103}})

    sleeper_pts = {"1": 25.0, "2": 5.0, "3": 15.0}
    pos = {"1": "WR", "2": "WR", "3": "WR"}
    got = espn.disagreements(sleeper_pts, pos, 2026, 5)

    assert got["ok"] is True and got["coverage"] == 1.0
    p1 = got["by_player"]["1"]
    assert p1["sleeper_rank"] == 1 and p1["espn_rank"] == 3
    assert p1["gap"] == -2                     # Sleeper rates them higher
    assert p1["sleeper_label"] == "WR1" and p1["espn_label"] == "WR3"
    assert got["by_player"]["2"]["gap"] == 2   # ESPN rates them higher


def test_partial_coverage_drops_espn_entirely(monkeypatch):
    """
    Worse than no coverage: some players would carry a two-source read and some
    wouldn't, invisibly skewing which ones get flagged.
    """
    espn._cache.clear()
    espn._inflight.clear()
    _prime(2026, 5, {101: 5.0})                # only 1 of 4 players
    monkeypatch.setattr(sleeper_data, "get_meta", lambda: {
        "1": {"espn_id": 101}, "2": {"espn_id": 102},
        "3": {"espn_id": 103}, "4": {"espn_id": 104}})

    got = espn.disagreements({str(i): 10.0 for i in range(1, 5)},
                             {str(i): "WR" for i in range(1, 5)}, 2026, 5)
    assert got["ok"] is False
    assert got["coverage"] == 0.25
    assert got["by_player"] == {}


def test_full_coverage_is_accepted(monkeypatch):
    espn._cache.clear()
    espn._inflight.clear()
    _prime(2026, 5, {101: 5.0, 102: 6.0, 103: 7.0, 104: 8.0})
    monkeypatch.setattr(sleeper_data, "get_meta", lambda: {
        str(i): {"espn_id": 100 + i} for i in range(1, 5)})
    got = espn.disagreements({str(i): 10.0 + i for i in range(1, 5)},
                             {str(i): "WR" for i in range(1, 5)}, 2026, 5)
    assert got["ok"] is True and got["coverage"] == 1.0


def test_missing_or_garbage_espn_ids_are_skipped(monkeypatch):
    espn._cache.clear()
    espn._inflight.clear()
    _prime(2026, 5, {101: 5.0, 102: 6.0})
    monkeypatch.setattr(sleeper_data, "get_meta", lambda: {
        "1": {"espn_id": 101}, "2": {"espn_id": "102"},   # string id still works
        "3": {"espn_id": "not-a-number"}, "4": {}})
    got = espn.disagreements({"1": 1.0, "2": 2.0}, {"1": "WR", "2": "WR"}, 2026, 5)
    assert got["ok"] is True                    # the two we asked about are covered


def test_fetch_failure_caches_briefly_and_returns_empty(monkeypatch):
    espn._cache.clear()
    espn._inflight.clear()

    class Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw): raise RuntimeError("espn changed")

    monkeypatch.setattr(espn.httpx, "AsyncClient", lambda **kw: Boom())

    assert asyncio.run(espn.refresh(2026, 5)) == {}
    marker, data = espn._cache[(2026, 5)]
    assert data == {}
    # A failure must expire on the short TTL, not sit for two hours.
    assert espn.CACHE_TTL - (time.time() - marker) == pytest.approx(espn.FAIL_TTL, abs=2)
