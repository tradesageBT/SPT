"""
Sleeper Fantasy draft assistant — public API, no auth required.

Scoring and roster settings are read from the league itself rather than typed
in: Sleeper exposes roster_positions and scoring_settings on GET /league/{id},
so PPR, superflex and every flex slot are derived automatically.

GET /api/sleeper-draft/state?league_id={id}
"""
import asyncio

import httpx
from fastapi import APIRouter, Query, HTTPException

import draft_values

router = APIRouter(prefix="/api/sleeper-draft")
SLEEPER = "https://api.sleeper.app/v1"
TIMEOUT = 10.0

# The league this assistant is set up for. Still a query param so the room works
# for any other league, but this is what it defaults to.
DEFAULT_LEAGUE_ID = "1389372044419809280"


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


@router.get("/state")
async def get_draft_state(league_id: str = Query(DEFAULT_LEAGUE_ID)):
    # The league doc carries roster_positions and scoring_settings — that is what
    # removes the need for any manual configuration.
    league_raw, drafts_raw, rosters_raw, users_raw = await asyncio.gather(
        _get(f"league/{league_id}"),
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

    # ── Values, using THIS league's scoring ───────────────────────────────────
    # Previously this read the global players_cache, which carries whatever
    # (ppr, num_qbs) the last league sync happened to write — so a dynasty
    # superflex sync mispriced this redraft league, and with no sync at all the
    # list came back empty. Both are read from the league doc now.
    roster = draft_values.parse_roster_positions(league_raw.get("roster_positions"))
    ppr = draft_values.parse_ppr(league_raw.get("scoring_settings"))
    num_qbs = roster["num_qbs"]

    all_players = await draft_values.load_values(num_qbs=num_qbs, ppr=ppr)

    by_pos = draft_values.group_by_position(all_players)
    starters = {
        "QB": roster["qb"], "RB": roster["rb"], "WR": roster["wr"],
        "TE": roster["te"], "K": roster["k"], "DEF": roster["dst"],
    }
    flex_counts = {k: roster[k] for k in draft_values.FLEX_KEYS}
    repl = draft_values.replacement_levels(by_pos, starters, flex_counts, num_teams)
    all_players = draft_values.apply_vor(by_pos, repl)
    all_players = draft_values.apply_tiers(all_players)

    available = [
        {
            "player_id": p["sleeper_id"],
            "name": p["name"],
            "position": p["position"],
            "nfl_team": p.get("nfl_team", ""),
            "redraft_value": p["value"],
            "redraft_pos_rank": p.get("pos_rank"),
            "tier": p.get("tier"),
            "vor": p.get("vor"),
        }
        for p in all_players
        if str(p["sleeper_id"]) not in drafted_ids
    ]
    available.sort(key=lambda x: x["redraft_value"], reverse=True)

    # On the clock
    picks_made = len(picks_out)
    otc_slot = None if is_auction or status != "drafting" else _on_clock(picks_made, num_teams)
    otc_roster_id = slot_to_roster.get(str(otc_slot)) if otc_slot else None
    otc_name = _team_name(otc_roster_id) if otc_roster_id else ""

    return {
        "draft_id": draft_id,
        "league_name": league_raw.get("name", ""),
        # Echoed so the UI can show what was auto-detected — the only way to
        # confirm the parse matches the real league settings.
        "league_settings": {
            "ppr": ppr,
            "num_qbs": num_qbs,
            "superflex": roster["sflex"] > 0,
            "starters": starters,
            "flex": flex_counts,
            "bench": roster["bench"],
            "idp": roster["idp"],
            "unknown_slots": roster["unknown"],
        },
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
