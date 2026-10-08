"""
Dynasty pick values must fall monotonically in overall pick number.

The bug this pins: pick values were scaled per round, so a 2027 2nd (~2.03-2.05)
priced at 1,911 while a 2027 1st (~1.10-1.12) priced at 1,646. Seven of twelve
second-rounders outvalued the worst first. Nothing tested pick value at all.
"""
import pytest

import pick_curve


# Real FantasyCalc values, from the live picks_cache.
A2027 = {1: 2930, 2: 1576, 3: 1062, 4: 849}
A2026 = {1: 3160, 2: 1708, 3: 1162, 4: 881}
A2028 = {1: 2143, 2: 1315, 3: 976, 4: 802}
A2029 = {1: 1982, 2: 1246, 3: 983, 4: 809}
ALL_SEASONS = {"2026": A2026, "2027": A2027, "2028": A2028, "2029": A2029}


def _values(anchors, num_teams, rounds):
    return [v for _, _, v in pick_curve.curve(anchors, num_teams, rounds)]


# ── The guarantee ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("num_teams", [8, 10, 12, 14])
@pytest.mark.parametrize("season", sorted(ALL_SEASONS))
def test_value_strictly_decreases_across_every_pick(season, num_teams):
    """
    The assertion whose absence let the bug ship. Covers every consecutive pick
    from 1.01 to the end of the last round, not just within a round.
    """
    vals = _values(ALL_SEASONS[season], num_teams, rounds=4)
    for i in range(len(vals) - 1):
        assert vals[i] > vals[i + 1], (
            f"{season} {num_teams}-team: pick {i + 1} ({vals[i]}) "
            f"does not beat pick {i + 2} ({vals[i + 1]})"
        )


def test_the_reported_inversion_is_gone():
    """A 1.10-1.12 must price above a 2.03-2.05. It priced 1,646 vs 1,911."""
    late_first = pick_curve.value_at(A2027, 1, 11, 12)      # ~1.10-1.12
    early_second = pick_curve.value_at(A2027, 2, 4, 12)     # ~2.03-2.05
    assert late_first > early_second


def test_round_boundaries_hold():
    """Where the old code broke: last pick of a round vs first of the next."""
    for rnd in (1, 2, 3):
        assert (pick_curve.value_at(A2027, rnd, 12, 12)
                > pick_curve.value_at(A2027, rnd + 1, 1, 12))


def test_no_second_rounder_outvalues_any_first():
    """Seven of twelve used to."""
    worst_first = pick_curve.value_at(A2027, 1, 12, 12)
    best_second = pick_curve.value_at(A2027, 2, 1, 12)
    assert worst_first > best_second


# ── Anchored to FantasyCalc ──────────────────────────────────────────────────

def test_each_rounds_midpoint_is_fantasycalcs_own_value():
    """The curve infers shape, never the level."""
    for rnd, want in A2027.items():
        got = pick_curve.value_at(A2027, rnd, (12 + 1) / 2, 12)
        assert got == pytest.approx(want, rel=0.001), rnd


def test_early_picks_still_carry_a_real_premium():
    """
    The point of the original change — 1.01 must clearly beat a late first —
    just without inverting the rounds to achieve it.
    """
    first, ninth, last = (pick_curve.value_at(A2027, 1, s, 12) for s in (1, 9, 12))
    assert first > ninth > last
    assert first / last > 1.5


def test_seasons_are_priced_independently():
    """A 2027 1st and a 2029 1st sit on different curves."""
    assert (pick_curve.value_at(A2027, 1, 1, 12)
            > pick_curve.value_at(A2029, 1, 1, 12))


# ── Degenerate input must never raise or invert ──────────────────────────────

def test_no_anchors_returns_zero_so_callers_can_fall_back():
    assert pick_curve.value_at({}, 1, 1, 12) == 0
    assert pick_curve.value_at(None or {}, 2, 6, 12) == 0


def test_single_round_of_data_is_flat_not_invented():
    vals = {pick_curve.value_at({1: 3000}, 1, s, 12) for s in range(1, 13)}
    assert vals == {3000}


def test_garbage_values_are_skipped():
    anchors = {1: 2930, 2: None, 3: "nonsense", 4: 849}
    vals = _values(anchors, 12, rounds=4)
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))


def test_non_decreasing_anchors_cannot_reintroduce_an_inversion():
    """
    One bad cache row must not undo the guarantee.

    Asserts non-increasing rather than strictly decreasing: the clamp flattens a
    corrupted segment to near-zero slope, so adjacent picks can tie once rounded
    to integers. Ties are fine — inventing a gradient out of garbage data would
    not be. Strict decrease is asserted above, on real FantasyCalc values.
    """
    anchors = {1: 1000, 2: 5000, 3: 900}        # round 2 absurdly high
    vals = _values(anchors, 12, rounds=3)
    assert all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
    assert vals[0] > vals[-1]                   # still falls overall


def test_zero_and_negative_values_are_dropped():
    vals = _values({1: 2930, 2: 0, 3: -5, 4: 849}, 12, rounds=4)
    assert all(v >= 1 for v in vals)
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))


def test_rounds_beyond_the_anchor_data_extrapolate_downward():
    """A 5-round rookie draft with only 4 rounds of FantasyCalc data."""
    vals = _values(A2027, 12, rounds=5)
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
    assert vals[-1] >= 1


def test_fractional_slots_are_accepted():
    """compute_league_profiles passes a midpoint like 1.5 or 11.5."""
    a = pick_curve.value_at(A2027, 1, 1.5, 12)
    b = pick_curve.value_at(A2027, 1, 2.0, 12)
    assert a > b
