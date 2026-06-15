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


async def get_all_players() -> dict:
    """Returns giant map of sleeper_id -> player object. Cache daily."""
    return await _get("/players/nfl") or {}
