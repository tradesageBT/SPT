# Claude Code Guidelines for SPT

## Git

- Always work on and push to `main` directly — no feature branches needed
- Always set git author before committing:
  ```
  git config user.email noreply@anthropic.com
  git config user.name Claude
  ```
- Run this before every commit session to avoid the stop hook warning

## Deployment

- The app is hosted on Render at `spt-4g5a.onrender.com`
- Render auto-deploys from `main` — push to main to deploy
- Free tier takes ~2–5 minutes to redeploy

## Stack

- **Backend**: FastAPI + PostgreSQL (via psycopg2) on Render
- **Frontend**: React (Vite) served as static files from the backend
- **Data sources**: Sleeper API (league/roster/transaction data), FantasyCalc API (dynasty values)

## Database

- `init_db()` uses `CREATE TABLE IF NOT EXISTS` — new columns must also have a corresponding `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration in the same function
- DB is a Render-managed PostgreSQL instance; `DATABASE_URL` is set via environment variable

## Key Files

- `backend/routers/leagues.py` — league sync, PPR/TEP/superflex detection
- `backend/value_engine.py` — team profile computation, pick ownership + trade chain
- `backend/cache_manager.py` — FantasyCalc/Sleeper player cache (24h TTL, invalidates on scoring setting change)
- `frontend/src/pages/TeamProfile.jsx` — team detail page including pick pills + trade history
- `frontend/src/components/TeamCard.jsx` — league dashboard team rows (custom badges go in `CUSTOM_BADGES`)
