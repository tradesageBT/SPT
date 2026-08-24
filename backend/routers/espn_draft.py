"""
ESPN Fantasy Football auction draft assistant.
Proxies to ESPN's unofficial API using the user's session cookies.
"""
import re
import json
import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/espn-draft")

ESPN_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"   # league-specific endpoints
ESPN_PLAYERS_BASE = "https://fantasy.espn.com/apis/v3/games/ffl"          # global player pool
ESPN_TIMEOUT = 15.0

# Global ESPN ID → {name, position} map built from Sleeper (loaded once per process)
_SLEEPER_ESPN_MAP: dict[int, dict] = {}
_SLEEPER_ESPN_MAP_LOADED: bool = False
_SLEEPER_ESPN_MAP_ERROR: str = ""

# Per-process cache: (league_id, season) -> {espn_id: {name, position}}
_ESPN_PLAYER_MAP: dict[tuple, dict] = {}
_ESPN_PLAYER_MAP_ERROR: dict[tuple, str] = {}

# ESPN position ID → our position label (skill + kicker/dst + IDP)
_ESPN_POS = {
    1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF",
    9: "DL", 10: "LB", 11: "DB", 12: "DB",
}

IDP_POSITIONS = {"DL", "LB", "DB"}

# ESPN lineup slot ID → position (for roster config parsing)
_ESPN_SLOT_TO_POS = {
    0: "QB", 2: "RB", 4: "WR", 6: "TE",
    17: "FLEX",   # RB/WR/TE flex
    23: "WTTE",   # WR/TE flex
    24: "SFLEX",  # Offensive Player / Superflex (QB eligible)
    5: "K", 16: "DEF",
    9: "DL", 10: "LB", 11: "DB",
}
_BENCH_SLOTS = {20, 21}  # bench and IR — excluded from starting slot counts


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
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://fantasy.espn.com/",
        "X-Fantasy-Source": "kona",
        "X-Fantasy-Platform": "kona-PROD-a9859dc50a6834b09fd4443e08103dcd4a4c08ad",
    }


async def _fetch_espn(url: str, espn_s2: str, swid: str, params: dict | None = None, extra_headers: dict | None = None) -> dict:
    headers = {**_espn_headers(espn_s2, swid), **(extra_headers or {})}
    async with httpx.AsyncClient(timeout=ESPN_TIMEOUT, verify=False, follow_redirects=False) as client:
        r = await client.get(url, headers=headers, params=params)
    if r.status_code in (301, 302, 303, 307, 308):
        location = r.headers.get("location", "unknown")
        raise HTTPException(status_code=401, detail=f"ESPN redirected ({r.status_code}) → {location}")
    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="ESPN credentials invalid or expired. Re-enter your espn_s2 and SWID cookies.")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="ESPN league not found. Check your league ID and season year.")
    r.raise_for_status()
    return r.json()


async def _load_sleeper_espn_map():
    """Build ESPN-ID → {name, position} from Sleeper's player list (includes espn_id for each player)."""
    global _SLEEPER_ESPN_MAP, _SLEEPER_ESPN_MAP_LOADED, _SLEEPER_ESPN_MAP_ERROR
    if _SLEEPER_ESPN_MAP_LOADED:
        return
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get("https://api.sleeper.app/v1/players/nfl")
        r.raise_for_status()
        sleeper_data = r.json()
        result: dict[int, dict] = {}
        for _sid, player in sleeper_data.items():
            espn_id = player.get("espn_id")
            if not espn_id:
                continue
            first = player.get("first_name") or ""
            last = player.get("last_name") or ""
            name = f"{first} {last}".strip()
            pos = player.get("position") or ""
            if name:
                result[int(espn_id)] = {"name": name, "position": pos}
        _SLEEPER_ESPN_MAP = result
        _SLEEPER_ESPN_MAP_LOADED = True
        _SLEEPER_ESPN_MAP_ERROR = ""
    except Exception as e:
        _SLEEPER_ESPN_MAP_ERROR = str(e)


async def _load_espn_players(league_id: str, season: int, espn_s2: str, swid: str):
    """Fetch ESPN's player list once and cache it for this league+season."""
    key = (league_id, season)
    # Only skip if we have actual data; retry if previous attempt errored
    if key in _ESPN_PLAYER_MAP and key not in _ESPN_PLAYER_MAP_ERROR:
        return

    player_map = {}
    last_err = None

    async def _player_fetch(url: str, params: dict, extra_headers: dict | None = None) -> list:
        """Fetch with follow_redirects=True since player endpoints may CDN-redirect."""
        hdrs = {**_espn_headers(espn_s2, swid), **(extra_headers or {})}
        async with httpx.AsyncClient(timeout=ESPN_TIMEOUT, verify=False, follow_redirects=True) as client:
            r = await client.get(url, headers=hdrs, params=params)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("players") or data.get("items") or []
        return []

    def _parse_player_entries(entries: list):
        for entry in entries:
            pid = entry.get("id")
            pool = entry.get("playerPoolEntry") or {}
            profile = pool.get("player") or pool.get("playerProfile") or {}
            pos_id = profile.get("defaultPositionId") or pool.get("defaultPositionId")
            name = profile.get("fullName") or profile.get("name", "")
            if pid and name:
                player_map[int(pid)] = {"name": name, "position": _ESPN_POS.get(pos_id, "")}

    # Try 1: kona_player_info with X-Fantasy-Filter (follow redirects for CDN)
    _kona_filter = '{"players":{"filterStatus":{"value":["FREEAGENT","WAIVERS","ONTEAM"]},"limit":2000,"offset":0}}'
    try:
        url = f"{ESPN_BASE}/seasons/{season}/segments/0/leagues/{league_id}"
        entries = await _player_fetch(url, {"view": "kona_player_info"}, {"X-Fantasy-Filter": _kona_filter})
        _parse_player_entries(entries)
        if player_map:
            _ESPN_PLAYER_MAP[key] = player_map
            _ESPN_PLAYER_MAP_ERROR.pop(key, None)
            return
        last_err = f"kona_player_info: 0 players returned"
    except Exception as e:
        last_err = f"kona_player_info: {e}"

    # Try 2: players_wl on lm-api-reads with follow_redirects
    try:
        url = f"{ESPN_BASE}/seasons/{season}/players"
        entries = await _player_fetch(url, {"view": "players_wl", "scoringPeriodId": 0})
        _parse_player_entries(entries)
        if player_map:
            _ESPN_PLAYER_MAP[key] = player_map
            _ESPN_PLAYER_MAP_ERROR.pop(key, None)
            return
        last_err = f"{last_err} | players_wl lm-api-reads: 0 players"
    except Exception as e:
        last_err = f"{last_err} | players_wl lm-api-reads: {e}"

    # Try 3: players_wl on original fantasy.espn.com with follow_redirects
    try:
        url = f"{ESPN_PLAYERS_BASE}/seasons/{season}/players"
        entries = await _player_fetch(url, {"view": "players_wl", "scoringPeriodId": 0})
        _parse_player_entries(entries)
        if player_map:
            _ESPN_PLAYER_MAP[key] = player_map
            _ESPN_PLAYER_MAP_ERROR.pop(key, None)
            return
        last_err = f"{last_err} | players_wl fantasy.espn.com: 0 players"
    except Exception as e:
        last_err = f"{last_err} | players_wl fantasy.espn.com: {e}"

    # All attempts failed
    _ESPN_PLAYER_MAP[key] = {}
    _ESPN_PLAYER_MAP_ERROR[key] = last_err or "Unknown error loading ESPN player list"


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


_last_replacement_n: dict = {}  # debug: expose computed replacement levels

def _compute_vor(players: list[dict], num_teams: int, roster_slots: dict | None = None) -> list[dict]:
    """Add vor (value over replacement) using actual starting slots per position."""
    rs = roster_slots or {}
    qb = rs.get("QB", 1)
    rb = rs.get("RB", 2)
    wr = rs.get("WR", 2)
    te = rs.get("TE", 1)
    flex = rs.get("FLEX", 0)    # RB/WR/TE flex
    wtte = rs.get("WTTE", 0)    # WR/TE flex
    sf = rs.get("SFLEX", 0)     # superflex / OP (QB eligible)
    k = rs.get("K", 1)
    dfn = rs.get("DEF", 1)

    # Estimate effective starters per position across the league
    # SFLEX mostly goes to QB (85%), remainder splits among skill positions
    replacement_n = {
        "QB":  max(1, round(num_teams * (qb + sf * 0.85))),
        "RB":  max(1, round(num_teams * (rb + flex * 0.40 + sf * 0.06))),
        "WR":  max(1, round(num_teams * (wr + flex * 0.40 + wtte * 0.55 + sf * 0.06))),
        "TE":  max(1, round(num_teams * (te + flex * 0.20 + wtte * 0.45 + sf * 0.03))),
        "K":   max(1, round(num_teams * k)),
        "DEF": max(1, round(num_teams * dfn)),
    }
    _last_replacement_n.clear()
    _last_replacement_n.update(replacement_n)

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
    import asyncio as _asyncio

    # Fetch main data + standalone mRoster in parallel (standalone returns full playerPoolEntry)
    data, roster_data = await _asyncio.gather(
        _fetch_espn(url, espn_s2, swid, params={"view": ["mDraftDetail", "mSettings", "mTeam", "mMembers"]}),
        _fetch_espn(url, espn_s2, swid, params={"view": "mRoster"}),
    )

    # Load Sleeper ESPN-ID map (global, once per process) in parallel with ESPN fallback
    await _asyncio.gather(
        _load_sleeper_espn_map(),
        _load_espn_players(league_id, season, espn_s2, swid),
    )

    # Build player map: Sleeper first, ESPN-specific map on top
    espn_player_map: dict[int, dict] = {**_SLEEPER_ESPN_MAP}
    espn_player_map.update(_ESPN_PLAYER_MAP.get((league_id, season), {}))

    # Add names from standalone mRoster response (full playerPoolEntry returned when fetched alone)
    def _extract_roster_names(response: dict):
        for team in response.get("teams", []):
            for entry in (team.get("roster") or {}).get("entries", []):
                pid = entry.get("playerId")
                pool = entry.get("playerPoolEntry") or {}
                player = pool.get("player") or {}
                name = player.get("fullName") or player.get("name", "")
                pos_id = player.get("defaultPositionId") or pool.get("defaultPositionId")
                if pid and name:
                    espn_player_map[int(pid)] = {"name": name, "position": _ESPN_POS.get(pos_id, "")}

    _extract_roster_names(roster_data)
    # Also try the main data's roster entries as additional fallback
    _extract_roster_names(data)

    # --- Parse draft settings ---
    settings = data.get("settings", {})
    draft_settings = settings.get("draftSettings", {})
    rounds = draft_settings.get("rounds", 15)
    pick_order = draft_settings.get("pickOrder", [])
    num_teams = len(pick_order) if pick_order else settings.get("size", 10)

    # --- Parse roster slot config (starting slots only, no bench/IR) ---
    lineup_counts = settings.get("rosterSettings", {}).get("lineupSlotCounts", {})
    roster_slots: dict[str, int] = {}
    for sid_str, cnt in lineup_counts.items():
        sid = int(sid_str)
        if sid in _BENCH_SLOTS or not cnt:
            continue
        pos = _ESPN_SLOT_TO_POS.get(sid)
        if pos:
            roster_slots[pos] = roster_slots.get(pos, 0) + cnt

    # --- Parse members (owners) ---
    member_map: dict[str, str] = {}
    for m in data.get("members", []):
        mid = m.get("id", "")
        display = m.get("displayName") or f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
        if mid and display:
            member_map[mid] = display

    # --- Parse teams ---
    espn_teams = data.get("teams", [])
    team_map: dict[int, str] = {}
    for t in espn_teams:
        tid = t.get("id")
        name = f"{t.get('location', '')} {t.get('nickname', '')}".strip()
        if not name:
            owner_id = t.get("primaryOwner", "")
            name = member_map.get(owner_id, "") or f"Team {tid}"
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
    all_picks = draft_detail.get("picks", [])

    # In ESPN auction drafts, nominations in-progress have playerId/teamId = -1.
    # Filter these out — they're not completed picks.
    raw_picks = [pk for pk in all_picks if pk.get("playerId", -1) > 0 and pk.get("teamId", -1) > 0]

    # Fetch names for any pick IDs not yet in our map (targeted kona_player_info with filterIds)
    missing_ids = [int(pk["playerId"]) for pk in raw_picks if int(pk.get("playerId", 0)) not in espn_player_map]
    if missing_ids:
        try:
            _filter = json.dumps({"players": {"filterIds": {"value": missing_ids[:200]}, "limit": 200}})
            targeted = await _fetch_espn(url, espn_s2, swid,
                                         params={"view": "kona_player_info"},
                                         extra_headers={"X-Fantasy-Filter": _filter})
            for entry in (targeted.get("players") or []):
                pid = entry.get("id")
                pool = entry.get("playerPoolEntry") or {}
                profile = pool.get("player") or pool.get("playerProfile") or {}
                name = profile.get("fullName") or profile.get("name", "")
                pos_id = profile.get("defaultPositionId") or pool.get("defaultPositionId")
                if pid and name:
                    espn_player_map[int(pid)] = {"name": name, "position": _ESPN_POS.get(pos_id, "")}
        except Exception:
            pass

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

        # Try to extract name/position from inline playerPoolEntry data on the pick
        pk_pool = pk.get("playerPoolEntry", {})
        pk_player = pk_pool.get("player", pk_pool.get("playerProfile", {}))
        inline_name = pk_player.get("fullName", "") or pk_player.get("name", "")
        inline_pos_id = pk_player.get("defaultPositionId") or pk_pool.get("defaultPositionId")

        player_name = ep.get("name") or inline_name or f"Player {eid}"
        position = ep.get("position") or _ESPN_POS.get(inline_pos_id, "")

        is_keeper = bool(pk.get("isKeeper") or pk.get("keeper") or pk.get("reservedForKeeper"))

        enriched_pick = {
            "overall": pk.get("overallPickNumber"),
            "round": pk.get("roundId"),
            "pick": pk.get("roundPickNumber"),
            "team_id": team_id,
            "team_name": team_map.get(team_id, f"Team {team_id}"),
            "player_name": player_name,
            "position": position,
            "espn_id": eid,
            "bid_amount": bid_amount,
            "is_keeper": is_keeper,
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
    available = _compute_vor(available, num_teams, roster_slots)
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
        picks_for_team = team_picks.get(team_id, [])
        spent = team_budget_spent.get(team_id, 0)
        remaining = budget - spent
        slots_rem = max(0, rounds - len(picks_for_team))
        t_max_bid = max(1, remaining - max(0, slots_rem - 1))

        pos_counts: dict[str, int] = {}
        for pk in picks_for_team:
            pos = pk.get("position", "")
            if pos:
                pos_counts[pos] = pos_counts.get(pos, 0) + 1

        teams_out.append({
            "slot": slot,
            "team_name": slot_to_team.get(slot, f"Team {slot}"),
            "is_me": team_id == my_team_id,
            "budget_spent": spent,
            "budget_remaining": remaining,
            "slots_remaining": slots_rem,
            "max_bid": t_max_bid,
            "pos_counts": pos_counts,
            "players": picks_for_team,
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
        "roster_slots": roster_slots,
        "debug_replacement_n": dict(_last_replacement_n),
        "debug_player_map_size": len(espn_player_map),
        "debug_sleeper_map_size": len(_SLEEPER_ESPN_MAP),
        "debug_sleeper_error": _SLEEPER_ESPN_MAP_ERROR or None,
        "debug_sample_picks": [
            {"espn_id": pk.get("playerId"), "resolved": espn_player_map.get(int(pk.get("playerId") or 0), {}).get("name", "NOT_FOUND")}
            for pk in raw_picks[:5]
        ],
        "idp_available": idp_available,
        "idp_load_error": _ESPN_PLAYER_MAP_ERROR.get((league_id, season)) or _SLEEPER_ESPN_MAP_ERROR or None,
        "teams": teams_out,
    }


@router.get("/players/search")
async def search_redraft_players(q: str = Query(""), limit: int = Query(20), mode: str = Query("redraft")):
    """Search player cache by name — used by the trade evaluator. mode=redraft|dynasty."""
    from cache_manager import get_cached_players
    players = get_cached_players()
    q_norm = _normalize(q)
    is_dynasty = mode == "dynasty"
    results = []
    for p in players.values():
        redraft_val = p.get("redraft_value", 0) or 0
        dynasty_val = p.get("fc_value", 0) or 0
        primary_val = dynasty_val if is_dynasty else redraft_val
        if not primary_val:
            continue
        if q_norm and q_norm not in _normalize(p["name"]):
            continue
        results.append({
            "sleeper_id": p["sleeper_id"],
            "name": p["name"],
            "position": p["position"],
            "nfl_team": p.get("nfl_team", ""),
            "redraft_value": redraft_val,
            "fc_value": dynasty_val,
            "overall_rank": p.get("overall_rank") if is_dynasty else p.get("redraft_overall_rank"),
            "pos_rank": p.get("pos_rank") if is_dynasty else p.get("redraft_pos_rank"),
            "redraft_pos_rank": p.get("redraft_pos_rank"),
        })
    results.sort(key=lambda x: x["fc_value"] if is_dynasty else x["redraft_value"], reverse=True)
    return results[:limit]
