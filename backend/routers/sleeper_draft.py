"""
Sleeper Fantasy draft assistant — public API, no auth required.

GET /api/sleeper-draft/state?league_id={id}
"""
import asyncio
from collections import defaultdict

import httpx
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/api/sleeper-draft")
SLEEPER = "https://api.sleeper.app/v1"
TIMEOUT = 10.0


async def _get(path: str):
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{SLEEPER}/{path}")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Sleeper: not found — {path}")
    r.raise_for_status()
    return r.json()


def _on_clock(picks_made: int, num_teams: int) -> int | None:
    """Return 1-based draft slot for the next pick (snake)."""
    rnd = picks_made // num_teams
    pos = picks_made % num_teams
    return (pos + 1) if rnd % 2 == 0 else (num_teams - pos)


def _vor(players: list, num_teams: int) -> list:
    pos_vals: dict[str, list] = defaultdict(list)
    for p in players:
        v = p.get("redraft_value") or 0
        if v:
            pos_vals[p["position"]].append(v)
    repl: dict[str, int] = {}
    for pos, vals in pos_vals.items():
        vals.sort(reverse=True)
        n = num_teams if pos in ("RB", "WR") else num_teams // 2
        repl[pos] = vals[n] if len(vals) > n else (vals[-1] if vals else 0)
    for p in players:
        v = p.get("redraft_value") or 0
        p["vor"] = v - repl.get(p["position"], 0)
    return players


def _tiers(players: list) -> list:
    tier = 1
    for i, p in enumerate(players):
        if i > 0:
            prev = players[i - 1].get("redraft_value") or 1
            curr = p.get("redraft_value") or 0
            if prev > 0 and curr > 0 and (prev - curr) / prev > 0.08:
                tier += 1
        p["tier"] = tier
    return players


@router.get("/state")
async def get_draft_state(league_id: str = Query(...)):
    from cache_manager import get_cached_players

    # Fetch drafts list, rosters, and users in parallel
    drafts_raw, rosters_raw, users_raw = await asyncio.gather(
        _get(f"league/{league_id}/drafts"),
        _get(f"league/{league_id}/rosters"),
        _get(f"league/{league_id}/users"),
    )

    if not drafts_raw:
        raise HTTPException(status_code=404, detail="No drafts found for this league.")

    # Prefer active → most recent
    draft = next((d for d in drafts_raw if d.get("status") in ("drafting", "pre_draft")), drafts_raw[0])
    draft_id = draft["draft_id"]

    # Fetch full draft detail + picks in parallel
    draft_detail, picks_raw = await asyncio.gather(
        _get(f"draft/{draft_id}"),
        _get(f"draft/{draft_id}/picks"),
    )

    settings = draft_detail.get("settings", {})
    num_teams = int(settings.get("teams", 12))
    rounds = int(settings.get("rounds", 15))
    is_auction = draft_detail.get("type", "snake") == "auction"
    status = draft_detail.get("status", "pre_draft")

    # Build lookup maps
    slot_to_roster: dict[str, int] = draft_detail.get("slot_to_roster_id", {}) or {}
    roster_map = {r["roster_id"]: r for r in rosters_raw}
    user_map = {u["user_id"]: u.get("display_name") or u.get("username") or f"User {u['user_id']}" for u in users_raw}

    def _team_name(roster_id) -> str:
        r = roster_map.get(roster_id, {})
        return user_map.get(r.get("owner_id", ""), f"Team {roster_id}")

    teams = [
        {"roster_id": slot_to_roster.get(str(s)), "name": _team_name(slot_to_roster.get(str(s))), "draft_slot": s}
        for s in range(1, num_teams + 1)
        if slot_to_roster.get(str(s))
    ]

    # Parse picks
    picks_out = []
    drafted_ids: set[str] = set()
    for pk in picks_raw:
        pid = str(pk.get("player_id") or "")
        if pid:
            drafted_ids.add(pid)
        meta = pk.get("metadata") or {}
        roster_id = pk.get("roster_id")
        first = meta.get("first_name", "")
        last = meta.get("last_name", "")
        picks_out.append({
            "pick_no": pk.get("pick_no"),
            "round": pk.get("round"),
            "player_id": pid,
            "player_name": f"{first} {last}".strip() or pid,
            "position": meta.get("position", ""),
            "nfl_team": meta.get("team", ""),
            "roster_id": roster_id,
            "team_name": _team_name(roster_id),
            "amount": meta.get("amount"),
        })

    # Available players from players_cache
    players_cache = get_cached_players()
    available = []
    for p in players_cache.values():
        if str(p["sleeper_id"]) in drafted_ids:
            continue
        rv = p.get("redraft_value") or 0
        if not rv:
            continue
        available.append({
            "player_id": p["sleeper_id"],
            "name": p["name"],
            "position": p["position"],
            "nfl_team": p.get("nfl_team", ""),
            "redraft_value": rv,
            "fc_value": p.get("fc_value") or 0,
            "redraft_pos_rank": p.get("redraft_pos_rank"),
            "tier": None,
            "vor": None,
        })

    available.sort(key=lambda x: x["redraft_value"], reverse=True)
    available = _vor(available, num_teams)
    available = _tiers(available)

    # On the clock
    picks_made = len(picks_out)
    otc_slot = None if is_auction or status != "drafting" else _on_clock(picks_made, num_teams)
    otc_roster_id = slot_to_roster.get(str(otc_slot)) if otc_slot else None
    otc_name = _team_name(otc_roster_id) if otc_roster_id else ""

    return {
        "draft_id": draft_id,
        "status": status,
        "is_auction": is_auction,
        "picks_made": picks_made,
        "total_picks": num_teams * rounds,
        "num_teams": num_teams,
        "rounds": rounds,
        "on_the_clock_roster_id": otc_roster_id,
        "on_the_clock_name": otc_name,
        "teams": teams,
        "picks": picks_out[-25:],
        "all_picks": picks_out,
        "available": available,
    }
