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
import random
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, HTTPException, Body

import draft_values
import sleeper_data
from draft_values import POSITIONS, FLEX_SHARES, TIER_BREAK
from database import db

router = APIRouter(prefix="/api/auction-draft")
log = logging.getLogger(__name__)

# Room codes are read aloud and typed on phones, so drop characters that get
# confused with each other (0/O, 1/I/L).
ROOM_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# POSITIONS / FLEX_SHARES / TIER_BREAK now live in draft_values, shared with
# the Sleeper draft room so the two can't drift apart.


# Sleeper metadata / stats / projections now live in sleeper_data, shared with
# the Sleeper draft room so /players/nfl is fetched once rather than per router.
STAT_KEYS = sleeper_data.STAT_KEYS


def _league_points(stats: dict, ppr: float, pass_td_pts: float, rush_att_pts: float):
    # No scoring_settings here — the auction tool has no access to a league's
    # rules, so return scoring is skipped and this behaves exactly as before.
    return draft_values.league_points(stats, ppr, pass_td_pts, rush_att_pts)


async def _load_values(num_qbs: int, ppr: float) -> list[dict]:
    return await draft_values.load_values(num_qbs, ppr)


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
    season = sleeper_data.current_season()
    players, proj, last = await asyncio.gather(
        _load_values(num_qbs, ppr),
        sleeper_data.season("projections", season),
        sleeper_data.season("stats", season - 1),
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
    if not sleeper_data.meta_fresh() and not sleeper_data.meta_loading():
        asyncio.create_task(sleeper_data.load_meta())

    for p in all_players:
        sid = p["sleeper_id"]
        pr, la = proj.get(sid) or None, last.get(sid) or None
        # Restate fantasy points under this league's scoring
        if pr:
            pr = {**pr, "pts_league": _league_points(pr, ppr, pass_td_pts, rush_att_pts)}
        if la:
            la = {**la, "pts_league": _league_points(la, ppr, pass_td_pts, rush_att_pts)}
        p["proj"], p["last"] = pr, la
        p["meta"] = sleeper_data.get_meta().get(sid) or None

    return {
        "players": all_players[:400],
        "seasons": {"projected": season, "actual": season - 1},
        "stats_available": bool(proj) or bool(last),
        "meta_ready": sleeper_data.meta_fresh(),
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
