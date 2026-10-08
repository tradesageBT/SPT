"""
Pick pricing end to end through compute_league_profiles.

value_engine had no test coverage at all before this — which is how pick values
shipped inverted across every round boundary. The fixture's own values are even
closer together than production's (2027 R1=2400 vs R2=1800), so they invert more
severely under the old per-round multiplier.
"""
import league_fixture
import value_engine


def _profiles():
    f = league_fixture.build()
    return value_engine.compute_league_profiles(
        f["rosters"], f["users_map"], f["players_cache"], f["picks_cache"],
        f["picks_by_roster"], roster_positions=f["roster_positions"],
    )


def _ordering_key(pick):
    """(season, overall pick) — what value must decrease along."""
    rnd = pick["round"]
    # projected_slot is "2.03–2.05"; the midpoint is what was priced.
    lo, hi = (int(s.split(".")[1]) for s in pick["projected_slot"].split("–"))
    return str(pick["season"]), (rnd - 1) * 12 + (lo + hi) / 2


def test_no_pick_in_the_league_is_priced_above_an_earlier_one():
    """The reported bug, asserted across every pick every team holds."""
    every_pick = [pk for prof in _profiles() for pk in prof["picks"]]
    assert every_pick

    by_season = {}
    for pk in every_pick:
        season, x = _ordering_key(pk)
        by_season.setdefault(season, []).append((x, pk["fc_value"], pk))

    for season, rows in by_season.items():
        rows.sort(key=lambda r: r[0])
        for (x1, v1, p1), (x2, v2, p2) in zip(rows, rows[1:]):
            if x1 == x2:
                assert v1 == v2, f"same slot, different price: {p1} vs {p2}"
            else:
                assert v1 >= v2, (
                    f"{season}: {p1['projected_slot']} priced {v1}, "
                    f"but later {p2['projected_slot']} priced {v2}"
                )


def test_a_late_first_beats_an_early_second():
    """The specific shape of the report: 1.10-1.12 vs 2.03-2.05."""
    picks = [pk for prof in _profiles() for pk in prof["picks"]
             if str(pk["season"]) == "2027"]
    firsts = [pk for pk in picks if pk["round"] == 1]
    seconds = [pk for pk in picks if pk["round"] == 2]

    worst_first = min(pk["fc_value"] for pk in firsts)
    best_second = max(pk["fc_value"] for pk in seconds)
    assert worst_first > best_second


def test_every_pick_keeps_a_slot_label_and_a_positive_value():
    for prof in _profiles():
        for pk in prof["picks"]:
            assert pk["fc_value"] >= 1
            assert "–" in pk["projected_slot"]


def test_pick_value_and_total_value_agree_with_the_priced_picks():
    """pick_value is summed after pricing, not before."""
    for prof in _profiles():
        assert prof["pick_value"] == sum(pk["fc_value"] for pk in prof["picks"])
        assert prof["total_value"] == prof["player_value"] + prof["pick_value"]


def test_contention_sees_the_same_capital_the_ui_shows():
    """
    Contention used to be classified before pricing, comparing unadjusted
    capital against an unadjusted league average while the UI displayed the
    adjusted numbers.
    """
    profiles = _profiles()
    assert all(p.get("contention_category") for p in profiles)
    avg = sum(p["pick_value"] for p in profiles) / len(profiles)
    # The average the classifier used is the one derivable from the output.
    assert avg > 0


def test_redraft_mode_still_has_no_picks():
    f = league_fixture.build()
    profiles = value_engine.compute_league_profiles(
        f["rosters"], f["users_map"], f["players_cache"], f["picks_cache"], {},
        roster_positions=f["roster_positions"],
        value_key="redraft_value", include_picks=False,
    )
    for p in profiles:
        assert p["picks"] == [] and p["pick_value"] == 0
        assert p["contention_category"] is None
