"""
DraftKings Classic scoring.

Values pinned against hand-computed stat lines. The bonus behaviour gets the
most attention because it is the part that cannot be expressed as a per-unit
rate, and therefore the part a delta-based scorer (like league_points) gets
wrong by construction.
"""
import pytest

import dk_scoring as dk


# ── Offense, per-unit rates ──────────────────────────────────────────────────

def test_passing_line():
    # 250 yards, 2 TD, 1 INT. No bonus at 250.
    line = {"pass_yd": 250, "pass_td": 2, "pass_int": 1}
    assert dk.dk_points(line, expected_bonuses=False) == pytest.approx(10 + 8 - 1)


def test_receiving_is_full_ppr():
    line = {"rec": 8, "rec_yd": 80, "rec_td": 1}
    # 8 receptions + 8.0 yards + 6 TD
    assert dk.dk_points(line, expected_bonuses=False) == pytest.approx(8 + 8 + 6)


def test_rushing_line():
    line = {"rush_yd": 70, "rush_td": 1}
    assert dk.dk_points(line, expected_bonuses=False) == pytest.approx(7 + 6)


def test_negatives_and_extras():
    line = {"rush_yd": 50, "fum_lost": 1, "rush_2pt": 1, "kr_td": 1}
    # 5.0 - 1 + 2 + 6
    assert dk.dk_points(line, expected_bonuses=False) == pytest.approx(5 - 1 + 2 + 6)


def test_empty_line_is_zero():
    assert dk.dk_points({}) == 0.0
    assert dk.dk_points(None) == 0.0


# ── Bonuses — the part a delta scorer cannot express ─────────────────────────

def test_deterministic_bonuses_fire_at_the_threshold():
    just_under = dk.dk_points({"rush_yd": 99}, expected_bonuses=False)
    exactly = dk.dk_points({"rush_yd": 100}, expected_bonuses=False)
    assert exactly - just_under == pytest.approx(0.1 + 3.0)

    assert dk.dk_points({"pass_yd": 299}, expected_bonuses=False) == pytest.approx(11.96)
    assert dk.dk_points({"pass_yd": 300}, expected_bonuses=False) == pytest.approx(12.0 + 3.0)


def test_bonuses_stack():
    line = {"rush_yd": 120, "rec_yd": 110, "rec": 5}
    base = 12.0 + 11.0 + 5
    assert dk.dk_points(line, expected_bonuses=False) == pytest.approx(base + 6.0)


def test_expected_bonus_is_nonzero_below_the_threshold():
    """
    The reason this exists: a 95-yard projection is not a zero-bonus player.
    Scoring a mean through a hard threshold systematically undervalues exactly
    the high-volume players a cash lineup is built on.
    """
    det = dk.dk_points({"rush_yd": 95}, expected_bonuses=False)
    exp = dk.dk_points({"rush_yd": 95}, expected_bonuses=True)
    assert det == pytest.approx(9.5)
    assert exp > det + 0.5, "a 95-yard projection should carry real bonus equity"
    assert exp < det + 3.0, "but not the full bonus"


def test_expected_bonus_rises_with_the_projection():
    vals = [dk.dk_points({"rush_yd": y}, expected_bonuses=True) - y * 0.1
            for y in (60, 80, 95, 110, 140)]
    assert vals == sorted(vals), "bonus equity must increase with volume"
    assert vals[0] < 0.6, "60 yards carries little bonus equity"
    assert vals[-1] > 1.9, "140 yards carries most of it"


def test_expected_bonus_is_capped_by_the_bonus_itself():
    for y in (100, 200, 400):
        equity = dk.dk_points({"rush_yd": y}, expected_bonuses=True) - y * 0.1
        assert 0.0 <= equity <= 3.0


def test_tiny_projections_get_no_bonus_equity():
    assert dk.dk_points({"rush_yd": 10}, expected_bonuses=True) == pytest.approx(1.0)
    assert dk.dk_points({"pass_yd": 40}, expected_bonuses=True) == pytest.approx(1.6)


def test_probability_is_a_probability():
    for proj, thresh in [(0, 100), (50, 100), (100, 100), (250, 100), (300, 300)]:
        p = dk._bonus_probability(proj, thresh)
        assert 0.0 <= p <= 1.0, (proj, thresh)
    # At the threshold the median sits below the mean for a right-skewed
    # distribution, so P(>= mean) is a little under a half.
    assert 0.35 < dk._bonus_probability(100, 100) < 0.5


# ── A realistic full line ────────────────────────────────────────────────────

def test_a_full_receiving_day():
    """9 catches, 124 yards, 1 TD — a real DK stat line, hand-computed."""
    line = {"rec": 9, "rec_yd": 124, "rec_td": 1}
    # 9 + 12.4 + 6 + 3 bonus
    assert dk.dk_points(line, expected_bonuses=False) == pytest.approx(30.4)


def test_a_full_passing_day():
    """330 yards, 3 TD, 1 INT, 20 rush yards."""
    line = {"pass_yd": 330, "pass_td": 3, "pass_int": 1, "rush_yd": 20}
    # 13.2 + 12 - 1 + 2.0 + 3 bonus
    assert dk.dk_points(line, expected_bonuses=False) == pytest.approx(29.2)


# ── Defense ──────────────────────────────────────────────────────────────────

def test_points_allowed_tiers():
    assert dk.dst_points_allowed(0) == 10.0
    assert dk.dst_points_allowed(3) == 7.0
    assert dk.dst_points_allowed(6) == 7.0
    assert dk.dst_points_allowed(7) == 4.0
    assert dk.dst_points_allowed(13) == 4.0
    assert dk.dst_points_allowed(14) == 1.0
    assert dk.dst_points_allowed(20) == 1.0
    assert dk.dst_points_allowed(21) == 0.0
    assert dk.dst_points_allowed(27) == 0.0
    assert dk.dst_points_allowed(28) == -1.0
    assert dk.dst_points_allowed(34) == -1.0
    assert dk.dst_points_allowed(35) == -4.0
    assert dk.dst_points_allowed(70) == -4.0


def test_tiers_never_increase_with_points_allowed():
    vals = [dk.dst_points_allowed(n) for n in range(0, 60)]
    assert vals == sorted(vals, reverse=True)


def test_dst_line():
    line = {"sacks": 4, "interceptions": 2, "fumble_recoveries": 1,
            "def_tds": 1, "points_allowed": 10}
    # 4 + 4 + 2 + 6 + 4 (7-13 tier)
    assert dk.dk_dst_points(line) == pytest.approx(20.0)


def test_dst_shutout():
    assert dk.dk_dst_points({"sacks": 3, "points_allowed": 0}) == pytest.approx(13.0)


def test_dst_blowout_loss_goes_negative():
    assert dk.dk_dst_points({"points_allowed": 45}) == pytest.approx(-4.0)


def test_dst_blocks_and_safeties():
    line = {"points_allowed": 24, "safeties": 1, "punt_blocks": 1, "fg_blocks": 1}
    assert dk.dk_dst_points(line) == pytest.approx(0.0 + 2 + 2 + 2)
