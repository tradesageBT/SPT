"""
Manual auction draft tracker — platform agnostic.

You enter each purchase as it happens, so this works for Yahoo, ESPN, Sleeper,
or an in-person auction with no API access at all. The server computes auction
dollar values from FantasyCalc redraft values; live budget/inflation state is
held client-side so entry stays instant during a draft.

Values are fetched for the auction's OWN scoring (ppr + superflex) rather than
read from the shared players_cache, which is global and carries whatever scoring
the last league sync happened to write. Nothing here writes to that cache.

  GET /api/auction-draft/pool?teams=12&budget=200&ppr=1&qb=1&rb=2&wr=2&te=1&flex=1&...
"""
import json
import time
import random
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Query, HTTPException, Body

import fantasycalc_client
from database import db

router = APIRouter(prefix="/api/auction-draft")
log = logging.getLogger(__name__)

# Room codes are read aloud and typed on phones, so drop characters that get
# confused with each other (0/O, 1/I/L).
ROOM_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# How often each position actually fills a given flex slot type. Used to push
# replacement level deeper for the positions a flex slot competes for.
FLEX_SHARES = {
    "flex":        {"RB": 0.45, "WR": 0.45, "TE": 0.10},               # RB/WR/TE
    "sflex":       {"QB": 0.75, "WR": 0.12, "RB": 0.10, "TE": 0.03},   # QB/RB/WR/TE
    "wr_rb_flex":  {"RB": 0.50, "WR": 0.50},                           # WR/RB
    "rec_flex":    {"WR": 0.75, "TE": 0.25},                           # WR/TE
}

# A new tier starts when the drop from the previous player exceeds this
TIER_BREAK = 0.08


# ── Sleeper season stats + projections ────────────────────────────────────────
#
# Sleeper keys these on their own player_id and FantasyCalc gives us sleeperId,
# so this joins directly with no name matching. Cached in memory rather than in
# Postgres: it needs no migration and survives between requests on a warm
# process. It is lost on redeploy, and on a plan that spins down when idle it is
# also lost on cold start — in both cases it simply refetches.

SLEEPER_BASE = "https://api.sleeper.com"
STATS_TTL = 6 * 3600
# A failure (or an empty parse) is cached only briefly: caching it for the full
# TTL would blank stats for the rest of a draft off one transient timeout.
STATS_FAIL_TTL = 60

# Kept deliberately small — this is a glanceable panel, not a stat page.
STAT_KEYS = (
    "pts_ppr", "pts_half_ppr", "pts_std", "gp", "gms_active",
    "pass_yd", "pass_td", "pass_int",
    "rush_att", "rush_yd", "rush_td",
    "rec", "rec_tgt", "rec_yd", "rec_td",
)

_stats_cache: dict[str, tuple[float, dict]] = {}

# ── Injury / depth-chart metadata ─────────────────────────────────────────────
#
# Lives in Sleeper's /players/nfl, which is a ~10MB download taking 10-30s —
# cache_manager avoids it for exactly that reason. So it is loaded in the
# BACKGROUND and never blocks a pool request: the board returns immediately and
# the injury line appears once the fetch lands. Worst case it isn't there yet.

META_TTL = 6 * 3600
META_KEYS = (
    "injury_status", "injury_notes", "practice_participation",
    "depth_chart_order", "depth_chart_position", "status",
)

_meta: dict[str, dict] = {}
_meta_at = 0.0
_meta_loading = False


def _meta_fresh() -> bool:
    # Deliberately not `bool(_meta) and ...`: a failed load stamps _meta_at too,
    # so an outage backs off rather than refetching on every request.
    return _meta_at > 0 and (time.time() - _meta_at) < META_TTL


async def _load_meta():
    global _meta, _meta_at, _meta_loading
    if _meta_loading:
        return
    _meta_loading = True
    try:
        import sleeper_client
        data = await sleeper_client.get_all_players()
        out: dict[str, dict] = {}
        if isinstance(data, dict):
            for pid, p in data.items():
                if not isinstance(p, dict):
                    continue
                picked = {
                    k: p[k] for k in META_KEYS
                    if p.get(k) not in (None, "", [])
                }
                if picked:
                    out[str(pid)] = picked
        if out:
            _meta = out
            log.info("Loaded injury metadata for %d players", len(out))
    except Exception as e:
        log.warning("Sleeper player metadata failed (%s); continuing without", e)
    finally:
        # Stamped unconditionally: on failure this backs off for the TTL instead
        # of leaving _meta_fresh() false and refetching 10MB on every request.
        _meta_at = time.time()
        _meta_loading = False


def _current_season() -> int:
    """NFL season is named for the year it starts; roll over in March."""
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 3 else now.year - 1


def _normalize_sleeper(payload) -> dict:
    """
    Sleeper's shape isn't contractually guaranteed and differs between
    endpoints/seasons, so accept both a list of entries and a dict keyed by
    player_id, and tolerate stats being nested under "stats" or inlined.
    """
    entries = []
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        for pid, val in payload.items():
            if isinstance(val, dict):
                val = dict(val)
                val.setdefault("player_id", pid)
                entries.append(val)

    out: dict[str, dict] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        pid = e.get("player_id")
        if pid is None and isinstance(e.get("player"), dict):
            pid = e["player"].get("player_id")
        if pid is None:
            continue
        stats = e.get("stats") if isinstance(e.get("stats"), dict) else e
        picked = {k: stats[k] for k in STAT_KEYS if isinstance(stats.get(k), (int, float))}
        if picked:
            out[str(pid)] = picked
    return out


async def _sleeper_season(kind: str, season: int) -> dict:
    """kind: 'projections' or 'stats'. Returns {sleeper_id: {stat: value}}."""
    key = f"{kind}:{season}"
    hit = _stats_cache.get(key)
    if hit and (time.time() - hit[0]) < STATS_TTL:
        return hit[1]

    url = f"{SLEEPER_BASE}/{kind}/nfl/{season}?season_type=regular"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url)
        r.raise_for_status()
        data = _normalize_sleeper(r.json())
    except Exception as e:
        log.warning("Sleeper %s for %s failed (%s); continuing without", kind, season, e)
        data = {}

    # Successes hold for the full TTL; failures and empty parses expire fast so a
    # transient Sleeper blip doesn't cost the whole draft.
    ttl_marker = time.time() if data else (time.time() - STATS_TTL + STATS_FAIL_TTL)
    _stats_cache[key] = (ttl_marker, data)
    return data


def _league_points(stats: dict, ppr: float, pass_td_pts: float, rush_att_pts: float):
    """
    Sleeper's pts_* figures assume 4-point passing TDs and no per-carry bonus.
    Rather than recompute scoring from scratch (which would need fumbles and
    2pt conversions we don't pull), adjust its total by only the deltas that
    differ from that baseline.
    """
    if not stats:
        return None
    base_key = "pts_ppr" if ppr == 1 else "pts_half_ppr" if ppr == 0.5 else "pts_std"
    base = stats.get(base_key)
    if base is None:
        return None
    adj = base
    adj += (stats.get("pass_td") or 0) * (pass_td_pts - 4.0)
    adj += (stats.get("rush_att") or 0) * rush_att_pts
    return round(adj, 1)


def _norm_pos(pos: str) -> str:
    p = (pos or "").upper().strip()
    if p in ("DST", "D/ST", "DEFENSE"):
        return "DEF"
    if p == "PK":
        return "K"
    return p


async def _load_values(num_qbs: int, ppr: float) -> list[dict]:
    """
    Redraft values for this auction's scoring, straight from FantasyCalc.

    Deliberately does NOT touch players_cache: that table is global and shared
    with league syncs, so writing this auction's scoring into it would clobber
    the values every other league is computed from.
    """
    try:
        entries = await fantasycalc_client.get_values(
            num_qbs=num_qbs, ppr=ppr, is_dynasty=False
        )
        out = []
        for entry in entries:
            player = entry.get("player", {})
            sid = str(player.get("sleeperId") or "")
            pos = _norm_pos(player.get("position", ""))
            if not sid or pos not in POSITIONS:
                continue
            out.append({
                "sleeper_id": sid,
                "name": player.get("name", ""),
                "position": pos,
                "nfl_team": player.get("nflTeamAbbr", ""),
                "age": player.get("age"),
                "value": entry.get("value", 0) or 0,
            })
        if out:
            return out
        log.warning("FantasyCalc returned no usable players; falling back to cache")
    except Exception as e:
        log.warning("FantasyCalc fetch failed (%s); falling back to cache", e)

    # Fallback so the tool still opens if FantasyCalc is down mid-draft.
    from cache_manager import get_cached_players
    out = []
    for p in get_cached_players().values():
        val = p.get("redraft_value") or 0
        pos = _norm_pos(p.get("position"))
        if not val or pos not in POSITIONS:
            continue
        out.append({
            "sleeper_id": p["sleeper_id"],
            "name": p["name"],
            "position": pos,
            "nfl_team": p.get("nfl_team", ""),
            "age": p.get("age"),
            "value": val,
        })
    return out


@router.get("/pool")
async def get_auction_pool(
    teams: int = Query(12, ge=2, le=32),
    budget: int = Query(200, ge=10, le=1000),
    ppr: float = Query(1.0, ge=0, le=2),
    qb: int = Query(1, ge=0, le=5),
    rb: int = Query(2, ge=0, le=10),
    wr: int = Query(2, ge=0, le=10),
    te: int = Query(1, ge=0, le=5),
    flex: int = Query(1, ge=0, le=5),
    sflex: int = Query(0, ge=0, le=3),
    wr_rb_flex: int = Query(0, ge=0, le=5),
    rec_flex: int = Query(0, ge=0, le=5),
    k: int = Query(1, ge=0, le=3),
    dst: int = Query(1, ge=0, le=3),
    bench: int = Query(7, ge=0, le=20),
    pass_td_pts: float = Query(4.0, ge=0, le=12),
    rush_att_pts: float = Query(0.0, ge=0, le=2),
):
    """Player pool with auction dollar values derived from value over replacement."""
    starters = {"QB": qb, "RB": rb, "WR": wr, "TE": te, "K": k, "DEF": dst}
    flex_counts = {"flex": flex, "sflex": sflex, "wr_rb_flex": wr_rb_flex, "rec_flex": rec_flex}
    roster_size = sum(starters.values()) + sum(flex_counts.values()) + bench

    # A superflex slot means QBs are valued as in a 2QB league
    num_qbs = qb + sflex

    # Values and Sleeper stats are independent, so fetch them together.
    # return_exceptions keeps a Sleeper outage from failing the whole pool.
    season = _current_season()
    players, proj, last = await asyncio.gather(
        _load_values(num_qbs, ppr),
        _sleeper_season("projections", season),
        _sleeper_season("stats", season - 1),
        return_exceptions=True,
    )
    if isinstance(players, Exception):
        raise HTTPException(status_code=502, detail=f"Could not load player values: {players}")
    if isinstance(proj, Exception):
        proj = {}
    if isinstance(last, Exception):
        last = {}

    # ── Group by position ─────────────────────────────────────────────────────
    by_pos: dict[str, list] = {p: [] for p in POSITIONS}
    for p in players:
        by_pos[p["position"]].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x["value"], reverse=True)

    # ── Replacement level: the last starter at each position ──────────────────
    # Flex slots are spread across the positions eligible for them, which pushes
    # those positions' replacement level deeper and correctly raises their value.
    repl: dict[str, float] = {}
    for pos in POSITIONS:
        pool = by_pos[pos]
        if not pool:
            repl[pos] = 0
            continue
        n_start = starters.get(pos, 0) * teams
        for ftype, count in flex_counts.items():
            n_start += round(FLEX_SHARES[ftype].get(pos, 0) * count * teams)
        idx = min(max(n_start, 1), len(pool)) - 1
        repl[pos] = pool[idx]["value"]

    all_players: list[dict] = []
    for pos in POSITIONS:
        for i, pl in enumerate(by_pos[pos], start=1):
            pl["vor"] = round(pl["value"] - repl[pos])
            pl["pos_rank"] = i
            all_players.append(pl)

    # ── Convert VOR to dollars ────────────────────────────────────────────────
    # Every roster slot costs at least $1, so only money above that floor is
    # actually discretionary and available to bid with.
    all_players.sort(key=lambda x: x["vor"], reverse=True)
    draftable_n = teams * roster_size
    draftable = all_players[:draftable_n]

    total_money = teams * budget
    discretionary = max(total_money - draftable_n, 0)
    total_vor = sum(p["vor"] for p in draftable if p["vor"] > 0) or 1
    per_vor = discretionary / total_vor

    for p in all_players:
        p["auction_value"] = max(1, round(1 + p["vor"] * per_vor)) if p["vor"] > 0 else 1

    # ── Tiers within each position ────────────────────────────────────────────
    for pos in POSITIONS:
        pool = sorted(
            (p for p in all_players if p["position"] == pos),
            key=lambda x: x["value"],
            reverse=True,
        )
        tier = 1
        for i, p in enumerate(pool):
            if i > 0:
                prev = pool[i - 1]["value"] or 1
                if prev > 0 and (prev - p["value"]) / prev > TIER_BREAK:
                    tier += 1
            p["tier"] = tier

    all_players.sort(key=lambda x: (x["auction_value"], x["value"]), reverse=True)

    # Kick the 10MB metadata fetch off in the background — never awaited here
    if not _meta_fresh() and not _meta_loading:
        asyncio.create_task(_load_meta())

    for p in all_players:
        sid = p["sleeper_id"]
        pr, la = proj.get(sid) or None, last.get(sid) or None
        # Restate fantasy points under this league's scoring
        if pr:
            pr = {**pr, "pts_league": _league_points(pr, ppr, pass_td_pts, rush_att_pts)}
        if la:
            la = {**la, "pts_league": _league_points(la, ppr, pass_td_pts, rush_att_pts)}
        p["proj"], p["last"] = pr, la
        p["meta"] = _meta.get(sid) or None

    return {
        "players": all_players[:400],
        "seasons": {"projected": season, "actual": season - 1},
        "stats_available": bool(proj) or bool(last),
        "meta_ready": _meta_fresh(),
        "settings": {
            "teams": teams,
            "budget": budget,
            "ppr": ppr,
            "pass_td_pts": pass_td_pts,
            "rush_att_pts": rush_att_pts,
            "num_qbs": num_qbs,
            "roster_size": roster_size,
            "total_money": total_money,
            "draftable": draftable_n,
            "starters": starters,
            "flex_counts": flex_counts,
            "bench": bench,
        },
    }


# ── Shared rooms ──────────────────────────────────────────────────────────────
#
# Several managers in the same league run this at once, so picks are shared
# rather than tracked separately in each browser. Picks are an append-only
# table: two people entering at the same moment each insert a row instead of
# overwriting a shared blob, so neither can clobber the other. Every mutation
# returns the full authoritative list, which keeps the client from having to
# merge anything.
#
# These handlers are deliberately sync `def`, not `async def`: db() is a blocking
# psycopg2 connect, and FastAPI runs async handlers on the event loop itself. As
# `def` they run in the threadpool, so one client's slow query cannot stall
# everyone else's polling.

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _picks(conn, code: str) -> list:
    return conn.execute(
        "SELECT * FROM auction_picks WHERE room_code = ? ORDER BY id", (code,)
    ).fetchall()


def _norm_code(code: str) -> str:
    return (code or "").strip().upper()


def _as_int(value, field: str, default: int = 0) -> int:
    """Coerce a JSON value to int, 400ing rather than 500ing on junk.

    Note JSON has no NaN: a NaN price arrives as null, which would silently
    become a $0 pick, so None is treated as absent and takes the default.
    """
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid {field}: {value!r}")


@router.post("/room")
def create_room(body: dict = Body(...)):
    """Create a shared room. Settings are league-wide; each client keeps its own myTeam."""
    settings = body.get("settings", {}) or {}
    with db() as conn:
        code = None
        for _ in range(12):
            candidate = "".join(random.choice(ROOM_CHARS) for _ in range(5))
            if not conn.execute(
                "SELECT code FROM auction_rooms WHERE code = ?", (candidate,)
            ).fetchone():
                code = candidate
                break
        if not code:
            raise HTTPException(status_code=500, detail="Could not allocate a room code.")
        conn.execute(
            "INSERT INTO auction_rooms (code, settings, created_at) VALUES (?, ?, ?)",
            (code, json.dumps(settings), _now()),
        )
    return {"code": code, "settings": settings, "picks": []}


@router.get("/room/{code}")
def get_room(code: str):
    code = _norm_code(code)
    with db() as conn:
        room = conn.execute(
            "SELECT * FROM auction_rooms WHERE code = ?", (code,)
        ).fetchone()
        if not room:
            raise HTTPException(status_code=404, detail=f"Room {code} not found. Check the code.")
        picks = _picks(conn, code)
    try:
        settings = json.loads(room.get("settings") or "{}")
    except Exception:
        settings = {}
    try:
        nominated = json.loads(room.get("nominated") or "null")
    except Exception:
        nominated = None
    return {"code": code, "settings": settings, "picks": picks, "nominated": nominated}


@router.post("/room/{code}/nominate")
def set_nomination(code: str, body: dict = Body(...)):
    """
    Who is currently up for bid, shared with everyone in the room.

    Rides the existing GET /room payload rather than adding a second poll, so
    there is only one sync path to reason about. An empty body clears it.
    """
    code = _norm_code(code)
    player = body.get("player")
    with db() as conn:
        if not conn.execute(
            "SELECT code FROM auction_rooms WHERE code = ?", (code,)
        ).fetchone():
            raise HTTPException(status_code=404, detail=f"Room {code} not found.")
        conn.execute(
            "UPDATE auction_rooms SET nominated = ? WHERE code = ?",
            (json.dumps(player) if player else None, code),
        )
    return {"nominated": player}


@router.post("/room/{code}/pick")
def add_pick(code: str, body: dict = Body(...)):
    code = _norm_code(code)
    with db() as conn:
        if not conn.execute(
            "SELECT code FROM auction_rooms WHERE code = ?", (code,)
        ).fetchone():
            raise HTTPException(status_code=404, detail=f"Room {code} not found.")
        # Manual entries get a unique client-side id, so only real players are
        # deduped. Returning the list unchanged makes a double-entry a no-op
        # rather than an error the second manager has to interpret.
        sid = str(body.get("sleeper_id") or "")
        if sid and not sid.startswith("manual_"):
            dup = conn.execute(
                "SELECT id FROM auction_picks WHERE room_code = ? AND sleeper_id = ?",
                (code, sid),
            ).fetchone()
            if dup:
                return {"picks": _picks(conn, code), "duplicate": True}
        conn.execute(
            """
            INSERT INTO auction_picks
                (room_code, sleeper_id, name, position, nfl_team,
                 auction_value, price, team, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                sid,
                str(body.get("name") or ""),
                str(body.get("position") or ""),
                str(body.get("nfl_team") or ""),
                _as_int(body.get("auction_value"), "auction_value"),
                _as_int(body.get("price"), "price"),
                _as_int(body.get("team"), "team"),
                _now(),
            ),
        )
        # The sold player is no longer up for bid. Doing this here rather than as
        # a separate client POST avoids a late clear wiping the next nomination.
        conn.execute("UPDATE auction_rooms SET nominated = NULL WHERE code = ?", (code,))
        picks = _picks(conn, code)
    return {"picks": picks, "nominated": None}


@router.delete("/room/{code}/pick/{pick_id}")
def delete_pick(code: str, pick_id: int):
    """Undo one pick by id. The client decides *which* id — it undoes its own."""
    code = _norm_code(code)
    with db() as conn:
        existed = conn.execute(
            "SELECT id FROM auction_picks WHERE room_code = ? AND id = ?", (code, pick_id)
        ).fetchone()
        if existed:
            conn.execute(
                "DELETE FROM auction_picks WHERE room_code = ? AND id = ?", (code, pick_id)
            )
        picks = _picks(conn, code)
    # `deleted` lets the client tell "undone" from "already gone" instead of
    # silently reporting success either way.
    return {"picks": picks, "deleted": bool(existed)}


@router.delete("/room/{code}/picks")
def clear_picks(code: str):
    """Clear a room in one statement — deleting 200+ picks one at a time was
    slow, raced the poll, and left the room half-cleared if it failed partway."""
    code = _norm_code(code)
    with db() as conn:
        conn.execute("DELETE FROM auction_picks WHERE room_code = ?", (code,))
        conn.execute("UPDATE auction_rooms SET nominated = NULL WHERE code = ?", (code,))
    return {"picks": [], "nominated": None}
