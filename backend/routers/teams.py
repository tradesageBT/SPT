import json
from fastapi import APIRouter, HTTPException
from database import db
import cache_manager
from trade_engine import categorize_players

router = APIRouter(prefix="/api/leagues", tags=["teams"])


def _team_row_to_dict(row) -> dict:
    d = dict(row)
    for field in ("positional_breakdown", "positional_surplus", "positional_need", "roster_data"):
        if d.get(field):
            d[field] = json.loads(d[field])
    return d


@router.get("/{league_id}/teams")
async def get_teams(league_id: str):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM teams WHERE sleeper_league_id = ? ORDER BY total_value DESC",
            (league_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="League not found or not yet synced")
    return [_team_row_to_dict(r) for r in rows]


@router.get("/{league_id}/teams/{roster_id}")
async def get_team(league_id: str, roster_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM teams WHERE sleeper_league_id = ? AND roster_id = ?",
            (league_id, roster_id),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Team not found")

    team = _team_row_to_dict(row)
    roster_data = team.get("roster_data") or {}

    # Attach full player data from cache
    players_cache = cache_manager.get_cached_players()
    enriched = roster_data.get("players", [])
    for p in enriched:
        cached = players_cache.get(p["sleeper_id"], {})
        p.setdefault("name", cached.get("name", p["sleeper_id"]))
        p.setdefault("position", cached.get("position", ""))
        p.setdefault("nfl_team", cached.get("nfl_team", ""))
        p.setdefault("age", cached.get("age"))

    # Smash/Pass/Trash
    profile_for_cat = {
        "roster_id": team["roster_id"],
        "players": enriched,
        "picks": roster_data.get("picks", []),
        "positional_surplus": team.get("positional_surplus") or {},
        "contention_score": team.get("contention_score", 0.5),
    }
    categorized = categorize_players(profile_for_cat)

    return {
        **team,
        "roster_data": {"players": enriched, "picks": roster_data.get("picks", [])},
        "categorized": categorized,
    }
