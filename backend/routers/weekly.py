"""
In-season endpoints — lineup optimizer, waiver assistant, my leagues.

One router for both dynasty and redraft: everything here is computed live from
Sleeper and touches neither the `teams` table nor `redraft_snapshots`, so there
is nothing for a mode split to split.

ROUTE ORDER MATTERS. `{league_id}` is an unconstrained str, so a route declared
above a literal segment will swallow it. League routes are namespaced under
/league/ and the literal /state and /user routes are declared first.
"""
import logging

from fastapi import APIRouter, Query, HTTPException

import projections
import sleeper_client
import weekly as weekly_engine

router = APIRouter(prefix="/api/weekly", tags=["weekly"])
log = logging.getLogger(__name__)


@router.get("/state")
async def get_state():
    """Current NFL week and season, straight from Sleeper."""
    state = await projections.nfl_state()
    season, week = await projections.current_week()
    return {
        "season": season,
        "week": week,
        "display_week": state.get("display_week"),
        "season_type": state.get("season_type"),
    }


@router.get("/user/{username}")
async def get_user(username: str):
    """
    Resolve a Sleeper username. This is the entirety of "logging in" — the
    Sleeper API is public and read-only, so there is no password or token.
    """
    user = await sleeper_client.get_user(username)
    if not user or not user.get("user_id"):
        raise HTTPException(
            status_code=404,
            detail=f"No Sleeper user named “{username}”. Check the spelling — "
                   "it's your username, not your display name.",
        )
    return {
        "user_id": user["user_id"],
        "username": user.get("username") or username,
        "display_name": user.get("display_name") or username,
        "avatar": user.get("avatar"),
    }


@router.get("/user/{user_id}/leagues")
async def get_user_leagues(user_id: str, season: int | None = Query(None)):
    """
    Every league this user is in. Returns fast — no rosters, no projections —
    so the page can render rows immediately and fill in summaries after.
    """
    if season is None:
        season, _ = await projections.current_week()
    leagues = await sleeper_client.get_user_leagues(user_id, season)

    out = []
    for lg in leagues or []:
        roster_id = None
        out.append({
            "league_id": lg.get("league_id"),
            "name": lg.get("name", ""),
            "season": lg.get("season"),
            "avatar": lg.get("avatar"),
            "total_rosters": lg.get("total_rosters"),
            "mode": weekly_engine.league_mode(lg),
            "roster_id": roster_id,          # resolved by /summary
            "status": lg.get("status"),
        })
    return {"user_id": user_id, "season": season, "leagues": out}


@router.get("/league/{league_id}/lineup")
async def get_lineup(
    league_id: str,
    roster_id: int = Query(...),
    week: int | None = Query(None),
):
    """Your current lineup against the optimal one, and the swaps worth making."""
    report = await weekly_engine.lineup_report(league_id, roster_id, week)
    if not report:
        raise HTTPException(status_code=404, detail=f"Sleeper league {league_id} not found.")
    return report


@router.get("/league/{league_id}/waivers")
async def get_waivers(
    league_id: str,
    roster_id: int = Query(...),
    week: int | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    mode: str | None = Query(None, pattern="^(dynasty|redraft|keeper)$"),
):
    """
    Who the rest of Sleeper is adding, narrowed to players free in your league.

    `mode` overrides what Sleeper reports the league type to be — worth having
    because plenty of dynasty leagues are set up as redraft and never corrected.
    """
    report = await weekly_engine.waiver_report(league_id, roster_id, week, limit, mode)
    if not report:
        raise HTTPException(status_code=404, detail=f"Sleeper league {league_id} not found.")
    return report


@router.get("/league/{league_id}/summary")
async def get_summary(
    league_id: str,
    user_id: str | None = Query(None),
    roster_id: int | None = Query(None),
    week: int | None = Query(None),
):
    """
    One glanceable row for the My Leagues page. Pass `user_id` and the roster is
    resolved for you — the league list endpoint deliberately doesn't fetch
    rosters, so it can return instantly.
    """
    if user_id is None and roster_id is None:
        raise HTTPException(status_code=422, detail="Pass user_id or roster_id.")
    report = await weekly_engine.league_summary(league_id, user_id, roster_id, week)
    if not report:
        raise HTTPException(status_code=404, detail=f"Sleeper league {league_id} not found.")
    return report
