"""
Populates and reads players_cache + picks_cache.
Both are refreshed at most once per day.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from database import db
import sleeper_client
import fantasycalc_client

CACHE_TTL_HOURS = 24
SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_stale(last_updated: str | None, hours: int = CACHE_TTL_HOURS) -> bool:
    if not last_updated:
        return True
    try:
        ts = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - ts > timedelta(hours=hours)
    except Exception:
        return True


def get_cached_players() -> dict:
    """Return {sleeper_id: {name, position, nfl_team, age, fc_value}} from DB."""
    with db() as conn:
        rows = conn.execute("SELECT * FROM players_cache").fetchall()
    return {r["sleeper_id"]: dict(r) for r in rows}


def get_cached_picks() -> dict:
    """Return {pick_key: {season, round, fc_value}} from DB."""
    with db() as conn:
        rows = conn.execute("SELECT * FROM picks_cache").fetchall()
    return {r["pick_key"]: dict(r) for r in rows}


def players_cache_is_stale() -> bool:
    with db() as conn:
        row = conn.execute(
            "SELECT last_updated FROM players_cache LIMIT 1"
        ).fetchone()
    return _is_stale(row["last_updated"] if row else None)


async def refresh_cache(num_qbs: int = 1):
    """
    Fetch fresh data from Sleeper (player metadata) + FantasyCalc (values),
    merge, and upsert into SQLite.
    """
    now = _now_iso()

    # --- FantasyCalc values ---
    fc_data = await fantasycalc_client.get_values(num_qbs=num_qbs)

    fc_player_map: dict[str, int] = {}   # sleeper_id -> value
    picks_rows: list[dict] = []

    _FP_PATTERN = re.compile(r"^FP_(\d{4})_(\d)$")

    for entry in fc_data:
        value = entry.get("value", 0)
        player = entry.get("player", {})
        position = player.get("position", "")
        sleeper_id = str(player.get("sleeperId") or "")

        # FantasyCalc returns generic future picks as position="PICK"
        # with sleeperId like "FP_2026_1"
        if position == "PICK":
            m = _FP_PATTERN.match(sleeper_id)
            if m:
                season, rnd = int(m.group(1)), int(m.group(2))
                picks_rows.append({
                    "pick_key": f"{season}_{rnd}",
                    "season": season,
                    "round": rnd,
                    "subtype": "MID",
                    "fc_value": value,
                    "last_updated": now,
                })
        elif sleeper_id:
            fc_player_map[sleeper_id] = value

    # --- Sleeper player metadata ---
    sleeper_players = await sleeper_client.get_all_players()

    player_rows = []
    for sid, p in sleeper_players.items():
        pos = p.get("position", "")
        if pos not in SKILL_POSITIONS:
            continue
        player_rows.append({
            "sleeper_id": str(sid),
            "name": p.get("full_name") or p.get("last_name", ""),
            "position": pos,
            "nfl_team": p.get("team", ""),
            "age": p.get("age"),
            "years_exp": p.get("years_exp"),
            "fc_value": fc_player_map.get(str(sid), 0),
            "last_updated": now,
        })

    with db() as conn:
        conn.executemany(
            """
            INSERT INTO players_cache
                (sleeper_id, name, position, nfl_team, age, years_exp, fc_value, last_updated)
            VALUES
                (:sleeper_id, :name, :position, :nfl_team, :age, :years_exp, :fc_value, :last_updated)
            ON CONFLICT(sleeper_id) DO UPDATE SET
                name=excluded.name, position=excluded.position, nfl_team=excluded.nfl_team,
                age=excluded.age, years_exp=excluded.years_exp, fc_value=excluded.fc_value,
                last_updated=excluded.last_updated
            """,
            player_rows,
        )
        conn.executemany(
            """
            INSERT INTO picks_cache
                (pick_key, season, round, subtype, fc_value, last_updated)
            VALUES
                (:pick_key, :season, :round, :subtype, :fc_value, :last_updated)
            ON CONFLICT(pick_key) DO UPDATE SET
                fc_value=excluded.fc_value, last_updated=excluded.last_updated
            """,
            picks_rows,
        )

    return {"players": len(player_rows), "picks": len(picks_rows)}


def resolve_pick_value(picks_cache: dict, season: str | int, round_num: int) -> int:
    """
    Map a Sleeper pick (season + round) to its FC value.
    Key format is "{year}_{round}" matching FP_{year}_{round} from FC.
    """
    season = int(season)
    rnd = int(round_num)
    key = f"{season}_{rnd}"
    if key in picks_cache:
        return picks_cache[key]["fc_value"]

    # Fallback: find nearest year we have, then rough guess by round
    same_round = [v["fc_value"] for v in picks_cache.values() if v["round"] == rnd]
    if same_round:
        return int(sum(same_round) / len(same_round))

    fallback = {1: 3000, 2: 1500, 3: 1000, 4: 800}
    return fallback.get(rnd, 500)
