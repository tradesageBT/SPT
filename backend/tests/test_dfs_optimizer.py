"""
The DFS solver, checked against exhaustive search.

A cap-constrained optimizer that is subtly wrong doesn't crash — it quietly
returns lineups a few points below optimal, forever. So every randomized pool is
compared against brute force, including the cases where greedy-by-points (the
approach the weekly optimizer uses, which cannot work here) demonstrably fails.
"""
import itertools
import random

import pytest

import dfs_optimizer as dfs


def _p(pid, pos, salary, points, game="G1"):
    return {"player_id": pid, "position": pos, "salary": salary,
            "points": points, "game_id": game, "name": pid, "team": game[:2]}


def _oracle(players, cap=dfs.DEFAULT_CAP, min_games=dfs.MIN_GAMES):
    """
    Exhaustive best legal total. Deliberately shares no logic with the solver:
    enumerate every legal roster shape and take the max.
    """
    by = {}
    for p in players:
        by.setdefault(p["position"], []).append(p)

    best = None
    for counts in dfs._FLEX_CASES.values():
        pools = []
        ok = True
        for pos, k in counts.items():
            group = by.get(pos, [])
            if len(group) < k:
                ok = False
                break
            pools.append(list(itertools.combinations(group, k)))
        if not ok:
            continue
        for combo in itertools.product(*pools):
            picked = [p for grp in combo for p in grp]
            if sum(p["salary"] for p in picked) > cap:
                continue
            if len({p["game_id"] for p in picked}) < min_games:
                continue
            total = sum(p["points"] for p in picked)
            if best is None or total > best:
                best = total
    return best


def _small_pool(rng, cap_scale=1.0):
    """A pool small enough to brute-force but rich enough to be interesting."""
    out = []
    plan = [("QB", 4), ("RB", 5), ("WR", 6), ("TE", 4), ("DST", 3)]
    for pos, n in plan:
        for i in range(n):
            out.append(_p(f"{pos}{i}", pos,
                          int(rng.randrange(3000, 11000, 100) * cap_scale),
                          round(rng.uniform(2, 28), 1),
                          game=f"G{i % 3}"))
    return out


# ── Exactness ────────────────────────────────────────────────────────────────

def test_matches_brute_force_across_random_pools():
    rng = random.Random(11)
    for trial in range(40):
        pool = _small_pool(rng)
        got = dfs.optimize(pool)
        want = _oracle(pool)
        if want is None:
            assert got is None, trial
            continue
        assert got is not None, trial
        assert got["total_points"] == pytest.approx(want, abs=0.01), trial


def test_matches_brute_force_when_the_cap_binds_hard():
    """A tight cap is where greedy-by-points goes wrong, so test it hardest."""
    rng = random.Random(7)
    for trial in range(40):
        pool = _small_pool(rng)
        for cap in (32000, 36000, 40000):
            got = dfs.optimize(pool, cap=cap)
            want = _oracle(pool, cap=cap)
            if want is None:
                assert got is None, (trial, cap)
                continue
            assert got["total_points"] == pytest.approx(want, abs=0.01), (trial, cap)


def test_greedy_by_points_is_beaten():
    """
    The concrete reason lineup.optimize() cannot be reused: one expensive stud
    eats the cap and strands the rest of the roster.
    """
    # Two games, because DraftKings requires a lineup to span at least two.
    pool = [
        _p("qb_stud", "QB", 20000, 30.0, "A"), _p("qb_ok", "QB", 5000, 20.0, "A"),
        _p("rb1", "RB", 5000, 18.0, "A"), _p("rb2", "RB", 5000, 17.0, "B"),
        _p("rb3", "RB", 4000, 15.0, "A"),
        _p("wr1", "WR", 5000, 18.0, "B"), _p("wr2", "WR", 5000, 17.0, "A"),
        _p("wr3", "WR", 5000, 16.0, "B"), _p("wr4", "WR", 4000, 14.0, "A"),
        _p("te1", "TE", 5000, 14.0, "B"), _p("te2", "TE", 3000, 9.0, "A"),
        _p("dst1", "DST", 3000, 9.0, "B"), _p("dst2", "DST", 2000, 6.0, "A"),
    ]
    got = dfs.optimize(pool, cap=dfs.DEFAULT_CAP)
    assert got["total_points"] == pytest.approx(_oracle(pool), abs=0.01)
    # Taking the 30-point QB at $20k cannot be afforded alongside the rest.
    assert all(p["player_id"] != "qb_stud" for p in got["players"])


# ── Legality ─────────────────────────────────────────────────────────────────

def _assert_legal(got, cap=dfs.DEFAULT_CAP):
    assert len(got["players"]) == 9
    assert got["total_salary"] <= cap
    ids = [p["player_id"] for p in got["players"]]
    assert len(set(ids)) == 9, "no player may appear twice"
    counts = {}
    for p in got["players"]:
        counts[p["position"]] = counts.get(p["position"], 0) + 1
    assert counts.get("QB") == 1
    assert counts.get("DST") == 1
    assert counts.get("RB", 0) >= 2
    assert counts.get("WR", 0) >= 3
    assert counts.get("TE", 0) >= 1
    # Exactly one extra skill player beyond the dedicated slots — the FLEX.
    extra = (counts.get("RB", 0) - 2) + (counts.get("WR", 0) - 3) + (counts.get("TE", 0) - 1)
    assert extra == 1


def test_every_returned_lineup_is_legal():
    rng = random.Random(3)
    for _ in range(30):
        got = dfs.optimize(_small_pool(rng))
        if got:
            _assert_legal(got)


def test_slots_are_filled_in_display_order():
    rng = random.Random(5)
    got = dfs.optimize(_small_pool(rng))
    assert [r["slot"] for r in got["lineup"]] == list(dfs.CLASSIC_SLOTS)
    assert all(r["player"] is not None for r in got["lineup"])
    # Every chosen player appears exactly once across the slots.
    seated = [r["player"]["player_id"] for r in got["lineup"]]
    assert sorted(seated) == sorted(p["player_id"] for p in got["players"])


def test_flex_holds_a_flex_eligible_position():
    rng = random.Random(9)
    for _ in range(20):
        got = dfs.optimize(_small_pool(rng))
        if not got:
            continue
        flex = [r for r in got["lineup"] if r["slot"] == "FLEX"][0]
        assert flex["player"]["position"] in dfs.FLEX_POSITIONS


def test_min_games_rule_is_enforced():
    """DraftKings requires players from at least two games."""
    rng = random.Random(21)
    pool = [{**p, "game_id": "ONLY"} for p in _small_pool(rng)]
    assert dfs.optimize(pool) is None

    two = []
    for i, p in enumerate(_small_pool(rng)):
        two.append({**p, "game_id": "A" if i % 2 else "B"})
    got = dfs.optimize(two)
    assert got is not None
    assert len({p["game_id"] for p in got["players"]}) >= dfs.MIN_GAMES


# ── Degenerate input ─────────────────────────────────────────────────────────

def test_pool_too_thin_returns_none():
    assert dfs.optimize([]) is None
    assert dfs.optimize([_p("qb", "QB", 5000, 20.0)]) is None


def test_cap_too_low_returns_none():
    rng = random.Random(1)
    assert dfs.optimize(_small_pool(rng), cap=5000) is None


def test_players_without_a_projection_are_skipped():
    rng = random.Random(13)
    pool = _small_pool(rng)
    pool.append({"player_id": "ghost", "position": "WR", "salary": 3000,
                 "points": None, "game_id": "G0"})
    got = dfs.optimize(pool)
    assert all(p["player_id"] != "ghost" for p in got["players"])


def test_exclusion_is_respected():
    rng = random.Random(17)
    pool = _small_pool(rng)
    first = dfs.optimize(pool)
    banned = first["players"][0]["player_id"]
    alt = dfs.optimize(pool, exclude={banned})
    assert all(p["player_id"] != banned for p in alt["players"])
    assert alt["total_points"] <= first["total_points"]


# ── Alternates ───────────────────────────────────────────────────────────────

def test_alternates_are_distinct_and_descending():
    rng = random.Random(23)
    got = dfs.optimize_set(_small_pool(rng), count=4)
    assert len(got) >= 2
    keys = [frozenset(p["player_id"] for p in g["players"]) for g in got]
    assert len(set(keys)) == len(keys), "alternates must be different lineups"
    totals = [g["total_points"] for g in got]
    assert totals == sorted(totals, reverse=True)
    assert totals[0] == pytest.approx(_oracle(_small_pool(random.Random(23))), abs=0.01)


def test_alternates_are_each_legal():
    rng = random.Random(31)
    for g in dfs.optimize_set(_small_pool(rng), count=3):
        _assert_legal(g)
