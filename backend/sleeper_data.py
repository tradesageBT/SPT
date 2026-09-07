"""
Shared Sleeper data layer: player metadata, season stats and projections.

Extracted from the auction router so both draft rooms read from one cache.
/players/nfl is a ~10MB download, so fetching it per-router would double that
for no reason.

Everything is cached in memory rather than Postgres: it needs no migration and
survives between requests on a warm process. It is lost on redeploy, and on a
plan that spins down when idle it is also lost on cold start — in both cases it
simply refetches.
"""
import time
import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

SLEEPER_BASE = "https://api.sleeper.com"

STATS_TTL = 6 * 3600
# A failure (or an empty parse) is cached only briefly: caching it for the full
# TTL would blank stats for the rest of a draft off one transient timeout.
STATS_FAIL_TTL = 60

# Kept deliberately small — this feeds a glanceable panel, not a stat page.
STAT_KEYS = (
    "pts_ppr", "pts_half_ppr", "pts_std", "gp", "gms_active",
    "pass_yd", "pass_td", "pass_int",
    "rush_att", "rush_yd", "rush_td",
    "rec", "rec_tgt", "rec_yd", "rec_td",
    # Return yardage. Standard scoring awards nothing for these, so a league
    # that scores them needs the raw yards to add on top of Sleeper's total.
    "kr_yd", "pr_yd",
)

_stats_cache: dict[str, tuple[float, dict]] = {}

# ── Player metadata (/players/nfl) ────────────────────────────────────────────
#
# ~10MB and 10-30s to download — cache_manager avoids it for exactly that
# reason. Callers load it in the BACKGROUND and never await it on a request
# path: the board returns immediately and this fills in when it lands.

META_TTL = 6 * 3600
# Injury/depth fields, plus the identity fields needed to build K/DEF entries
# (FantasyCalc carries neither position, so their names come from here).
META_KEYS = (
    "injury_status", "injury_notes", "practice_participation",
    "depth_chart_order", "depth_chart_position", "status",
    "position", "team", "full_name", "first_name", "last_name", "active",
    # For the weekly lineup optimizer: fantasy_positions is what actually
    # decides slot eligibility (a WR carrying RB eligibility is real, and
    # `position` alone gets that wrong), and bye_week explains an absent
    # projection rather than leaving it looking like missing data.
    "fantasy_positions", "bye_week",
    # ESPN's projections are keyed by their own player ids. Sleeper carries the
    # mapping, so keeping it here means the second opinion costs no extra
    # download — this 10MB blob is already being fetched.
    "espn_id",
)

_meta: dict[str, dict] = {}
_meta_at = 0.0
_meta_loading = False


def current_season() -> int:
    """NFL season is named for the year it starts; roll over in March."""
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 3 else now.year - 1


def meta_fresh() -> bool:
    # Deliberately not `bool(_meta) and ...`: a failed load stamps _meta_at too,
    # so an outage backs off rather than refetching on every request.
    return _meta_at > 0 and (time.time() - _meta_at) < META_TTL


def meta_loading() -> bool:
    return _meta_loading


def get_meta() -> dict:
    return _meta


async def load_meta():
    global _meta, _meta_at, _meta_loading
    if _meta_loading:
        return
    _meta_loading = True
    try:
        import sleeper_client
        data = await sleeper_client.get_all_players()
        out: dict[str, dict] = {}
        if isinstance(data, dict):
            for pid, p in data.items():
                if not isinstance(p, dict):
                    continue
                picked = {
                    k: p[k] for k in META_KEYS
                    if p.get(k) not in (None, "", [])
                }
                if picked:
                    out[str(pid)] = picked
        if out:
            _meta = out
            log.info("Loaded Sleeper player metadata for %d players", len(out))
    except Exception as e:
        log.warning("Sleeper player metadata failed (%s); continuing without", e)
    finally:
        # Stamped unconditionally: on failure this backs off for the TTL instead
        # of leaving meta_fresh() false and refetching 10MB on every request.
        _meta_at = time.time()
        _meta_loading = False


# ── Season stats / projections ────────────────────────────────────────────────

def normalize(payload) -> dict:
    """
    Sleeper's shape isn't contractually guaranteed and differs between
    endpoints/seasons, so accept both a list of entries and a dict keyed by
    player_id, and tolerate stats being nested under "stats" or inlined.
    """
    entries = []
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        for pid, val in payload.items():
            if isinstance(val, dict):
                val = dict(val)
                val.setdefault("player_id", pid)
                entries.append(val)

    out: dict[str, dict] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        pid = e.get("player_id")
        if pid is None and isinstance(e.get("player"), dict):
            pid = e["player"].get("player_id")
        if pid is None:
            continue
        stats = e.get("stats") if isinstance(e.get("stats"), dict) else e
        picked = {k: stats[k] for k in STAT_KEYS if isinstance(stats.get(k), (int, float))}
        if picked:
            out[str(pid)] = picked
    return out


async def season(kind: str, year: int) -> dict:
    """kind: 'projections' or 'stats'. Returns {sleeper_id: {stat: value}}."""
    key = f"{kind}:{year}"
    hit = _stats_cache.get(key)
    if hit and (time.time() - hit[0]) < STATS_TTL:
        return hit[1]

    url = f"{SLEEPER_BASE}/{kind}/nfl/{year}?season_type=regular"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url)
        r.raise_for_status()
        data = normalize(r.json())
    except Exception as e:
        log.warning("Sleeper %s for %s failed (%s); continuing without", kind, year, e)
        data = {}

    # Successes hold for the full TTL; failures and empty parses expire fast so a
    # transient Sleeper blip doesn't cost the whole draft.
    ttl_marker = time.time() if data else (time.time() - STATS_TTL + STATS_FAIL_TTL)
    _stats_cache[key] = (ttl_marker, data)
    return data


# ── Kickers and defenses ──────────────────────────────────────────────────────

_KDEF = {"K", "DEF", "DST"}


def load_kdef(last_stats: dict | None = None) -> list[dict]:
    """
    Kickers and defenses, which FantasyCalc doesn't carry at all.

    Returned deliberately UNRANKED (`value: 0`, no vor/tier) and ordered by last
    season's standard points — PPR is meaningless for these positions. Callers
    must append these AFTER tiering: a run of zero-value players would otherwise
    make every kicker its own tier, since (prev - 0) / prev exceeds any break.

    Degrades to [] if the metadata cache hasn't loaded — the board must never
    depend on this.
    """
    stats = last_stats or {}
    out = []
    for pid, m in (_meta or {}).items():
        pos = str(m.get("position") or "").upper()
        if pos not in _KDEF:
            continue
        # Sleeper marks retired/inactive players; drop them but keep anyone
        # whose flag is simply missing.
        if m.get("active") is False:
            continue
        name = m.get("full_name") or " ".join(
            x for x in (m.get("first_name"), m.get("last_name")) if x
        ).strip()
        if not name:
            continue
        pts = (stats.get(str(pid)) or {}).get("pts_std")
        out.append({
            "sleeper_id": str(pid),
            "name": name,
            "position": "DEF" if pos in ("DEF", "DST") else "K",
            "nfl_team": m.get("team") or "",
            "value": 0,
            "vor": None,
            "tier": None,
            "last_pts": round(pts) if isinstance(pts, (int, float)) else None,
        })

    # Best last season first; anyone without stats (rookies, new starters) sorts
    # last rather than being dropped.
    out.sort(key=lambda p: (p["last_pts"] is not None, p["last_pts"] or 0), reverse=True)
    return out
