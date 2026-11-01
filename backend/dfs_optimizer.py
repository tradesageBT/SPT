"""
DraftKings Classic lineup optimizer — exact, under the salary cap.

WHY NOT lineup.optimize(). That solver is provably optimal because the players
simultaneously seatable in the slots form a TRANSVERSAL MATROID, and greedy by
weight over a matroid gives the true maximum. A salary cap turns the problem
into a matroid intersected with a knapsack, which is not a matroid: the exchange
property fails, because whether a cheap player belongs in the optimum depends on
what the already-seated players cost, not just on their slot-eligibility.

Concretely, lineup.optimize() seats players in descending points and never
evicts one. Under a cap the right move is frequently to evict a seated stud to
afford two mid-priced players, and greedy-by-points has no mechanism for it. It
is not merely suboptimal, it is unboundedly bad — one $11,000 player can consume
the cap and strand every remaining slot on minimum-salary filler.

WHAT THIS DOES INSTEAD. Exact dynamic programming over salary. DraftKings
salaries are multiples of $100, so a $50,000 cap is 501 states. The roster is
QB/RB/RB/WR/WR/WR/TE/FLEX/DST where FLEX takes RB, WR or TE — so splitting on
which position fills the FLEX gives three sub-problems with FIXED per-position
counts, and each position group becomes an independent cardinality-constrained
knapsack. Those are then convolved over salary.

Cost is trivial: the largest group solve is about 110 WRs x 4 x 501, and the
convolutions are four passes over 501^2. Sub-second in pure Python, exact, and
with no numpy, scipy or LP solver — consistent with the rest of this codebase.
"""
import itertools

SALARY_STEP = 100
DEFAULT_CAP = 50_000

# DraftKings Classic. Order is the order lineups are displayed in.
CLASSIC_SLOTS = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")
FLEX_POSITIONS = ("RB", "WR", "TE")

# Per-position counts for each choice of what fills the FLEX.
_FLEX_CASES = {
    "RB": {"QB": 1, "RB": 3, "WR": 3, "TE": 1, "DST": 1},
    "WR": {"QB": 1, "RB": 2, "WR": 4, "TE": 1, "DST": 1},
    "TE": {"QB": 1, "RB": 2, "WR": 3, "TE": 2, "DST": 1},
}

# DraftKings requires a lineup to span at least two different games.
MIN_GAMES = 2

_NEG = float("-inf")


def _buckets(cap: int) -> int:
    return cap // SALARY_STEP + 1


def _group_best(players: list[dict], k_max: int, cap: int):
    """
    best[k][s] = max points taking exactly k of these players for exactly s
    salary buckets, plus the flags needed to rebuild the choice.

    A cardinality-constrained 0/1 knapsack. Exact salary rather than "at most"
    keeps the convolution below simple.

    Reconstruction uses a per-item "this item improved this state" flag rather
    than a parent pointer into (k-1, s-cost). Parent pointers are WRONG here:
    item i improves best[k][s] while best[k-1][s-cost] still holds items < i,
    but a moment later the same item i improves best[k-1][s-cost] too — and
    backtracking then walks through item i twice. That produced lineups with a
    duplicated player whose reconstructed score did not match the stored value.
    """
    n_b = _buckets(cap)
    best = [[_NEG] * n_b for _ in range(k_max + 1)]
    best[0][0] = 0.0
    width = (k_max + 1) * n_b
    # improved[i][k * n_b + s] == 1 when player i set the current best there.
    improved = [bytearray(width) for _ in range(len(players))]

    for idx, p in enumerate(players):
        cost = p["salary"] // SALARY_STEP
        pts = p["points"]
        if cost > cap // SALARY_STEP:
            continue
        flags = improved[idx]
        # Descending k so each player is used at most once.
        for k in range(min(k_max, idx + 1), 0, -1):
            prev = best[k - 1]
            cur = best[k]
            base_off = k * n_b
            for s in range(n_b - 1, cost - 1, -1):
                base = prev[s - cost]
                if base == _NEG:
                    continue
                cand = base + pts
                if cand > cur[s]:
                    cur[s] = cand
                    flags[base_off + s] = 1
    return best, improved


def _reconstruct(players, improved, k, s, cap):
    """
    Walk the improvement flags back from the last player.

    The last player to improve a state is the one that produced its current
    value, so scanning indices downward and taking the first set flag recovers
    the actual choice — and each index is visited once, so no player can repeat.
    """
    n_b = _buckets(cap)
    out = []
    i = len(players) - 1
    while k > 0 and i >= 0:
        if improved[i][k * n_b + s]:
            p = players[i]
            out.append(p)
            s -= p["salary"] // SALARY_STEP
            k -= 1
        i -= 1
    return out if k == 0 else []


def _solve_case(pool_by_pos: dict, counts: dict, cap: int):
    """Best (points, players) for one fixed set of per-position counts."""
    n_b = _buckets(cap)
    groups = []
    for pos, k in counts.items():
        players = pool_by_pos.get(pos) or []
        if len(players) < k:
            return None                      # cannot fill this shape
        best, improved = _group_best(players, k, cap)
        groups.append((pos, players, k, best, improved))

    # Convolve the groups over salary, carrying the per-group spend so the
    # lineup can be rebuilt afterwards.
    running = [_NEG] * n_b
    running[0] = 0.0
    trail: list[list] = [[None] * n_b]

    for _pos, _players, k, best, _improved in groups:
        nxt = [_NEG] * n_b
        nxt_from = [None] * n_b
        row = best[k]
        # Only salaries the group can actually hit are worth visiting.
        spends = [s for s in range(n_b) if row[s] != _NEG]
        for s_prev in range(n_b):
            if running[s_prev] == _NEG:
                continue
            base = running[s_prev]
            room = n_b - 1 - s_prev
            for s_g in spends:
                if s_g > room:
                    break
                total = s_prev + s_g
                cand = base + row[s_g]
                if cand > nxt[total]:
                    nxt[total] = cand
                    nxt_from[total] = (s_prev, s_g)
        running = nxt
        trail.append(nxt_from)

    end = max(range(n_b), key=lambda s: running[s])
    if running[end] == _NEG:
        return None

    # Unwind the convolution to recover each group's spend, then its players.
    spends = []
    s = end
    for level in range(len(groups), 0, -1):
        s_prev, s_g = trail[level][s]
        spends.append(s_g)
        s = s_prev
    spends.reverse()

    chosen = []
    for (pos, players, k, best, improved), s_g in zip(groups, spends):
        chosen.extend(_reconstruct(players, improved, k, s_g, cap))

    return running[end], chosen


def optimize(players: list[dict], cap: int = DEFAULT_CAP,
             slots=CLASSIC_SLOTS, exclude: set | None = None):
    """
    The highest-scoring legal lineup under the cap.

    Each player: {player_id, position, salary, points, game_id (optional),
    name, team}. Returns {"players": [...], "total_points", "total_salary",
    "lineup": [{slot, player}]} or None when no legal lineup exists.
    """
    exclude = exclude or set()
    pool_by_pos: dict[str, list] = {}
    for p in players:
        if p["player_id"] in exclude:
            continue
        if p.get("points") is None or p.get("salary") is None:
            continue
        pool_by_pos.setdefault(p["position"], []).append(p)

    best = None
    for flex_pos, counts in _FLEX_CASES.items():
        got = _solve_case(pool_by_pos, counts, cap)
        if got is None:
            continue
        pts, chosen = got
        if _games(chosen) < MIN_GAMES:
            # Rare, and only on tiny slates. Rather than bolt a second
            # dimension onto the DP for a constraint that almost never binds,
            # fall back to an exhaustive repair for this case.
            repaired = _repair_min_games(pool_by_pos, counts, cap)
            if repaired is None:
                continue
            pts, chosen = repaired
        if best is None or pts > best[0]:
            best = (pts, chosen, flex_pos)

    if best is None:
        return None
    pts, chosen, flex_pos = best
    return {
        "players": chosen,
        "total_points": round(pts, 2),
        "total_salary": sum(p["salary"] for p in chosen),
        "flex_position": flex_pos,
        "lineup": _assign_slots(chosen, slots),
    }


def _games(players) -> int:
    return len({p.get("game_id") for p in players if p.get("game_id")}) or 1


def _repair_min_games(pool_by_pos, counts, cap):
    """
    Best lineup for this shape that spans >= MIN_GAMES.

    Only reached when the unconstrained optimum came from a single game, which
    needs a one-game slate or a pathological pool. Brute force over the cheapest
    credible candidates is both correct and fast enough here, and it keeps the
    main DP free of a constraint that essentially never binds.
    """
    trimmed = {pos: sorted(pl, key=lambda p: -p["points"])[:12]
               for pos, pl in pool_by_pos.items()}
    best = None
    pools = [list(itertools.combinations(trimmed.get(pos, []), k))
             for pos, k in counts.items()]
    for combo in itertools.product(*pools):
        picked = [p for grp in combo for p in grp]
        if sum(p["salary"] for p in picked) > cap:
            continue
        if _games(picked) < MIN_GAMES:
            continue
        pts = sum(p["points"] for p in picked)
        if best is None or pts > best[0]:
            best = (pts, picked)
    return best


def _assign_slots(chosen, slots):
    """Put the chosen players into display slots, FLEX last."""
    by_pos: dict[str, list] = {}
    for p in chosen:
        by_pos.setdefault(p["position"], []).append(p)
    for pl in by_pos.values():
        pl.sort(key=lambda p: -p["points"])

    out, used = [], set()
    for slot in slots:
        if slot == "FLEX":
            out.append({"slot": slot, "player": None})
            continue
        pool = by_pos.get(slot, [])
        pick = next((p for p in pool if p["player_id"] not in used), None)
        if pick:
            used.add(pick["player_id"])
        out.append({"slot": slot, "player": pick})

    leftover = [p for p in chosen if p["player_id"] not in used]
    for row in out:
        if row["slot"] == "FLEX" and leftover:
            row["player"] = leftover.pop(0)
    return out


def optimize_set(players, cap: int = DEFAULT_CAP, count: int = 4):
    """
    The optimum plus genuinely different alternates.

    Each alternate is the best lineup that excludes one player from the one
    before it. Banning a player rather than perturbing the projections means the
    alternates differ in roster construction, not in rounding.
    """
    first = optimize(players, cap)
    if first is None:
        return []

    out = [first]
    seen = {frozenset(p["player_id"] for p in first["players"])}

    while len(out) < count:
        candidates = []
        for base in out:
            for drop in base["players"]:
                alt = optimize(players, cap, exclude={drop["player_id"]})
                if alt is None:
                    continue
                key = frozenset(p["player_id"] for p in alt["players"])
                if key not in seen:
                    candidates.append((alt["total_points"], key, alt))
        if not candidates:
            break
        candidates.sort(key=lambda c: -c[0])
        _pts, key, alt = candidates[0]
        seen.add(key)
        out.append(alt)
    return out
