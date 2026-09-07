"""
Shared draft valuation logic.

Extracted from the auction router so the Sleeper draft room uses the same
replacement-level model rather than its own cruder one. Everything here is pure
except `load_values`, which does one FantasyCalc fetch.
"""
import time
import logging

import fantasycalc_client
import slots

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

# Values move slowly, and the league hub computes live on every page load, so
# without this each load was a FantasyCalc round trip.
VALUES_TTL = 30 * 60
_values_cache: dict[tuple, tuple[float, list]] = {}


def norm_pos(pos: str) -> str:
    p = (pos or "").upper().strip()
    if p in ("DST", "D/ST", "DEFENSE"):
        return "DEF"
    if p == "PK":
        return "K"
    return p


# ── Sleeper roster parsing ────────────────────────────────────────────────────

# Slot identity lives in slots.py so the same table serves the lineup optimizer.
# This module still owns slot COUNTS; that one owns names and eligibility.
_SLOT_MAP = slots.SLOT_MAP
# Present on rosters but never drafted
_IGNORED_SLOTS = slots.NON_LINEUP
# We have no IDP values, so these are counted only to warn about them
_IDP_SLOTS = slots.UNPROJECTED


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

    Cached per (num_qbs, ppr) — different leagues want different scoring, and
    the league hub recomputes live on every load.

    Deliberately does NOT touch players_cache: that table is global and shared
    with league syncs, so writing one league's scoring into it would clobber the
    values every other league is computed from.
    """
    key = (num_qbs, ppr)
    hit = _values_cache.get(key)
    if hit and (time.time() - hit[0]) < VALUES_TTL:
        # Copy: callers mutate entries (vor, tier, pos_rank, fc_value aliasing)
        return [dict(p) for p in hit[1]]

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
            _values_cache[key] = (time.time(), [dict(p) for p in out])
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


# ── Roster needs ──────────────────────────────────────────────────────────────
#
# "Need" spans starters, flex eligibility AND bench depth, so the board keeps
# giving guidance deep into a draft rather than going quiet once starters fill.

# How bench spots typically get spent in a redraft league. K/DEF get none —
# nobody carries a backup kicker.
BENCH_SHARES = {"QB": 0.10, "RB": 0.40, "WR": 0.40, "TE": 0.10}


def roster_targets(starters: dict, flex_counts: dict, bench: int) -> dict:
    """
    How many of each position a team should end up with.

    starters + flex allocation + bench allocation. Because FLEX_SHARES and
    BENCH_SHARES each sum to 1, the targets sum to exactly the number of
    draftable roster spots.
    """
    targets = {pos: float(starters.get(pos, 0) or 0) for pos in POSITIONS}
    for ftype, count in (flex_counts or {}).items():
        for pos, share in FLEX_SHARES.get(ftype, {}).items():
            targets[pos] += share * (count or 0)
    for pos, share in BENCH_SHARES.items():
        targets[pos] += share * (bench or 0)
    return targets


def team_needs(counts: dict, targets: dict, starters: dict, roster_size: float | None = None) -> dict:
    """
    What a team still needs, most-wanted first.

    Ranked by how far each position is from its target PROPORTIONALLY, not by
    raw gap. Raw gap always favours whichever position has the largest target —
    in a 3WR league that pins the answer to "WR" for the entire draft, which
    tells you nothing about how two teams differ. Proportional gap correctly
    says QB for the team with no quarterback and TE for the team with no tight
    end.

    K and DEF are held back until the roster is nearly full: they are required
    starters from pick one, so without this they'd surface the moment the skill
    starters fill and suggest drafting a kicker in the middle rounds.
    """
    gaps, prop = {}, {}
    urgent = []
    owned_total = sum((counts or {}).values())
    size = roster_size if roster_size is not None else sum(targets.values())
    spots_left = max(0, size - owned_total)
    kdef_left = sum(
        max(0, (targets.get(p, 0) or 0) - (counts.get(p, 0) or 0)) for p in ("K", "DEF")
    )

    for pos in POSITIONS:
        owned = counts.get(pos, 0) or 0
        target = targets.get(pos, 0) or 0
        gaps[pos] = round(target - owned, 2)
        score = (gaps[pos] / target) if target > 0 else 0
        # Defer kickers and defenses until the roster is nearly full
        if pos in ("K", "DEF") and spots_left > kdef_left + 3:
            score *= 0.05
        # Rounded so genuine ties actually tie: the targets carry float noise in
        # the far decimals, which would otherwise decide the order before the
        # magnitude tiebreak below ever got consulted.
        prop[pos] = round(score, 3)
        if owned < (starters.get(pos, 0) or 0):
            urgent.append(pos)

    # Proportion first, raw gap as the tiebreak. Early on every position is 100%
    # unfilled and ties, and there the magnitude is what matters — needing three
    # receivers is a bigger hole than needing one tight end.
    ordered = [
        p for p in sorted(prop, key=lambda p: (prop[p], gaps[p]), reverse=True)
        if gaps[p] > 0
    ]
    return {
        "gaps": gaps,
        "ordered": ordered,
        "top_need": ordered[0] if ordered else None,
        "urgent": urgent,
    }


def snake_slot(pick_index: int, num_teams: int) -> int:
    """1-based draft slot for a 0-based overall pick index."""
    rnd, pos = divmod(pick_index, num_teams)
    return pos + 1 if rnd % 2 == 0 else num_teams - pos


# ── Points under a league's scoring ───────────────────────────────────────────

# Return yardage. Deliberately yardage only — a return TOUCHDOWN is already
# inside Sleeper's points total, so adding kr_td/pr_td would double-count it.
RETURN_YARD_KEYS = ("kr_yd", "pr_yd")


def _rate(scoring_settings: dict | None, key: str, default: float = 0.0) -> float:
    """One league scoring rate, total against missing/garbage values."""
    try:
        val = (scoring_settings or {}).get(key)
        return default if val is None else float(val)
    except (TypeError, ValueError):
        return default


def league_points(
    stats: dict,
    ppr: float,
    pass_td_pts: float | None = None,
    rush_att_pts: float | None = None,
    scoring_settings: dict | None = None,
    position: str | None = None,
):
    """
    Sleeper's own points figure, restated for categories its baseline misses.

    Sleeper's pts_* are computed under STANDARD scoring, so rather than
    recomputing from scratch — which would need fumbles and 2pt conversions we
    don't pull — this adjusts by only what differs:

      * passing TDs, where the baseline is 4
      * per-carry bonus, where the baseline is 0
      * TE reception premium, where the baseline is 0
      * return yardage, where the baseline is also 0, so it is a pure addition

    `pass_td_pts` / `rush_att_pts` default to whatever `scoring_settings` says,
    falling back to the standard 4.0 / 0.0 when it says nothing. They stay
    overridable because the auction tool collects them from the user directly,
    for leagues we have no Sleeper settings for. Callers that pass only
    `scoring_settings` used to silently get 4.0 / 0.0 and score every QB and RB
    wrong; now they get the league's real values.
    """
    if not stats:
        return None
    base_key = "pts_ppr" if ppr == 1 else "pts_half_ppr" if ppr == 0.5 else "pts_std"
    base = stats.get(base_key)
    if base is None:
        return None

    if pass_td_pts is None:
        pass_td_pts = _rate(scoring_settings, "pass_td", 4.0)
    if rush_att_pts is None:
        rush_att_pts = _rate(scoring_settings, "rush_att", 0.0)

    adj = base
    adj += (stats.get("pass_td") or 0) * (pass_td_pts - 4.0)
    adj += (stats.get("rush_att") or 0) * rush_att_pts

    # TE premium. Sleeper's pts_ppr is generic PPR, so a TEP league's bonus per
    # reception is missing entirely. It applies to tight ends only, so it is
    # skipped unless the caller identifies the player — either via `position` or
    # a "position" key on the stat row. Sleeper's own stat payloads carry that
    # key; sleeper_data.normalize() drops it, so those callers must pass it.
    tep = _rate(scoring_settings, "bonus_rec_te", 0.0)
    if tep and norm_pos(position or stats.get("position") or "") == "TE":
        adj += (stats.get("rec") or 0) * tep

    for key in RETURN_YARD_KEYS:
        rate = _rate(scoring_settings, key, 0.0)
        if rate:
            adj += (stats.get(key) or 0) * rate

    return round(adj, 1)


def return_yard_rates(scoring_settings: dict | None) -> dict:
    """The league's per-yard return rates, for captioning a restated figure."""
    out = {}
    for key in RETURN_YARD_KEYS:
        try:
            rate = float((scoring_settings or {}).get(key, 0) or 0)
        except (TypeError, ValueError):
            rate = 0.0
        if rate:
            out[key] = rate
    return out
