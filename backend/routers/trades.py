import json
from fastapi import APIRouter, HTTPException, Query, Request
from database import db
from trade_engine import generate_all_trades, generate_trades_between, categorize_players
import logger

router = APIRouter(prefix="/api/leagues", tags=["trades"])


def _load_profiles(league_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM teams WHERE sleeper_league_id = ? ORDER BY total_value DESC",
            (league_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="League not synced yet")

    profiles = []
    for row in rows:
        d = dict(row)
        for f in ("positional_breakdown", "positional_surplus", "positional_need"):
            d[f] = json.loads(d[f]) if d.get(f) else {}
        roster_data = json.loads(d.get("roster_data") or "{}")
        d["players"] = roster_data.get("players", [])
        d["picks"] = roster_data.get("picks", [])
        profiles.append(d)

    return profiles


@router.get("/{league_id}/players")
async def get_league_players(league_id: str):
    """All players across all rosters — used to populate the trade filter search."""
    profiles = _load_profiles(league_id)
    seen = set()
    players = []
    for p in profiles:
        for player in p["players"]:
            sid = player.get("sleeper_id")
            if sid and sid not in seen:
                seen.add(sid)
                players.append({
                    "sleeper_id": sid,
                    "name": player.get("name", sid),
                    "position": player.get("position", ""),
                    "roster_id": p["roster_id"],
                    "display_name": p["display_name"],
                    "fc_value": player.get("fc_value", 0),
                    "is_starter": player.get("is_starter", False),
                })
    return sorted(players, key=lambda x: x["name"])


@router.get("/{league_id}/trades")
async def get_all_trade_ideas(
    request: Request,
    league_id: str,
    roster_id: int | None = Query(None),
    include_smash: bool = Query(False),
    include_picks: bool = Query(False),
    force_player_id: str | None = Query(None),
):
    profiles = _load_profiles(league_id)

    # When forcing a specific player, find their team and inject them into the
    # tradeable pool regardless of their smash/pass/trash tier.
    force_profile = None
    force_player = None
    if force_player_id:
        for p in profiles:
            match = next((pl for pl in p["players"] if pl.get("sleeper_id") == force_player_id), None)
            if match:
                force_profile = p
                force_player = match
                break

    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
    if force_player_id and force_player:
        logger.log("trade_search", {
            "league_id": league_id,
            "player_id": force_player_id,
            "player_name": force_player.get("name"),
            "include_smash": include_smash,
            "include_picks": include_picks,
        }, ip=ip)

    force_mode = force_player_id is not None

    if roster_id is not None:
        focus = next((p for p in profiles if p["roster_id"] == roster_id), None)
        if not focus:
            raise HTTPException(status_code=404, detail="Roster not found")
        others = [p for p in profiles if p["roster_id"] != roster_id]
        cat_focus = _categorize_with_forced(focus, force_player, force_profile)
        trades = []
        for other in others:
            cat_other = _categorize_with_forced(other, force_player, force_profile)
            trades.extend(generate_trades_between(
                focus, other, cat_focus, cat_other,
                include_smash=include_smash,
                include_picks=include_picks,
                force_mode=force_mode,
            ))
        result = sorted(trades, key=lambda x: x["value_delta"])
    else:
        cats = {p["roster_id"]: _categorize_with_forced(p, force_player, force_profile) for p in profiles}
        from itertools import combinations
        all_trades = []
        for a, b in combinations(profiles, 2):
            all_trades.extend(generate_trades_between(
                a, b, cats[a["roster_id"]], cats[b["roster_id"]],
                include_smash=include_smash,
                include_picks=include_picks,
                force_mode=force_mode,
            ))
        result = all_trades

    if force_player_id:
        result = [t for t in result if _trade_has_player(t, force_player_id)]

    return result


def _categorize_with_forced(profile: dict, force_player: dict | None, force_profile: dict | None) -> dict:
    cats = categorize_players(profile)
    if force_player and force_profile and profile["roster_id"] == force_profile["roster_id"]:
        all_in_pool = cats["smash"] + cats["pass"] + cats["trash"]
        already_in = any(p["sleeper_id"] == force_player["sleeper_id"] for p in all_in_pool)
        if not already_in:
            cats = dict(cats)
            cats["pass"] = [force_player] + cats["pass"]
        elif not any(p["sleeper_id"] == force_player["sleeper_id"] for p in cats["pass"]):
            # Player is in smash or trash — move them to pass so they're tradeable
            cats = {k: [p for p in v if p["sleeper_id"] != force_player["sleeper_id"]] for k, v in cats.items()}
            cats["pass"] = [force_player] + cats["pass"]
    return cats


def _trade_has_player(trade: dict, sleeper_id: str) -> bool:
    return any(p.get("sleeper_id") == sleeper_id for p in trade["a_gives"] + trade["b_gives"])
