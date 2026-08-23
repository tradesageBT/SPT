"""
ESPN Fantasy Football auction draft assistant.
Proxies to ESPN's unofficial API using the user's session cookies.
"""
import re
import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/espn-draft")

ESPN_BASE = "https://fantasy.espn.com/apis/v3/games/ffl"
ESPN_TIMEOUT = 15.0

# Per-process cache: (league_id, season) -> {espn_id: {name, position}}
_ESPN_PLAYER_MAP: dict[tuple, dict] = {}

# ESPN position ID → our position label (skill + kicker/dst + IDP)
_ESPN_POS = {
    1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF",
    9: "DL", 10: "LB", 11: "DB", 12: "DB",
}

IDP_POSITIONS = {"DL", "LB", "DB"}


def _normalize(name: str) -> str:
    name = name.lower()
    for suffix in (" jr", " sr", " ii", " iii", " iv"):
        name = name.replace(suffix, "")
    return re.sub(r"[^a-z]", "", name)


def _espn_headers(espn_s2: str, swid: str) -> dict:
    return {
        "Cookie": f"espn_s2={espn_s2}; SWID={swid}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://fantasy.espn.com/",
    }


async def _fetch_espn(url: str, espn_s2: str, swid: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=ESPN_TIMEOUT, verify=False, follow_redirects=False) as client:
        r = await client.get(url, headers=_espn_headers(espn_s2, swid), params=params)
    if r.status_code in (301, 302, 303, 307, 308):
        raise HTTPException(status_code=401, detail="ESPN rejected the request — your espn_s2 or SWID cookie is invalid. Copy them again from fantasy.espn.com in a desktop browser (F12 → Application → Cookies).")
    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="ESPN credentials invalid or expired. Re-enter your espn_s2 and SWID cookies.")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="ESPN league not found. Check your league ID and season year.")
    r.raise_for_status()
    return r.json()


async def _load_espn_players(league_id: str, season: int, espn_s2: str, swid: str):
    """Fetch ESPN's player list once and cache it for this league+season."""
    key = (league_id, season)
    if key in _ESPN_PLAYER_MAP:
        return
    url = f"{ESPN_BASE}/seasons/{season}/players"
    try:
        data = await _fetch_espn(url, espn_s2, swid, params={"view": "players_wl"})
    except Exception:
        _ESPN_PLAYER_MAP[key] = {}
        return
    player_map = {}
    for entry in (data if isinstance(data, list) else []):
        pid = entry.get("id")
        pool = entry.get("playerPoolEntry", {})
        profile = pool.get("playerProfile", pool.get("player", {}))
        pos_id = profile.get("defaultPositionId") or pool.get("defaultPositionId")
        if pid:
            player_map[int(pid)] = {
                "name": profile.get("fullName", profile.get("name", "")),
                "position": _ESPN_POS.get(pos_id, ""),
            }
    _ESPN_PLAYER_MAP[key] = player_map


def _compute_tiers(players: list[dict]) -> list[dict]:
    """Assign tier numbers based on value drop-offs (>8% from previous player)."""
    if not players:
        return players
    tier = 1
    for i, p in enumerate(players):
        if i == 0:
            p["tier"] = tier
            continue
        prev_val = players[i - 1]["redraft_value"]
        curr_val = p["redraft_value"]
        if prev_val > 0 and (prev_val - curr_val) / prev_val > 0.08:
            tier += 1
        p["tier"] = tier
    return players


def _compute_vor(players: list[dict], num_teams: int) -> list[dict]:
    """Add vor (value over replacement) to each player."""
    replacement_n = {"QB": max(1, num_teams // 2), "RB": num_teams, "WR": num_teams, "TE": max(1, num_teams // 2), "K": num_teams, "DEF": num_teams}
    by_pos: dict[str, list[int]] = {}
    for p in players:
        by_pos.setdefault(p["position"], []).append(p["redraft_value"])
    replacement: dict[str, int] = {}
    for pos, vals in by_pos.items():
        n = replacement_n.get(pos, num_teams)
        replacement[pos] = vals[n - 1] if len(vals) >= n else (vals[-1] if vals else 0)
    for p in players:
        p["vor"] = p["redraft_value"] - replacement.get(p["position"], 0)
    return players


def _compute_auction_values(players: list[dict], budget: int, num_teams: int, rounds: int) -> list[dict]:
    """Add projected auction $ to each player by scaling redraft values."""
    # Total usable dollars above the $1-per-pick floor
    usable = max(1, (budget - rounds) * num_teams)
    total_val = sum(p["redraft_value"] for p in players) or 1
    for p in players:
        p["auction_value"] = max(1, round(p["redraft_value"] / total_val * usable))
    return players


@router.get("/state")
async def get_espn_draft_state(
    league_id: str = Query(...),
    espn_s2: str = Query(...),
    swid: str = Query(...),
    season: int = Query(2025),
    my_slot: int = Query(1),
    budget: int = Query(200),
):
    from cache_manager import get_cached_players

    url = f"{ESPN_BASE}/seasons/{season}/segments/0/leagues/{league_id}"
    data = await _fetch_espn(url, espn_s2, swid, params={"view": ["mDraftDetail", "mSettings", "mTeam"]})

    # Load ESPN player name map (once per session per league)
    await _load_espn_players(league_id, season, espn_s2, swid)
    espn_player_map = _ESPN_PLAYER_MAP.get((league_id, season), {})

    # --- Parse draft settings ---
    settings = data.get("settings", {})
    draft_settings = settings.get("draftSettings", {})
    num_teams = settings.get("size", 10)
    rounds = draft_settings.get("rounds", 15)
    pick_order = draft_settings.get("pickOrder", [])

    # --- Parse teams ---
    espn_teams = data.get("teams", [])
    team_map: dict[int, str] = {}
    for t in espn_teams:
        tid = t.get("id")
        name = f"{t.get('location', '')} {t.get('nickname', '')}".strip() or f"Team {tid}"
        team_map[tid] = name

    slot_to_team: dict[int, str] = {
        i + 1: team_map.get(tid, f"Team {tid}")
        for i, tid in enumerate(pick_order)
    }

    my_team_id = pick_order[my_slot - 1] if my_slot <= len(pick_order) else None

    # --- Parse picks ---
    draft_detail = data.get("draftDetail", {})
    in_progress = draft_detail.get("inProgress", False)
    drafted = draft_detail.get("drafted", False)
    raw_picks = draft_detail.get("picks", [])

    picks_made = len(raw_picks)
    total_picks = num_teams * rounds

    if drafted and not in_progress:
        status = "complete"
    elif picks_made > 0 or in_progress:
        status = "drafting"
    else:
        status = "pre_draft"

    team_budget_spent: dict[int, int] = {}
    team_picks: dict[int, list] = {t.get("id"): [] for t in espn_teams}

    enriched_picks = []
    taken_espn_ids: set[int] = set()
    for pk in raw_picks:
        eid = int(pk.get("playerId", 0))
        if eid:
            taken_espn_ids.add(eid)
        ep = espn_player_map.get(eid, {})
        team_id = pk.get("teamId")
        bid_amount = pk.get("bidAmount", 0)

        if team_id:
            team_budget_spent[team_id] = team_budget_spent.get(team_id, 0) + bid_amount

        enriched_pick = {
            "overall": pk.get("overallPickNumber"),
            "round": pk.get("roundId"),
            "pick": pk.get("roundPickNumber"),
            "team_id": team_id,
            "team_name": team_map.get(team_id, f"Team {team_id}"),
            "player_name": ep.get("name", f"Player {eid}"),
            "position": ep.get("position", ""),
            "espn_id": eid,
            "bid_amount": bid_amount,
        }
        enriched_picks.append(enriched_pick)
        if team_id:
            team_picks.setdefault(team_id, []).append(enriched_pick)

    # --- My budget calculation ---
    my_budget_spent = team_budget_spent.get(my_team_id, 0) if my_team_id else 0
    my_budget_remaining = budget - my_budget_spent
    my_picks_count = len(team_picks.get(my_team_id, [])) if my_team_id else 0
    my_slots_remaining = max(0, rounds - my_picks_count)
    max_bid = max(1, my_budget_remaining - max(0, my_slots_remaining - 1))

    # --- Skill position available players from our cache ---
    players_cache = get_cached_players()

    taken_names: set[str] = {_normalize(pk["player_name"]) for pk in enriched_picks if pk["player_name"]}

    available_raw = [
        p for p in players_cache.values()
        if p.get("redraft_value", 0) > 0
        and _normalize(p["name"]) not in taken_names
    ]
    available_raw.sort(key=lambda x: x.get("redraft_value", 0), reverse=True)
    available_raw = available_raw[:300]

    available = [
        {
            "sleeper_id": p["sleeper_id"],
            "name": p["name"],
            "position": p["position"],
            "nfl_team": p.get("nfl_team", ""),
            "age": p.get("age"),
            "redraft_value": p.get("redraft_value", 0),
            "redraft_overall_rank": p.get("redraft_overall_rank"),
            "redraft_pos_rank": p.get("redraft_pos_rank"),
            "tier": 0,
            "vor": 0,
            "auction_value": 0,
        }
        for p in available_raw
    ]
    available = _compute_tiers(available)
    available = _compute_vor(available, num_teams)
    available = _compute_auction_values(available, budget, num_teams, rounds)

    # --- IDP available players from ESPN's player map ---
    idp_available = sorted(
        [
            {
                "espn_id": eid,
                "name": ep["name"],
                "position": ep["position"],
                "nfl_team": "",
                "tier": None,
                "vor": None,
                "auction_value": None,
                "redraft_value": None,
                "redraft_pos_rank": None,
            }
            for eid, ep in espn_player_map.items()
            if ep.get("position") in IDP_POSITIONS
            and eid not in taken_espn_ids
            and ep.get("name")
        ],
        key=lambda x: x["name"],
    )

    # --- Per-team summary ---
    teams_out = []
    for i, team_id in enumerate(pick_order):
        slot = i + 1
        spent = team_budget_spent.get(team_id, 0)
        teams_out.append({
            "slot": slot,
            "team_name": slot_to_team.get(slot, f"Team {slot}"),
            "is_me": team_id == my_team_id,
            "budget_spent": spent,
            "budget_remaining": budget - spent,
            "players": team_picks.get(team_id, []),
        })

    return {
        "status": status,
        "picks_made": picks_made,
        "total_picks": total_picks,
        "num_teams": num_teams,
        "rounds": rounds,
        "budget": budget,
        "my_budget_spent": my_budget_spent,
        "my_budget_remaining": my_budget_remaining,
        "my_slots_remaining": my_slots_remaining,
        "max_bid": max_bid,
        "recent_picks": list(reversed(enriched_picks[-10:])),
        "available": available,
        "idp_available": idp_available,
        "teams": teams_out,
    }
