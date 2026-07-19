import os
import time
import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from database import init_db, db
from routers import leagues, teams, trades
import logger

app = FastAPI(title="Smash Pass Trash", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[ERROR] {request.method} {request.url.path}: {type(exc).__name__}: {exc}\n{tb}")
        logger.log("error", {
            "path": request.url.path,
            "method": request.method,
            "exc_type": type(exc).__name__,
            "exc_msg": str(exc),
        })
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}"},
        )

app.include_router(leagues.router)
app.include_router(teams.router)
app.include_router(trades.router)


@app.on_event("startup")
async def startup():
    import asyncio
    last_exc = None
    for attempt in range(6):
        try:
            init_db()
            logger.init_events_table()
            return
        except Exception as exc:
            last_exc = exc
            wait = 2 ** attempt  # 1s, 2s, 4s, 8s, 16s, 32s
            print(f"[STARTUP] DB connection attempt {attempt + 1} failed: {exc}. Retrying in {wait}s…")
            await asyncio.sleep(wait)
    raise RuntimeError(f"DB unavailable after 6 startup attempts: {last_exc}")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    ms = round((time.time() - start) * 1000)

    path = request.url.path
    # Only log API calls — skip static assets and SPA html
    if path.startswith("/api/") and path != "/api/health":
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        logger.log("request", {
            "method": request.method,
            "path": path,
            "status": response.status_code,
            "ms": ms,
            "query": str(request.query_params) or None,
        }, ip=ip)

    return response


@app.get("/api/health")
async def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}


@app.get("/api/admin/events")
async def get_events(limit: int = 200, event: str | None = None):
    with db() as conn:
        if event:
            rows = conn.execute(
                "SELECT * FROM events WHERE event = ? ORDER BY created_at DESC LIMIT ?",
                (event, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return rows


@app.get("/api/admin/summary")
async def get_summary():
    with db() as conn:
        leagues_viewed = conn.execute(
            "SELECT data->>'path' as path, COUNT(*) as views FROM events "
            "WHERE event='request' AND data->>'path' LIKE '/api/leagues/%' "
            "AND data->>'method'='GET' AND data->>'path' NOT LIKE '%/trades%' "
            "AND data->>'path' NOT LIKE '%/teams/%' "
            "GROUP BY path ORDER BY views DESC LIMIT 20"
        ).fetchall()

        top_teams = conn.execute(
            "SELECT data->>'path' as path, COUNT(*) as views FROM events "
            "WHERE event='request' AND data->>'path' LIKE '%/teams/%' "
            "GROUP BY path ORDER BY views DESC LIMIT 20"
        ).fetchall()

        trade_searches = conn.execute(
            "SELECT data->>'data' as info, COUNT(*) as count FROM events "
            "WHERE event='trade_search' "
            "GROUP BY info ORDER BY count DESC LIMIT 20"
        ).fetchall()

        daily = conn.execute(
            "SELECT DATE(created_at) as day, COUNT(*) as requests, COUNT(DISTINCT ip) as unique_ips "
            "FROM events WHERE event='request' "
            "GROUP BY day ORDER BY day DESC LIMIT 30"
        ).fetchall()

    return {
        "leagues_viewed": leagues_viewed,
        "top_teams": top_teams,
        "trade_searches": trade_searches,
        "daily_traffic": daily,
    }


# Serve built React app in production
_static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(_static_dir, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        return FileResponse(os.path.join(_static_dir, "index.html"))
