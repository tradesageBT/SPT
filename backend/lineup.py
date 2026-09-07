"""
Optimal weekly lineups.

Pure functions — no network, no database, no imports beyond `slots` — so the
riskiest logic in the weekly feature is fully testable offline.

WHY NOT GREEDY. Filling slots one at a time in league order is wrong, and wrong
in ways that show up in ordinary leagues:

  Slot order. Pool RB3=14.1, QB2=13.8, WR4=6.2 with SUPER_FLEX listed before
  FLEX. Greedy takes SUPER_FLEX<-RB3 then FLEX<-WR4 = 20.3. Optimal is
  SUPER_FLEX<-QB2, FLEX<-RB3 = 27.9 — greedy gives away 7.6 points and benches
  your QB2.

  Sorting slots narrowest-first fixes that case, because QB c SUPER_FLEX and
  {RB,WR,TE} c FLEX c SUPER_FLEX nest. But REC_FLEX (WR/TE) and WRRB_FLEX
  (RB/WR) are the same width and neither contains the other, so nesting fails:
  pool WR=18.0, TE=11.5, RB=4.0 gives narrow-first 22.0 against an optimal 29.5.

WHY NOT HUNGARIAN. The players that can be *simultaneously* assigned to slots
form a transversal matroid, and greedy by weight over a matroid is provably
optimal. So taking players in descending points and asking "can this one join
the matching, reassigning others if needed" gives the true maximum — in about
thirty lines, with no numpy or scipy, and independent of slot ordering.
"""
import slots

# Projections carry several points of noise. An optimizer that flags a
# 0.3-point swap recommends three pointless changes a week and stops being
# trusted inside two weeks, so changes below this are reported as noise.
MIN_DELTA = 1.0


def _augment(pi, slot_idx, eligible, slot_owner, seen) -> bool:
    """
    Kuhn's augmenting path: try to seat player `pi`, bumping incumbents into
    other slots they are also eligible for. Returns False only if no
    rearrangement seats them.
    """
    for si in slot_idx:
        if si in seen or not eligible[pi][si]:
            continue
        seen.add(si)
        holder = slot_owner.get(si)
        if holder is None or _augment(holder, slot_idx, eligible, slot_owner, seen):
            slot_owner[si] = pi
            return True
    return False


def optimize(candidates: list[dict], slot_tokens: list[str]) -> dict:
    """
    Best legal assignment of `candidates` to `slot_tokens`.

    Each candidate: {player_id, position, fantasy_positions, points, available}.
    `available` False (bye, Out, IR) keeps a player out of the lineup entirely.

    Returns {"assignment": [{slot, slot_label, player_id|None, points}],
             "total": float, "started": [player_id], "benched": [player_id]}.
    Slots with no eligible player left come back with player_id None rather than
    raising — carrying one kicker and one defense is normal.
    """
    playable = [c for c in candidates if c.get("available", True)]

    # Deterministic order. Ties are constant in projections, and without a
    # stable tiebreak the page reshuffles between refreshes and looks broken.
    playable.sort(key=lambda c: (-(c.get("points") or 0.0), str(c.get("player_id"))))

    # IDP slots have no projections in either source; they are displayed but
    # never filled by the optimizer, so nothing competes for them.
    fillable = [i for i, t in enumerate(slot_tokens) if slots.is_projected(t)]

    eligible = [
        {si: slots.is_eligible(slot_tokens[si], c.get("fantasy_positions"), c.get("position"))
         for si in fillable}
        for c in playable
    ]

    # Narrow slots first only as a search-order heuristic — the matroid argument
    # makes the result order-independent, but seating constrained slots early
    # means far less backtracking.
    order = sorted(fillable, key=lambda si: slots.slot_width(slot_tokens[si]))

    slot_owner: dict[int, int] = {}
    for pi in range(len(playable)):
        _augment(pi, order, eligible, slot_owner, set())

    assignment, started = [], []
    for si, token in enumerate(slot_tokens):
        pi = slot_owner.get(si)
        player = playable[pi] if pi is not None else None
        if player:
            started.append(player["player_id"])
        assignment.append({
            "slot": token,
            "slot_label": slots.slot_label(token),
            "player_id": player["player_id"] if player else None,
            "points": round(player.get("points") or 0.0, 2) if player else None,
            "optimizable": slots.is_projected(token),
        })

    started_set = set(started)
    return {
        "assignment": assignment,
        "total": round(sum(p.get("points") or 0.0
                           for p in playable if p["player_id"] in started_set), 2),
        "started": started,
        "benched": [c["player_id"] for c in candidates if c["player_id"] not in started_set],
    }


def greedy_total(candidates: list[dict], slot_tokens: list[str]) -> float:
    """
    Narrow-slot-first greedy. Not used to build lineups — it exists so the
    optimizer can assert it never does worse in production, where a silent
    matching bug would otherwise just quietly recommend bad lineups.
    """
    playable = sorted(
        (c for c in candidates if c.get("available", True)),
        key=lambda c: (-(c.get("points") or 0.0), str(c.get("player_id"))),
    )
    taken, total = set(), 0.0
    order = sorted((i for i, t in enumerate(slot_tokens) if slots.is_projected(t)),
                   key=lambda si: slots.slot_width(slot_tokens[si]))
    for si in order:
        for c in playable:
            if c["player_id"] in taken:
                continue
            if slots.is_eligible(slot_tokens[si], c.get("fantasy_positions"), c.get("position")):
                taken.add(c["player_id"])
                total += c.get("points") or 0.0
                break
    return round(total, 2)


def diff(current: list, optimal: list, by_id: dict, min_delta: float = MIN_DELTA) -> list[dict]:
    """
    Which swaps are worth making, slot by slot.

    `current` and `optimal` are assignment lists over the same slots; `by_id`
    maps player_id to whatever the caller wants echoed back. Changes worth less
    than `min_delta` are dropped — inside projection noise, "optimal" and
    "0.4 points better" are the same statement.
    """
    changes = []
    for cur, opt in zip(current, optimal):
        if not opt["optimizable"]:
            continue
        if cur["player_id"] == opt["player_id"]:
            continue
        gain = (opt["points"] or 0.0) - (cur["points"] or 0.0)
        if gain < min_delta:
            continue
        changes.append({
            "slot": opt["slot"],
            "slot_label": opt["slot_label"],
            "start": by_id.get(opt["player_id"]),
            "sit": by_id.get(cur["player_id"]),
            "gain": round(gain, 2),
        })
    return sorted(changes, key=lambda c: -c["gain"])
