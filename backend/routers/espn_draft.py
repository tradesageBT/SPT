"""
ESPN Fantasy Football draft assistant.
Proxies to ESPN's unofficial API using the user's session cookies.
"""
import re
import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/espn-draft")

ESPN_BASE = "https://fantasy.espn.com/apis/v3/games/ffl"
ESPN_TIMEOUT = 15.0

# Per-process cache: (league_id, season) -> {espn_id: {name, position, nfl_team}}
_ESPN_PLAYER_MAP: dict[tuple, dict] = {}

# ESPN position ID → our position label
_ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}

# Default roster slots for redraft — used to infer user roster needs
_DEFAULT_ROSTER_SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1}


def _normalize(name: str) -> str:
    name = name.lower()
    for suffix in (" jr", " sr", " ii", " iii", " iv"):
        name = name.replace(suffix, "")
    return re.sub(r"[^a-z]", "", name)


def _espn_headers(espn_s2: str, swid: str) -> dict:
    return {
        "Cookie": f"espn_s2={espn_s2}; SWID={swid}",
        "User-Agent": "Mozilla/5.0",
    }


async def _fetch_espn(url: str, espn_s2: str, swid: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=ESPN_TIMEOUT, verify=False) as client:
        r = await client.get(url, headers=_espn_headers(espn_s2, swid), params=params)
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


def _snake_slot(pick_num: int, num_teams: int) -> int:
    """Return 1-indexed draft slot for the given overall pick in a snake draft."""
    round_num = (pick_num - 1) // num_teams
    pick_in_round = (pick_num - 1) % num_teams
    if round_num % 2 == 0:
        return pick_in_round + 1
    else:
        return num_teams - pick_in_round


def _picks_until_my_turn(current_overall: int, my_slot: int, num_teams: int) -> int:
    """How many picks until the user is on the clock (0 = right now)."""
    pick = current_overall + 1
    for i in range(num_teams * 2 + 1):
        if _snake_slot(pick + i, num_teams) == my_slot:
            return i
    return -1


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


@router.get("/state")
async def get_espn_draft_state(
    league_id: str = Query(...),
    espn_s2: str = Query(...),
    swid: str = Query(...),
    season: int = Query(2025),
    my_slot: int = Query(1),
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
    pick_order = draft_settings.get("pickOrder", [])  # teamIds in slot order

    # --- Parse teams ---
    espn_teams = data.get("teams", [])
    team_map: dict[int, str] = {}
    for t in espn_teams:
        tid = t.get("id")
        name = f"{t.get('location', '')} {t.get('nickname', '')}".strip() or f"Team {tid}"
        team_map[tid] = name

    # slot -> team name (pick_order is teamIds in draft slot order)
    slot_to_team: dict[int, str] = {
        i + 1: team_map.get(tid, f"Team {tid}")
        for i, tid in enumerate(pick_order)
    }

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

    # Build set of picked ESPN player IDs
    picked_espn_ids: set[int] = {int(p.get("playerId", 0)) for p in raw_picks if p.get("playerId")}

    # Enrich picks with player info
    enriched_picks = []
    for pk in raw_picks:
        eid = int(pk.get("playerId", 0))
        ep = espn_player_map.get(eid, {})
        team_id = pk.get("teamId")
        slot_num = _snake_slot(pk["overallPickNumber"], num_teams) if num_teams else 1
        enriched_picks.append({
            "overall": pk.get("overallPickNumber"),
            "round": pk.get("roundId"),
            "pick": pk.get("roundPickNumber"),
            "team_name": team_map.get(team_id, f"Team {team_id}"),
            "player_name": ep.get("name", f"Player {eid}"),
            "position": ep.get("position", ""),
            "espn_id": eid,
        })

    # --- Available players from our cache ---
    players_cache = get_cached_players()

    # Build name → cache player lookup for matching picked players
    name_to_cache: dict[str, dict] = {}
    for p in players_cache.values():
        name_to_cache[_normalize(p["name"])] = p

    # Find which cache sleeper_ids are taken (by name match from ESPN picks)
    taken_names: set[str] = set()
    for pk in enriched_picks:
        n = _normalize(pk["player_name"])
        if n:
            taken_names.add(n)

    # Also directly exclude by ESPN player ID if we have a name match
    available_raw = [
        p for p in players_cache.values()
        if p.get("redraft_value", 0) > 0
        and _normalize(p["name"]) not in taken_names
    ]
    available_raw.sort(key=lambda x: x.get("redraft_value", 0), reverse=True)

    # Cap at 300 available players
    available_raw = available_raw[:300]

    # Compute tiers and VOR
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
        }
        for p in available_raw
    ]
    available = _compute_tiers(available)
    available = _compute_vor(available, num_teams)

    # --- On the clock ---
    next_pick = picks_made + 1
    otc_slot = _snake_slot(next_pick, num_teams) if num_teams and status == "drafting" else None
    otc_team = slot_to_team.get(otc_slot, "") if otc_slot else ""
    my_pick_next = (otc_slot == my_slot) if otc_slot else False
    picks_until = _picks_until_my_turn(picks_made, my_slot, num_teams) if status == "drafting" else -1

    # --- Per-team pick summary ---
    team_picks: dict[int, list] = {t.get("id"): [] for t in espn_teams}
    for pk in enriched_picks:
        slot_of_pick = _snake_slot(pk["overall"], num_teams) if num_teams else 1
        team_id_for_slot = pick_order[slot_of_pick - 1] if slot_of_pick <= len(pick_order) else None
        if team_id_for_slot:
            team_picks.setdefault(team_id_for_slot, []).append(pk)

    teams_out = []
    for i, team_id in enumerate(pick_order):
        slot = i + 1
        teams_out.append({
            "slot": slot,
            "team_name": slot_to_team.get(slot, f"Team {slot}"),
            "is_me": slot == my_slot,
            "players": team_picks.get(team_id, []),
        })

    return {
        "status": status,
        "picks_made": picks_made,
        "total_picks": total_picks,
        "num_teams": num_teams,
        "rounds": rounds,
        "on_the_clock_slot": otc_slot,
        "on_the_clock_team": otc_team,
        "my_pick_next": my_pick_next,
        "picks_until_my_turn": picks_until,
        "recent_picks": list(reversed(enriched_picks[-10:])),
        "available": available,
        "teams": teams_out,
    }
