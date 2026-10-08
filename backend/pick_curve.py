"""
Dynasty pick value as a function of overall draft position.

Pure — no imports, no I/O — so the curve can be tested exhaustively offline.

WHY THIS EXISTS. Pick values used to be scaled relative to each round's own
base, with a spread that shrank by round:

    k   = max(0.20, 0.65 - (round - 1) * 0.15)
    adj = 1.0 + k * (mid_slot - slot) / mid_slot

Nothing tied one round to the next, so round 1 spanned 0.50x-1.50x of its base
while round 2 spanned 0.62x-1.38x of a base only 1.86x smaller. The ranges
overlapped: a 2.01 priced above a 1.12, and seven of twelve second-rounders
outvalued the worst first. Pick value has to fall monotonically in overall pick
number, and per-round scaling cannot guarantee that.

WHAT REPLACES IT. One continuous curve over overall pick number. FantasyCalc
publishes a single value per (season, round) — its ids are FP_{year}_{round},
round-granular only — so each round's value is treated as the value at the
MIDDLE of that round, and everything in between is interpolated.

Interpolation is geometric (linear in log space), which is both the realistic
shape — steep at the top of the draft, flattening out later — and monotonic
whenever the anchors decrease. That is the whole guarantee: ordering cannot
invert, because the curve is strictly decreasing by construction.

The cost, accepted deliberately: within-round spread is gentler than the old
multiplier gave (1.01 lands around 1.8x a 1.12, where the old code showed 3.0x).
FantasyCalc gives us nothing about shape inside a round, so a steeper curve would
be inventing precision we don't have.
"""
import math

# Below this the exponential is meaningless and we'd be dividing by noise.
_MIN_VALUE = 1.0


def round_midpoint(round_num: int, num_teams: int) -> float:
    """Overall pick number at the middle of a round — where a round's value sits."""
    return (round_num - 1) * num_teams + (num_teams + 1) / 2


def overall_pick(round_num: int, slot: float, num_teams: int) -> float:
    """Overall pick number for an in-round slot. Fractional slots are fine."""
    return (round_num - 1) * num_teams + slot


def _anchor_points(anchors: dict, num_teams: int) -> list[tuple[float, float]]:
    """
    [(overall_pick, value)] sorted by pick, forced strictly decreasing.

    The clamp is defensive: FantasyCalc's own values are well ordered, but one
    bad cache row would otherwise be enough to reintroduce an inversion, which
    is the exact failure this module exists to prevent.
    """
    points = []
    for rnd, value in sorted(anchors.items()):
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if v < _MIN_VALUE or rnd is None:
            continue
        x = round_midpoint(int(rnd), num_teams)
        if points and v >= points[-1][1]:
            v = points[-1][1] * 0.999        # keep it strictly decreasing
        points.append((x, v))
    return points


def value_at(anchors: dict, round_num: int, slot: float, num_teams: int) -> int:
    """
    Value of the pick at `slot` within `round_num`.

    `anchors` is {round: value} from FantasyCalc — the value at each round's
    midpoint. Returns 0 when there is nothing to interpolate from, so callers
    can fall back rather than get a fabricated number.
    """
    points = _anchor_points(anchors, num_teams)
    if not points:
        return 0

    x = overall_pick(int(round_num), float(slot), num_teams)

    if len(points) == 1:
        # One round of data: no slope to infer, so the round is flat. Better a
        # defensible constant than a made-up gradient.
        return max(1, round(points[0][1]))

    # Decay rate per pick for each segment, in log space.
    def rate(i: int) -> float:
        (x0, v0), (x1, v1) = points[i], points[i + 1]
        return (math.log(v1) - math.log(v0)) / (x1 - x0)

    if x <= points[0][0]:                       # before the first anchor
        x0, v0, r = points[0][0], points[0][1], rate(0)
    elif x >= points[-1][0]:                    # past the last anchor
        x0, v0, r = points[-1][0], points[-1][1], rate(len(points) - 2)
    else:
        i = max(j for j in range(len(points) - 1) if points[j][0] <= x)
        x0, v0, r = points[i][0], points[i][1], rate(i)

    return max(1, round(v0 * math.exp(r * (x - x0))))


def curve(anchors: dict, num_teams: int, rounds: int) -> list[tuple[int, int, int]]:
    """
    [(round, slot, value)] for every pick — used by the tests to assert the
    whole sequence decreases, and handy for eyeballing a league's board.
    """
    return [(rnd, slot, value_at(anchors, rnd, slot, num_teams))
            for rnd in range(1, rounds + 1)
            for slot in range(1, num_teams + 1)]
