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
import sleeper_data

router = APIRouter(prefix="/api/sleeper-draft")
SLEEPER = "https://api.sleeper.app/v1"
TIMEOUT = 10.0

# The league this assistant is set up for. Still a query param so the room works
# for any other league, but this is what it defaults to.
DEFAULT_LEAGUE_ID = "1401244151114117120"


async def _get(path: str):
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{SLEEPER}/{path}")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Sleeper: not found — {path}")
    r.raise_for_status()
    return r.json()


# How hard positional need bends the ranking. Matches the dynasty draft room's
# existing weighting (frontend DraftRoom.jsx: fc_value * (1 + need * 1.5)) so the
# two boards don't disagree about what "fit" means.
NEED_BOOST = 1.5


def _best_fit(available: list[dict]) -> str | None:
    """
    The pick that best balances value against what this roster still needs.

    Previously the client took `available.find(p => p.fills_need)` — the first
    player in a VALUE-sorted list carrying a boolean flag. That flag is true
    whenever a position has any gap at all, and in a superflex league QB keeps a
    positive gap until the third quarterback while superflex pricing puts QBs at
    the top of the board. So "best fit" returned a QB nearly every pick and was
    really just "best available" under another name.

    Ranked on VOR rather than raw value: VOR is replacement-adjusted, so it
    answers the actual draft question — how much does this player beat what I
    could still get later at the same position — where raw superflex value
    structurally favours quarterbacks. Need then scales that, using the
    proportional score, which decays as the position fills instead of staying
    flat until it snaps to zero.
    """
    candidates = [p for p in available if p.get("fills_need")]
    if not candidates:
        return None

    def score(p):
        # vor is None for K/DEF, and negative below replacement — a player worth
        # less than the waiver wire should never win on need alone.
        vor = max(p.get("vor") or 0, 0)
        return vor * (1 + (p.get("need_weight") or 0) * NEED_BOOST)

    best = max(candidates, key=lambda p: (score(p), p.get("redraft_value") or 0))
    # Everyone left is below replacement (late draft): fall back to the
    # value ordering rather than picking arbitrarily among a field of zeroes.
    if score(best) <= 0:
        best = candidates[0]
    return best["player_id"]


def _on_clock(picks_made: int, num_teams: int) -> int | None:
    """Return 1-based draft slot for the next pick (snake)."""
    rnd = picks_made // num_teams
    pos = picks_made % num_teams
    return (pos + 1) if rnd % 2 == 0 else (num_teams - pos)


@router.get("/state")
async def get_draft_state(
    league_id: str = Query(DEFAULT_LEAGUE_ID),
    my_roster_id: int | None = Query(None),
):
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

    picks_made = len(picks_out)

    # ── Per-team roster state and needs ───────────────────────────────────────
    # Needs span starters, flex eligibility and bench depth, so the board keeps
    # advising deep into the draft instead of going quiet once starters fill.
    targets = draft_values.roster_targets(starters, flex_counts, roster["bench"])

    counts_by_roster: dict[int, dict] = {}
    for pk in picks_out:
        rid = pk.get("roster_id")
        if rid is None:
            continue
        pos = draft_values.norm_pos(pk.get("position"))
        if pos not in draft_values.POSITIONS:
            continue
        counts_by_roster.setdefault(rid, {})
        counts_by_roster[rid][pos] = counts_by_roster[rid].get(pos, 0) + 1

    needs_by_roster = {
        t["roster_id"]: draft_values.team_needs(
            counts_by_roster.get(t["roster_id"], {}), targets, starters,
            roster_size=sum(targets.values()),
        )
        for t in teams
    }
    for t in teams:
        rid = t["roster_id"]
        t["counts"] = counts_by_roster.get(rid, {})
        t["needs"] = needs_by_roster.get(rid, {})

    # ── Upcoming picks, in order ──────────────────────────────────────────────
    # Enough to always reach the viewer's next turn; the client trims.
    upcoming = []
    if not is_auction:
        for i in range(picks_made, min(picks_made + 24, num_teams * rounds)):
            rnd = i // num_teams + 1
            slot = draft_values.snake_slot(i, num_teams)
            rid = slot_to_roster.get(str(slot))
            need = needs_by_roster.get(rid) or {}
            upcoming.append({
                "pick_no": i + 1,
                "round": rnd,
                "roster_id": rid,
                "team_name": _team_name(rid),
                # Round 1 rosters are empty, so a "need" there is meaningless.
                "top_need": None if rnd == 1 else need.get("top_need"),
                "urgent": [] if rnd == 1 else need.get("urgent", []),
                "counts": counts_by_roster.get(rid, {}),
            })

    # ── Kickers and defenses ──────────────────────────────────────────────────
    # FantasyCalc carries neither, so they come from Sleeper's own player data,
    # ordered by last season's points. Appended AFTER apply_tiers deliberately:
    # a run of zero-value players run through tiering would make every kicker
    # its own tier, since (prev - 0) / prev exceeds any break threshold.
    if not sleeper_data.meta_fresh() and not sleeper_data.meta_loading():
        asyncio.create_task(sleeper_data.load_meta())
    last_season = await sleeper_data.season("stats", sleeper_data.current_season() - 1)
    kdef = sleeper_data.load_kdef(last_season)

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
            "last_pts": None,
        }
        for p in all_players
        if str(p["sleeper_id"]) not in drafted_ids
    ] + [
        {
            "player_id": p["sleeper_id"],
            "name": p["name"],
            "position": p["position"],
            "nfl_team": p.get("nfl_team", ""),
            "redraft_value": 0,
            "redraft_pos_rank": None,
            "tier": None,
            "vor": None,
            "last_pts": p.get("last_pts"),
        }
        for p in kdef
        if str(p["sleeper_id"]) not in drafted_ids
    ]
    # Valued players order by value; K/DEF are all zero so they fall to the
    # bottom and sort among themselves by last season's points.
    available.sort(key=lambda x: (x["redraft_value"], x["last_pts"] or 0), reverse=True)

    # ── Stats, projections and injury data ────────────────────────────────────
    # Points are restated under this league's scoring: Sleeper's totals are
    # computed under standard rules, so they miss the league's pass-TD value,
    # any per-carry bonus, TE premium, and return yardage. `position` is passed
    # because the TE premium applies to tight ends only.
    proj = await sleeper_data.season("projections", sleeper_data.current_season())
    scoring = league_raw.get("scoring_settings") or {}
    for p in available:
        pid = str(p["player_id"])
        pr, la = proj.get(pid) or None, last_season.get(pid) or None
        if pr:
            pr = {**pr, "pts_league": draft_values.league_points(
                pr, ppr, scoring_settings=scoring, position=p["position"])}
        if la:
            la = {**la, "pts_league": draft_values.league_points(
                la, ppr, scoring_settings=scoring, position=p["position"])}
        p["proj"], p["last"] = pr, la
        p["meta"] = sleeper_data.get_meta().get(pid) or None

    # Flag which players fill a need for the viewer. The ORDER is untouched —
    # the list stays value-sorted and the client decides how to surface this.
    my_needs = needs_by_roster.get(my_roster_id) if my_roster_id is not None else None
    best_fit_id = None
    if my_needs:
        gaps = my_needs.get("gaps", {})
        prop = my_needs.get("prop", {})
        for p in available:
            p["fills_need"] = gaps.get(p["position"], 0) > 0
            p["need_weight"] = prop.get(p["position"], 0)
        best_fit_id = _best_fit(available)

    # On the clock
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
        "upcoming": upcoming,
        "my_needs": my_needs,
        # Computed server-side: the client used to derive this itself by taking
        # the first value-sorted player with a need flag, which made it a
        # synonym for best available.
        "best_fit_id": best_fit_id,
        "targets": {k: round(v, 2) for k, v in targets.items()},
        "seasons": {
            "projected": sleeper_data.current_season(),
            "actual": sleeper_data.current_season() - 1,
        },
        # Non-empty when the league scores return yardage, so the UI can say so
        # rather than showing a restated number with no explanation.
        "return_rates": draft_values.return_yard_rates(scoring),
        "picks": picks_out[-25:],
        "all_picks": picks_out,
        "available": available,
    }
