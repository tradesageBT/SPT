import httpx
from typing import Any

BASE = "https://api.sleeper.app/v1"
TIMEOUT = 30.0


async def _get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
        r = await client.get(f"{BASE}{path}")
        r.raise_for_status()
        return r.json()


async def get_league(league_id: str) -> dict:
    return await _get(f"/league/{league_id}")


async def get_rosters(league_id: str) -> list:
    return await _get(f"/league/{league_id}/rosters") or []


async def get_users(league_id: str) -> list:
    return await _get(f"/league/{league_id}/users") or []


async def get_traded_picks(league_id: str) -> list:
    """Returns all pick trades ever made in this league.
    Each entry: {season, round, roster_id (original), owner_id (current), previous_owner_id}
    """
    return await _get(f"/league/{league_id}/traded_picks") or []


async def get_transactions(league_id: str, leg: int) -> list:
    try:
        return await _get(f"/league/{league_id}/transactions/{leg}") or []
    except Exception:
        return []


async def get_all_players() -> dict:
    """Returns giant map of sleeper_id -> player object. Cache daily."""
    return await _get("/players/nfl") or {}


async def get_league_drafts(league_id: str) -> list:
    try:
        return await _get(f"/league/{league_id}/drafts") or []
    except Exception:
        return []


async def get_draft(draft_id: str) -> dict:
    try:
        return await _get(f"/draft/{draft_id}") or {}
    except Exception:
        return {}


async def get_draft_picks(draft_id: str) -> list:
    try:
        return await _get(f"/draft/{draft_id}/picks") or []
    except Exception:
        return []


# ── Weekly / in-season endpoints ──────────────────────────────────────────────
# Everything below is read-only and needs no token — Sleeper's API cannot be
# written to, so there is nothing to authenticate. Sleeper asks callers to stay
# under 1000 requests/minute; the callers here all cache.


async def get_nfl_state() -> dict:
    """
    Current week and season, straight from Sleeper.

    Returns {season, season_type, week, display_week, leg, ...}. Prefer this
    over sleeper_data.current_season(): that one infers the year from the
    calendar with a March rollover, which disagrees with Sleeper for several
    weeks each spring.
    """
    try:
        return await _get("/state/nfl") or {}
    except Exception:
        return {}


async def get_matchups(league_id: str, week: int) -> list:
    """
    Per-roster lineups for one week: {roster_id, matchup_id, starters,
    players, starters_points, players_points, points}.

    This — not `rosters` — is the authoritative lineup for a given week.
    `rosters["starters"]` only ever holds the live week's starters.
    """
    try:
        return await _get(f"/league/{league_id}/matchups/{week}") or []
    except Exception:
        return []


async def get_trending(kind: str = "add", lookback_hours: int = 24, limit: int = 200) -> list:
    """
    Players being added or dropped across all of Sleeper: [{player_id, count}].

    League-agnostic, so callers must filter to who is actually unrostered in
    their own league — ask for far more than you intend to show.
    """
    if kind not in ("add", "drop"):
        raise ValueError(f"trending kind must be add or drop, got {kind!r}")
    try:
        return await _get(
            f"/players/nfl/trending/{kind}"
            f"?lookback_hours={int(lookback_hours)}&limit={int(limit)}"
        ) or []
    except Exception:
        return []


async def get_user(username: str) -> dict:
    """
    Resolve a Sleeper username (or user_id) to {user_id, display_name, avatar}.

    This is the whole of "logging in": the API is public and read-only, so no
    password, token or OAuth is involved. Returns {} for an unknown username.
    """
    try:
        return await _get(f"/user/{username}") or {}
    except Exception:
        return {}


async def get_user_leagues(user_id: str, season: str | int) -> list:
    """Every NFL league this user is in for a season. [] if none or on error."""
    try:
        return await _get(f"/user/{user_id}/leagues/nfl/{season}") or []
    except Exception:
        return []
