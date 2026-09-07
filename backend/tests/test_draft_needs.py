"""
Positional needs and best-fit selection for the Sleeper draft room.

Pins the reported bug: in a superflex league the "best fit" panel recommended a
QB almost every pick regardless of how many were already rostered. None of this
had test coverage before.
"""
import draft_values
from routers.sleeper_draft import _best_fit


# The league the draft room defaults to: 1 QB + SUPER_FLEX, 2 RB, 3 WR, 1 TE,
# 1 FLEX, K, DEF, 7 bench.
ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX",
                    "SUPER_FLEX", "K", "DEF"] + ["BN"] * 7

SLOTS = draft_values.parse_roster_positions(ROSTER_POSITIONS)
STARTERS = {"QB": SLOTS["qb"], "RB": SLOTS["rb"], "WR": SLOTS["wr"],
            "TE": SLOTS["te"], "K": SLOTS["k"], "DEF": SLOTS["dst"]}
FLEX_COUNTS = {k: SLOTS[k] for k in draft_values.FLEX_KEYS}
TARGETS = draft_values.roster_targets(STARTERS, FLEX_COUNTS, SLOTS["bench"])


def _needs(counts):
    return draft_values.team_needs(counts, TARGETS, STARTERS,
                                   roster_size=sum(TARGETS.values()))


# ── The target arithmetic, pinned ────────────────────────────────────────────

def test_superflex_is_read_as_two_quarterbacks():
    assert SLOTS["num_qbs"] == 2
    assert SLOTS["sflex"] == 1 and SLOTS["bench"] == 7


def test_qb_target_and_its_components():
    """1.0 starter + 0.75 SUPER_FLEX share + 0.10x7 bench share."""
    assert round(TARGETS["QB"], 2) == 2.45
    assert round(TARGETS["RB"], 2) == 5.35
    assert round(TARGETS["WR"], 2) == 6.37
    assert round(TARGETS["TE"], 2) == 1.83


def test_targets_sum_to_draftable_spots():
    """Guards FLEX_SHARES and BENCH_SHARES each summing to 1."""
    assert round(sum(TARGETS.values()), 6) == 18.0        # 11 starters + 7 bench


def test_raw_qb_gap_stays_positive_until_the_third_quarterback():
    """
    The root of the bug: `fills_need` is a boolean on this gap, so every QB on
    the board looked equally needed right up to the third one.
    """
    gaps = [_needs({"QB": n})["gaps"]["QB"] for n in range(4)]
    assert gaps == [2.45, 1.45, 0.45, -0.55]


# ── The needs RANKING was never the problem ──────────────────────────────────

def test_top_need_is_never_qb_once_two_are_rostered():
    for n in (2, 3, 4):
        needs = _needs({"QB": n})
        assert needs["top_need"] != "QB", (n, needs["ordered"])


def test_proportional_weight_decays_as_the_position_fills():
    """Unlike the raw gap, this has magnitude — which is what best fit needs."""
    props = [_needs({"QB": n})["prop"]["QB"] for n in range(3)]
    assert props == [1.0, 0.592, 0.184]


def test_prop_is_returned_for_every_position():
    needs = _needs({"QB": 1, "RB": 2})
    assert set(needs["prop"]) == set(draft_values.POSITIONS)


# ── Best fit ─────────────────────────────────────────────────────────────────

def _player(pid, pos, value, vor, needs):
    """Shaped like a row of the `available` list the endpoint builds."""
    return {
        "player_id": pid, "position": pos,
        "redraft_value": value, "vor": vor,
        "fills_need": needs["gaps"].get(pos, 0) > 0,
        "need_weight": needs["prop"].get(pos, 0),
    }


def _board(needs):
    """
    A superflex board: QBs priced at the top, as FantasyCalc actually returns
    them when numQbs=2. VOR narrows the gap but does not close it.
    """
    return [
        _player("qb_top", "QB", 9000, 4200, needs),
        _player("qb_2",   "QB", 8000, 3400, needs),
        _player("rb_top", "RB", 6000, 3000, needs),
        _player("wr_top", "WR", 5500, 2900, needs),
        _player("te_top", "TE", 5000, 2600, needs),
    ]


def test_the_reported_bug_two_qbs_rostered_no_longer_returns_a_qb():
    """With 2 QBs and 3 WRs already in, best fit must not be another QB."""
    needs = _needs({"QB": 2, "RB": 1, "WR": 3, "TE": 1})
    assert _best_fit(_board(needs)) != "qb_top"


def test_three_qbs_rostered_removes_qbs_from_the_running_entirely():
    needs = _needs({"QB": 3, "RB": 1, "WR": 1})
    board = _board(needs)
    assert all(not p["fills_need"] for p in board if p["position"] == "QB")
    assert _best_fit(board) not in ("qb_top", "qb_2")


def test_the_fix_is_not_simply_inverted_a_qb_is_reachable_with_none_rostered():
    """An empty roster genuinely needs a quarterback in a superflex league."""
    needs = _needs({})
    assert _best_fit(_board(needs)) == "qb_top"


def test_best_fit_can_differ_from_best_available():
    """
    The old implementation structurally could not: it took the first entry of a
    value-sorted list, so once one position topped the board it always won.
    """
    needs = _needs({"QB": 2, "RB": 1, "WR": 2, "TE": 1})
    board = _board(needs)
    best_available = board[0]["player_id"]
    assert _best_fit(board) != best_available


def test_the_old_implementation_would_have_failed_these():
    """Reproduces the previous logic to show the difference is real, not luck."""
    needs = _needs({"QB": 2, "RB": 1, "WR": 3, "TE": 1})
    board = _board(needs)
    old = next((p["player_id"] for p in board if p["fills_need"]), None)
    assert old == "qb_top"                    # the bug, exactly
    assert _best_fit(board) != old            # and the fix


def test_need_still_loses_to_a_big_enough_value_gap():
    """
    Fit is a weighting, not a veto — a genuinely elite player at a thinner need
    should still win, or the panel just becomes "draft your worst position".
    """
    needs = _needs({"QB": 1, "RB": 1, "WR": 1, "TE": 1})
    board = [
        _player("qb_elite", "QB", 9000, 9000, needs),
        _player("wr_ok", "WR", 3000, 1200, needs),
    ]
    assert _best_fit(board) == "qb_elite"


def test_no_candidates_returns_none():
    needs = _needs({"QB": 9, "RB": 9, "WR": 9, "TE": 9, "K": 9, "DEF": 9})
    board = _board(needs)
    assert all(not p["fills_need"] for p in board)
    assert _best_fit(board) is None


def test_kickers_and_defenses_do_not_crash_on_null_vor():
    """K/DEF carry vor=None and value=0 all the way through the endpoint."""
    needs = _needs({"QB": 2, "RB": 4, "WR": 5, "TE": 2})
    board = [
        {"player_id": "k1", "position": "K", "redraft_value": 0, "vor": None,
         "fills_need": True, "need_weight": needs["prop"]["K"]},
        {"player_id": "rb", "position": "RB", "redraft_value": 2000, "vor": 800,
         "fills_need": True, "need_weight": needs["prop"]["RB"]},
    ]
    assert _best_fit(board) == "rb"


def test_all_below_replacement_falls_back_to_value_order():
    """Late in a draft everyone left is under replacement; still pick someone."""
    needs = _needs({"QB": 1, "RB": 1})
    board = [
        _player("a", "RB", 400, -50, needs),
        _player("b", "RB", 200, -90, needs),
    ]
    assert _best_fit(board) == "a"
