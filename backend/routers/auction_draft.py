"""
Manual auction draft tracker — platform agnostic.

You enter each purchase as it happens, so this works for Yahoo, ESPN, Sleeper,
or an in-person auction with no API access at all. The server computes auction
dollar values from the player cache; live budget/inflation state is held
client-side so entry stays instant during a draft.

  GET /api/auction-draft/pool?teams=12&budget=200&qb=1&rb=2&wr=2&te=1&flex=1&k=1&dst=1&bench=7
"""
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/auction-draft")

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# How often each position fills a FLEX slot across a typical league
FLEX_SHARE = {"RB": 0.45, "WR": 0.45, "TE": 0.10}

# A new tier starts when the drop from the previous player exceeds this
TIER_BREAK = 0.08


def _norm_pos(pos: str) -> str:
    p = (pos or "").upper().strip()
    if p in ("DST", "D/ST", "DEFENSE"):
        return "DEF"
    if p == "PK":
        return "K"
    return p


@router.get("/pool")
async def get_auction_pool(
    teams: int = Query(12, ge=2, le=32),
    budget: int = Query(200, ge=10, le=1000),
    qb: int = Query(1, ge=0, le=5),
    rb: int = Query(2, ge=0, le=10),
    wr: int = Query(2, ge=0, le=10),
    te: int = Query(1, ge=0, le=5),
    flex: int = Query(1, ge=0, le=5),
    k: int = Query(1, ge=0, le=3),
    dst: int = Query(1, ge=0, le=3),
    bench: int = Query(7, ge=0, le=20),
    mode: str = Query("redraft"),
):
    """Player pool with auction dollar values derived from value over replacement."""
    from cache_manager import get_cached_players

    is_dynasty = mode == "dynasty"
    val_key = "fc_value" if is_dynasty else "redraft_value"

    starters = {"QB": qb, "RB": rb, "WR": wr, "TE": te, "K": k, "DEF": dst}
    roster_size = qb + rb + wr + te + flex + k + dst + bench

    # ── Group by position ─────────────────────────────────────────────────────
    by_pos: dict[str, list] = {p: [] for p in POSITIONS}
    for p in get_cached_players().values():
        val = p.get(val_key) or 0
        if not val:
            continue
        pos = _norm_pos(p.get("position"))
        if pos not in by_pos:
            continue
        by_pos[pos].append({
            "sleeper_id": p["sleeper_id"],
            "name": p["name"],
            "position": pos,
            "nfl_team": p.get("nfl_team", ""),
            "value": val,
            "pos_rank": p.get("pos_rank") if is_dynasty else p.get("redraft_pos_rank"),
        })

    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x["value"], reverse=True)

    # ── Replacement level: the last starter at each position ──────────────────
    # Flex slots are spread across RB/WR/TE, which pushes their replacement
    # level deeper and correctly raises the value of those positions.
    repl: dict[str, float] = {}
    for pos in POSITIONS:
        pool = by_pos[pos]
        if not pool:
            repl[pos] = 0
            continue
        n_start = starters.get(pos, 0) * teams
        n_start += round(FLEX_SHARE.get(pos, 0) * flex * teams)
        idx = min(max(n_start, 1), len(pool)) - 1
        repl[pos] = pool[idx]["value"]

    all_players: list[dict] = []
    for pos in POSITIONS:
        for pl in by_pos[pos]:
            pl["vor"] = round(pl["value"] - repl[pos])
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

    return {
        "players": all_players[:400],
        "settings": {
            "teams": teams,
            "budget": budget,
            "roster_size": roster_size,
            "total_money": total_money,
            "draftable": draftable_n,
            "starters": starters,
            "flex": flex,
            "bench": bench,
        },
    }
