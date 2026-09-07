"""
ESPN's weekly projections, used as a RANK-ONLY second opinion.

Why rank-only. ESPN publishes `appliedTotal` — points already scored under
ESPN's rules — not raw stats. Our scorer, draft_values.league_points, is
structurally a delta function: it needs Sleeper's precomputed pts_ppr as a base
and adjusts a few categories on top. ESPN has no such base, so putting the two
numbers on one scale would mean two different scoring methodologies with a
systematic offset — and that offset would show up in the UI as "the experts
disagree", which is exactly the signal this is supposed to make trustworthy.

Positional RANKS are scale-free, so the methodology offset cancels completely.
"ESPN has him WR12, Sleeper has him WR28" is a real disagreement about the
player. "ESPN says 11.2, Sleeper says 13.8" mostly is not.

Two safety properties, because this endpoint is undocumented and will break:

  * It is never on the request path. A cold or stale cache means the caller
    ships Sleeper-only immediately and a background refresh fills in later.
  * Coverage is all-or-nothing. Partial coverage is worse than none — if ESPN
    knows 60% of a roster, some players carry a two-source read and some don't,
    and that asymmetry is invisible while systematically skewing which players
    get flagged.
"""
import asyncio
import logging
import time

import httpx

import draft_values
import sleeper_data

log = logging.getLogger(__name__)

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
TIMEOUT = 20.0

CACHE_TTL = 2 * 3600
FAIL_TTL = 15 * 60
# Below this share of the players we care about, ESPN is dropped entirely.
MIN_COVERAGE = 0.8

# statSourceId 1 is a projection; 0 is actual production.
_PROJECTION_SOURCE = 1

_cache: dict[tuple, tuple[float, dict]] = {}
_inflight: set[tuple] = set()


def _filter_header(week: int) -> str:
    return (
        '{"players":{"filterStatsForExternalIds":{"value":[%d]},'
        '"filterSlotIds":{"value":[0,2,4,6,17,16]},'
        '"limit":600,"offset":0,'
        '"sortPercOwned":{"sortAsc":false,"sortPriority":1}}}' % week
    )


def _extract(payload, week: int) -> dict:
    """{espn_id: projected_points} for one week."""
    players = payload.get("players") if isinstance(payload, dict) else payload
    out: dict[int, float] = {}
    for entry in (players or []):
        if not isinstance(entry, dict):
            continue
        pool = entry.get("playerPoolEntry") or {}
        player = pool.get("player") or entry.get("player") or {}
        pid = entry.get("id") or player.get("id")
        if pid is None:
            continue
        for stat in (player.get("stats") or []):
            if stat.get("statSourceId") != _PROJECTION_SOURCE:
                continue
            if int(stat.get("scoringPeriodId") or -1) != int(week):
                continue
            total = stat.get("appliedTotal")
            if isinstance(total, (int, float)):
                out[int(pid)] = float(total)
                break
    return out


async def _fetch(season: int, week: int) -> dict:
    url = f"{BASE}/seasons/{season}/segments/0/leaguedefaults/3"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            r = await client.get(
                url,
                params={"view": "kona_player_info"},
                headers={"X-Fantasy-Filter": _filter_header(week)},
            )
        r.raise_for_status()
        return _extract(r.json(), week)
    except Exception as e:
        log.warning("ESPN projections %s wk%s unavailable (%s); "
                    "continuing with Sleeper only", season, week, e)
        return {}


async def refresh(season: int, week: int) -> dict:
    key = (int(season), int(week))
    data = await _fetch(season, week)
    ttl = CACHE_TTL if data else FAIL_TTL
    _cache[key] = (time.time() if data else time.time() - CACHE_TTL + ttl, data)
    _inflight.discard(key)
    return data


def cached(season: int, week: int) -> dict:
    """
    Whatever we already have, without blocking. {} when cold — the caller ships
    Sleeper-only rather than waiting on an endpoint that may never answer.
    """
    key = (int(season), int(week))
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < CACHE_TTL:
        return hit[1]

    if key not in _inflight:
        # Check for a loop BEFORE building the coroutine: constructing it and
        # then failing to schedule it leaks a never-awaited coroutine.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None               # sync context — serve what we have
        if loop is not None:
            _inflight.add(key)
            loop.create_task(refresh(season, week))
    return hit[1] if hit else {}


def _ranks(points: dict, positions: dict) -> dict:
    """{player_id: positional rank}, best = 1."""
    by_pos: dict[str, list] = {}
    for pid, pts in points.items():
        pos = positions.get(pid)
        if pos:
            by_pos.setdefault(pos, []).append((pts, str(pid)))
    out = {}
    for pos, rows in by_pos.items():
        # Sort on points desc, id asc — a stable tiebreak so ranks don't shuffle.
        for i, (_, pid) in enumerate(sorted(rows, key=lambda r: (-r[0], r[1])), start=1):
            out[pid] = i
    return out


def disagreements(sleeper_points: dict, positions: dict,
                  season: int, week: int, player_ids=None) -> dict:
    """
    Where the two sources rank a player differently.

    Returns {"ok": bool, "coverage": float, "by_player": {id: {...}}}. `ok` is
    False whenever ESPN is unusable, and callers must then show "1 of 2 sources"
    rather than quietly presenting a one-source read as a consensus.
    """
    espn_raw = cached(season, week)
    ids = [str(p) for p in (player_ids if player_ids is not None else sleeper_points)]
    if not espn_raw or not ids:
        return {"ok": False, "coverage": 0.0, "by_player": {}}

    meta = sleeper_data.get_meta()
    espn_points: dict[str, float] = {}
    for pid in sleeper_points:
        espn_id = (meta.get(str(pid)) or {}).get("espn_id")
        if espn_id is None:
            continue
        try:
            val = espn_raw.get(int(espn_id))
        except (TypeError, ValueError):
            continue
        if val is not None:
            espn_points[str(pid)] = val

    covered = sum(1 for pid in ids if pid in espn_points)
    coverage = round(covered / len(ids), 3)
    if coverage < MIN_COVERAGE:
        # Partial coverage skews which players get flagged, invisibly. Better to
        # say ESPN is unavailable than to show a lopsided comparison.
        return {"ok": False, "coverage": coverage, "by_player": {}}

    s_rank = _ranks(sleeper_points, positions)
    e_rank = _ranks(espn_points, positions)

    out = {}
    for pid in ids:
        sr, er = s_rank.get(pid), e_rank.get(pid)
        if sr is None or er is None:
            continue
        pos = draft_values.norm_pos(positions.get(pid) or "")
        out[pid] = {
            "sleeper_rank": sr,
            "espn_rank": er,
            # Positive: ESPN rates them higher than Sleeper does.
            "gap": sr - er,
            "sleeper_label": f"{pos}{sr}" if pos else str(sr),
            "espn_label": f"{pos}{er}" if pos else str(er),
        }
    return {"ok": True, "coverage": coverage, "by_player": out}
