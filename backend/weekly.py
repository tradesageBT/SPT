"""
In-season orchestration: what to start this week, and who to pick up.

Mode-agnostic by design. The dynasty/redraft split elsewhere in this app is a
STORAGE split — dynasty reads the `leagues` + `teams` tables, redraft reads a
`redraft_snapshots` blob. Nothing here reads either: rosters, roster_positions,
scoring and matchups all come live from Sleeper, so there is nothing to split
and a parallel pair of modules would be pure copy-paste. Mode enters in exactly
one place, the dynasty value column on the waiver page.
"""
import asyncio
import logging

import draft_values
import lineup
import projections
import sleeper_client
import sleeper_data
import slots

log = logging.getLogger(__name__)

# Sleeper league settings.type
_MODE_BY_TYPE = {0: "redraft", 1: "keeper", 2: "dynasty"}

# Injury designations that keep a player out of a lineup entirely.
_OUT_STATUSES = {"OUT", "IR", "PUP", "SUS", "NA", "DNR"}


def league_mode(league: dict) -> str:
    """Sleeper tells us whether a league is dynasty; no need to ask the user."""
    try:
        raw = (league.get("settings") or {}).get("type")
        return _MODE_BY_TYPE.get(int(raw), "redraft")
    except (TypeError, ValueError):
        return "redraft"


def rostered_ids(rosters: list) -> set[str]:
    """
    Everyone on a roster anywhere in the league — the complement of this is what
    "free agent" means. Taxi and reserve are separate arrays that may not appear
    in `players`, so all three are unioned, same as value_engine does.
    """
    out: set[str] = set()
    for r in (rosters or []):
        for key in ("players", "taxi", "reserve"):
            for pid in (r.get(key) or []):
                if pid:
                    out.add(str(pid))
    return out


def _availability(pid: str, row: dict | None, meta: dict | None) -> tuple[bool, str | None]:
    """
    Whether a player can be started, and why not.

    A missing projection row and a projected 0.0 are different facts: the first
    means the player isn't playing (bye, or not in the projection set), the
    second means they are expected to do nothing. Conflating them would silently
    bench someone over a data gap.
    """
    status = ((meta or {}).get("injury_status") or "").upper()
    if status in _OUT_STATUSES:
        return False, status.title()
    if row is None:
        return False, "No game"
    return True, None


def _candidate(pid: str, row: dict | None, meta: dict | None,
               points: float | None) -> dict:
    available, reason = _availability(pid, row, meta)
    row = row or {}
    meta = meta or {}
    return {
        "player_id": pid,
        "name": row.get("name") or meta.get("full_name") or pid,
        "position": row.get("position") or draft_values.norm_pos(meta.get("position") or ""),
        "fantasy_positions": row.get("fantasy_positions") or meta.get("fantasy_positions"),
        "nfl_team": row.get("team") or meta.get("team") or "",
        "opponent": row.get("opponent") or "",
        "points": points if points is not None else 0.0,
        "projected": points is not None,
        "injury_status": meta.get("injury_status"),
        "available": available,
        "unavailable_reason": reason,
    }


async def league_context(league_id: str, week: int | None = None) -> dict:
    """
    Everything one league needs for a week, in three parallel Sleeper calls
    plus a projections fetch that is shared across every league on the page.
    """
    season, current = await projections.current_week()
    week = int(week or current)

    league, rosters, users, matchups = await asyncio.gather(
        sleeper_client.get_league(league_id),
        sleeper_client.get_rosters(league_id),
        sleeper_client.get_users(league_id),
        sleeper_client.get_matchups(league_id, week),
    )
    if not league:
        return {}

    roster_positions = league.get("roster_positions") or []
    scoring = league.get("scoring_settings") or {}
    ppr = draft_values.parse_ppr(scoring)

    # Meta is enrichment (injuries, names for unprojected players), never a
    # prerequisite — it's a 10MB download, so it loads in the background and the
    # page works without it.
    if not sleeper_data.meta_fresh() and not sleeper_data.meta_loading():
        asyncio.create_task(sleeper_data.load_meta())

    proj = await projections.weekly(season, week, "projections",
                                    is_final=week < current)
    return {
        "league": league,
        "league_id": league_id,
        "league_name": league.get("name", ""),
        "mode": league_mode(league),
        "season": season,
        "week": week,
        "is_current_week": week == current,
        "rosters": rosters or [],
        "users": {u["user_id"]: u for u in (users or [])},
        "matchups": {m.get("roster_id"): m for m in (matchups or [])},
        "slot_tokens": slots.lineup_slots(roster_positions),
        "roster_positions": roster_positions,
        "scoring": scoring,
        "ppr": ppr,
        "proj": proj,
        "points": projections.score_all(proj, ppr, scoring),
    }


def _my_players(ctx: dict, roster_id: int) -> list[str]:
    """
    This roster's players for the requested week.

    Matchups are authoritative per-week; `rosters` only ever describes the live
    week, so it is the fallback rather than the source.
    """
    m = ctx["matchups"].get(roster_id) or {}
    if m.get("players"):
        return [str(p) for p in m["players"] if p]
    roster = next((r for r in ctx["rosters"] if r.get("roster_id") == roster_id), {})
    return [str(p) for p in (roster.get("players") or []) if p]


def _current_assignment(ctx: dict, roster_id: int, by_id: dict) -> list[dict]:
    """The lineup as actually set, positionally matched to the league's slots."""
    m = ctx["matchups"].get(roster_id) or {}
    starters = [str(p) for p in (m.get("starters") or [])]
    if not starters:
        roster = next((r for r in ctx["rosters"] if r.get("roster_id") == roster_id), {})
        starters = [str(p) for p in (roster.get("starters") or [])]

    out = []
    for i, token in enumerate(ctx["slot_tokens"]):
        pid = starters[i] if i < len(starters) else ""
        c = by_id.get(pid) if pid and pid != "0" else None
        # A started player who is Out or on bye scores nothing. Crediting them
        # their projection would flatter the lineup you already have and hide
        # exactly the swap most worth making.
        pts = None if c is None else (round(c["points"], 2) if c["available"] else 0.0)
        out.append({
            "slot": token,
            "slot_label": slots.slot_label(token),
            "player_id": c["player_id"] if c else None,
            "points": pts,
            "unavailable_reason": c["unavailable_reason"] if c else None,
            "optimizable": slots.is_projected(token),
        })
    return out


async def lineup_report(league_id: str, roster_id: int, week: int | None = None) -> dict:
    """Current lineup vs optimal, and the swaps worth making."""
    ctx = await league_context(league_id, week)
    if not ctx:
        return {}

    meta = sleeper_data.get_meta()
    candidates = [
        _candidate(pid, ctx["proj"].get(pid), meta.get(pid), ctx["points"].get(pid))
        for pid in _my_players(ctx, roster_id)
    ]
    by_id = {c["player_id"]: c for c in candidates}

    best = lineup.optimize(candidates, ctx["slot_tokens"])

    # A silent matching bug wouldn't crash, it would quietly recommend worse
    # lineups. Cheap enough to check every request.
    floor = lineup.greedy_total(candidates, ctx["slot_tokens"])
    if best["total"] < floor - 0.01:
        log.error("lineup optimizer underperformed greedy (%s < %s) for league %s roster %s",
                  best["total"], floor, league_id, roster_id)

    current = _current_assignment(ctx, roster_id, by_id)
    current_total = round(sum(a["points"] or 0.0 for a in current if a["optimizable"]), 2)

    def _embed(rows):
        """
        Attach the player to each slot rather than making the client join on
        player_id — a started player appears in no other list, so the client
        would have nothing to look them up in.
        """
        return [{**r, "player": by_id.get(r["player_id"])} for r in rows]

    started = set(best["started"])
    roster = next((r for r in ctx["rosters"] if r.get("roster_id") == roster_id), {})
    owner = ctx["users"].get(roster.get("owner_id")) or {}

    notes = []
    if any(not slots.is_projected(t) for t in ctx["slot_tokens"]):
        notes.append("IDP slots are shown but not optimized — neither projection "
                     "source covers defensive players.")
    if any(c["position"] in ("K", "DEF") and c["projected"] for c in candidates):
        notes.append("Kicker and defense points are approximate: Sleeper's "
                     "baseline differs from most leagues' rules for them.")

    return {
        "league_id": league_id,
        "league_name": ctx["league_name"],
        "mode": ctx["mode"],
        "season": ctx["season"],
        "week": ctx["week"],
        "is_current_week": ctx["is_current_week"],
        "roster_id": roster_id,
        "team_name": owner.get("display_name") or f"Roster {roster_id}",
        "ppr": ctx["ppr"],
        "min_delta": lineup.MIN_DELTA,
        "sources_ok": {"sleeper": bool(ctx["proj"])},
        "current": {"slots": _embed(current), "total": current_total},
        "optimal": {"slots": _embed(best["assignment"]), "total": best["total"]},
        "delta": round(best["total"] - current_total, 2),
        "changes": lineup.diff(current, best["assignment"], by_id),
        "bench": sorted((c for c in candidates
                         if c["player_id"] not in started and c["available"]),
                        key=lambda c: -c["points"]),
        "unavailable": [
            {"player_id": c["player_id"], "name": c["name"], "position": c["position"],
             "reason": c["unavailable_reason"]}
            for c in candidates if not c["available"]
        ],
        "notes": notes,
    }
