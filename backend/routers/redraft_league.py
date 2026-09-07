"""
Redraft league hub — Sleeper only, public API, no auth.

Mirrors the dynasty value engine with the dynasty concepts removed: no rookie
picks, no dynasty values, no contention windows. Scoring and roster settings are
read from the league itself, so nothing is configured by hand.

  GET  /api/redraft-league/{league_id}                    live rankings
  GET  /api/redraft-league/{league_id}/teams/{roster_id}  live team detail
  POST /api/redraft-league/{league_id}/sync               snapshot for trades
  GET  /api/redraft-league/{league_id}/players            rostered players (for search)
  GET  /api/redraft-league/{league_id}/trades             ideas from the snapshot

Rankings compute live because they are cheap. Trade generation is O(T^2 * n^4)
— hundreds of thousands of fairness checks for a 12-team league, each survivor
running two roster simulations — so it reads a snapshot instead.
"""
import json
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, HTTPException

import draft_values
import value_engine
import trade_engine
import sleeper_client
from database import db

router = APIRouter(prefix="/api/redraft-league")
log = logging.getLogger(__name__)

VALUE_KEY = "redraft_value"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Bench-ish slots never appear in the `starters` array
_NON_LINEUP = {"BN", "IR", "TAXI"}
_SLOT_LABEL = {
    "SUPER_FLEX": "SFLEX", "REC_FLEX": "W/T", "WRRB_FLEX": "W/R",
    "DEF": "DEF", "DST": "DEF",
}


def _lineup(roster: dict, roster_positions: list, by_id: dict) -> list[dict]:
    """
    Starters in the league's own slot order — QB, RB, RB, WR... FLEX, SFLEX.

    Sleeper returns `starters` positionally matched to the non-bench entries of
    roster_positions, but compute_team_profile turns it into a set and loses
    that ordering, so it's rebuilt from the raw roster here.
    """
    slots = [p for p in (roster_positions or []) if str(p).upper() not in _NON_LINEUP]
    starters = list(roster.get("starters") or [])
    out = []
    for i, slot in enumerate(slots):
        pid = str(starters[i]) if i < len(starters) else ""
        player = by_id.get(pid) if pid and pid != "0" else None
        out.append({
            "slot": _SLOT_LABEL.get(str(slot).upper(), str(slot).upper()),
            "player": player,          # None for an unfilled slot
        })
    return out


def _players_cache(values: list[dict]) -> dict:
    """
    Shape draft_values.load_values output like the players_cache row dict that
    value_engine._player_entry expects, deriving the ranks it wants.

    fc_value is set to the redraft number as well as redraft_value: the trade
    engine only ever compares magnitudes, so aliasing here means it needs no
    changes at all.
    """
    ordered = sorted(values, key=lambda p: p.get("value", 0) or 0, reverse=True)
    pos_seen: dict[str, int] = {}
    cache: dict[str, dict] = {}
    for i, p in enumerate(ordered, start=1):
        pos = p.get("position", "")
        pos_seen[pos] = pos_seen.get(pos, 0) + 1
        val = p.get("value", 0) or 0
        cache[str(p["sleeper_id"])] = {
            "sleeper_id": str(p["sleeper_id"]),
            "name": p.get("name", ""),
            "position": pos,
            "nfl_team": p.get("nfl_team", ""),
            "age": p.get("age"),
            "fc_value": val,          # alias — see docstring
            "redraft_value": val,
            "overall_rank": i,
            "pos_rank": pos_seen[pos],
            "redraft_overall_rank": i,
            "redraft_pos_rank": pos_seen[pos],
        }
    return cache


async def _league_state(league_id: str, want_rosters: bool = False):
    """Fetch the league and compute profiles. Shared by every endpoint here."""
    league, rosters, users = await asyncio.gather(
        sleeper_client.get_league(league_id),
        sleeper_client.get_rosters(league_id),
        sleeper_client.get_users(league_id),
    )
    if not league:
        raise HTTPException(status_code=404, detail=f"Sleeper league {league_id} not found.")

    roster_positions = league.get("roster_positions") or []
    slots = draft_values.parse_roster_positions(roster_positions)
    ppr = draft_values.parse_ppr(league.get("scoring_settings"))

    values = await draft_values.load_values(num_qbs=slots["num_qbs"], ppr=ppr)
    cache = _players_cache(values)
    users_map = {u["user_id"]: u for u in (users or [])}

    profiles = value_engine.compute_league_profiles(
        rosters or [], users_map, cache, {},
        roster_positions=roster_positions,
        value_key=VALUE_KEY,
        include_picks=False,
    )
    value_engine.strength_tiers(profiles)

    settings = {
        "ppr": ppr,
        "num_qbs": slots["num_qbs"],
        "superflex": slots["sflex"] > 0,
        "starters": {"QB": slots["qb"], "RB": slots["rb"], "WR": slots["wr"],
                     "TE": slots["te"], "K": slots["k"], "DEF": slots["dst"]},
        "flex": {k: slots[k] for k in draft_values.FLEX_KEYS},
        "bench": slots["bench"],
        "roster_positions": roster_positions,
    }
    if want_rosters:
        return league, profiles, settings, (rosters or [])
    return league, profiles, settings


@router.get("/{league_id}")
async def get_league_hub(league_id: str):
    """Power rankings, positional strength and ranks. Computed live."""
    league, profiles, settings = await _league_state(league_id)
    return {
        "league_id": league_id,
        "league_name": league.get("name", ""),
        "season": league.get("season", ""),
        "num_teams": len(profiles),
        "settings": settings,
        "teams": profiles,
    }


@router.get("/{league_id}/teams/{roster_id}")
async def get_team(league_id: str, roster_id: int):
    """One team's detail — lineup in slot order, bench, positional strength."""
    league, profiles, settings, rosters = await _league_state(league_id, want_rosters=True)
    profile = next((p for p in profiles if p["roster_id"] == roster_id), None)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Roster {roster_id} not in this league.")

    by_id = {str(p["sleeper_id"]): p for p in profile["players"]}
    raw = next((r for r in rosters if r.get("roster_id") == roster_id), {})
    lineup = _lineup(raw, settings.get("roster_positions"), by_id)

    started = {e["player"]["sleeper_id"] for e in lineup if e["player"]}
    bench = sorted(
        (p for p in profile["players"] if str(p["sleeper_id"]) not in started),
        key=lambda p: p.get(VALUE_KEY, 0), reverse=True,
    )
    return {
        "league_id": league_id,
        "league_name": league.get("name", ""),
        "settings": settings,
        "num_teams": len(profiles),
        **profile,
        "lineup": lineup,
        "bench": bench,
        "players": sorted(profile["players"], key=lambda p: p.get(VALUE_KEY, 0), reverse=True),
    }


@router.post("/{league_id}/sync")
async def sync_league(league_id: str):
    """Snapshot the league so trade generation has something affordable to read."""
    league, profiles, settings = await _league_state(league_id)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO redraft_snapshots (league_id, league_name, profiles, settings, computed_at)
            VALUES (:lid, :name, :profiles, :settings, :at)
            ON CONFLICT(league_id) DO UPDATE SET
                league_name=excluded.league_name,
                profiles=excluded.profiles,
                settings=excluded.settings,
                computed_at=excluded.computed_at
            """,
            {"lid": league_id, "name": league.get("name", ""),
             "profiles": json.dumps(profiles), "settings": json.dumps(settings),
             "at": _now()},
        )
    return {"ok": True, "league_name": league.get("name", ""),
            "teams_synced": len(profiles), "computed_at": _now()}


def _load_snapshot(league_id: str):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM redraft_snapshots WHERE league_id = ?", (league_id,)
        ).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail="This league hasn't been synced yet — hit Sync to generate trade ideas.",
        )
    return json.loads(row.get("profiles") or "[]"), row.get("computed_at")


@router.get("/{league_id}/players")
def get_players(league_id: str):
    """
    Every rostered player, for the trade-idea search box.

    Read from the snapshot rather than live: the trades endpoint generates from
    the snapshot, so a player who has been traded away since the last sync would
    otherwise be offered in search and then match nothing.
    """
    profiles, _ = _load_snapshot(league_id)
    seen: set[str] = set()
    players = []
    for prof in profiles:
        for pl in prof.get("players") or []:
            sid = str(pl.get("sleeper_id") or "")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            players.append({
                "sleeper_id": sid,
                "name": pl.get("name", sid),
                "position": pl.get("position", ""),
                "nfl_team": pl.get("nfl_team", ""),
                "roster_id": prof["roster_id"],
                "display_name": prof.get("display_name", ""),
                "redraft_value": pl.get(VALUE_KEY, 0),
                "is_starter": pl.get("is_starter", False),
            })
    return sorted(players, key=lambda x: x["name"])


def _categorize_with_forced(profile, thresholds, force_player, force_roster_id):
    """
    Same idea as the dynasty router: a forced player must be tradeable even if
    their own tier says untouchable (smash) or worthless (trash), so move them
    into `pass` on their own team only.
    """
    cats = trade_engine.categorize_players(profile, thresholds)
    if not force_player or profile["roster_id"] != force_roster_id:
        return cats
    sid = force_player["sleeper_id"]
    cats = {k: [p for p in v if p.get("sleeper_id") != sid] for k, v in cats.items()}
    cats["pass"] = [force_player] + cats["pass"]
    return cats


def _has_player(trade, sleeper_id: str) -> bool:
    return any(p.get("sleeper_id") == sleeper_id for p in trade["a_gives"] + trade["b_gives"])


@router.get("/{league_id}/trades")
def get_trades(
    league_id: str,
    roster_id: int | None = Query(None),
    include_smash: bool = Query(False),
    expand: bool = Query(False),
    force_player_id: str | None = Query(None),
):
    """
    Trade ideas from the last snapshot.

    Sync `def` not `async def`: this is CPU-bound for hundreds of milliseconds,
    so FastAPI should run it in the threadpool rather than on the event loop.
    """
    profiles, computed_at = _load_snapshot(league_id)
    if len(profiles) < 2:
        return {"trades": [], "computed_at": computed_at}

    force_player = None
    force_roster_id = None
    if force_player_id:
        for prof in profiles:
            match = next(
                (p for p in prof.get("players") or []
                 if str(p.get("sleeper_id")) == force_player_id), None)
            if match:
                force_player, force_roster_id = match, prof["roster_id"]
                break
        if not force_player:
            raise HTTPException(
                status_code=404,
                detail="That player isn't on a roster in this league's last sync.",
            )

    # Cutoffs from this league's own distribution — the module constants are
    # calibrated to the dynasty value scale.
    thresholds = trade_engine.derive_thresholds(profiles)
    cats = {
        p["roster_id"]: _categorize_with_forced(p, thresholds, force_player, force_roster_id)
        for p in profiles
    }

    focus = next((p for p in profiles if p["roster_id"] == roster_id), None) if roster_id else None
    if focus is None and force_player:
        # Only pairs involving the forced player's team can ever contain them.
        focus = next(p for p in profiles if p["roster_id"] == force_roster_id)
    pairs = (
        [(focus, o) for o in profiles if o["roster_id"] != focus["roster_id"]]
        if focus else
        [(a, b) for i, a in enumerate(profiles) for b in profiles[i + 1:]]
    )

    def _generate(em: bool) -> list[dict]:
        out = []
        for a, b in pairs:
            out.extend(trade_engine.generate_trades_between(
                a, b, cats[a["roster_id"]], cats[b["roster_id"]],
                include_smash=include_smash,
                include_picks=False,          # redraft has none
                force_mode=bool(force_player),
                expand_mode=em,
                force_player_id=force_player_id,
            ))
        return out

    trades = _generate(expand)
    if force_player:
        trades = [t for t in trades if _has_player(t, force_player_id)]
        # Escalate once if the standard fairness band came back thin.
        if len(trades) < 5 and not expand:
            seen = {tuple(sorted(x["sleeper_id"] for x in t["a_gives"] + t["b_gives"]))
                    for t in trades}
            for t in _generate(True):
                if not _has_player(t, force_player_id):
                    continue
                key = tuple(sorted(x["sleeper_id"] for x in t["a_gives"] + t["b_gives"]))
                if key not in seen:
                    trades.append(t)
                    seen.add(key)

    trades.sort(key=lambda t: -(t["lineup_delta_a"] + t["lineup_delta_b"]))
    return {"trades": trades[:60], "computed_at": computed_at}
