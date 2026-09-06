"""
Shared draft valuation logic.

Extracted from the auction router so the Sleeper draft room uses the same
replacement-level model rather than its own cruder one. Everything here is pure
except `load_values`, which does one FantasyCalc fetch.
"""
import logging

import fantasycalc_client

log = logging.getLogger(__name__)

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# How often each position actually fills a given flex slot type. Used to push
# replacement level deeper for the positions a flex slot competes for.
FLEX_SHARES = {
    "flex":        {"RB": 0.45, "WR": 0.45, "TE": 0.10},               # RB/WR/TE
    "sflex":       {"QB": 0.75, "WR": 0.12, "RB": 0.10, "TE": 0.03},   # QB/RB/WR/TE
    "wr_rb_flex":  {"RB": 0.50, "WR": 0.50},                           # WR/RB
    "rec_flex":    {"WR": 0.75, "TE": 0.25},                           # WR/TE
}
FLEX_KEYS = tuple(FLEX_SHARES)

# A new tier starts when the drop from the previous player exceeds this
TIER_BREAK = 0.08


def norm_pos(pos: str) -> str:
    p = (pos or "").upper().strip()
    if p in ("DST", "D/ST", "DEFENSE"):
        return "DEF"
    if p == "PK":
        return "K"
    return p


# ── Sleeper roster parsing ────────────────────────────────────────────────────

# Sleeper's roster_positions tokens -> our slot model
_SLOT_MAP = {
    "QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "K": "k",
    "DEF": "dst", "DST": "dst",
    "FLEX": "flex", "SUPER_FLEX": "sflex", "REC_FLEX": "rec_flex",
    "WRRB_FLEX": "wr_rb_flex", "WRRB": "wr_rb_flex",
}
# Present on rosters but never drafted
_IGNORED_SLOTS = {"BN", "IR", "TAXI"}
# We have no IDP values, so these are counted only to warn about them
_IDP_SLOTS = {"DL", "LB", "DB", "IDP_FLEX", "DEF_LINE", "LINEBACKER", "DEF_BACK"}


def parse_roster_positions(roster_positions) -> dict:
    """
    Turn Sleeper's roster_positions array into starter/flex/bench counts.

    Deliberately total: unknown tokens are ignored rather than raising, because
    a parse failure here would blank the draft board.
    """
    slots = {k: 0 for k in ("qb", "rb", "wr", "te", "k", "dst", *FLEX_KEYS)}
    bench = 0
    idp = 0
    unknown: list[str] = []

    for raw in (roster_positions or []):
        token = str(raw or "").upper().strip()
        if token in _SLOT_MAP:
            slots[_SLOT_MAP[token]] += 1
        elif token == "BN":
            bench += 1
        elif token in _IDP_SLOTS:
            idp += 1
        elif token in _IGNORED_SLOTS:
            continue          # IR / TAXI aren't drafted
        elif token:
            unknown.append(token)

    return {
        **slots,
        "bench": bench,
        "idp": idp,
        "unknown": unknown,
        # Matches the auction tool's convention: a superflex slot means QBs are
        # valued as in a 2QB league.
        "num_qbs": slots["qb"] + slots["sflex"],
    }


def parse_ppr(scoring_settings) -> float:
    """
    Points per reception from a Sleeper league's scoring_settings.

    Absent `rec` genuinely means standard scoring in Sleeper, so the default is
    0. (leagues.py defaults to 1.0, which mis-reads a standard league as full
    PPR — not changed here, but not copied either.)
    """
    try:
        return float((scoring_settings or {}).get("rec", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


# ── Values ────────────────────────────────────────────────────────────────────

async def load_values(num_qbs: int, ppr: float) -> list[dict]:
    """
    Redraft values for a specific league's scoring, straight from FantasyCalc.

    Deliberately does NOT touch players_cache: that table is global and shared
    with league syncs, so writing one league's scoring into it would clobber the
    values every other league is computed from.
    """
    try:
        entries = await fantasycalc_client.get_values(
            num_qbs=num_qbs, ppr=ppr, is_dynasty=False
        )
        out = []
        for entry in entries:
            player = entry.get("player", {})
            sid = str(player.get("sleeperId") or "")
            pos = norm_pos(player.get("position", ""))
            if not sid or pos not in POSITIONS:
                continue
            out.append({
                "sleeper_id": sid,
                "name": player.get("name", ""),
                "position": pos,
                "nfl_team": player.get("nflTeamAbbr", ""),
                "age": player.get("age"),
                "value": entry.get("value", 0) or 0,
            })
        if out:
            return out
        log.warning("FantasyCalc returned no usable players; falling back to cache")
    except Exception as e:
        log.warning("FantasyCalc fetch failed (%s); falling back to cache", e)

    # Fallback so the tool still opens if FantasyCalc is down mid-draft.
    from cache_manager import get_cached_players
    out = []
    for p in get_cached_players().values():
        val = p.get("redraft_value") or 0
        pos = norm_pos(p.get("position"))
        if not val or pos not in POSITIONS:
            continue
        out.append({
            "sleeper_id": p["sleeper_id"],
            "name": p["name"],
            "position": pos,
            "nfl_team": p.get("nfl_team", ""),
            "age": p.get("age"),
            "value": val,
        })
    return out


def group_by_position(players: list) -> dict:
    """Players bucketed by position, each bucket sorted by value descending."""
    by_pos: dict[str, list] = {p: [] for p in POSITIONS}
    for p in players:
        pos = p.get("position")
        if pos in by_pos:
            by_pos[pos].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x["value"], reverse=True)
    return by_pos


def replacement_levels(by_pos: dict, starters: dict, flex_counts: dict, teams: int) -> dict:
    """
    Value of the last startable player at each position.

    Flex slots are spread across the positions eligible for them, which pushes
    those positions' replacement level deeper and correctly raises their value —
    this is what makes a superflex league price QBs properly.
    """
    repl: dict[str, float] = {}
    for pos in POSITIONS:
        pool = by_pos.get(pos) or []
        if not pool:
            repl[pos] = 0
            continue
        n_start = (starters.get(pos, 0) or 0) * teams
        for ftype, count in (flex_counts or {}).items():
            share = FLEX_SHARES.get(ftype, {}).get(pos, 0)
            n_start += round(share * (count or 0) * teams)
        idx = min(max(n_start, 1), len(pool)) - 1
        repl[pos] = pool[idx]["value"]
    return repl


def apply_vor(by_pos: dict, repl: dict) -> list:
    out = []
    for pos in POSITIONS:
        for i, p in enumerate(by_pos.get(pos) or [], start=1):
            p["vor"] = round(p["value"] - repl.get(pos, 0))
            p["pos_rank"] = i
            out.append(p)
    return out


def apply_tiers(players: list) -> list:
    """Tier within each position — a break where the drop exceeds TIER_BREAK."""
    for pos in POSITIONS:
        pool = sorted(
            (p for p in players if p.get("position") == pos),
            key=lambda x: x["value"],
            reverse=True,
        )
        tier = 1
        for i, p in enumerate(pool):
            if i > 0:
                prev = pool[i - 1]["value"] or 1
                if prev > 0 and (prev - p["value"]) / prev > TIER_BREAK:
                    tier += 1
            p["tier"] = tier
    return players
