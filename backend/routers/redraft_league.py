"""
Redraft league hub — Sleeper only, public API, no auth.

Mirrors the dynasty value engine with the dynasty concepts removed: no rookie
picks, no dynasty values, no contention windows. Scoring and roster settings are
read from the league itself, so nothing is configured by hand.

  GET  /api/redraft-league/{league_id}                    live rankings
  GET  /api/redraft-league/{league_id}/teams/{roster_id}  live team detail
  POST /api/redraft-league/{league_id}/sync               snapshot for trades
  GET  /api/redraft-league/{league_id}/trades             ideas from the snapshot

Rankings compute live because they are cheap. Trade generation is O(T^2 * n^4)
— hundreds of thousands of fairness checks for a 12-team league, each survivor
running two roster simulations — so it reads a snapshot instead.
"""
import json
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, HTTPException

import draft_values
import value_engine
import trade_engine
import sleeper_client
from database import db

router = APIRouter(prefix="/api/redraft-league")
log = logging.getLogger(__name__)

VALUE_KEY = "redraft_value"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _players_cache(values: list[dict]) -> dict:
    """
    Shape draft_values.load_values output like the players_cache row dict that
    value_engine._player_entry expects, deriving the ranks it wants.

    fc_value is set to the redraft number as well as redraft_value: the trade
    engine only ever compares magnitudes, so aliasing here means it needs no
    changes at all.
    """
    ordered = sorted(values, key=lambda p: p.get("value", 0) or 0, reverse=True)
    pos_seen: dict[str, int] = {}
    cache: dict[str, dict] = {}
    for i, p in enumerate(ordered, start=1):
        pos = p.get("position", "")
        pos_seen[pos] = pos_seen.get(pos, 0) + 1
        val = p.get("value", 0) or 0
        cache[str(p["sleeper_id"])] = {
            "sleeper_id": str(p["sleeper_id"]),
            "name": p.get("name", ""),
            "position": pos,
            "nfl_team": p.get("nfl_team", ""),
            "age": p.get("age"),
            "fc_value": val,          # alias — see docstring
            "redraft_value": val,
            "overall_rank": i,
            "pos_rank": pos_seen[pos],
            "redraft_overall_rank": i,
            "redraft_pos_rank": pos_seen[pos],
        }
    return cache


async def _league_state(league_id: str):
    """Fetch the league and compute profiles. Shared by every endpoint here."""
    league, rosters, users = await asyncio.gather(
        sleeper_client.get_league(league_id),
        sleeper_client.get_rosters(league_id),
        sleeper_client.get_users(league_id),
    )
    if not league:
        raise HTTPException(status_code=404, detail=f"Sleeper league {league_id} not found.")

    roster_positions = league.get("roster_positions") or []
    slots = draft_values.parse_roster_positions(roster_positions)
    ppr = draft_values.parse_ppr(league.get("scoring_settings"))

    values = await draft_values.load_values(num_qbs=slots["num_qbs"], ppr=ppr)
    cache = _players_cache(values)
    users_map = {u["user_id"]: u for u in (users or [])}

    profiles = value_engine.compute_league_profiles(
        rosters or [], users_map, cache, {},
        roster_positions=roster_positions,
        value_key=VALUE_KEY,
        include_picks=False,
    )
    value_engine.strength_tiers(profiles)

    settings = {
        "ppr": ppr,
        "num_qbs": slots["num_qbs"],
        "superflex": slots["sflex"] > 0,
        "starters": {"QB": slots["qb"], "RB": slots["rb"], "WR": slots["wr"],
                     "TE": slots["te"], "K": slots["k"], "DEF": slots["dst"]},
        "flex": {k: slots[k] for k in draft_values.FLEX_KEYS},
        "bench": slots["bench"],
        "roster_positions": roster_positions,
    }
    return league, profiles, settings


@router.get("/{league_id}")
async def get_league_hub(league_id: str):
    """Power rankings, positional strength and ranks. Computed live."""
    league, profiles, settings = await _league_state(league_id)
    return {
        "league_id": league_id,
        "league_name": league.get("name", ""),
        "season": league.get("season", ""),
        "num_teams": len(profiles),
        "settings": settings,
        "teams": profiles,
    }


@router.get("/{league_id}/teams/{roster_id}")
async def get_team(league_id: str, roster_id: int):
    """One team's detail — roster, positional strength, starters and bench."""
    league, profiles, settings = await _league_state(league_id)
    profile = next((p for p in profiles if p["roster_id"] == roster_id), None)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Roster {roster_id} not in this league.")

    players = sorted(profile["players"], key=lambda p: p.get(VALUE_KEY, 0), reverse=True)
    return {
        "league_id": league_id,
        "league_name": league.get("name", ""),
        "settings": settings,
        "num_teams": len(profiles),
        **profile,
        "players": players,
    }


@router.post("/{league_id}/sync")
async def sync_league(league_id: str):
    """Snapshot the league so trade generation has something affordable to read."""
    league, profiles, settings = await _league_state(league_id)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO redraft_snapshots (league_id, league_name, profiles, settings, computed_at)
            VALUES (:lid, :name, :profiles, :settings, :at)
            ON CONFLICT(league_id) DO UPDATE SET
                league_name=excluded.league_name,
                profiles=excluded.profiles,
                settings=excluded.settings,
                computed_at=excluded.computed_at
            """,
            {"lid": league_id, "name": league.get("name", ""),
             "profiles": json.dumps(profiles), "settings": json.dumps(settings),
             "at": _now()},
        )
    return {"ok": True, "league_name": league.get("name", ""),
            "teams_synced": len(profiles), "computed_at": _now()}


def _load_snapshot(league_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM redraft_snapshots WHERE league_id = ?", (league_id,)
        ).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="This league hasn't been synced yet — hit Sync to generate trade ideas.",
        )
    return json.loads(row.get("profiles") or "[]"), row.get("computed_at")


@router.get("/{league_id}/trades")
def get_trades(
    league_id: str,
    roster_id: int | None = Query(None),
    include_smash: bool = Query(False),
    expand: bool = Query(False),
):
    """
    Trade ideas from the last snapshot.

    Sync `def` not `async def`: this is CPU-bound for hundreds of milliseconds,
    so FastAPI should run it in the threadpool rather than on the event loop.
    """
    profiles, computed_at = _load_snapshot(league_id)
    if len(profiles) < 2:
        return {"trades": [], "computed_at": computed_at}

    # Cutoffs from this league's own distribution — the module constants are
    # calibrated to the dynasty value scale.
    thresholds = trade_engine.derive_thresholds(profiles)
    cats = {p["roster_id"]: trade_engine.categorize_players(p, thresholds) for p in profiles}

    focus = next((p for p in profiles if p["roster_id"] == roster_id), None) if roster_id else None
    pairs = (
        [(focus, o) for o in profiles if o["roster_id"] != roster_id]
        if focus else
        [(a, b) for i, a in enumerate(profiles) for b in profiles[i + 1:]]
    )

    trades = []
    for a, b in pairs:
        trades.extend(trade_engine.generate_trades_between(
            a, b, cats[a["roster_id"]], cats[b["roster_id"]],
            include_smash=include_smash,
            include_picks=False,          # redraft has none
            expand_mode=expand,
        ))
    trades.sort(key=lambda t: -(t["lineup_delta_a"] + t["lineup_delta_b"]))
    return {"trades": trades[:60], "computed_at": computed_at}
