"""Slot identity and eligibility — the table the lineup optimizer is built on."""
import draft_values
import slots


REAL_LEAGUE = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX",
               "SUPER_FLEX", "K", "DEF"] + ["BN"] * 7 + ["IR"] * 5


def test_lineup_slots_keeps_league_order_and_drops_bench():
    assert slots.lineup_slots(REAL_LEAGUE) == [
        "QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF",
    ]


def test_lineup_slots_is_total():
    assert slots.lineup_slots(None) == []
    assert slots.lineup_slots([]) == []
    assert slots.lineup_slots(["  qb ", "bn", "WeIrD"]) == ["QB", "WEIRD"]


def test_labels():
    assert slots.slot_label("SUPER_FLEX") == "SFLEX"
    assert slots.slot_label("REC_FLEX") == "W/T"
    assert slots.slot_label("WRRB_FLEX") == "W/R"
    assert slots.slot_label("DST") == "DEF"
    # Unknown tokens fall through to themselves rather than vanishing
    assert slots.slot_label("QB") == "QB"
    assert slots.slot_label("SOMETHING_NEW") == "SOMETHING_NEW"


def test_flex_eligibility_matches_the_replacement_model():
    """
    slots.SLOT_ELIGIBILITY and draft_values.FLEX_SHARES encode the same fact —
    who can fill a flex slot — for two different purposes. If they ever drift,
    the draft board and the lineup optimizer disagree about the same league.
    """
    pairs = [("FLEX", "flex"), ("SUPER_FLEX", "sflex"),
             ("REC_FLEX", "rec_flex"), ("WRRB_FLEX", "wr_rb_flex")]
    for token, share_key in pairs:
        assert slots.eligible_positions(token) == set(draft_values.FLEX_SHARES[share_key]), token


def test_is_eligible_prefers_fantasy_positions_over_position():
    # A WR who also carries RB eligibility can fill a WRRB_FLEX either way,
    # but only fantasy_positions makes him legal in an RB slot.
    assert slots.is_eligible("RB", ["WR", "RB"], "WR") is True
    assert slots.is_eligible("RB", None, "WR") is False
    # Falls back to `position` when the richer field hasn't loaded yet
    assert slots.is_eligible("FLEX", None, "TE") is True
    assert slots.is_eligible("FLEX", None, "QB") is False
    assert slots.is_eligible("SUPER_FLEX", None, "QB") is True


def test_is_eligible_handles_defense_aliases():
    assert slots.is_eligible("DEF", None, "DST") is True
    assert slots.is_eligible("DST", None, "DEF") is True
    assert slots.is_eligible("K", None, "PK") is True


def test_unknown_slot_admits_nobody():
    assert slots.eligible_positions("NOT_A_SLOT") == frozenset()
    assert slots.is_eligible("NOT_A_SLOT", ["QB"], "QB") is False


def test_slot_width_orders_narrow_before_wide():
    assert slots.slot_width("QB") == 1
    assert slots.slot_width("REC_FLEX") == 2
    assert slots.slot_width("FLEX") == 3
    assert slots.slot_width("SUPER_FLEX") == 4


def test_idp_slots_are_flagged_unprojected():
    assert slots.is_projected("FLEX") is True
    assert slots.is_projected("IDP_FLEX") is False
    assert slots.is_projected("LB") is False


def test_draft_values_still_parses_through_the_shared_table():
    """The slot-count parser now reads slots.SLOT_MAP; behaviour must not move."""
    parsed = draft_values.parse_roster_positions(REAL_LEAGUE)
    assert parsed["qb"] == 1 and parsed["rb"] == 2 and parsed["wr"] == 3
    assert parsed["te"] == 1 and parsed["k"] == 1 and parsed["dst"] == 1
    assert parsed["flex"] == 1 and parsed["sflex"] == 1
    assert parsed["bench"] == 7
    assert parsed["num_qbs"] == 2          # QB + SUPER_FLEX
    assert parsed["unknown"] == []
