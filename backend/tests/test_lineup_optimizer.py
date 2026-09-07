"""
The lineup optimizer, checked against exhaustive search.

This is the highest-risk code in the weekly feature: a silent matching bug
wouldn't crash, it would just quietly recommend worse lineups every week. So
every randomized roster is compared against a brute-force oracle.
"""
import functools
import random

import lineup
import slots


def _oracle(candidates, slot_tokens):
    """
    Exhaustive best legal total, by memoized search over (slot, players-used).

    Deliberately a different algorithm from the one under test — no matching, no
    matroid argument, just try everything. Each slot may also be left empty, so
    this stays correct when there are fewer players than slots (the case an
    itertools.permutations oracle silently gets wrong by yielding nothing).
    """
    fillable = [i for i, t in enumerate(slot_tokens) if slots.is_projected(t)]
    playable = [c for c in candidates if c.get("available", True)]
    ok = [[slots.is_eligible(slot_tokens[si], c.get("fantasy_positions"), c.get("position"))
           for si in fillable] for c in playable]

    @functools.lru_cache(maxsize=None)
    def best(k, used):
        if k == len(fillable):
            return 0.0
        out = best(k + 1, used)                      # leave this slot empty
        for pi, c in enumerate(playable):
            bit = 1 << pi
            if used & bit or not ok[pi][k]:
                continue
            out = max(out, c["points"] + best(k + 1, used | bit))
        return out

    return round(best(0, 0), 2)


def _p(pid, pos, pts, fantasy_positions=None, available=True):
    return {"player_id": pid, "position": pos, "points": pts,
            "fantasy_positions": fantasy_positions, "available": available}


# ── The two documented greedy failures ───────────────────────────────────────

def test_superflex_slot_order_counterexample():
    """
    Greedy in league order takes SUPER_FLEX<-RB3 then FLEX<-WR4 = 20.3.
    Optimal is SUPER_FLEX<-QB2, FLEX<-RB3 = 27.9.
    """
    pool = [_p("rb3", "RB", 14.1), _p("qb2", "QB", 13.8), _p("wr4", "WR", 6.2)]
    got = lineup.optimize(pool, ["SUPER_FLEX", "FLEX"])
    assert got["total"] == 27.9
    seated = {a["slot"]: a["player_id"] for a in got["assignment"]}
    assert seated == {"SUPER_FLEX": "qb2", "FLEX": "rb3"}


def test_non_laminar_flex_counterexample():
    """
    REC_FLEX (WR/TE) and WRRB_FLEX (RB/WR) are the same width and neither
    contains the other, so even narrow-first greedy fails: 22.0 vs 29.5.
    """
    pool = [_p("wr", "WR", 18.0), _p("te", "TE", 11.5), _p("rb", "RB", 4.0)]
    tokens = ["REC_FLEX", "WRRB_FLEX"]
    got = lineup.optimize(pool, tokens)
    assert got["total"] == 29.5
    assert lineup.greedy_total(pool, tokens) == 22.0     # the trap, pinned
    seated = {a["slot"]: a["player_id"] for a in got["assignment"]}
    assert seated == {"REC_FLEX": "te", "WRRB_FLEX": "wr"}


# ── Randomized against the oracle ────────────────────────────────────────────

def test_matches_brute_force_over_random_rosters():
    rng = random.Random(1234)
    tokens = ["QB", "RB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX"]
    for trial in range(300):
        pool = []
        for i in range(rng.randint(3, 9)):
            pos = rng.choice(["QB", "RB", "WR", "TE"])
            pool.append(_p(f"p{i}", pos, round(rng.uniform(0, 25), 1)))
        got = lineup.optimize(pool, tokens)
        assert got["total"] == _oracle(pool, tokens), (trial, pool)


def test_matches_brute_force_with_exotic_flex():
    rng = random.Random(99)
    tokens = ["REC_FLEX", "WRRB_FLEX", "FLEX", "SUPER_FLEX"]
    for trial in range(300):
        pool = [_p(f"p{i}", rng.choice(["QB", "RB", "WR", "TE"]),
                   round(rng.uniform(0, 25), 1))
                for i in range(rng.randint(2, 7))]
        got = lineup.optimize(pool, tokens)
        assert got["total"] == _oracle(pool, tokens), (trial, pool)


def test_never_worse_than_greedy():
    """The invariant asserted in production."""
    rng = random.Random(7)
    tokens = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]
    for _ in range(300):
        pool = [_p(f"p{i}", rng.choice(["QB", "RB", "WR", "TE"]),
                   round(rng.uniform(0, 25), 1))
                for i in range(rng.randint(4, 12))]
        assert lineup.optimize(pool, tokens)["total"] >= lineup.greedy_total(pool, tokens)


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_fewer_players_than_slots_leaves_holes():
    """Carrying exactly one kicker and one defense is normal, not an error."""
    got = lineup.optimize([_p("k1", "K", 8.0)], ["K", "DEF"])
    seated = {a["slot"]: a["player_id"] for a in got["assignment"]}
    assert seated == {"K": "k1", "DEF": None}
    assert got["total"] == 8.0


def test_empty_inputs():
    assert lineup.optimize([], ["QB", "FLEX"])["total"] == 0.0
    assert lineup.optimize([_p("a", "QB", 10)], [])["assignment"] == []


def test_negative_points_still_fill_the_slot():
    """A defense can project negative; benching it for nobody is not an option."""
    got = lineup.optimize([_p("d", "DEF", -2.0)], ["DEF"])
    assert got["assignment"][0]["player_id"] == "d"
    assert got["started"] == ["d"]


def test_unavailable_players_are_never_started():
    pool = [_p("bye", "QB", 22.0, available=False), _p("ok", "QB", 9.0)]
    got = lineup.optimize(pool, ["QB"])
    assert got["assignment"][0]["player_id"] == "ok"
    assert "bye" in got["benched"]


def test_ties_break_deterministically():
    """Without a stable tiebreak the page reshuffles between refreshes."""
    pool = [_p("b", "WR", 10.0), _p("a", "WR", 10.0)]
    runs = {tuple(a["player_id"] for a in lineup.optimize(pool, ["WR"])["assignment"])
            for _ in range(20)}
    assert len(runs) == 1
    assert runs.pop() == ("a",)          # tie broken on player_id


def test_multi_position_eligibility_is_used():
    """A WR carrying RB eligibility can fill an RB slot; position alone can't."""
    pool = [_p("dual", "WR", 12.0, fantasy_positions=["WR", "RB"])]
    assert lineup.optimize(pool, ["RB"])["assignment"][0]["player_id"] == "dual"
    plain = [_p("plain", "WR", 12.0)]
    assert lineup.optimize(plain, ["RB"])["assignment"][0]["player_id"] is None


def test_idp_slots_are_displayed_but_not_filled():
    pool = [_p("lb", "LB", 11.0)]
    got = lineup.optimize(pool, ["QB", "LB"])
    lb = [a for a in got["assignment"] if a["slot"] == "LB"][0]
    assert lb["optimizable"] is False and lb["player_id"] is None
    assert got["total"] == 0.0           # IDP never counts toward the delta


# ── diff() ───────────────────────────────────────────────────────────────────

def _assign(slot, pid, pts, optimizable=True):
    return {"slot": slot, "slot_label": slots.slot_label(slot),
            "player_id": pid, "points": pts, "optimizable": optimizable}


def test_diff_reports_worthwhile_swaps_only():
    current = [_assign("FLEX", "a", 8.0)]
    optimal = [_assign("FLEX", "b", 14.0)]
    got = lineup.diff(current, optimal, {"a": {"name": "A"}, "b": {"name": "B"}})
    assert len(got) == 1
    assert got[0]["gain"] == 6.0 and got[0]["start"]["name"] == "B"


def test_diff_suppresses_noise():
    """A 0.4-point swap is not a recommendation, it is projection noise."""
    current = [_assign("FLEX", "a", 8.0)]
    optimal = [_assign("FLEX", "b", 8.4)]
    assert lineup.diff(current, optimal, {}) == []


def test_diff_sorts_by_gain_and_skips_idp():
    current = [_assign("FLEX", "a", 1.0), _assign("WR", "c", 1.0),
               _assign("LB", "e", 1.0, optimizable=False)]
    optimal = [_assign("FLEX", "b", 4.0), _assign("WR", "d", 20.0),
               _assign("LB", "f", 30.0, optimizable=False)]
    got = lineup.diff(current, optimal, {})
    assert [c["slot"] for c in got] == ["WR", "FLEX"]
