import asyncio
import json
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from database import db
from trade_engine import generate_all_trades, generate_trades_between, categorize_players, compute_trade_breakdown
import sleeper_client
import cache_manager
import logger

# In-memory cache for recent-transactions: {league_id: (timestamp, payload)}
# Avoids the 23 parallel Sleeper API calls on every Trade Feed tab click.
_TXNS_CACHE: dict[str, tuple[float, list]] = {}
_TXNS_TTL = 300  # 5 minutes


def clear_transactions_cache(league_id: str) -> None:
    _TXNS_CACHE.pop(league_id, None)

router = APIRouter(prefix="/api/leagues", tags=["trades"])


def _load_profiles(league_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM teams WHERE sleeper_league_id = ? ORDER BY total_value DESC",
            (league_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="League not synced yet")

    profiles = []
    for row in rows:
        d = dict(row)
        for f in ("positional_breakdown", "positional_surplus", "positional_need", "positional_rank"):
            d[f] = json.loads(d[f]) if d.get(f) else {}
        roster_data = json.loads(d.get("roster_data") or "{}")
        d["players"] = roster_data.get("players", [])
        d["picks"] = roster_data.get("picks", [])
        profiles.append(d)

    return profiles


# ---------------------------------------------------------------------------
# Manual trade evaluator
# ---------------------------------------------------------------------------

class TradeAsset(BaseModel):
    sleeper_id: str
    name: str
    position: str
    fc_value: int = 0


class TradeEvalRequest(BaseModel):
    a_roster_id: int
    b_roster_id: int
    a_gives: list[TradeAsset]
    b_gives: list[TradeAsset]


@router.post("/{league_id}/evaluate-trade")
async def evaluate_trade(league_id: str, body: TradeEvalRequest):
    profiles = _load_profiles(league_id)

    team_a = next((p for p in profiles if p["roster_id"] == body.a_roster_id), None)
    team_b = next((p for p in profiles if p["roster_id"] == body.b_roster_id), None)
    if not team_a or not team_b:
        raise HTTPException(status_code=404, detail="Roster not found")

    a_gives = [a.model_dump() for a in body.a_gives]
    b_gives = [b.model_dump() for b in body.b_gives]

    # Enrich with age + is_starter from stored roster data (picks have no age)
    for item in a_gives:
        match = next((p for p in team_a["players"] if p.get("sleeper_id") == item["sleeper_id"]), {})
        item["age"] = match.get("age")
        item["is_starter"] = match.get("is_starter", False)
    for item in b_gives:
        match = next((p for p in team_b["players"] if p.get("sleeper_id") == item["sleeper_id"]), {})
        item["age"] = match.get("age")
        item["is_starter"] = match.get("is_starter", False)

    breakdown_a = compute_trade_breakdown(team_a, a_gives, b_gives)
    breakdown_b = compute_trade_breakdown(team_b, b_gives, a_gives)

    value_a = sum(x["fc_value"] for x in a_gives)
    value_b = sum(x["fc_value"] for x in b_gives)

    def _avg_age(items):
        ages = [x["age"] for x in items if x.get("position") != "PK" and x.get("age")]
        return round(sum(ages) / len(ages), 1) if ages else None

    lineup_delta_a = breakdown_a["lineup_delta"]
    lineup_delta_b = breakdown_b["lineup_delta"]
    value_diff = value_a - value_b  # positive = A gives more raw value

    # Winner: raw value is primary (who received more assets); lineup delta is
    # tiebreak for value-close trades (e.g. swapping surplus positions).
    # Lineup delta alone is unreliable as a primary signal — a team can improve
    # their starting lineup by consolidating depth into one stud while still
    # giving away more total dynasty value.
    is_win_win = lineup_delta_a > 0 and lineup_delta_b > 0 and abs(value_diff) <= 500
    ld_diff = lineup_delta_a - lineup_delta_b   # positive = A improved more
    if is_win_win:
        winner = "even"
    elif abs(value_diff) > 500:
        # value_diff > 0 means A gives more value → B wins
        winner = "b" if value_diff > 0 else "a"
    elif abs(ld_diff) >= 300:
        winner = "a" if ld_diff > 0 else "b"
    else:
        winner = "even"

    pos_rank_a = team_a.get("positional_rank") or {}
    pos_rank_b = team_b.get("positional_rank") or {}
    n = pos_rank_a.get("n") or pos_rank_b.get("n") or 0

    return {
        "value_a_gives": value_a,
        "value_b_gives": value_b,
        "value_delta": abs(value_diff),
        "lineup_delta_a": lineup_delta_a,
        "lineup_delta_b": lineup_delta_b,
        "breakdown_a": breakdown_a,
        "breakdown_b": breakdown_b,
        "avg_age_a_gives": _avg_age(a_gives),
        "avg_age_b_gives": _avg_age(b_gives),
        "team_a_name": team_a["display_name"],
        "team_b_name": team_b["display_name"],
        "contention_a": team_a.get("contention_category"),
        "contention_b": team_b.get("contention_category"),
        "positional_rank_a": pos_rank_a,
        "positional_rank_b": pos_rank_b,
        "num_teams": n,
        "is_win_win": is_win_win,
        "winner": winner,
    }


@router.get("/{league_id}/players")
async def get_league_players(league_id: str):
    """All players across all rosters — used to populate the trade filter search."""
    profiles = _load_profiles(league_id)
    seen = set()
    players = []
    for p in profiles:
        for player in p["players"]:
            sid = player.get("sleeper_id")
            if sid and sid not in seen:
                seen.add(sid)
                players.append({
                    "sleeper_id": sid,
                    "name": player.get("name", sid),
                    "position": player.get("position", ""),
                    "roster_id": p["roster_id"],
                    "display_name": p["display_name"],
                    "fc_value": player.get("fc_value", 0),
                    "is_starter": player.get("is_starter", False),
                })
    return sorted(players, key=lambda x: x["name"])


@router.get("/{league_id}/trades")
async def get_all_trade_ideas(
    request: Request,
    league_id: str,
    roster_id: int | None = Query(None),
    include_smash: bool = Query(False),
    include_picks: bool = Query(False),
    force_player_id: str | None = Query(None),
    expand: bool = Query(False),
    exclude: list[str] = Query(default=[]),
):
    excluded_ids: set[str] = set(exclude)
    profiles = _load_profiles(league_id)

    # When forcing a specific player, find their team and inject them into the
    # tradeable pool regardless of their smash/pass/trash tier.
    force_profile = None
    force_player = None
    if force_player_id:
        for p in profiles:
            match = next((pl for pl in p["players"] if pl.get("sleeper_id") == force_player_id), None)
            if match:
                force_profile = p
                force_player = match
                break

    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
    if force_player_id and force_player:
        logger.log("trade_search", {
            "league_id": league_id,
            "player_id": force_player_id,
            "player_name": force_player.get("name"),
            "include_smash": include_smash,
            "include_picks": include_picks,
        }, ip=ip)

    force_mode = force_player_id is not None
    expand_mode = expand and force_mode  # expand only makes sense with a forced player

    def _cat(profile):
        cats = _categorize_with_forced(profile, force_player, force_profile)
        if excluded_ids:
            cats = {k: [p for p in v if p.get("sleeper_id") not in excluded_ids] for k, v in cats.items()}
        return cats

    def _run_generation(em: bool) -> list[dict]:
        # When a player is forced, only run pairs involving their team —
        # the other team pairs can never produce trades with that player anyway.
        if force_profile and not roster_id:
            focus = force_profile
            others = [p for p in profiles if p["roster_id"] != focus["roster_id"]]
            cat_focus = _cat(focus)
            trades = []
            for other in others:
                cat_other = _cat(other)
                trades.extend(generate_trades_between(
                    focus, other, cat_focus, cat_other,
                    include_smash=include_smash,
                    include_picks=include_picks,
                    force_mode=force_mode,
                    expand_mode=em,
                    force_player_id=force_player_id,
                ))
            return trades

        if roster_id is not None:
            focus = next((p for p in profiles if p["roster_id"] == roster_id), None)
            if not focus:
                raise HTTPException(status_code=404, detail="Roster not found")
            others = [p for p in profiles if p["roster_id"] != roster_id]
            cat_focus = _cat(focus)
            trades = []
            for other in others:
                cat_other = _cat(other)
                trades.extend(generate_trades_between(
                    focus, other, cat_focus, cat_other,
                    include_smash=include_smash,
                    include_picks=include_picks,
                    force_mode=force_mode,
                    expand_mode=em,
                    force_player_id=force_player_id,
                ))
            return sorted(trades, key=lambda x: x["value_delta"])

        cats = {p["roster_id"]: _cat(p) for p in profiles}
        from itertools import combinations
        all_trades = []
        for a, b in combinations(profiles, 2):
            all_trades.extend(generate_trades_between(
                a, b, cats[a["roster_id"]], cats[b["roster_id"]],
                include_smash=include_smash,
                include_picks=include_picks,
                force_mode=force_mode,
                expand_mode=em,
                force_player_id=force_player_id,
            ))
        return all_trades

    result = _run_generation(expand_mode)

    if excluded_ids:
        result = [t for t in result if not any(p.get("sleeper_id") in excluded_ids for p in t["a_gives"] + t["b_gives"])]

    if force_player_id:
        result = [t for t in result if _trade_has_player(t, force_player_id)]
        # Auto-escalate once if still thin — avoids double-running in normal cases
        if len(result) < 5 and not expand_mode:
            result_expanded = [t for t in _run_generation(True) if _trade_has_player(t, force_player_id)]
            seen = {tuple(sorted(x["sleeper_id"] for x in t["a_gives"] + t["b_gives"])) for t in result}
            for t in result_expanded:
                key = tuple(sorted(x["sleeper_id"] for x in t["a_gives"] + t["b_gives"]))
                if key not in seen:
                    result.append(t)
                    seen.add(key)

    return result


def _categorize_with_forced(profile: dict, force_player: dict | None, force_profile: dict | None) -> dict:
    cats = categorize_players(profile)
    if force_player and force_profile and profile["roster_id"] == force_profile["roster_id"]:
        all_in_pool = cats["smash"] + cats["pass"] + cats["trash"]
        already_in = any(p["sleeper_id"] == force_player["sleeper_id"] for p in all_in_pool)
        if not already_in:
            cats = dict(cats)
            cats["pass"] = [force_player] + cats["pass"]
        elif not any(p["sleeper_id"] == force_player["sleeper_id"] for p in cats["pass"]):
            # Player is in smash or trash — move them to pass so they're tradeable
            cats = {k: [p for p in v if p["sleeper_id"] != force_player["sleeper_id"]] for k, v in cats.items()}
            cats["pass"] = [force_player] + cats["pass"]
    return cats


def _trade_has_player(trade: dict, sleeper_id: str) -> bool:
    return any(p.get("sleeper_id") == sleeper_id for p in trade["a_gives"] + trade["b_gives"])


_ROUND_LABEL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
_GRADE_LABELS = [None, "F", "D", "C", "B", "A"]
_WIN_NOW  = {"All-In", "Championship Window", "Sustainable Contender"}
_REBUILD  = {"Full Rebuild", "Retooling"}
_SKILL_POS = {"QB", "RB", "WR", "TE"}


def _join_reasons(parts: list[str]) -> str:
    if not parts:
        return ""
    parts[0] = parts[0].capitalize()
    if len(parts) == 1:
        return parts[0] + "."
    return ", ".join(parts[:-1]) + ", and " + parts[-1] + "."


def _trade_grade(
    net_value: int,
    gave_val: int,
    recv_assets: list,
    gave_assets: list,
    profile: dict,
    is_best_piece: bool,
    best_piece_val: int = 0,
    best_piece_name: str = "",
) -> tuple[str, str]:
    deal_size = gave_val + sum(a.get("fc_value", 0) for a in recv_assets)
    if deal_size < 500:
        return "C", "Trade too small to evaluate."

    # Factor 1: value exchange → base grade
    value_pct = net_value / (deal_size / 2) * 100
    if value_pct >= 20:    grade = 5  # A
    elif value_pct >= 8:   grade = 4  # B
    elif value_pct >= -8:  grade = 3  # C
    elif value_pct >= -20: grade = 2  # D
    else:                  grade = 1  # F

    # Factor 2: best piece — +1 for receiving it, 0 for giving it (no penalty for fair multi-piece trades)
    significant_piece = best_piece_val >= 1000
    best_mod = 1 if (is_best_piece and significant_piece) else 0

    # Factor 3: age fit vs team contention stage
    contention = profile.get("contention_category", "")
    ages = [a["age"] for a in recv_assets if a.get("position") in _SKILL_POS and a.get("age")]
    age_mod = 0
    if ages:
        avg_age = sum(ages) / len(ages)
        if contention in _WIN_NOW:
            age_mod = 1 if avg_age >= 27 else -1 if avg_age <= 23 else 0
        elif contention in _REBUILD:
            age_mod = 1 if avg_age <= 24 else -1 if avg_age >= 28 else 0
        else:  # Ascending, Treading Water, etc.
            age_mod = 1 if avg_age <= 25 else 0

    # Factor 4: positional fit vs team needs
    pos_need = profile.get("positional_need", {})
    fit = 0
    for a in recv_assets:
        if a.get("position") in _SKILL_POS:
            need = pos_need.get(a["position"], "Adequate")
            if need == "Need":       fit += 1
            elif need == "Strength": fit -= 1
    for a in gave_assets:
        if a.get("position") in _SKILL_POS:
            need = pos_need.get(a["position"], "Adequate")
            if need == "Need":       fit -= 1
            elif need == "Strength": fit += 1
    pos_mod = 1 if fit >= 2 else -1 if fit <= -2 else 0

    grade = max(1, min(5, grade + best_mod + age_mod + pos_mod))

    # Build human-readable reason
    parts = []

    if value_pct >= 20:
        parts.append("received significantly more value")
    elif value_pct >= 8:
        parts.append("favorable value exchange")
    elif value_pct >= -8:
        parts.append("roughly even on value")
    elif value_pct >= -20:
        parts.append("gave up more value")
    else:
        parts.append("significantly overpaid")

    if significant_piece:
        piece_label = f"landed {best_piece_name}" if best_piece_name else "landed the best asset"
        if is_best_piece:
            parts.append(piece_label)
        else:
            gave_label = f"gave up {best_piece_name}" if best_piece_name else "gave up the top asset"
            parts.append(gave_label)

    if age_mod > 0:
        if contention in _WIN_NOW:
            parts.append("received prime-age players for their window")
        else:
            parts.append("added youth for the rebuild")
    elif age_mod < 0:
        if contention in _WIN_NOW:
            parts.append("received too much youth while in win-now mode")
        else:
            parts.append("took on aging veterans in a rebuild")

    if pos_mod > 0:
        parts.append("addressed a positional need")
    elif pos_mod < 0:
        parts.append("gave up assets at a position of need")

    return _GRADE_LABELS[grade], _join_reasons(parts)


@router.get("/{league_id}/recent-transactions")
async def get_recent_transactions(league_id: str):
    """Return the most recent completed trades in this league's current season."""
    cached = _TXNS_CACHE.get(league_id)
    if cached and time.time() - cached[0] < _TXNS_TTL:
        return cached[1]

    profiles = _load_profiles(league_id)
    roster_names    = {p["roster_id"]: p["display_name"] for p in profiles}
    roster_profiles = {p["roster_id"]: p for p in profiles}

    txn_results = await asyncio.gather(*[
        sleeper_client.get_transactions(league_id, week)
        for week in range(0, 23)
    ])

    all_txns = [
        t for week_txns in txn_results for t in week_txns
        if t.get("type") == "trade" and t.get("status") == "complete"
    ]
    recent = sorted(all_txns, key=lambda t: t.get("created") or 0, reverse=True)[:40]

    players_cache = cache_manager.get_cached_players()
    picks_cache = cache_manager.get_cached_picks()
    result = []

    for txn in recent:
        adds  = txn.get("adds") or {}
        drops = txn.get("drops") or {}
        picks = txn.get("draft_picks") or []
        created = txn.get("created")

        sides: dict[int, dict] = {}
        received_val: dict[int, int] = {}
        received_assets: dict[int, list] = {}
        received_full: dict[int, list] = {}  # full asset info for display
        best_piece_val = 0
        best_piece_rid: int | None = None
        best_piece_name = ""

        for pid, to_rid in adds.items():
            from_rid = drops.get(str(pid))
            if from_rid is None:
                continue
            from_rid = int(from_rid)
            to_rid_int = int(to_rid)
            sides.setdefault(from_rid, {
                "team_name": roster_names.get(from_rid, f"Team {from_rid}"),
                "gave": [],
            })
            p = players_cache.get(str(pid), {})
            val = p.get("fc_value", 0)
            pname = p.get("name", str(pid))
            asset_info = {
                "name": pname,
                "position": p.get("position", ""),
                "fc_value": val,
            }
            sides[from_rid]["gave"].append(asset_info)
            received_val[to_rid_int] = received_val.get(to_rid_int, 0) + val
            received_assets.setdefault(to_rid_int, []).append({
                "position": p.get("position", ""),
                "fc_value": val,
                "age": p.get("age"),
            })
            received_full.setdefault(to_rid_int, []).append(asset_info)
            if val > best_piece_val:
                best_piece_val = val
                best_piece_rid = to_rid_int
                best_piece_name = pname

        for pick in picks:
            from_rid = pick.get("previous_owner_id")
            to_rid = pick.get("owner_id")
            if from_rid is None:
                continue
            from_rid = int(from_rid)
            sides.setdefault(from_rid, {
                "team_name": roster_names.get(from_rid, f"Team {from_rid}"),
                "gave": [],
            })
            rnd = int(pick.get("round", 1))
            season = str(pick.get("season", ""))
            pick_val = cache_manager.resolve_pick_value(picks_cache, season, rnd)
            pick_name = f"{season} {_ROUND_LABEL.get(rnd, f'Rd {rnd}')}"
            pick_info = {
                "name": pick_name,
                "position": "PK",
                "fc_value": pick_val,
            }
            sides[from_rid]["gave"].append(pick_info)
            if to_rid is not None:
                to_rid_int = int(to_rid)
                received_val[to_rid_int] = received_val.get(to_rid_int, 0) + pick_val
                received_assets.setdefault(to_rid_int, []).append({
                    "position": "PK",
                    "fc_value": pick_val,
                    "age": None,
                })
                received_full.setdefault(to_rid_int, []).append(pick_info)
                if pick_val > best_piece_val:
                    best_piece_val = pick_val
                    best_piece_rid = to_rid_int
                    best_piece_name = pick_name

        if len(sides) < 2:
            continue

        sides_list = list(sides.values())
        roster_ids = list(sides.keys())
        for i, rid in enumerate(roster_ids):
            gave_val = sum(a.get("fc_value", 0) for a in sides_list[i]["gave"])
            recv_val = received_val.get(rid, 0)
            recv_ast = received_assets.get(rid, [])
            sides_list[i]["total_value"] = gave_val
            sides_list[i]["net_value"] = recv_val - gave_val
            sides_list[i]["received"] = received_full.get(rid, [])
            grade, reason = _trade_grade(
                net_value=recv_val - gave_val,
                gave_val=gave_val,
                recv_assets=recv_ast,
                gave_assets=sides_list[i]["gave"],
                profile=roster_profiles.get(rid, {}),
                is_best_piece=(rid == best_piece_rid and best_piece_val >= 1000),
                best_piece_val=best_piece_val,
                best_piece_name=best_piece_name,
            )
            sides_list[i]["grade"] = grade
            sides_list[i]["reason"] = reason

        # Winner = team with highest net value (received − gave)
        net_vals = [s["net_value"] for s in sides_list]
        best_idx = max(range(len(sides_list)), key=lambda i: net_vals[i])
        best_net = net_vals[best_idx]
        winner = sides_list[best_idx]["team_name"] if best_net > 200 else "even"
        delta = best_net if best_net > 200 else 0

        date_str = (
            datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%b %d, %Y")
            if created else None
        )
        result.append({
            "date": date_str,
            "ts": created or 0,
            "sides": sides_list,
            "value_delta": delta,
            "winner": winner,
        })

    _TXNS_CACHE[league_id] = (time.time(), result)
    return result
