"""
Weekly projections, restated under a league's own scoring.

Separate from sleeper_data.season() on purpose. That one fetches season TOTALS
and caches them under f"{kind}:{year}"; a weekly variant sharing that key would
overwrite the totals the draft rooms depend on. It also runs everything through
normalize(), which keeps only STAT_KEYS and throws away position and team —
fine for a stat panel, fatal here, because slot eligibility needs position and
the only other source is the 10MB player-meta blob that loads in the background.
Depending on that would mean the optimizer can compute nothing on a cold
process. So this keeps the identity fields and treats meta as enrichment.
"""
import time
import logging

import httpx

import draft_values
import sleeper_client

log = logging.getLogger(__name__)

BASE = "https://api.sleeper.com"
TIMEOUT = 20.0

# Mirrors sleeper_data's shape: successes hold for the full TTL, failures expire
# fast so a transient Sleeper blip doesn't cost the whole page.
WEEKLY_TTL = 30 * 60
FINAL_TTL = 6 * 3600          # a completed week's projections never change again
FAIL_TTL = 60
STATE_TTL = 5 * 60

_weekly_cache: dict[tuple, tuple[float, dict]] = {}
_state_cache: tuple[float, dict] | None = None

# Stats we score from, plus the identity fields eligibility needs.
_STAT_KEYS = (
    "pts_ppr", "pts_half_ppr", "pts_std",
    "pass_yd", "pass_td", "pass_int",
    "rush_att", "rush_yd", "rush_td",
    "rec", "rec_tgt", "rec_yd", "rec_td",
    "kr_yd", "pr_yd",
)


async def nfl_state() -> dict:
    """Current week/season, cached briefly. {} if Sleeper is unreachable."""
    global _state_cache
    if _state_cache and (time.time() - _state_cache[0]) < STATE_TTL:
        return _state_cache[1]
    data = await sleeper_client.get_nfl_state()
    marker = time.time() if data else (time.time() - STATE_TTL + FAIL_TTL)
    _state_cache = (marker, data)
    return data


async def current_week() -> tuple[int, int]:
    """
    (season, week) from Sleeper, falling back to the calendar heuristic.

    `display_week` is what Sleeper's own UI shows — during the gap between a
    week finishing and the next starting, it points at the upcoming week, which
    is the one you'd be setting a lineup for.
    """
    import sleeper_data
    state = await nfl_state()
    season = int(state.get("season") or sleeper_data.current_season())
    week = int(state.get("display_week") or state.get("week") or 1)
    return season, max(1, week)


def normalize(payload) -> dict:
    """
    Sleeper's weekly payload -> {sleeper_id: {stats..., position, team, name}}.

    The payload is a list of rows, each carrying a nested `player` object. Keeps
    identity alongside the stats so callers never need the meta blob to know
    what position someone plays.
    """
    out: dict[str, dict] = {}
    for row in (payload or []):
        if not isinstance(row, dict):
            continue
        pid = row.get("player_id") or (row.get("player") or {}).get("player_id")
        if not pid:
            continue
        stats = row.get("stats") or {}
        entry = {k: stats[k] for k in _STAT_KEYS
                 if isinstance(stats.get(k), (int, float))}
        player = row.get("player") or {}
        pos = draft_values.norm_pos(player.get("position") or "")
        first, last = player.get("first_name") or "", player.get("last_name") or ""
        entry.update({
            "position": pos,
            "fantasy_positions": [draft_values.norm_pos(p)
                                  for p in (player.get("fantasy_positions") or []) if p],
            "team": row.get("team") or player.get("team") or "",
            "opponent": row.get("opponent") or "",
            "name": (f"{first} {last}".strip() or player.get("full_name") or str(pid)),
        })
        out[str(pid)] = entry
    return out


async def weekly(season: int, week: int, kind: str = "projections",
                 is_final: bool = False) -> dict:
    """
    One week of projections or actuals. {} on failure — never raises.

    `is_final` promotes the TTL: a completed week's numbers are frozen, so
    there's no reason to keep refetching them every half hour.
    """
    key = (kind, int(season), int(week))
    ttl = FINAL_TTL if is_final else WEEKLY_TTL
    hit = _weekly_cache.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]

    url = f"{BASE}/{kind}/nfl/{season}/{week}?season_type=regular"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url)
        r.raise_for_status()
        data = normalize(r.json())
    except Exception as e:
        log.warning("Sleeper weekly %s %s/%s failed (%s); continuing without",
                    kind, season, week, e)
        data = {}

    marker = time.time() if data else (time.time() - ttl + FAIL_TTL)
    _weekly_cache[key] = (marker, data)
    return data


def score(stats: dict, ppr: float, scoring_settings: dict | None) -> float | None:
    """
    A stat row's points under this league's rules.

    league_points is stat-key based rather than season-aware, so the same
    function that restates a season total restates one week unchanged. The row
    carries its own position, which is what lets the TE premium apply.
    """
    if not stats:
        return None
    return draft_values.league_points(
        stats, ppr,
        scoring_settings=scoring_settings,
        position=stats.get("position"),
    )


def score_all(rows: dict, ppr: float, scoring_settings: dict | None) -> dict:
    """{sleeper_id: points} for every row that could be scored."""
    out = {}
    for pid, row in (rows or {}).items():
        pts = score(row, ppr, scoring_settings)
        if pts is not None:
            out[pid] = pts
    return out
