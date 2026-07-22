import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks

from database import db, init_db
import sleeper_client
import cache_manager
from value_engine import compute_league_profiles, build_picks_by_roster

router = APIRouter(prefix="/api/leagues", tags=["leagues"])

SYNC_TTL_MINUTES = 60
MAX_CHAIN_SEASONS = 3  # limit historical seasons fetched to stay within request timeout


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _sync_stale(last_synced_at: str | None) -> bool:
    return cache_manager._is_stale(last_synced_at, hours=SYNC_TTL_MINUTES / 60)


async def _sync_league(league_id: str, force: bool = False, background_tasks: BackgroundTasks | None = None):
    """
    Fetch Sleeper data, compute team profiles, persist to DB.
    Returns the league row.
    """
    # Fetch league info
    league_info = await sleeper_client.get_league(league_id)
    if not league_info:
        raise HTTPException(status_code=404, detail="League not found")

    # Dynasty leagues roll over to a NEW league_id every season, and each
    # league's /transactions endpoint only holds THAT season's trades. To get
    # the full trade history of a pick (which may have been dealt years ago),
    # walk the previous_league_id chain and fetch transactions from every
    # season this league has existed. Capped at MAX_CHAIN_SEASONS to bound
    # the number of parallel Sleeper API calls and stay within request timeout.
    league_chain = [league_id]
    seen_ids = {league_id}
    prev_id = league_info.get("previous_league_id")
    while prev_id and prev_id != "0" and prev_id not in seen_ids and len(league_chain) < MAX_CHAIN_SEASONS:
        league_chain.append(prev_id)
        seen_ids.add(prev_id)
        prev_info = await sleeper_client.get_league(prev_id)
        prev_id = prev_info.get("previous_league_id") if prev_info else None

    txn_tasks = [
        sleeper_client.get_transactions(lid, leg)
        for lid in league_chain
        for leg in range(0, 23)
    ]
    rosters, users, traded_picks, *txn_results = await asyncio.gather(
        sleeper_client.get_rosters(league_id),
        sleeper_client.get_users(league_id),
        sleeper_client.get_traded_picks(league_id),
        *txn_tasks,
    )
    all_transactions_raw = [t for leg_txns in txn_results for t in leg_txns]
    all_transactions = [t for t in all_transactions_raw
                        if t.get("type") == "trade" and t.get("status") == "complete"]
    # Map (season, round, original_roster_id) → list of transactions involving that pick
    transaction_map: dict[tuple, list] = {}
    for txn in all_transactions:
        for dp in (txn.get("draft_picks") or []):
            key = (str(dp["season"]), int(dp["round"]), int(dp["roster_id"]))
            transaction_map.setdefault(key, []).append(txn)

    # Build acquisition maps split by type.
    # Season-rollover free_agent transactions (created when Sleeper imports rosters to a new
    # season) look identical to real FA adds and would incorrectly overwrite draft/trade history.
    # We resolve this with a priority: trade > drafted-by-this-roster > FA/waiver.
    player_trade_acq: dict[tuple, dict] = {}   # most recent trade per (player, roster)
    player_fa_acq: dict[tuple, dict] = {}      # most recent FA/waiver per (player, roster)
    for txn in sorted(all_transactions_raw, key=lambda t: t.get("created") or 0):
        txn_type = txn.get("type", "")
        if txn_type not in ("trade", "free_agent", "waiver"):
            continue
        faab = txn.get("settings", {}).get("waiver_bid") if txn_type == "waiver" else None
        for pid, rid in (txn.get("adds") or {}).items():
            key = (str(pid), int(rid))
            if txn_type == "trade":
                player_trade_acq[key] = {"type": "traded", "faab": None}
            else:
                player_fa_acq[key] = {"type": "claimed", "faab": faab}

    # Get drafted players so season-rollover FAs don't mask "homegrown" status
    _, player_draft = await _build_drafted_picks_map(league_chain)

    users_map = {u["user_id"]: u for u in users}

    # Detect superflex/2QB — SUPER_FLEX effectively means 2-QB values
    roster_positions = league_info.get("roster_positions", [])
    has_superflex = "SUPER_FLEX" in roster_positions
    num_qbs = 2 if has_superflex else max(1, sum(1 for p in roster_positions if p == "QB"))

    # Read scoring settings: PPR (rec), TEP (bonus_rec_te)
    scoring = league_info.get("scoring_settings", {})
    ppr = float(scoring.get("rec", 1.0))          # 0, 0.5, or 1.0
    tep = float(scoring.get("bonus_rec_te", 0.0)) # TE premium (0, 0.25, 0.5, 1.0)
    # FantasyCalc doesn't have a TEP param, but ppr already captures most of the
    # TE value signal. We store tep so we can show it in the UI.

    # Player cache: if stale, only block when the cache is completely empty.
    # If we have existing data, serve it immediately and refresh in background
    # to avoid blocking the sync on a 10-30s FantasyCalc+Sleeper fetch cycle
    # (which can push the total request time past Render's 60s timeout).
    players_cache = cache_manager.get_cached_players()
    picks_cache = cache_manager.get_cached_picks()

    if cache_manager.players_cache_is_stale(ppr=ppr, num_qbs=num_qbs):
        if not players_cache:
            # Cache is completely empty — must block and fetch before computing profiles
            await cache_manager.refresh_cache(num_qbs=num_qbs, ppr=ppr)
            players_cache = cache_manager.get_cached_players()
            picks_cache = cache_manager.get_cached_picks()
        elif background_tasks is not None:
            background_tasks.add_task(cache_manager.refresh_cache, num_qbs=num_qbs, ppr=ppr)
        else:
            await cache_manager.refresh_cache(num_qbs=num_qbs, ppr=ppr)
            players_cache = cache_manager.get_cached_players()
            picks_cache = cache_manager.get_cached_picks()

    current_season = int(league_info.get("season", 2026))
    draft_rounds = league_info.get("settings", {}).get("draft_rounds", 4)
    num_teams = len(rosters)

    roster_display_map = {
        r["roster_id"]: users_map.get(r.get("owner_id", ""), {}).get("display_name", f"Team {r['roster_id']}")
        for r in rosters
    }

    picks_by_roster = build_picks_by_roster(
        traded_picks,
        num_teams=num_teams,
        current_season=current_season,
        draft_rounds=draft_rounds,
        roster_display_map=roster_display_map,
        transaction_map=transaction_map,
        players_cache=players_cache,
    )

    profiles = compute_league_profiles(
        rosters, users_map, players_cache, picks_cache, picks_by_roster
    )

    for profile in profiles:
        for player in profile["players"]:
            pid = player["sleeper_id"]
            roster_id = profile["roster_id"]
            key = (pid, roster_id)
            draft_info = player_draft.get(pid)
            if key in player_trade_acq:
                # Most recent trade to this roster wins unconditionally
                player["acquisition_type"] = "traded"
                player["faab_bid"] = None
            elif draft_info and draft_info.get("roster_id") == roster_id:
                # Player was drafted by this roster — rollover FAs don't override this
                player["acquisition_type"] = "homegrown"
                player["faab_bid"] = None
            elif key in player_fa_acq:
                info = player_fa_acq[key]
                player["acquisition_type"] = info["type"]
                player["faab_bid"] = info["faab"]
            else:
                player["acquisition_type"] = "homegrown"
                player["faab_bid"] = None

    now = _now_iso()

    with db() as conn:
        conn.execute(
            """
            INSERT INTO leagues (sleeper_league_id, league_name, season, scoring_settings,
                                 roster_positions, num_qbs, ppr, tep, last_synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sleeper_league_id) DO UPDATE SET
                league_name=excluded.league_name, season=excluded.season,
                scoring_settings=excluded.scoring_settings,
                roster_positions=excluded.roster_positions,
                num_qbs=excluded.num_qbs, ppr=excluded.ppr, tep=excluded.tep,
                last_synced_at=excluded.last_synced_at
            """,
            (
                league_id,
                league_info.get("name", ""),
                league_info.get("season", ""),
                json.dumps(league_info.get("scoring_settings", {})),
                json.dumps(roster_positions),
                num_qbs,
                ppr,
                tep,
                now,
            ),
        )

        for p in profiles:
            conn.execute(
                """
                INSERT INTO teams (
                    sleeper_league_id, roster_id, owner_id, display_name, avatar,
                    total_value, player_value, pick_value, starter_value, bench_value,
                    positional_breakdown, positional_surplus, positional_need,
                    positional_rank,
                    contention_score, contention_category,
                    roster_data, computed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sleeper_league_id, roster_id) DO UPDATE SET
                    owner_id=excluded.owner_id, display_name=excluded.display_name,
                    avatar=excluded.avatar, total_value=excluded.total_value,
                    player_value=excluded.player_value, pick_value=excluded.pick_value,
                    starter_value=excluded.starter_value, bench_value=excluded.bench_value,
                    positional_breakdown=excluded.positional_breakdown,
                    positional_surplus=excluded.positional_surplus,
                    positional_need=excluded.positional_need,
                    positional_rank=excluded.positional_rank,
                    contention_score=excluded.contention_score,
                    contention_category=excluded.contention_category,
                    roster_data=excluded.roster_data, computed_at=excluded.computed_at
                """,
                (
                    league_id,
                    p["roster_id"],
                    p["owner_id"],
                    p["display_name"],
                    p["avatar"],
                    p["total_value"],
                    p["player_value"],
                    p["pick_value"],
                    p["starter_value"],
                    p["bench_value"],
                    json.dumps(p["positional_breakdown"]),
                    json.dumps(p["positional_surplus"]),
                    json.dumps(p["positional_need"]),
                    json.dumps(p.get("positional_rank", {})),
                    p["contention_score"],
                    p["contention_category"],
                    json.dumps({"players": p["players"], "picks": p["picks"]}),
                    now,
                ),
            )

    return league_info, profiles


@router.get("/{league_id}")
async def get_league(league_id: str, background_tasks: BackgroundTasks):
    init_db()

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM leagues WHERE sleeper_league_id = ?", (league_id,)
        ).fetchone()

    if row and not _sync_stale(row["last_synced_at"]):
        with db() as conn:
            teams = conn.execute(
                "SELECT * FROM teams WHERE sleeper_league_id = ? ORDER BY total_value DESC",
                (league_id,),
            ).fetchall()
        return {
            "league_id": league_id,
            "league_name": row["league_name"],
            "season": row["season"],
            "num_qbs": row["num_qbs"],
            "ppr": row.get("ppr", 1.0),
            "tep": row.get("tep", 0.0),
            "superflex": row["num_qbs"] >= 2,
            "last_synced_at": row["last_synced_at"],
            "teams": [_team_row_to_dict(t) for t in teams],
        }

    # Need to sync
    league_info, profiles = await _sync_league(league_id, background_tasks=background_tasks)
    scoring = league_info.get("scoring_settings", {})
    roster_positions = league_info.get("roster_positions", [])
    nqbs = max(1, sum(1 for p in roster_positions if p in ("QB", "SUPER_FLEX")))
    return {
        "league_id": league_id,
        "league_name": league_info.get("name", ""),
        "season": league_info.get("season", ""),
        "num_qbs": nqbs,
        "ppr": float(scoring.get("rec", 1.0)),
        "tep": float(scoring.get("bonus_rec_te", 0.0)),
        "superflex": "SUPER_FLEX" in roster_positions,
        "last_synced_at": _now_iso(),
        "teams": profiles,
    }


@router.post("/{league_id}/sync")
async def force_sync(league_id: str, background_tasks: BackgroundTasks):
    init_db()
    league_info, profiles = await _sync_league(league_id, force=True, background_tasks=background_tasks)
    return {
        "ok": True,
        "league_name": league_info.get("name"),
        "teams_synced": len(profiles),
    }


@router.get("/{league_id}/draft")
async def get_draft_state(league_id: str):
    """
    Return the active (or most recent) startup draft state for this league.
    Designed for live polling — client calls every ~5 seconds.
    """
    drafts = await sleeper_client.get_league_drafts(league_id)
    if not drafts:
        raise HTTPException(status_code=404, detail="No drafts found for this league")

    # Prefer an in-progress draft; fall back to most recently created
    active = next((d for d in drafts if d.get("status") == "drafting"), None)
    draft = active or sorted(drafts, key=lambda d: d.get("created") or 0, reverse=True)[0]
    draft_id = draft["draft_id"]

    draft_detail, picks = await asyncio.gather(
        sleeper_client.get_draft(draft_id),
        sleeper_client.get_draft_picks(draft_id),
    )

    players_cache = cache_manager.get_cached_players()
    picked_ids = {str(p.get("player_id")) for p in picks}

    slot_to_roster = draft_detail.get("slot_to_roster_id") or {}
    # Sleeper returns string keys; normalise to int→int
    slot_to_roster_int = {int(k): int(v) for k, v in slot_to_roster.items()}
    roster_to_slot = {v: k for k, v in slot_to_roster_int.items()}

    with db() as conn:
        rows = conn.execute(
            "SELECT roster_id, display_name FROM teams WHERE sleeper_league_id = ?",
            (league_id,),
        ).fetchall()
    team_names = {r["roster_id"]: r["display_name"] for r in rows}

    settings = draft_detail.get("settings") or {}
    num_teams = int(settings.get("teams", len(slot_to_roster_int) or 12))
    num_rounds = int(settings.get("rounds", 4))
    total_picks = num_teams * num_rounds
    picks_made = len(picks)
    is_snake = draft_detail.get("type") == "snake"

    def _pick_to_slot(pick_num: int) -> int:
        rnd = (pick_num - 1) // num_teams          # 0-indexed round
        pos = (pick_num - 1) % num_teams            # 0-indexed position in round
        if is_snake and rnd % 2 == 1:
            return num_teams - pos                  # reverses in even rounds
        return pos + 1

    on_the_clock_slot = None
    on_the_clock_roster = None
    on_the_clock_team = None
    if picks_made < total_picks:
        on_the_clock_slot = _pick_to_slot(picks_made + 1)
        on_the_clock_roster = slot_to_roster_int.get(on_the_clock_slot)
        on_the_clock_team = team_names.get(on_the_clock_roster, f"Team {on_the_clock_roster}") if on_the_clock_roster else None

    # Available players: from cache, exclude already-picked, sort by value
    available = [
        {
            "sleeper_id": sid,
            "name": p.get("name", sid),
            "position": p.get("position", ""),
            "nfl_team": p.get("nfl_team", ""),
            "age": p.get("age"),
            "fc_value": p.get("fc_value", 0),
        }
        for sid, p in players_cache.items()
        if sid not in picked_ids
    ]
    available.sort(key=lambda x: x["fc_value"], reverse=True)

    # Recent picks feed (last 20, newest first)
    recent_picks = []
    for pick in reversed(picks[-20:]):
        pid = str(pick.get("player_id", ""))
        p = players_cache.get(pid, {})
        roster_id = pick.get("roster_id")
        recent_picks.append({
            "overall_pick": pick.get("pick_no"),
            "round": pick.get("round"),
            "pick_in_round": pick.get("draft_slot"),
            "roster_id": roster_id,
            "team_name": team_names.get(roster_id, f"Team {roster_id}") if roster_id else "",
            "player_name": p.get("name", pid) if pid else "Unknown",
            "position": p.get("position", ""),
            "nfl_team": p.get("nfl_team", ""),
            "fc_value": p.get("fc_value", 0),
        })

    # Team builds: aggregate picks by roster, ordered by draft slot
    team_builds: dict = {}
    for pick in picks:
        pid = str(pick.get("player_id", ""))
        roster_id = pick.get("roster_id")
        if not roster_id:
            continue
        p = players_cache.get(pid, {})
        team_builds.setdefault(roster_id, []).append({
            "sleeper_id": pid,
            "name": p.get("name", pid),
            "position": p.get("position", ""),
            "nfl_team": p.get("nfl_team", ""),
            "fc_value": p.get("fc_value", 0),
            "overall_pick": pick.get("pick_no"),
        })

    teams = [
        {
            "roster_id": roster_id,
            "team_name": team_names.get(roster_id, f"Team {roster_id}"),
            "slot": roster_to_slot.get(roster_id),
            "players": sorted(drafted, key=lambda x: x["overall_pick"] or 0),
        }
        for roster_id, drafted in sorted(
            team_builds.items(), key=lambda x: roster_to_slot.get(x[0], 999)
        )
    ]

    return {
        "draft_id": draft_id,
        "status": draft_detail.get("status", "unknown"),
        "type": draft_detail.get("type", "snake"),
        "num_teams": num_teams,
        "num_rounds": num_rounds,
        "picks_made": picks_made,
        "total_picks": total_picks,
        "on_the_clock_slot": on_the_clock_slot,
        "on_the_clock_roster": on_the_clock_roster,
        "on_the_clock_team": on_the_clock_team,
        "available": available[:200],
        "recent_picks": recent_picks,
        "teams": teams,
    }


def _team_row_to_dict(row) -> dict:
    d = dict(row)
    for field in ("positional_breakdown", "positional_surplus", "positional_rank", "roster_data"):
        if d.get(field):
            d[field] = json.loads(d[field])
    return d


async def _build_league_chain(league_id: str) -> list[str]:
    """Walk previous_league_id links and return all league IDs oldest→newest."""
    chain = [league_id]
    seen = {league_id}
    info = await sleeper_client.get_league(league_id)
    prev_id = info.get("previous_league_id") if info else None
    while prev_id and prev_id != "0" and prev_id not in seen:
        chain.append(prev_id)
        seen.add(prev_id)
        prev_info = await sleeper_client.get_league(prev_id)
        prev_id = prev_info.get("previous_league_id") if prev_info else None
    return chain


async def _build_drafted_picks_map(league_chain: list[str]) -> tuple[dict, dict]:
    """
    Returns:
      drafted_map:     {(season, round, orig_roster_id): {slot_in_round, player_name}}
      player_draft:    {player_id: {season, round, slot_in_round}}
    for every pick that has actually been drafted across all seasons.
    """
    draft_lists = await asyncio.gather(*[sleeper_client.get_league_drafts(lid) for lid in league_chain])
    # slot_to_roster_id is NOT in the list response; only filter on status
    complete_drafts = [
        d for dl in draft_lists for d in dl
        if d.get("status") == "complete"
    ]
    if not complete_drafts:
        return {}, {}

    detail_results = await asyncio.gather(*[
        asyncio.gather(
            sleeper_client.get_draft(d["draft_id"]),
            sleeper_client.get_draft_picks(d["draft_id"]),
        )
        for d in complete_drafts
    ])

    drafted_map = {}
    player_draft = {}
    for draft_info, draft_picks in detail_results:
        slot_to_roster = {int(k): int(v) for k, v in (draft_info.get("slot_to_roster_id") or {}).items()}
        if not slot_to_roster:
            continue
        num_teams = draft_info.get("settings", {}).get("teams", len(slot_to_roster))
        total_rounds = draft_info.get("settings", {}).get("rounds", 4)
        is_startup = total_rounds >= 8
        season = str(draft_info.get("season", ""))
        for pick in draft_picks:
            draft_slot = pick.get("draft_slot")
            if draft_slot is None:
                continue
            roster_id = slot_to_roster.get(int(draft_slot))
            if roster_id is None:
                continue
            rnd = pick.get("round", 0)
            pick_no = pick.get("pick_no", 0)
            slot_in_round = pick_no - (rnd - 1) * num_teams
            meta = pick.get("metadata", {})
            pname = f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip() or pick.get("player_id", "")
            drafted_map[(season, rnd, roster_id)] = {
                "round": rnd,
                "slot_in_round": slot_in_round,
                "player_name": pname,
                "is_startup": is_startup,
            }
            pid = pick.get("player_id", "")
            if pid:
                player_draft[str(pid)] = {
                    "season": season,
                    "round": rnd,
                    "slot_in_round": slot_in_round,
                    "is_startup": is_startup,
                    "roster_id": roster_id,
                }
    return drafted_map, player_draft


_ROUND_LABEL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


@router.get("/{league_id}/player/{player_id}/history")
async def get_player_history(league_id: str, player_id: str):
    """Full trade history for a player across all dynasty seasons."""
    from datetime import datetime, timezone

    league_chain = await _build_league_chain(league_id)

    rosters, users = await asyncio.gather(
        sleeper_client.get_rosters(league_id),
        sleeper_client.get_users(league_id),
    )
    users_map = {u["user_id"]: u for u in users}
    rmap = {
        r["roster_id"]: users_map.get(r.get("owner_id", ""), {}).get("display_name", f"Team {r['roster_id']}")
        for r in rosters
    }

    # All transactions across all seasons + drafted picks map in parallel
    txn_tasks = [
        sleeper_client.get_transactions(lid, leg)
        for lid in league_chain
        for leg in range(0, 23)
    ]
    txn_results, (drafted_map, player_draft) = await asyncio.gather(
        asyncio.gather(*txn_tasks),
        _build_drafted_picks_map(league_chain),
    )

    all_transactions = [
        t for leg_txns in txn_results for t in leg_txns
        if t.get("type") == "trade" and t.get("status") == "complete"
        and (player_id in (t.get("adds") or {}) or player_id in (t.get("drops") or {}))
    ]

    players_cache = cache_manager.get_cached_players()

    def _rname(rid):
        return rmap.get(int(rid), f"Team {rid}") if rid is not None else "Unknown"

    def _pick_str(dp):
        season = str(dp.get("season", ""))
        rnd = int(dp.get("round", 1))
        orig_rid = int(dp.get("roster_id", 0))
        rl = _ROUND_LABEL.get(rnd, f"Rd {rnd}")
        drafted = drafted_map.get((season, rnd, orig_rid))
        if drafted:
            slot = drafted["slot_in_round"]
            pname = drafted["player_name"]
            return f"{season} {rl} ({rnd}.{slot:02d} – {pname})"
        return f"{season} {rl} (originally {_rname(orig_rid)})"

    def _pstr(pid):
        p = players_cache.get(str(pid), {})
        name = p.get("name", f"Player {pid}")
        pos = p.get("position", "")
        return f"{name} ({pos})" if pos else name

    trades = []
    for txn in sorted(all_transactions, key=lambda t: t.get("created") or 0):
        adds = txn.get("adds") or {}
        drops = txn.get("drops") or {}
        new_rid = int(adds[player_id]) if player_id in adds else None
        old_rid = int(drops[player_id]) if player_id in drops else None

        created = txn.get("created")
        date_str = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%b %d, %Y")
                    if created else None)

        gave_up, also_received = [], []
        if new_rid is not None:
            for pid, prev_rid in drops.items():
                if str(pid) != player_id and int(prev_rid) == new_rid:
                    gave_up.append(_pstr(pid))
            for dp in (txn.get("draft_picks") or []):
                if int(dp.get("previous_owner_id", -1)) == new_rid:
                    gave_up.append(_pick_str(dp))
            for pid, nr in adds.items():
                if str(pid) != player_id and int(nr) == new_rid:
                    also_received.append(_pstr(pid))
            for dp in (txn.get("draft_picks") or []):
                if (int(dp.get("owner_id", -1)) == new_rid
                        and int(dp.get("previous_owner_id", -1)) != new_rid):
                    also_received.append(_pick_str(dp))

        trades.append({
            "date": date_str,
            "from": _rname(old_rid),
            "to": _rname(new_rid),
            "gave_up": gave_up,
            "also_received": also_received,
        })

    p_info = players_cache.get(str(player_id), {})
    return {
        "player_id": player_id,
        "player_name": p_info.get("name", player_id),
        "position": p_info.get("position", ""),
        "nfl_team": p_info.get("nfl_team", ""),
        "drafted_as": player_draft.get(str(player_id)),
        "trades": trades,
    }
