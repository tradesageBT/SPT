# Smash Pass Trash (SPT)

Dynasty fantasy football value engine. Connects Sleeper leagues to FantasyCalc values to produce team profiles, positional analysis, and trade ideas.

## Quick start

### 1. Install Python deps

```bash
pip install -r requirements.txt
```

### 2. Install frontend deps

```bash
cd frontend
npm install
```

### 3. Run

**Windows (PowerShell):**
```powershell
.\start.ps1
```

**Mac/Linux:**
```bash
chmod +x start.sh
./start.sh
```

Then open **http://localhost:5173** and paste a Sleeper league ID.

---

## Architecture

```
backend/
  main.py               FastAPI entry point
  database.py           SQLite setup + schema
  sleeper_client.py     Sleeper public API wrapper
  fantasycalc_client.py FantasyCalc public API wrapper
  cache_manager.py      Daily player/pick value cache
  value_engine.py       Team profile computations
  trade_engine.py       Smash/Pass/Trash + trade suggestions
  routers/
    leagues.py          GET /api/leagues/{id}, POST sync
    teams.py            GET /api/leagues/{id}/teams/{roster_id}
    trades.py           GET /api/leagues/{id}/trades

frontend/
  src/
    pages/              Home, LeagueDashboard, TeamProfile, TradeIdeas
    components/         TeamCard, PlayerTable, TradeCard, ...
    api/client.js       fetch wrapper for the FastAPI backend
```

## Data flow

1. User pastes a Sleeper league ID → frontend calls `GET /api/leagues/{id}`
2. Backend checks SQLite — if not cached (or stale >1 hour), fetches fresh data:
   - Sleeper: league info, rosters, users
   - FantasyCalc: dynasty player + pick values (cached 24 hours)
3. Value engine computes per-team profiles (total value, starter/bench split, positional breakdown vs league average, contention score)
4. Results are stored in SQLite and returned to the frontend
5. Trade ideas are computed on-demand (not persisted)

## Caching

| Store | Source | TTL |
|---|---|---|
| `players_cache` | Sleeper + FantasyCalc | 24 h |
| `picks_cache` | FantasyCalc | 24 h |
| `teams` table | computed | 1 h (or manual Refresh) |

## API reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/leagues/{id}` | Fetch or sync a league |
| `POST` | `/api/leagues/{id}/sync` | Force re-sync |
| `GET` | `/api/leagues/{id}/teams` | All team profiles |
| `GET` | `/api/leagues/{id}/teams/{roster_id}` | Single team + SPT categorization |
| `GET` | `/api/leagues/{id}/trades` | Trade ideas (all pairs or `?roster_id=N`) |
| `GET` | `/api/health` | Health check |

Interactive docs: **http://localhost:8000/docs**
