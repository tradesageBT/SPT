import httpx
from typing import Any

BASE = "https://api.fantasycalc.com"
TIMEOUT = 30.0


async def get_values(num_qbs: int = 1, ppr: float = 1.0) -> list[dict]:
    """
    Fetch dynasty player + pick values from FantasyCalc.
    Returns raw list of {value, player: {sleeperId, name, position, ...}}.
    """
    superflex = "true" if num_qbs >= 2 else "false"
    params = {
        "isDynasty": "true",
        "numQbs": str(num_qbs),
        "ppr": str(ppr),
        "superflex": superflex,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
        r = await client.get(f"{BASE}/values/current", params=params)
        r.raise_for_status()
        data = r.json()
    return data if isinstance(data, list) else []
