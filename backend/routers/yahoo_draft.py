"""
Yahoo Fantasy Sports draft assistant.

Endpoints:
  GET    /api/yahoo-draft/auth      → redirect to Yahoo OAuth
  GET    /api/yahoo-draft/callback  → exchange code, store tokens, redirect to /yahoo-draft
  GET    /api/yahoo-draft/status    → {"connected": bool}
  DELETE /api/yahoo-draft/auth      → clear tokens (disconnect)
  GET    /api/yahoo-draft/leagues   → user's NFL fantasy leagues
  GET    /api/yahoo-draft/state?league_key=449.l.X → live draft state

Multi-user: each browser gets a UUID session stored in an 'ysid' cookie.
Tokens are keyed by session_id so multiple people can use simultaneously.
"""
import os
import re
import uuid
import asyncio
import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse

from database import db

router = APIRouter(prefix="/api/yahoo-draft")

YAHOO_CLIENT_ID     = os.getenv("YAHOO_CLIENT_ID", "")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET", "")
YAHOO_REDIRECT_URI  = os.getenv(
    "YAHOO_REDIRECT_URI",
    "https://spt-4g5a.onrender.com/api/yahoo-draft/callback",
)
YAHOO_AUTH_URL  = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_API_BASE  = "https://fantasysports.yahooapis.com/fantasy/v2"
YAHOO_TIMEOUT   = 15.0

_norm_re = re.compile(r"[^a-z]")


def _normalize(s: str) -> str:
    s = s.lower()
    for sfx in (" jr", " sr", " ii", " iii", " iv"):
        s = s.replace(sfx, "")
    return _norm_re.sub("", s)


# ── Token storage (keyed by session_id) ───────────────────────────────────────

def _store_tokens(session_id: str, access: str, refresh: str, expires_in: int = 3600):
    exp = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO yahoo_tokens (session_id, access_token, refresh_token, expires_at)
            VALUES (:sid, :a, :r, :e)
            ON CONFLICT(session_id) DO UPDATE SET
                access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,
                expires_at=excluded.expires_at
            """,
            {"sid": session_id, "a": access, "r": refresh, "e": exp},
        )


def _get_tokens(session_id: str) -> dict | None:
    with db() as conn:
        return conn.execute(
            "SELECT * FROM yahoo_tokens WHERE session_id = :sid",
            {"sid": session_id},
        ).fetchone()


def _clear_tokens(session_id: str):
    with db() as conn:
        conn.execute("DELETE FROM yahoo_tokens WHERE session_id = :sid", {"sid": session_id})


def _is_expired(row: dict) -> bool:
    try:
        exp = datetime.fromisoformat(row["expires_at"])
        return datetime.now(timezone.utc) >= exp - timedelta(seconds=60)
    except Exception:
        return True


def _session_id(request: Request) -> str | None:
    return request.cookies.get("ysid")


def _set_session_cookie(response, session_id: str):
    response.set_cookie(
        "ysid", session_id,
        max_age=86400 * 30,
        httponly=True,
        samesite="lax",
    )


# ── OAuth helpers ─────────────────────────────────────────────────────────────

def _basic_auth() -> str:
    return "Basic " + base64.b64encode(
        f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}".encode()
    ).decode()


async def _do_refresh(session_id: str, refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=YAHOO_TIMEOUT) as client:
        r = await client.post(
            YAHOO_TOKEN_URL,
            headers={
                "Authorization": _basic_auth(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Yahoo token expired. Please reconnect.")
    data = r.json()
    _store_tokens(session_id, data["access_token"], data.get("refresh_token", refresh_token), data.get("expires_in", 3600))
    return data


async def _access_token(session_id: str) -> str:
    row = _get_tokens(session_id)
    if not row:
        raise HTTPException(status_code=401, detail="Not connected to Yahoo. Please connect first.")
    if _is_expired(row):
        data = await _do_refresh(session_id, row["refresh_token"])
        return data["access_token"]
    return row["access_token"]


# ── Yahoo API helper ──────────────────────────────────────────────────────────

async def _yahoo_get(path: str, session_id: str) -> dict:
    token = await _access_token(session_id)
    sep = "&" if "?" in path else "?"
    url = f"{YAHOO_API_BASE}/{path}{sep}format=json"

    async with httpx.AsyncClient(timeout=YAHOO_TIMEOUT) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"})

    if r.status_code == 401:
        # Auto-refresh once
        row = _get_tokens(session_id)
        if row:
            data = await _do_refresh(session_id, row["refresh_token"])
            async with httpx.AsyncClient(timeout=YAHOO_TIMEOUT) as client:
                r = await client.get(url, headers={"Authorization": f"Bearer {data['access_token']}"})

    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Yahoo league not found. Check your league key.")
    if not r.is_success:
        raise HTTPException(status_code=r.status_code, detail=f"Yahoo API error: {r.text[:300]}")
    return r.json()


# ── Yahoo JSON parsing helpers ────────────────────────────────────────────────

def _flat(obj) -> dict:
    """Flatten Yahoo's nested list-of-dicts attr format into a plain dict."""
    out: dict = {}
    if isinstance(obj, dict):
        out.update(obj)
    elif isinstance(obj, list):
        for item in obj:
            out.update(_flat(item))
    return out


def _iter_collection(block: dict) -> list:
    """Iterate a Yahoo numbered collection {0: x, 1: y, ..., count: N}."""
    try:
        count = int(block.get("count", 0))
    except (TypeError, ValueError):
        count = 0
    return [block[str(i)] for i in range(count) if str(i) in block]


def _parse_player_attrs(player_list) -> dict:
    """Parse the first element of a Yahoo player array into a flat dict."""
    if not player_list or not isinstance(player_list, list):
        return {}
    attrs = _flat(player_list[0])
    name_d = attrs.get("name", {})
    full_name = name_d.get("full", "") if isinstance(name_d, dict) else str(name_d)
    return {
        "player_key": attrs.get("player_key", ""),
        "yahoo_id": str(attrs.get("player_id", "")),
        "name": full_name,
        "position": attrs.get("display_position", ""),
        "nfl_team": attrs.get("editorial_team_abbr", ""),
    }


# ── OAuth endpoints ───────────────────────────────────────────────────────────

@router.get("/auth")
async def yahoo_auth(request: Request):
    if not YAHOO_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Yahoo OAuth not configured. Add YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET in Render environment variables.",
        )
    # Reuse existing session or mint a new one
    sid = _session_id(request) or str(uuid.uuid4())
    params = urlencode({
        "client_id": YAHOO_CLIENT_ID,
        "redirect_uri": YAHOO_REDIRECT_URI,
        "response_type": "code",
        "language": "en-us",
        "state": sid,
    })
    response = RedirectResponse(f"{YAHOO_AUTH_URL}?{params}")
    _set_session_cookie(response, sid)
    return response


@router.get("/callback")
async def yahoo_callback(code: str = Query(...), state: str = Query("")):
    if not YAHOO_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Yahoo OAuth not configured.")
    sid = state or str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=YAHOO_TIMEOUT) as client:
        r = await client.post(
            YAHOO_TOKEN_URL,
            headers={
                "Authorization": _basic_auth(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": YAHOO_REDIRECT_URI,
            },
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail=f"Yahoo OAuth failed: {r.text[:300]}")
    data = r.json()
    _store_tokens(sid, data["access_token"], data["refresh_token"], data.get("expires_in", 3600))
    response = RedirectResponse("/yahoo-draft?connected=true")
    _set_session_cookie(response, sid)
    return response


@router.get("/status")
async def yahoo_status(request: Request):
    sid = _session_id(request)
    configured = bool(YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET)
    if not sid:
        return {"connected": False, "configured": configured}
    row = _get_tokens(sid)
    return {"connected": bool(row), "configured": configured}


@router.delete("/auth")
async def yahoo_disconnect(request: Request):
    sid = _session_id(request)
    if sid:
        _clear_tokens(sid)
    response = JSONResponse({"disconnected": True})
    response.delete_cookie("ysid")
    return response


# ── Leagues ───────────────────────────────────────────────────────────────────

@router.get("/leagues")
async def get_leagues(request: Request):
    sid = _session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Not connected to Yahoo.")
    data = await _yahoo_get("users;use_login=1/games;game_codes=nfl/leagues", sid)
    leagues_out = []
    try:
        fc = data["fantasy_content"]
        user_block = fc.get("users", {}).get("0", {}).get("user", [{}])
        games_section = user_block[1] if len(user_block) > 1 else {}
        games = games_section.get("games", {})

        for game_item in _iter_collection(games):
            game_list = game_item.get("game", [{}])
            game_attrs = _flat(game_list[0]) if isinstance(game_list, list) else {}
            season = game_attrs.get("season", "")

            leagues_section = game_list[1] if len(game_list) > 1 else {}
            if not isinstance(leagues_section, dict):
                continue
            leagues_block = leagues_section.get("leagues", {})
            for league_item in _iter_collection(leagues_block):
                league_list = league_item.get("league", [{}])
                la = _flat(league_list)
                leagues_out.append({
                    "league_key": la.get("league_key", ""),
                    "name": la.get("name", ""),
                    "season": season,
                    "num_teams": la.get("num_teams", "?"),
                    "draft_status": la.get("draft_status", ""),
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Yahoo leagues: {e}")
    return leagues_out


# ── Draft state ───────────────────────────────────────────────────────────────

def _on_the_clock_key(picks_made: int, num_teams: int, draft_order: list[str]) -> str | None:
    if not draft_order or picks_made >= num_teams * len(draft_order):
        return None
    rnd = picks_made // num_teams
    pos = picks_made % num_teams
    slot = pos if rnd % 2 == 0 else (num_teams - 1 - pos)
    return draft_order[slot] if slot < len(draft_order) else None


def _vor(players: list, num_teams: int) -> list:
    from collections import defaultdict
    pos_vals: dict[str, list] = defaultdict(list)
    for p in players:
        v = p.get("redraft_value") or 0
        if v:
            pos_vals[p.get("position", "")].append(v)
    repl: dict[str, int] = {}
    for pos, vals in pos_vals.items():
        vals.sort(reverse=True)
        n = num_teams if pos in ("RB", "WR") else num_teams // 2
        repl[pos] = vals[n] if len(vals) > n else (vals[-1] if vals else 0)
    for p in players:
        v = p.get("redraft_value") or 0
        r = repl.get(p.get("position", ""), 0)
        p["vor"] = v - r
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
async def get_draft_state(request: Request, league_key: str = Query(...)):
    sid = _session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Not connected to Yahoo.")

    from cache_manager import get_cached_players

    # Parallel: settings, teams, draft results, and 6 pages of available players
    player_fetches = [
        _yahoo_get(f"league/{league_key}/players;status=A;sort=AR;start={i * 25};count=25", sid)
        for i in range(6)
    ]
    results = await asyncio.gather(
        _yahoo_get(f"league/{league_key}/settings", sid),
        _yahoo_get(f"league/{league_key}/teams", sid),
        _yahoo_get(f"league/{league_key}/draft_results;out=players", sid),
        *player_fetches,
        return_exceptions=True,
    )
    settings_raw, teams_raw, draft_raw = results[0], results[1], results[2]
    player_raws = results[3:]

    # ── Settings ──────────────────────────────────────────────────────────────
    is_auction = False
    num_teams = 12
    rounds = 15
    try:
        s = settings_raw["fantasy_content"]["league"][1]["settings"]
        is_auction = s.get("is_auction_draft", "0") == "1" or s.get("draft_type", "S") == "A"
        num_teams = int(s.get("num_teams", 12))
        rounds = int(s.get("max_teams", 15))
    except Exception:
        pass

    # ── Teams + draft order ───────────────────────────────────────────────────
    teams_out = []
    draft_order: list[str] = []
    try:
        teams_block = teams_raw["fantasy_content"]["league"][1]["teams"]
        slot_map: dict[int, str] = {}
        for item in _iter_collection(teams_block):
            tl = item.get("team", [])
            attrs = _flat(tl[0]) if tl else {}
            team_key = attrs.get("team_key", "")
            name = attrs.get("name", "")
            dpos = int(attrs.get("draft_position", 0) or 0)
            if dpos:
                slot_map[dpos] = team_key
            teams_out.append({"team_key": team_key, "name": name, "draft_position": dpos})
        if slot_map:
            draft_order = [slot_map.get(i, "") for i in range(1, max(slot_map) + 1)]
    except Exception:
        pass

    team_names = {t["team_key"]: t["name"] for t in teams_out}

    # ── Draft results ─────────────────────────────────────────────────────────
    picks_out = []
    player_map: dict[str, dict] = {}   # player_key → {name, position, nfl_team}
    try:
        league_data = draft_raw["fantasy_content"]["league"]
        dr_block = league_data[1]["draft_results"]
        for item in _iter_collection(dr_block):
            dr = item.get("draft_result", {})
            player_key = dr.get("player_key", "")
            pick_num = int(dr.get("pick", 0))
            round_num = int(dr.get("round", 0))
            team_key = dr.get("team_key", "")
            cost = int(dr.get("cost", 0) or 0)

            # Some endpoints include player info inline with ;out=players
            player_info = dr.get("players", {})
            if player_info:
                for pi in _iter_collection(player_info):
                    pattrs = _parse_player_attrs(pi.get("player", []))
                    if pattrs.get("player_key"):
                        player_map[pattrs["player_key"]] = pattrs

            picks_out.append({
                "pick": pick_num,
                "round": round_num,
                "team_key": team_key,
                "team_name": team_names.get(team_key, team_key),
                "player_key": player_key,
                "cost": cost,
            })
    except Exception:
        pass

    drafted_keys = {p["player_key"] for p in picks_out}

    # ── Available players ─────────────────────────────────────────────────────
    cache_by_name = {_normalize(p["name"]): p for p in get_cached_players().values()}
    available = []
    for page_raw in player_raws:
        if isinstance(page_raw, Exception):
            continue
        try:
            league_data = page_raw["fantasy_content"]["league"]
            players_block = league_data[1]["players"]
            for item in _iter_collection(players_block):
                pattrs = _parse_player_attrs(item.get("player", []))
                if not pattrs or pattrs["player_key"] in drafted_keys:
                    continue
                player_map[pattrs["player_key"]] = pattrs
                cached = cache_by_name.get(_normalize(pattrs["name"]), {})
                available.append({
                    **pattrs,
                    "redraft_value": cached.get("redraft_value") or 0,
                    "fc_value": cached.get("fc_value") or 0,
                    "redraft_pos_rank": cached.get("redraft_pos_rank"),
                    "tier": None,
                    "vor": None,
                })
        except Exception:
            continue

    available.sort(key=lambda x: x["redraft_value"] or 0, reverse=True)
    available = _vor(available, num_teams)
    available = _tiers(available)

    # Enrich picks with player names from map
    for pk in picks_out:
        info = player_map.get(pk["player_key"], {})
        pk["player_name"] = info.get("name", pk["player_key"])
        pk["position"] = info.get("position", "")
        pk["nfl_team"] = info.get("nfl_team", "")

    # ── On the clock ──────────────────────────────────────────────────────────
    picks_made = len(picks_out)
    otc_key = None if is_auction else _on_the_clock_key(picks_made, num_teams, draft_order)
    otc_name = team_names.get(otc_key, "") if otc_key else ""

    status = "complete" if picks_made >= num_teams * rounds else (
        "pre_draft" if picks_made == 0 else "drafting"
    )

    return {
        "status": status,
        "is_auction": is_auction,
        "picks_made": picks_made,
        "total_picks": num_teams * rounds,
        "num_teams": num_teams,
        "rounds": rounds,
        "on_the_clock_key": otc_key,
        "on_the_clock_name": otc_name,
        "teams": teams_out,
        "picks": picks_out[-25:],   # most recent 25
        "all_picks": picks_out,     # full history (for my-team filter)
        "available": available,
        "draft_order": draft_order,
    }
