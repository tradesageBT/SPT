"""
DraftKings NFL Classic scoring, computed from raw stat lines.

Deliberately NOT built on draft_values.league_points. That function is a *delta
adjuster*: it starts from Sleeper's precomputed pts_ppr/pts_half_ppr/pts_std and
nudges a few categories. DraftKings differs from standard PPR in ways that are
not expressible as a delta — the 100/300-yard bonuses are thresholds on yardage,
not per-unit rates — so this computes from scratch.

Source for the scoring table: DraftKings' own rules page. The values here were
cross-checked against four independent transcriptions, which agreed on every one.
"""

# ── Offense ──────────────────────────────────────────────────────────────────
PASS_YD = 0.04            # 1 point per 25 yards
PASS_TD = 4.0
PASS_INT = -1.0
PASS_300_BONUS = 3.0

RUSH_YD = 0.1             # 1 point per 10 yards
RUSH_TD = 6.0
RUSH_100_BONUS = 3.0

REC_YD = 0.1
RECEPTION = 1.0           # full PPR
REC_TD = 6.0
REC_100_BONUS = 3.0

FUMBLE_LOST = -1.0
TWO_POINT = 2.0
RETURN_TD = 6.0

# ── Expected-bonus model ─────────────────────────────────────────────────────
# A player projected for 95 rushing yards earns no bonus under a deterministic
# threshold, but his EXPECTED bonus is P(>=100) * 3, which is far from zero.
# Applying thresholds to a mean systematically undervalues exactly the
# high-volume players a cash lineup is built on, so the probability is modelled.
#
# Single-game yardage is right-skewed and roughly lognormal. A coefficient of
# variation near 0.55 is a reasonable central estimate for weekly fantasy
# yardage; the result is not sensitive to small changes in it, and it matters
# far more THAT the smoothing happens than exactly how steep it is.
YARDAGE_CV = 0.55

# Below this projection the bonus probability is negligible and the lognormal
# approximation is least trustworthy, so it is simply treated as zero.
_BONUS_FLOOR_RATIO = 0.35


def _bonus_probability(projected: float, threshold: float, cv: float = YARDAGE_CV) -> float:
    """
    P(actual >= threshold) for a lognormal with the given mean and CV.

    Pure stdlib: the lognormal CDF reduces to the normal CDF of log-space, and
    math.erf gives that without scipy.
    """
    import math

    if projected <= 0 or threshold <= 0:
        return 0.0
    if projected < threshold * _BONUS_FLOOR_RATIO:
        return 0.0

    # Lognormal parameters from mean and CV.
    sigma2 = math.log(1.0 + cv * cv)
    sigma = math.sqrt(sigma2)
    mu = math.log(projected) - sigma2 / 2.0
    z = (math.log(threshold) - mu) / sigma
    # P(X >= t) = 1 - Phi(z)
    return 0.5 * (1.0 - math.erf(z / math.sqrt(2.0)))


def dk_points(stats: dict, expected_bonuses: bool = True) -> float:
    """
    DraftKings Classic points for one projected (or actual) stat line.

    `stats` uses Sleeper's key names, which is what projections.weekly() returns:
    pass_yd, pass_td, pass_int, rush_yd, rush_td, rec, rec_yd, rec_td, plus the
    optional fum_lost, pass_2pt/rush_2pt/rec_2pt and kr_td/pr_td.

    With `expected_bonuses` the yardage bonuses are probability-weighted — right
    for projections. Set it False to score an ACTUAL stat line, where the
    threshold either was or was not met.
    """
    s = stats or {}

    def g(key):
        v = s.get(key)
        return float(v) if isinstance(v, (int, float)) else 0.0

    pass_yd, rush_yd, rec_yd = g("pass_yd"), g("rush_yd"), g("rec_yd")

    pts = 0.0
    pts += pass_yd * PASS_YD
    pts += g("pass_td") * PASS_TD
    pts += g("pass_int") * PASS_INT

    pts += rush_yd * RUSH_YD
    pts += g("rush_td") * RUSH_TD

    pts += rec_yd * REC_YD
    pts += g("rec") * RECEPTION
    pts += g("rec_td") * REC_TD

    # Sleeper splits fumbles several ways depending on the feed; accept any.
    pts += (g("fum_lost") + g("rush_fum_lost") + g("rec_fum_lost")) * FUMBLE_LOST
    pts += (g("pass_2pt") + g("rush_2pt") + g("rec_2pt")) * TWO_POINT
    pts += (g("kr_td") + g("pr_td")) * RETURN_TD

    if expected_bonuses:
        pts += _bonus_probability(pass_yd, 300.0) * PASS_300_BONUS
        pts += _bonus_probability(rush_yd, 100.0) * RUSH_100_BONUS
        pts += _bonus_probability(rec_yd, 100.0) * REC_100_BONUS
    else:
        pts += PASS_300_BONUS if pass_yd >= 300 else 0.0
        pts += RUSH_100_BONUS if rush_yd >= 100 else 0.0
        pts += REC_100_BONUS if rec_yd >= 100 else 0.0

    return round(pts, 3)


# ── Defense / special teams ──────────────────────────────────────────────────
DST_SACK = 1.0
DST_INT = 2.0
DST_FUMBLE_REC = 2.0
DST_TD = 6.0
DST_SAFETY = 2.0
DST_BLOCK = 2.0
DST_RETURN_TD = 6.0

# Points allowed, in descending generosity. Checked against three sources —
# this table is the single most commonly mis-transcribed part of DK scoring.
DST_POINTS_ALLOWED = (
    (0, 10.0),      # shutout
    (6, 7.0),       # 1-6
    (13, 4.0),      # 7-13
    (20, 1.0),      # 14-20
    (27, 0.0),      # 21-27
    (34, -1.0),     # 28-34
)
DST_POINTS_ALLOWED_WORST = -4.0     # 35+


def dst_points_allowed(points_allowed: float) -> float:
    """Tier value for the points a defense gave up."""
    for ceiling, value in DST_POINTS_ALLOWED:
        if points_allowed <= ceiling:
            return value
    return DST_POINTS_ALLOWED_WORST


def dk_dst_points(stats: dict) -> float:
    """
    DraftKings points for a defense/special teams unit.

    Used to score HISTORICAL defenses exactly, from the per-team defensive
    counting stats nflverse publishes. There is no free source of forward
    defensive projections, so this does not project — it measures.
    """
    s = stats or {}

    def g(key):
        v = s.get(key)
        return float(v) if isinstance(v, (int, float)) else 0.0

    pts = 0.0
    pts += g("sacks") * DST_SACK
    pts += g("interceptions") * DST_INT
    pts += g("fumble_recoveries") * DST_FUMBLE_REC
    pts += g("def_tds") * DST_TD
    pts += g("safeties") * DST_SAFETY
    pts += (g("punt_blocks") + g("fg_blocks") + g("pat_blocks")) * DST_BLOCK
    pts += g("return_tds") * DST_RETURN_TD
    pts += dst_points_allowed(g("points_allowed"))
    return round(pts, 3)
