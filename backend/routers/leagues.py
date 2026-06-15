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


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _sync_stale(last_synced_at: str | None) -> bool:
    return cache_manager._is_stale(last_synced_at, hours=SYNC_TTL_MINUTES / 60)


async def _sync_league(league_id: str, force: bool = False):
    """
    Fetch Sleeper data, compute team profiles, persist to DB.
    Returns the league row.
    """
    # Fetch league info
    league_info = await sleeper_client.get_league(league_id)
    if not league_info:
        raise HTTPException(status_code=404, detail="League not found")

    rosters, users, traded_picks = await asyncio.gather(
        sleeper_client.get_rosters(league_id),
        sleeper_client.get_users(league_id),
        sleeper_client.get_traded_picks(league_id),
    )

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

    # Refresh player cache if scoring settings changed or TTL expired
    if cache_manager.players_cache_is_stale(ppr=ppr, num_qbs=num_qbs):
        await cache_manager.refresh_cache(num_qbs=num_qbs, ppr=ppr)

    players_cache = cache_manager.get_cached_players()
    picks_cache = cache_manager.get_cached_picks()

    current_season = int(league_info.get("season", 2026))
    draft_rounds = league_info.get("settings", {}).get("draft_rounds", 4)
    num_teams = len(rosters)

    picks_by_roster = build_picks_by_roster(
        traded_picks,
        num_teams=num_teams,
        current_season=current_season,
        draft_rounds=draft_rounds,
    )

    profiles = compute_league_profiles(
        rosters, users_map, players_cache, picks_cache, picks_by_roster
    )

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
                    positional_breakdown, positional_surplus, contention_score,
                    roster_data, computed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sleeper_league_id, roster_id) DO UPDATE SET
                    owner_id=excluded.owner_id, display_name=excluded.display_name,
                    avatar=excluded.avatar, total_value=excluded.total_value,
                    player_value=excluded.player_value, pick_value=excluded.pick_value,
                    starter_value=excluded.starter_value, bench_value=excluded.bench_value,
                    positional_breakdown=excluded.positional_breakdown,
                    positional_surplus=excluded.positional_surplus,
                    contention_score=excluded.contention_score,
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
                    p["contention_score"],
                    json.dumps({"players": p["players"], "picks": p["picks"]}),
                    now,
                ),
            )

    return league_info, profiles


@router.get("/{league_id}")
async def get_league(league_id: str):
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
    league_info, profiles = await _sync_league(league_id)
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
async def force_sync(league_id: str):
    init_db()
    league_info, profiles = await _sync_league(league_id, force=True)
    return {
        "ok": True,
        "league_name": league_info.get("name"),
        "teams_synced": len(profiles),
    }


def _team_row_to_dict(row) -> dict:
    d = dict(row)
    for field in ("positional_breakdown", "positional_surplus", "roster_data"):
        if d.get(field):
            d[field] = json.loads(d[field])
    return d
