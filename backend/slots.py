"""
Sleeper roster-slot semantics: what a slot is called, and who may fill it.

Deliberately a leaf module with NO imports. Three separate roster_positions
parsers grew up in this codebase and they disagree with each other:

  * routers/leagues.py         — "2 if SUPER_FLEX else count(QB)"
  * draft_values.py            — the only complete one, but it counts slots and
                                 throws the ordering away
  * value_engine.py            — ranks positions, doesn't know REC_FLEX exists

This owns the slot half of all three so a fourth never appears, and it stays
dependency-free so lineup.py can import it and remain unit-testable with no
network and no database.
"""

# Sleeper's roster_positions tokens -> our internal slot keys. Moved here from
# draft_values._SLOT_MAP; that module still owns slot COUNTS, this owns slot
# IDENTITY.
SLOT_MAP = {
    "QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "K": "k",
    "DEF": "dst", "DST": "dst",
    "FLEX": "flex", "SUPER_FLEX": "sflex", "REC_FLEX": "rec_flex",
    "WRRB_FLEX": "wr_rb_flex", "WRRB": "wr_rb_flex",
}

# Present on a roster but never part of the starting lineup.
NON_LINEUP = frozenset({"BN", "IR", "TAXI"})

# Short display labels. A slot with no entry renders under its own token.
SLOT_LABEL = {
    "SUPER_FLEX": "SFLEX", "REC_FLEX": "W/T",
    "WRRB_FLEX": "W/R", "WRRB": "W/R",
    "DST": "DEF",
}

# IDP position tokens, grouped so an IDP_FLEX can admit all of them.
_DL = frozenset({"DL", "DE", "DT", "NT"})
_LB = frozenset({"LB", "OLB", "ILB"})
_DB = frozenset({"DB", "CB", "S", "FS", "SS"})
IDP_POSITIONS = _DL | _LB | _DB

# Who may fill each slot. The flex rows must stay in step with
# draft_values.FLEX_SHARES, which carries the same eligibility as replacement
# weights — the two are asserted equal in the tests.
SLOT_ELIGIBILITY = {
    "QB":         frozenset({"QB"}),
    "RB":         frozenset({"RB"}),
    "WR":         frozenset({"WR"}),
    "TE":         frozenset({"TE"}),
    "K":          frozenset({"K", "PK"}),
    "DEF":        frozenset({"DEF", "DST"}),
    "DST":        frozenset({"DEF", "DST"}),
    "FLEX":       frozenset({"RB", "WR", "TE"}),
    "SUPER_FLEX": frozenset({"QB", "RB", "WR", "TE"}),
    "REC_FLEX":   frozenset({"WR", "TE"}),
    "WRRB_FLEX":  frozenset({"RB", "WR"}),
    "WRRB":       frozenset({"RB", "WR"}),
    "IDP_FLEX":   IDP_POSITIONS,
    "DL":         _DL,
    "LB":         _LB,
    "DB":         _DB,
    "DEF_LINE":   _DL,
    "LINEBACKER": _LB,
    "DEF_BACK":   _DB,
}

# Slots we have no projections for, in either source. Shown but not optimized.
UNPROJECTED = frozenset({"IDP_FLEX", "DL", "LB", "DB",
                         "DEF_LINE", "LINEBACKER", "DEF_BACK"})


def norm_token(raw) -> str:
    return str(raw or "").upper().strip()


def lineup_slots(roster_positions) -> list[str]:
    """
    The league's starting slots, in the league's own order, bench excluded.

    Sleeper's `starters` array is positionally matched to exactly this list, so
    the index of a slot here is the index to read from `starters`.
    """
    return [t for t in (norm_token(p) for p in (roster_positions or []))
            if t and t not in NON_LINEUP]


def slot_label(token: str) -> str:
    t = norm_token(token)
    return SLOT_LABEL.get(t, t)


def eligible_positions(token: str) -> frozenset[str]:
    """Empty for an unrecognised token — callers treat that as 'nobody fits'."""
    return SLOT_ELIGIBILITY.get(norm_token(token), frozenset())


def slot_width(token: str) -> int:
    """How many positions a slot admits. Narrow slots are the constrained ones."""
    return len(eligible_positions(token))


def is_eligible(token: str, fantasy_positions=None, position: str | None = None) -> bool:
    """
    Sleeper's per-player `fantasy_positions` is the source of truth, not
    `position`: a WR who also carries RB eligibility is real, and `position`
    alone gets that wrong. Falls back to `position` when the richer field is
    missing, which is what happens before the player-meta cache has loaded.
    """
    allowed = eligible_positions(token)
    if not allowed:
        return False
    have = [norm_token(p) for p in (fantasy_positions or [])] or [norm_token(position)]
    return any(p in allowed for p in have if p)


def is_projected(token: str) -> bool:
    """False for IDP slots — neither Sleeper nor ESPN projects defensive players."""
    return norm_token(token) not in UNPROJECTED
