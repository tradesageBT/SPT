"""
league_points restates Sleeper's standard-scoring totals under a league's rules.

Two bugs are pinned here:
  * pass_td / rush_att were only ever applied when a caller passed them
    explicitly, so callers that passed scoring_settings alone silently scored
    every QB and RB under 4-point pass TDs and no per-carry bonus.
  * bonus_rec_te was read into the leagues table and displayed, but never
    actually applied to anyone's points.
"""
import draft_values


# 3 pass TDs, 30 carries, 6 catches, 40 return yards.
STATS = {
    "pts_ppr": 20.0, "pts_half_ppr": 17.0, "pts_std": 14.0,
    "pass_td": 3, "rush_att": 30, "rec": 6, "kr_yd": 25, "pr_yd": 15,
}


def test_baseline_is_sleepers_own_number():
    assert draft_values.league_points(STATS, 1) == 20.0
    assert draft_values.league_points(STATS, 0.5) == 17.0
    assert draft_values.league_points(STATS, 0) == 14.0


def test_pass_td_comes_from_scoring_settings():
    """The regression: scoring_settings alone used to be ignored for pass TDs."""
    six = draft_values.league_points(STATS, 1, scoring_settings={"pass_td": 6})
    assert six == 26.0                      # 20 + 3 TDs x 2 extra points
    assert six - draft_values.league_points(STATS, 1) == 6.0


def test_rush_att_comes_from_scoring_settings():
    got = draft_values.league_points(STATS, 1, scoring_settings={"rush_att": 0.25})
    assert got == 27.5                      # 20 + 30 carries x 0.25


def test_te_premium_applies_to_tight_ends_only():
    scoring = {"bonus_rec_te": 0.5}
    te = draft_values.league_points(STATS, 1, scoring_settings=scoring, position="TE")
    wr = draft_values.league_points(STATS, 1, scoring_settings=scoring, position="WR")
    assert te == 23.0                       # 20 + 6 catches x 0.5
    assert wr == 20.0                       # premium must not leak to other positions


def test_te_premium_reads_position_off_the_stat_row_when_not_passed():
    scoring = {"bonus_rec_te": 0.5}
    row = {**STATS, "position": "TE"}
    assert draft_values.league_points(row, 1, scoring_settings=scoring) == 23.0
    # No position anywhere: skipped rather than guessed
    assert draft_values.league_points(STATS, 1, scoring_settings=scoring) == 20.0


def test_return_yards_still_apply():
    got = draft_values.league_points(STATS, 1, scoring_settings={"kr_yd": 0.04, "pr_yd": 0.04})
    assert got == 21.6                      # 20 + 40 yards x 0.04


def test_the_users_actual_league_settings_compose():
    scoring = {"pass_td": 6, "rush_att": 0.25, "kr_yd": 0.04, "pr_yd": 0.04, "rec": 1}
    got = draft_values.league_points(STATS, 1, scoring_settings=scoring)
    assert got == 35.1                      # 20 + 6 + 7.5 + 1.6


def test_explicit_arguments_still_win_over_scoring_settings():
    """The auction tool collects these from the user for non-Sleeper leagues."""
    got = draft_values.league_points(
        STATS, 1, pass_td_pts=4.0, rush_att_pts=0.0, scoring_settings={"pass_td": 6, "rush_att": 0.25},
    )
    assert got == 20.0


def test_garbage_scoring_settings_do_not_raise():
    for bad in ({"pass_td": None}, {"pass_td": "six"}, {"rush_att": []}, {}, None):
        assert draft_values.league_points(STATS, 1, scoring_settings=bad) == 20.0


def test_missing_or_empty_stats_return_none():
    assert draft_values.league_points({}, 1) is None
    assert draft_values.league_points(None, 1) is None
    assert draft_values.league_points({"pass_td": 3}, 1) is None   # no base key
