"""
Draft pick order, including third round reversal.

A live draft showed the wrong team on the clock because the model was a pure
snake and the league used 3RR. None of this had test coverage.
"""
import draft_values


N = 12                       # teams


def _order(reversal, rounds=5, num_teams=N):
    """Slot for every pick of the first `rounds` rounds."""
    return [draft_values.snake_slot(i, num_teams, reversal)
            for i in range(rounds * num_teams)]


def _round_of(order, rnd, num_teams=N):
    return order[(rnd - 1) * num_teams: rnd * num_teams]


# ── Plain snake must not move ────────────────────────────────────────────────

def test_plain_snake_is_unchanged():
    o = _order(0)
    assert _round_of(o, 1) == list(range(1, 13))
    assert _round_of(o, 2) == list(range(12, 0, -1))
    assert _round_of(o, 3) == list(range(1, 13))
    assert _round_of(o, 4) == list(range(12, 0, -1))


def test_default_argument_keeps_the_old_signature_behaviour():
    for i in range(60):
        assert draft_values.snake_slot(i, N) == draft_values.snake_slot(i, N, 0)


def test_matches_the_previous_inlined_formula_for_a_plain_snake():
    """_on_clock was a duplicate of this; removing it must change nothing."""
    def old(picks_made, num_teams):
        rnd = picks_made // num_teams
        pos = picks_made % num_teams
        return (pos + 1) if rnd % 2 == 0 else (num_teams - pos)

    for i in range(N * 16):
        assert draft_values.snake_slot(i, N, 0) == old(i, N)


# ── Third round reversal ─────────────────────────────────────────────────────

def test_third_round_reversal_sequence():
    """
    Rounds 1-2 as normal; round 3 runs backwards again, so the team that picked
    last in round 2 does not also pick first in round 3.
    """
    o = _order(3)
    assert _round_of(o, 1) == list(range(1, 13))          # 1 -> 12
    assert _round_of(o, 2) == list(range(12, 0, -1))      # 12 -> 1
    assert _round_of(o, 3) == list(range(12, 0, -1))      # 12 -> 1  (the reversal)
    assert _round_of(o, 4) == list(range(1, 13))          # 1 -> 12
    assert _round_of(o, 5) == list(range(12, 0, -1))


def test_the_divergence_starts_exactly_at_pick_25():
    """2 x num_teams + 1 — everything before it must be identical."""
    snake, rrr = _order(0), _order(3)
    assert snake[:24] == rrr[:24]
    assert snake[24] == 1 and rrr[24] == 12
    assert all(a != b for a, b in zip(snake[24:36], rrr[24:36]))


def test_the_back_to_back_double_moves():
    """
    Standard snake gives slot 1 picks 24 and 25 back to back. 3RR removes that
    and compensates the team at the turn, which is the point of the option.
    """
    snake, rrr = _order(0), _order(3)
    assert snake[23] == 1 and snake[24] == 1              # slot 1 picks twice
    assert rrr[23] == 1 and rrr[24] == 12                 # no longer
    # Slot 12 waited from pick 13 to 36 under snake; now it picks at 25.
    assert snake.index(12, 24) == 35
    assert rrr.index(12, 24) == 24


def test_reversal_at_other_rounds_is_supported():
    """Sleeper allows any round, so this isn't hardcoded to 3."""
    o = _order(2, rounds=4)
    assert _round_of(o, 1) == list(range(1, 13))
    assert _round_of(o, 2) == list(range(1, 13))          # flipped from 12->1
    assert _round_of(o, 3) == list(range(12, 0, -1))


def test_every_team_picks_exactly_once_per_round():
    for reversal in (0, 2, 3, 4):
        o = _order(reversal, rounds=6)
        for rnd in range(1, 7):
            assert sorted(_round_of(o, rnd)) == list(range(1, 13)), (reversal, rnd)


def test_odd_team_counts():
    for teams in (8, 10, 11, 14):
        o = [draft_values.snake_slot(i, teams, 3) for i in range(teams * 4)]
        for rnd in range(4):
            chunk = o[rnd * teams:(rnd + 1) * teams]
            assert sorted(chunk) == list(range(1, teams + 1))


# ── Fitting the model to picks that actually happened ────────────────────────

def _observed(reversal, n_picks, num_teams=N):
    """[(pick_no, draft_slot)] as Sleeper would report them."""
    return [(i + 1, draft_values.snake_slot(i, num_teams, reversal))
            for i in range(n_picks)]


def test_declared_setting_is_used_when_it_matches():
    got, verified = draft_values.infer_reversal_round(_observed(3, 30), N, declared=3)
    assert (got, verified) == (3, True)


def test_a_wrong_declared_setting_is_corrected_from_the_picks():
    """The live failure: told it was a snake, but the picks say otherwise."""
    got, verified = draft_values.infer_reversal_round(_observed(3, 30), N, declared=0)
    assert (got, verified) == (3, True)


def test_a_spurious_reversal_setting_is_also_corrected():
    got, verified = draft_values.infer_reversal_round(_observed(0, 30), N, declared=3)
    assert (got, verified) == (0, True)


def test_before_round_three_the_two_are_indistinguishable():
    """
    Rounds 1-2 are identical under both rules, so the declared value must win —
    there is no evidence to overturn it.
    """
    for declared in (0, 3):
        got, _ = draft_values.infer_reversal_round(_observed(3, 24), N, declared=declared)
        assert got == declared


def test_one_pick_into_round_three_settles_it():
    got, verified = draft_values.infer_reversal_round(_observed(3, 25), N, declared=0)
    assert (got, verified) == (3, True)


def test_no_picks_yet_falls_back_to_the_declared_value():
    assert draft_values.infer_reversal_round([], N, declared=3) == (3, False)
    assert draft_values.infer_reversal_round([], N, declared=0) == (0, False)


def test_incoherent_picks_keep_the_declared_value_and_report_unverified():
    """Never assert a confident wrong answer."""
    nonsense = [(1, 5), (2, 5), (3, 5), (25, 7)]
    got, verified = draft_values.infer_reversal_round(nonsense, N, declared=3)
    assert (got, verified) == (3, False)


def test_partial_pick_data_is_ignored_not_fatal():
    """A pick missing draft_slot must not break the fit."""
    observed = _observed(3, 30) + [(31, None), (None, 4)]
    got, verified = draft_values.infer_reversal_round(observed, N, declared=0)
    assert (got, verified) == (3, True)
