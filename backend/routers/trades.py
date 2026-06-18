import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from database import db
from trade_engine import generate_all_trades, generate_trades_between, categorize_players, compute_trade_breakdown
import sleeper_client
import cache_manager
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
        for f in ("positional_breakdown", "positional_surplus", "positional_need", "positional_rank"):
            d[f] = json.loads(d[f]) if d.get(f) else {}
        roster_data = json.loads(d.get("roster_data") or "{}")
        d["players"] = roster_data.get("players", [])
        d["picks"] = roster_data.get("picks", [])
        profiles.append(d)

    return profiles


# ---------------------------------------------------------------------------
# Manual trade evaluator
# ---------------------------------------------------------------------------

class TradeAsset(BaseModel):
    sleeper_id: str
    name: str
    position: str
    fc_value: int = 0


class TradeEvalRequest(BaseModel):
    a_roster_id: int
    b_roster_id: int
    a_gives: list[TradeAsset]
    b_gives: list[TradeAsset]


@router.post("/{league_id}/evaluate-trade")
async def evaluate_trade(league_id: str, body: TradeEvalRequest):
    profiles = _load_profiles(league_id)

    team_a = next((p for p in profiles if p["roster_id"] == body.a_roster_id), None)
    team_b = next((p for p in profiles if p["roster_id"] == body.b_roster_id), None)
    if not team_a or not team_b:
        raise HTTPException(status_code=404, detail="Roster not found")

    a_gives = [a.model_dump() for a in body.a_gives]
    b_gives = [b.model_dump() for b in body.b_gives]

    # Enrich with age + is_starter from stored roster data (picks have no age)
    for item in a_gives:
        match = next((p for p in team_a["players"] if p.get("sleeper_id") == item["sleeper_id"]), {})
        item["age"] = match.get("age")
        item["is_starter"] = match.get("is_starter", False)
    for item in b_gives:
        match = next((p for p in team_b["players"] if p.get("sleeper_id") == item["sleeper_id"]), {})
        item["age"] = match.get("age")
        item["is_starter"] = match.get("is_starter", False)

    breakdown_a = compute_trade_breakdown(team_a, a_gives, b_gives)
    breakdown_b = compute_trade_breakdown(team_b, b_gives, a_gives)

    value_a = sum(x["fc_value"] for x in a_gives)
    value_b = sum(x["fc_value"] for x in b_gives)

    def _avg_age(items):
        ages = [x["age"] for x in items if x.get("position") != "PK" and x.get("age")]
        return round(sum(ages) / len(ages), 1) if ages else None

    lineup_delta_a = breakdown_a["lineup_delta"]
    lineup_delta_b = breakdown_b["lineup_delta"]
    value_diff = value_a - value_b  # positive = A gives more raw value

    # Winner: lineup delta comparison is primary; raw value delta is tiebreak
    is_win_win = lineup_delta_a > 0 and lineup_delta_b > 0
    ld_diff = lineup_delta_a - lineup_delta_b   # positive = A improved more
    if is_win_win:
        winner = "even"
    elif abs(ld_diff) >= 300:
        winner = "a" if ld_diff > 0 else "b"
    elif abs(value_diff) > 500:
        winner = "b" if value_diff > 0 else "a"
    else:
        winner = "even"

    pos_rank_a = team_a.get("positional_rank") or {}
    pos_rank_b = team_b.get("positional_rank") or {}
    n = pos_rank_a.get("n") or pos_rank_b.get("n") or 0

    return {
        "value_a_gives": value_a,
        "value_b_gives": value_b,
        "value_delta": abs(value_diff),
        "lineup_delta_a": lineup_delta_a,
        "lineup_delta_b": lineup_delta_b,
        "breakdown_a": breakdown_a,
        "breakdown_b": breakdown_b,
        "avg_age_a_gives": _avg_age(a_gives),
        "avg_age_b_gives": _avg_age(b_gives),
        "team_a_name": team_a["display_name"],
        "team_b_name": team_b["display_name"],
        "contention_a": team_a.get("contention_category"),
        "contention_b": team_b.get("contention_category"),
        "positional_rank_a": pos_rank_a,
        "positional_rank_b": pos_rank_b,
        "num_teams": n,
        "is_win_win": is_win_win,
        "winner": winner,
    }


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


_ROUND_LABEL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


@router.get("/{league_id}/recent-transactions")
async def get_recent_transactions(league_id: str):
    """Return the 15 most recent completed trades in this league's current season."""
    profiles = _load_profiles(league_id)
    roster_names = {p["roster_id"]: p["display_name"] for p in profiles}

    txn_results = await asyncio.gather(*[
        sleeper_client.get_transactions(league_id, week)
        for week in range(0, 23)
    ])

    all_txns = [
        t for week_txns in txn_results for t in week_txns
        if t.get("type") == "trade" and t.get("status") == "complete"
    ]
    recent = sorted(all_txns, key=lambda t: t.get("created") or 0, reverse=True)[:15]

    players_cache = cache_manager.get_cached_players()
    result = []

    for txn in recent:
        adds  = txn.get("adds") or {}
        drops = txn.get("drops") or {}
        picks = txn.get("draft_picks") or []
        created = txn.get("created")

        sides: dict[int, dict] = {}

        for pid, to_rid in adds.items():
            from_rid = drops.get(str(pid))
            if from_rid is None:
                continue
            from_rid = int(from_rid)
            sides.setdefault(from_rid, {
                "team_name": roster_names.get(from_rid, f"Team {from_rid}"),
                "gave": [],
            })
            p = players_cache.get(str(pid), {})
            sides[from_rid]["gave"].append({
                "name": p.get("name", str(pid)),
                "position": p.get("position", ""),
            })

        for pick in picks:
            from_rid = pick.get("previous_owner_id")
            if from_rid is None:
                continue
            from_rid = int(from_rid)
            sides.setdefault(from_rid, {
                "team_name": roster_names.get(from_rid, f"Team {from_rid}"),
                "gave": [],
            })
            rnd = int(pick.get("round", 1))
            season = str(pick.get("season", ""))
            sides[from_rid]["gave"].append({
                "name": f"{season} {_ROUND_LABEL.get(rnd, f'Rd {rnd}')}",
                "position": "PK",
            })

        if len(sides) < 2:
            continue

        date_str = (
            datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%b %d, %Y")
            if created else None
        )
        result.append({"date": date_str, "sides": list(sides.values())})

    return result
